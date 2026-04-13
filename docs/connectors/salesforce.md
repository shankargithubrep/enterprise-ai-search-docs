# Salesforce Connector

> **Connector type:** Native Elastic · **Protocol:** Salesforce REST API + Bulk API 2.0 · **Sync:** High-watermark timestamp (incremental) + full · **Auth:** OAuth 2.0 (JWT Bearer / Connected App)

---

## Table of Contents

- [Overview](#overview)
- [How It Works](#how-it-works)
  - [Incremental Sync — Step by Step](#incremental-sync--step-by-step)
  - [High-Watermark Timestamp Mechanism](#high-watermark-timestamp-mechanism)
  - [Object Types Synced](#object-types-synced)
  - [Full Sync vs Incremental Sync](#full-sync-vs-incremental-sync)
  - [Deletion Detection](#deletion-detection)
- [When to Use / When Not to Use](#when-to-use--when-not-to-use)
- [Configuration Reference](#configuration-reference)
  - [Core Parameters](#core-parameters)
  - [Connected App Setup](#connected-app-setup)
  - [Required Permissions](#required-permissions)
  - [Sync Schedule](#sync-schedule)
  - [Programmatic Provisioning](#programmatic-provisioning)
- [Supported Object Types & Field Mapping](#supported-object-types--field-mapping)
- [Known Limitations](#known-limitations)
- [Enterprise AI-KB Deployment Notes](#enterprise-ai-kb-deployment-notes)
- [Technical Q&A](#technical-qa)

---

## Overview

The Elastic Salesforce Connector synchronises records from Salesforce objects (Knowledge Articles, Cases, Solutions, custom objects) into Elasticsearch using the **Salesforce REST API** and **Bulk API 2.0**. Change detection uses a **high-watermark timestamp** — the connector queries for records with `LastModifiedDate > last_sync_timestamp`, which is native to Salesforce's SOQL query language and requires no server-side cursor infrastructure.

In the Enterprise AI-KB architecture, the Salesforce connector is particularly important because enterprise customers' primary knowledge sources are often Salesforce Knowledge articles — the structured FAQs, troubleshooting guides, and product documentation that contact centre agents need during live calls.

```
Salesforce Org (Knowledge Articles, Cases, custom objects)
        │
        ▼
Salesforce REST API / Bulk API 2.0 (SOQL queries)
        │
        ▼
Connector Process (Python 3.10+ / simple-salesforce)
        │
        ▼
Elasticsearch Bulk API ──► Ingest Pipeline (Jina v3 embedding)
        │
        ▼
Tenant Index (BM25 + kNN searchable)
```

| Component | Technology | Role |
|---|---|---|
| Connector process | Python 3.10+ / `simple-salesforce` | Authenticates, runs SOQL queries, fetches records and attachments |
| Auth mechanism | OAuth 2.0 JWT Bearer (server-to-server, no user login) | Daemon authentication using certificate |
| Change detection | High-watermark `LastModifiedDate` SOQL filter | Queries only records modified since last sync timestamp |
| Deletion detection | Salesforce Deleted Records API | `queryAll()` with `IsDeleted = true` filter |
| Ingest pipeline | Elasticsearch ingest node | Jina v3 embedding, field normalisation |
| Target store | Elasticsearch index | Tenant-scoped, BM25 + kNN searchable |

---

## How It Works

### Incremental Sync — Step by Step

1. **Schedule trigger** — Reads cron from `.elastic-connectors`. Default: `0 * * * *`.

2. **OAuth token** — Connector uses JWT Bearer flow: signs a JWT with the private key, sends to `https://{instance}.salesforce.com/services/oauth2/token`. Returns `access_token` + `instance_url`. Token valid for ~1 hour, refreshed automatically.

3. **High-watermark read** — Loads `last_sync_timestamp` from `sync_cursor` field in `.elastic-connectors`.

4. **SOQL query** — Constructs and runs incremental query for each configured object type:

   ```sql
   SELECT Id, Title, ArticleBody, LastModifiedDate, CreatedDate, ...
   FROM Knowledge__kav
   WHERE LastModifiedDate > 2025-01-15T10:00:00Z
     AND PublishStatus = 'Online'
   ORDER BY LastModifiedDate ASC
   ```

5. **Pagination** — Salesforce REST API returns up to 2,000 records per page. Connector follows `nextRecordsUrl` until all pages are consumed.

6. **Attachment fetch** — For records with file attachments, connector calls `GET /services/data/v58.0/sobjects/Attachment/{id}/Body` to download binary content, then passes to Tika.

7. **Field mapping** — Record fields mapped to Elastic document schema (see [Supported Object Types](#supported-object-types--field-mapping)).

8. **Bulk indexing** — Documents batched and sent to `_bulk` API with ingest pipeline.

9. **Deletion handling** — Separate query using `queryAll()` with `IsDeleted = true` and `LastModifiedDate > watermark` to find deleted records. Issues DELETE operations for these.

10. **Watermark update** — On success, `sync_cursor` updated to current UTC timestamp minus a 60-second buffer (to handle clock skew between Salesforce servers).

---

### High-Watermark Timestamp Mechanism

The high-watermark is the most important concept to understand. It is simply the `LastModifiedDate` of the most recently synced record, stored in `.elastic-connectors`.

```
sync_cursor = "2025-01-15T10:00:00.000Z"

Next sync SOQL:
  WHERE LastModifiedDate > '2025-01-15T10:00:00.000Z'

Records returned: only those modified after that timestamp
```

**The 60-second buffer:** The connector sets the new watermark to `now() - 60 seconds` rather than `now()`. This prevents edge cases where a record is modified at exactly the sync boundary and gets missed due to Salesforce server clock differences across its distributed infrastructure.

**Ordering matters:** Results are ordered by `LastModifiedDate ASC` so that if a sync is interrupted mid-page, the watermark reflects the last successfully processed record and the next sync resumes from there rather than re-processing everything.

---

### Object Types Synced

The connector supports these Salesforce object types by default:

| Object | SOQL table | Typical use for this deployment |
|---|---|---|
| Salesforce Knowledge Articles | `Knowledge__kav` | Primary knowledge base content — FAQs, troubleshooting guides |
| Cases | `Case` | Resolved case descriptions and solutions |
| Campaigns | `Campaign` | Product/service campaign information |
| Contacts | `Contact` | Contact directory (if relevant to agent assist) |
| Leads | `Lead` | Lead qualification information |
| Accounts | `Account` | Account/customer profile data |
| Opportunities | `Opportunity` | Deal context (less common for KB use case) |
| Custom objects | configurable | Any custom `__c` objects with relevant knowledge content |

For Enterprise AI-KB, the primary objects are `Knowledge__kav` and `Case`. Others can be enabled or disabled in configuration.

---

### Full Sync vs Incremental Sync

| | Incremental | Full |
|---|---|---|
| **SOQL filter** | `LastModifiedDate > watermark` | No date filter — all records |
| **API volume** | Low (only changed records) | Full record count per object |
| **Deletion detection** | `IsDeleted = true AND LastModifiedDate > watermark` | Full diff against ES index |
| **API governor impact** | Low | High — monitor API usage |

---

### Deletion Detection

Salesforce keeps deleted records in the Recycle Bin for 15 days. During this period, `queryAll()` returns them with `IsDeleted = true`. The connector uses this for incremental deletion detection:

```sql
SELECT Id, IsDeleted, LastModifiedDate
FROM Knowledge__kav ALL ROWS
WHERE IsDeleted = true
  AND LastModifiedDate > 2025-01-15T10:00:00Z
```

After 15 days in the Recycle Bin, records are permanently deleted and no longer queryable. This means:
- Incremental sync catches deletions within 15 days reliably
- For records permanently purged >15 days ago without being caught, only a full sync (full diff) detects them
- Weekly full sync is the safety net for this edge case

---

## When to Use / When Not to Use

| Scenario | Verdict | Reason |
|---|---|---|
| Salesforce Knowledge Articles as primary KB | ✅ Use | Exactly the target use case. Rich article structure maps well to search. |
| Case deflection — indexing resolved cases | ✅ Use | Case records with resolution notes are valuable KB content. Filter by `Status = 'Closed'`. |
| Custom Salesforce objects with knowledge content | ✅ Use | Any `__c` object with text fields can be configured as a sync target. |
| Salesforce org with <10,000 Knowledge articles | ✅ Use | Well within API governor limits for hourly incremental sync. |
| Multi-org Salesforce setup (per enterprise customer) | ✅ Use | One connector instance per Salesforce org. Standard pattern. |
| Salesforce org with >500K records across all objects | ⚠️ Partial | Monitor API governor limits. Initial full sync may take several hours. |
| Salesforce Files / ContentVersion (large attachments) | ⚠️ Partial | Binary attachment extraction works but 10 MB Tika limit applies. Large attached PDFs may be skipped. |
| Real-time sync (<5 min latency) | ⚠️ Partial | Salesforce doesn't support webhooks for the connector. Minimum cron interval is 1 minute. |
| Salesforce Event log files (debug/audit logs) | ❌ Don't use | Use Logstash Salesforce input for event logs. Connectors are for records/documents. |
| Salesforce with IP restrictions on Connected Apps | ❌ Check first | Connector VM IP must be whitelisted in Salesforce's trusted IP ranges for the Connected App. |

---

## Configuration Reference

### Core Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `domain` | string | required | Salesforce instance domain (e.g. `mycompany.my.salesforce.com` or `mycompany.sandbox.my.salesforce.com`). |
| `client_id` | string | required | Connected App consumer key. |
| `client_secret` | secret | required | Connected App consumer secret. Stored encrypted. |
| `username` | string | required | Salesforce API user username (dedicated service account recommended). |
| `password` | secret | required | Salesforce API user password + security token (concatenated: `Password123TOKEN456`). |
| `token_expiration_threshold` | integer | `60` | Seconds before token expiry to proactively refresh. Default 60s is appropriate. |
| `sobjects` | list | see defaults | List of Salesforce object API names to sync. |

---

### Connected App Setup

```
Salesforce Setup → Apps → App Manager → New Connected App

Connected App Name:  enterprise-elastic-connector
API Name:            enterprise_elastic_connector
Contact Email:       platform-team@example.com

Enable OAuth Settings: ✅
Callback URL:          https://login.salesforce.com/services/oauth2/callback
Selected OAuth Scopes:
  - Access and manage your data (api)
  - Perform requests on your behalf at any time (refresh_token, offline_access)

Require Secret for Web Server Flow: ✅
```

After creating the Connected App, note the **Consumer Key** (client_id) and **Consumer Secret** (client_secret).

---

### Required Permissions

Create a dedicated Salesforce API user (not a named human user) with these permissions:

| Permission | Why needed |
|---|---|
| `API Enabled` | Required for any REST API access |
| `View All Data` | Read access to all object records |
| `Modify All Data` | Not required — read-only access is sufficient. Do NOT grant this. |
| Object-level read access on synced objects | `Knowledge__kav`, `Case`, etc. must be readable by the API user's profile |
| Field-level read access on synced fields | All fields in the SOQL SELECT must be readable by the profile |

> **Security recommendation:** Create a dedicated Salesforce Integration User with a System Administrator profile stripped down to read-only API access only. Never use a human user account for connector authentication.

---

### Sync Schedule

```json
{
  "scheduling": {
    "incremental": {
      "enabled": true,
      "interval": "0 * * * *"
    },
    "full": {
      "enabled": true,
      "interval": "0 1 * * 0"
    }
  }
}
```

---

### Programmatic Provisioning

```python
def provision_salesforce_connector(
    tenant_id: str,
    sf_domain: str,
    client_id: str,
    client_secret: str,
    username: str,
    password_and_token: str,
    es_host: str,
    admin_key: str
) -> dict:

    es = Elasticsearch(f"https://{es_host}:9200", api_key=admin_key)

    es.connector.put(
        connector_id=f"{tenant_id}-salesforce",
        body={
            "index_name":   f"search-kb-{tenant_id}",
            "service_type": "salesforce",
            "name":         f"Tenant {tenant_id} — Salesforce",
            "configuration": {
                "domain":        {"value": sf_domain},
                "client_id":     {"value": client_id},
                "client_secret": {"value": client_secret},
                "username":      {"value": username},
                "password":      {"value": password_and_token},
                "sobjects":      {"value": [
                    "Knowledge__kav",
                    "Case"
                ]},
            },
            "scheduling": {
                "incremental": {"enabled": True, "interval": "0 * * * *"},
                "full":        {"enabled": True, "interval": "0 1 * * 0"},
            }
        }
    )
```

---

## Supported Object Types & Field Mapping

### Knowledge Articles (`Knowledge__kav`)

| Elasticsearch field | Salesforce field | Notes |
|---|---|---|
| `_id` | `Id` | Salesforce 18-character record ID |
| `body` | `ArticleBody` (or custom rich text field) | HTML stripped by Tika if HTML content |
| `title` | `Title` | Article title |
| `url` | Constructed: `https://{domain}/articles/{Id}` | Direct article URL |
| `created_at` | `CreatedDate` | ISO 8601 |
| `last_modified` | `LastModifiedDate` | Used as high-watermark |
| `author` | `CreatedBy.Name` | Requires relationship query |
| `type` | `ArticleType` | Knowledge article type |
| `language` | `Language` | Article language |

### Cases (`Case`)

| Elasticsearch field | Salesforce field | Notes |
|---|---|---|
| `_id` | `Id` | |
| `body` | `Description` + `Resolution` (concatenated) | Combined for richer search |
| `title` | `Subject` | Case subject line |
| `url` | `https://{domain}/{Id}` | |
| `created_at` | `CreatedDate` | |
| `last_modified` | `LastModifiedDate` | |
| `status` | `Status` | Filter to `Closed` for KB use |

---

## Known Limitations

| Limitation | Severity | Impact | Mitigation |
|---|---|---|---|
| Salesforce API governor limits | High | Each Salesforce org has daily API call limits (5,000–unlimited depending on edition). Connector consumes API calls on every sync. | Monitor `API Requests Last 24 Hours` in Salesforce Setup. Use Bulk API 2.0 for initial full sync of large orgs (fewer API calls for large datasets). |
| High-watermark misses batch failures | Medium | If a sync batch fails mid-way, watermark may advance past unprocessed records. | 60-second buffer mitigates clock skew. Weekly full sync catches stragglers. |
| 10 MB Tika limit on attachments | High | Large attached files silently skipped. | Pre-ingest chunking pipeline for known large attachment types. |
| Salesforce Knowledge requires specific license | Medium | `Knowledge__kav` object only accessible with Salesforce Knowledge license. Not included in all Salesforce editions. | Confirm license with customer before configuring Knowledge sync. Fall back to Case object if Knowledge not licensed. |
| Password + security token concatenation | Medium | Salesforce requires password+token as one string. Security token changes on password reset. | Dedicated API user with locked-down profile. Document token rotation procedure. |
| Deleted records only available for 15 days | Medium | Permanently purged records not detectable by incremental sync after 15-day Recycle Bin window. | Weekly full sync as safety net. |
| No Salesforce sandbox support without separate config | Low | Sandbox instances have different domains and credentials. Same connector config cannot point at both. | Maintain separate connector instances for sandbox vs production environments. |

---

## Enterprise AI-KB Deployment Notes

For this deployment, each enterprise customer has their own Salesforce org. The deployment pattern is:

- **One Connected App per Salesforce org** (per customer)
- **One Salesforce API user per org** — dedicated service account, read-only profile
- **Sync `Knowledge__kav` + `Case`** by default; enable additional objects per customer requirement
- **Filter Knowledge articles** to `PublishStatus = 'Online'` — do not index draft or archived articles
- **Filter Cases** to `Status = 'Closed'` — only resolved cases are useful as KB content

```sql
-- Recommended Knowledge sync SOQL filter
SELECT Id, Title, ArticleBody, LastModifiedDate, CreatedDate, Language, ArticleType
FROM Knowledge__kav
WHERE PublishStatus = 'Online'
  AND IsDeleted = false
  AND LastModifiedDate > :watermark

-- Recommended Case sync SOQL filter
SELECT Id, Subject, Description, Resolution__c, LastModifiedDate, CreatedDate
FROM Case
WHERE Status = 'Closed'
  AND IsDeleted = false
  AND LastModifiedDate > :watermark
```

---

## Technical Q&A

<details>
<summary><strong>Salesforce API governor limits — exactly how many API calls does the connector consume per sync cycle?</strong></summary>

For an incremental sync of a Salesforce org with 5,000 Knowledge articles where 50 were modified since last sync:

- Token acquisition: 1 call
- Knowledge SOQL query (50 records, fits in 1 page of 2,000): 1 call
- Case SOQL query (assuming 10 modified cases): 1 call
- Deletion check queries (2 object types): 2 calls
- Attachment downloads (if articles have attachments, e.g. 10 attachments): 10 calls
- **Total: ~15 API calls per incremental sync**

For a full sync of the same org (5,000 Knowledge articles + 10,000 Cases):
- Knowledge: ceil(5,000/2,000) = 3 pages = 3 calls
- Cases: ceil(10,000/2,000) = 5 pages = 5 calls
- Attachment downloads (assume 20% have attachments = 3,000 calls)
- **Total: ~3,010 API calls for full sync**

Against a typical Salesforce Enterprise edition limit of 1,000,000 calls/24h, even aggressive full syncing across 50 tenants simultaneously is well within limits. For smaller Salesforce editions (Professional = 5,000 calls/day per user), a full sync of a large org can consume the daily limit.

</details>

<details>
<summary><strong>How does the connector handle Salesforce rich text fields (HTML content in ArticleBody)?</strong></summary>

Salesforce Knowledge ArticleBody and other rich text fields return HTML content. The connector passes this HTML to Tika, which strips the HTML tags and extracts the plain text content. Embedded images in rich text are not OCR'd — their `alt` text is extracted if present.

The HTML stripping means formatting (bold, headers, lists) is lost in the indexed `body` field. For knowledge retrieval purposes this is generally acceptable — the semantic content is preserved. If the formatting context matters (e.g. step 1, step 2, step 3 in a procedure), consider pre-processing the HTML to preserve list structure before indexing.

One edge case: Salesforce sometimes stores HTML with Salesforce-specific markup like `<c:component>` tags. Tika does not understand these and may produce noisy output around them. Review Tika extraction quality on a sample of your customer's ArticleBody content before going live.

</details>

<details>
<summary><strong>If the Salesforce security token changes (password reset), how quickly does the connector fail and how do you recover?</strong></summary>

The connector fails on the next sync attempt after the token changes — typically within the hour. The failure mode is `INVALID_LOGIN: Invalid username, password, security token; or user locked out`. The sync job is marked `failed`.

Recovery steps:
1. Get the new security token from Salesforce Setup → My Personal Information → Reset My Security Token (sent via email)
2. Concatenate: `new_password + new_security_token`
3. Update via Connector API: `PUT /_connector/{id}/_configuration` with `{"password": {"value": "newpasswordNEWTOKEN"}}`
4. Trigger manual sync to verify: `POST /_connector/{id}/_sync_now`

Prevention: Use a dedicated Salesforce API user with a never-expiring password (set `Password Never Expires` in the user profile). Lock down the profile so the user cannot log in via the UI — only via API. This eliminates the password reset scenario.

</details>

<details>
<summary><strong>How does the connector handle Salesforce Knowledge's multi-language support — are all language variants indexed?</strong></summary>

Salesforce Knowledge supports articles in multiple languages as separate records — each language version is a separate `Knowledge__kav` record with the same `KnowledgeArticleId` but different `Language` field values.

The connector indexes each language version as a separate Elasticsearch document with its own `_id`. This means a Knowledge article with English, French, and Spanish versions creates 3 Elasticsearch documents.

For the the customer use case, this is the correct behaviour — each language version should be independently searchable. Ensure your index mapping includes the `language` field so you can filter search results by language at query time:

```json
GET search-kb-tenant-123/_search
{
  "query": {
    "bool": {
      "must": { "match": { "body": "reset password" } },
      "filter": { "term": { "language": "en" } }
    }
  }
}
```

</details>

---

*Connector version: Elastic 8.x · Last updated: 2025 · Enterprise AI-KB internal reference*
