# SharePoint Online Connector

> **Connector type:** Native Elastic · **Protocol:** Microsoft Graph API (delta query) · **Sync:** Cursor-based incremental + full · **Auth:** OAuth 2.0 / Azure AD app registration

---

## Table of Contents

- [Overview](#overview)
- [How It Works](#how-it-works)
  - [Incremental Sync — Step by Step](#incremental-sync--step-by-step)
  - [Delta Query — How Microsoft Graph Tracks Changes](#delta-query--how-microsoft-graph-tracks-changes)
  - [Full Sync vs Incremental Sync](#full-sync-vs-incremental-sync)
  - [Internal State Machine](#internal-state-machine)
- [When to Use / When Not to Use](#when-to-use--when-not-to-use)
- [Configuration Reference](#configuration-reference)
  - [Core Parameters](#core-parameters)
  - [Azure AD App Registration](#azure-ad-app-registration)
  - [Required API Permissions](#required-api-permissions)
  - [Sync Schedule](#sync-schedule)
  - [Programmatic Provisioning](#programmatic-provisioning)
- [Supported Content Types](#supported-content-types)
- [Known Limitations](#known-limitations)
- [Genesys AI-KB Deployment Notes](#genesys-ai-kb-deployment-notes)
  - [Site & Library Scoping](#site--library-scoping)
  - [Per-Tenant Provisioning Script](#per-tenant-provisioning-script)
  - [Monitoring](#monitoring)
- [Technical Q&A](#technical-qa)

---

## Overview

The Elastic SharePoint Online Connector synchronises documents from SharePoint Online document libraries and site pages into Elasticsearch using the **Microsoft Graph API**. Unlike the S3 connector's ETag-based polling, SharePoint uses **delta queries** — a cursor mechanism built into the Graph API that tracks changes server-side, so the connector only receives items that actually changed since the last sync rather than listing everything and diffing locally.

In the Genesys AI-KB architecture, the SharePoint connector indexes tenant knowledge base content stored in SharePoint document libraries — SOPs, FAQ pages, policy documents, and wiki content — making it searchable via BM25 + Jina v3 semantic hybrid search.

```
SharePoint Online (document libraries, site pages)
        │
        ▼
Microsoft Graph API (delta query — cursor-based)
        │
        ▼
Connector Process (Python 3.10+ / MSAL)
        │
        ▼
Apache Tika (content extraction)
        │
        ▼
Elasticsearch Bulk API ──► Ingest Pipeline (Jina v3 embedding)
        │
        ▼
Tenant Index (BM25 + kNN searchable)
```

| Component | Technology | Role |
|---|---|---|
| Connector process | Python 3.10+ / MSAL (Microsoft Authentication Library) | Authenticates, calls Graph API, manages delta tokens |
| Graph API client | `requests` + Microsoft Graph v1.0 | Lists drives, fetches items, downloads content |
| Content extractor | Apache Tika (embedded) | Extracts text from Office documents, PDF, HTML |
| Delta token store | `.elastic-connectors` `sync_cursor` field | Cursor pointing to next delta page — the key incremental state |
| Ingest pipeline | Elasticsearch ingest node | Jina v3 embedding, field normalisation, PII redaction |
| Target store | Elasticsearch index | Tenant-scoped, BM25 + kNN searchable |

---

## How It Works

### Incremental Sync — Step by Step

1. **Schedule trigger** — Connector reads cron schedule from `.elastic-connectors`. Default: `0 * * * *` (hourly).

2. **OAuth token acquisition** — MSAL uses the Azure AD app's `client_id` + `client_secret` to request a bearer token from `https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token`. Token is cached in memory and refreshed before expiry (typically 1 hour).

3. **Site enumeration** — Connector calls `GET /sites?search=*` (or the configured `site_collections` list) to enumerate SharePoint sites in scope.

4. **Drive enumeration** — For each site, calls `GET /sites/{site_id}/drives` to list document libraries.

5. **Delta query** — For each drive, calls `GET /drives/{drive_id}/root/delta?token={delta_token}` using the stored delta token from the previous sync. Graph API returns only items that changed (created, modified, deleted) since that token was issued.

6. **Content download** — For each new/modified item, calls `GET /drives/{drive_id}/items/{item_id}/content` to download the file binary.

7. **Tika extraction** — Binary content is passed to Apache Tika for text extraction. Same 10 MB limit applies.

8. **Field mapping** — Extracted content and SharePoint metadata are mapped to the Elastic document schema:

   | Elasticsearch field | Source |
   |---|---|
   | `_id` | SharePoint item ID |
   | `body` | Tika-extracted text |
   | `title` | SharePoint item name |
   | `url` | SharePoint web URL (`webUrl` field) |
   | `created_at` | `createdDateTime` |
   | `last_modified` | `lastModifiedDateTime` |
   | `created_by` | `createdBy.user.displayName` |
   | `size` | File size in bytes |
   | `mime_type` | SharePoint `file.mimeType` |

9. **Bulk indexing** — Documents batched and sent to Elasticsearch `_bulk` endpoint with the ingest pipeline parameter.

10. **Deletion handling** — Items returned by delta query with `deleted` flag set are issued as DELETE operations in the bulk request.

11. **Delta token update** — On successful completion, the new delta token (from the `@odata.deltaLink` in the final Graph API response) is saved to `sync_cursor` in `.elastic-connectors`.

---

### Delta Query — How Microsoft Graph Tracks Changes

The delta query is the key architectural difference from S3. Instead of listing all files and comparing locally, the connector asks Graph API: **"give me everything that changed since my last cursor."**

```
First sync:
GET /drives/{id}/root/delta
← Returns all items + @odata.deltaLink (cursor for next sync)

Second sync (incremental):
GET /drives/{id}/root/delta?token={cursor_from_step_1}
← Returns ONLY items changed since cursor was issued
← Returns new @odata.deltaLink for next sync

If page has more results:
GET {nextLink}  ← follows pagination until @odata.deltaLink appears
```

The delta token is opaque — it encodes the change position in Microsoft's change feed. If the token expires (Microsoft retains delta tokens for ~30 days), the connector falls back to a full sync automatically.

> **Key advantage over S3:** No full bucket listing required. For a library with 50,000 documents where only 20 changed in the last hour, the delta query returns 20 items — not 50,000.

---

### Full Sync vs Incremental Sync

| | Incremental | Full |
|---|---|---|
| **Trigger** | Cron (default: hourly) | Cron (default: weekly) + automatic delta token expiry |
| **Graph API calls** | Proportional to number of changes | Proportional to total item count |
| **Deletion detection** | Yes — `deleted` flag in delta response | Yes — full crawl + diff against ES index |
| **Delta token used?** | Yes | No — starts fresh, generates new token |
| **Fallback trigger** | N/A | Delta token expired (>30 days since last sync) |

---

### Internal State Machine

Same two-index pattern as all Elastic connectors:

**`.elastic-connectors`** — `sync_cursor` field stores the delta token per drive:

```json
{
  "sync_cursor": {
    "drive_id_abc123": "token_xyz...",
    "drive_id_def456": "token_uvw..."
  }
}
```

If a drive's delta token is missing or expired, that drive falls back to full sync automatically on next execution.

**`.elastic-connector-sync-jobs`** — tracks job execution, `indexed_document_count`, `deleted_document_count`, errors.

---

## When to Use / When Not to Use

| Scenario | Verdict | Reason |
|---|---|---|
| SharePoint Online document libraries (DOCX, PDF, PPTX) | ✅ Use | Primary use case. Delta query is efficient for typical document library churn rates. |
| SharePoint site pages / wiki content | ✅ Use | Site pages are supported via the Pages API. Good for wiki-style knowledge bases. |
| Multiple SharePoint sites per tenant | ✅ Use | Connector enumerates all sites in scope automatically. Configurable via `site_collections` allowlist. |
| OneDrive for Business | ✅ Use | Uses same Graph API. Configure as a drive under the user's site. |
| SharePoint Server (on-premises) | ❌ Don't use | On-premises SharePoint uses a different REST API. Requires custom connector. |
| SharePoint lists (not document libraries) | ⚠️ Partial | List items are supported but content extraction is limited to text fields — no binary attachment extraction from list attachments. |
| Very large libraries (>500K items, rarely changing) | ⚠️ Partial | Initial full sync is slow. Delta queries after that are fast. Plan for a long first-sync window. |
| Tenant using legacy SharePoint 2013 / 2016 workflows | ⚠️ Check | Workflow-generated documents may have unusual metadata. Test extraction quality on a sample. |
| Documents requiring SharePoint permissions enforcement | ❌ Not natively | Connector indexes all content the app registration can access. Row-level security / user-level access control not enforced in search results. |

---

## Configuration Reference

### Core Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `tenant_id` | string | required | Azure AD tenant ID (GUID). Found in Azure Portal → Azure Active Directory → Overview. |
| `tenant_name` | string | required | Your SharePoint tenant name (e.g. `genesys` for `genesys.sharepoint.com`). |
| `client_id` | string | required | Azure AD application (client) ID of the registered app. |
| `client_secret` | secret | required | Azure AD app client secret. Stored encrypted in `.elastic-connectors`. Rotate every 12 months. |
| `site_collections` | list of strings | `[]` (all sites) | Allowlist of site collection URLs. Empty = crawl all sites the app can access. For multi-tenant Genesys: set to specific tenant site. |
| `use_text_extraction_service` | boolean | `false` | Use Elastic's hosted text extraction service instead of local Tika. Set `false` for self-managed. |
| `use_document_level_security` | boolean | `false` | Enforce SharePoint ACLs in search results. Requires additional Graph API permissions. |

---

### Azure AD App Registration

Create one app registration per Genesys deployment region (not per tenant — one app covers all SharePoint tenants accessible in that Azure AD).

```
Azure Portal → Azure Active Directory → App registrations → New registration

Name:           genesys-elastic-connector-{region}
Account type:   Accounts in this organizational directory only
Redirect URI:   (leave blank — this is a daemon/service app, no user login)

After creation:
→ Certificates & secrets → New client secret (set 24-month expiry)
→ API permissions → Add permissions (see below)
→ Grant admin consent
```

---

### Required API Permissions

All permissions are **Application** type (not Delegated) — the connector runs as a background service with no user context.

| Permission | Type | Why needed |
|---|---|---|
| `Sites.Read.All` | Application | Enumerate SharePoint sites and read site metadata |
| `Files.Read.All` | Application | Read all files in all document libraries |
| `User.Read.All` | Application | Resolve `createdBy` / `modifiedBy` user display names |

> **Admin consent required** — these are high-privilege permissions. A Global Administrator or SharePoint Administrator must click "Grant admin consent" in the Azure Portal for the permissions to take effect.

> **Principle of least privilege note:** `Files.Read.All` grants access to ALL files across ALL sites in the tenant. For Genesys multi-tenant deployments where each "tenant" is a separate SharePoint tenant (separate Azure AD), this is fine. If multiple Genesys customers share one Azure AD tenant, use `site_collections` allowlist to scope access.

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
      "interval": "0 3 * * 0"
    }
  }
}
```

---

### Programmatic Provisioning

```http
PUT /_connector/tenant-123-sharepoint
Content-Type: application/json

{
  "index_name": "search-kb-tenant-123",
  "name": "Tenant 123 — SharePoint Online",
  "service_type": "sharepoint_online",
  "configuration": {
    "tenant_id":     { "value": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" },
    "tenant_name":   { "value": "tenant123corp" },
    "client_id":     { "value": "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy" },
    "client_secret": { "value": "your-client-secret-here" },
    "site_collections": { "value": [
      "https://tenant123corp.sharepoint.com/sites/KnowledgeBase"
    ]},
    "use_document_level_security": { "value": false }
  },
  "scheduling": {
    "incremental": { "enabled": true, "interval": "0 * * * *" },
    "full":        { "enabled": true, "interval": "0 3 * * 0" }
  }
}
```

---

## Supported Content Types

Same Tika-based extraction as S3. SharePoint-specific notes:

| Format | Notes |
|---|---|
| DOCX / XLSX / PPTX | Full extraction including embedded metadata (author, last modified by). |
| SharePoint site pages (ASPX) | HTML rendered content extracted — navigation chrome stripped by Tika. |
| OneNote (.one) | **Not supported** — Tika cannot parse OneNote binary format. OneNote content is silently skipped. |
| Embedded images in DOCX | Not OCR'd — image text is not extracted. |
| SharePoint list attachments | Not extracted in list sync mode. Only document library binary files are extracted. |
| Files >10 MB | Silently skipped by Tika. See [Known Limitations](#known-limitations). |

---

## Known Limitations

| Limitation | Severity | Impact | Mitigation |
|---|---|---|---|
| 10 MB Tika extraction limit | High | Large files silently skipped. | Pre-ingest chunking pipeline. Dead-letter index for skipped docs. |
| OneNote files not supported | Medium | OneNote notebooks are silently skipped. | Export OneNote pages to DOCX/PDF before connector sync, or accept the gap. |
| No document-level security enforcement | Medium | Connector indexes all accessible content regardless of SharePoint permissions. Search results do not reflect user-level ACLs. | Use Kibana Spaces + index-level permissions for tenant isolation. DLS requires additional configuration if needed. |
| Delta token expiry (30 days) | Low | If no sync runs for >30 days, delta token expires and next sync is a full crawl. | Keep incremental sync enabled. Monitor `.elastic-connector-sync-jobs` for `full` jobs triggered unexpectedly. |
| Throttling by Microsoft Graph API | Medium | Microsoft throttles Graph API at 10,000 requests per 10 minutes per app. Large initial syncs may hit this. Connector retries with backoff but sync time increases. | Schedule initial full syncs for off-peak hours. Stagger full syncs across tenants. |
| Guest/external user content | Low | Content shared with external users is indexed if the app registration has access. | Use `site_collections` allowlist to scope to known internal sites only. |
| SharePoint Syntex AI-processed content | Low | AI-extracted metadata from Syntex is not automatically included. Only standard SharePoint metadata fields are mapped. | Add custom field mappings via ingest pipeline if Syntex metadata is needed. |
| Client secret rotation | Medium | Connector fails immediately when client secret expires. No automatic rotation. | Set 12-month expiry. Calendar reminder for renewal. Update `.elastic-connectors` via Connector API when renewed. |

---

## Genesys AI-KB Deployment Notes

### Site & Library Scoping

For Genesys multi-tenant deployments, each customer tenant has its own SharePoint Online subscription (separate Azure AD). This means:

- One Azure AD app registration per customer tenant
- One connector instance per customer tenant
- `site_collections` should be set to the specific knowledge base site URL

```
Customer Tenant A (Azure AD: tenant-a.onmicrosoft.com)
  └── App registration: genesys-elastic-connector-us-east-1
  └── Site: https://tenanta.sharepoint.com/sites/KnowledgeBase
  └── Connector ID: tenant-a-sharepoint
  └── ES Index: search-kb-tenant-a

Customer Tenant B (Azure AD: tenant-b.onmicrosoft.com)
  └── App registration: genesys-elastic-connector-us-east-1
  └── Site: https://tenantb.sharepoint.com/sites/KnowledgeBase
  └── Connector ID: tenant-b-sharepoint
  └── ES Index: search-kb-tenant-b
```

### Per-Tenant Provisioning Script

```python
#!/usr/bin/env python3
"""
provision_sharepoint_connector.py
Run at tenant onboarding after Azure AD app registration is complete.
"""
from elasticsearch import Elasticsearch

def provision_sharepoint_connector(
    tenant_id: str,
    azure_tenant_id: str,
    azure_tenant_name: str,
    client_id: str,
    client_secret: str,
    site_url: str,
    es_host: str,
    admin_key: str
) -> dict:

    es = Elasticsearch(f"https://{es_host}:9200", api_key=admin_key)

    # Scoped API key
    key_resp = es.security.create_api_key(
        name=f"sharepoint-connector-{tenant_id}",
        role_descriptors={
            f"connector-{tenant_id}": {
                "indices": [{
                    "names": [f"search-kb-{tenant_id}*"],
                    "privileges": ["write", "create_index", "manage", "read"]
                }]
            }
        }
    )

    es.connector.put(
        connector_id=f"{tenant_id}-sharepoint",
        body={
            "index_name":   f"search-kb-{tenant_id}",
            "service_type": "sharepoint_online",
            "name":         f"Tenant {tenant_id} — SharePoint Online",
            "configuration": {
                "tenant_id":     {"value": azure_tenant_id},
                "tenant_name":   {"value": azure_tenant_name},
                "client_id":     {"value": client_id},
                "client_secret": {"value": client_secret},
                "site_collections": {"value": [site_url]},
                "use_document_level_security": {"value": False},
            },
            "scheduling": {
                "incremental": {"enabled": True, "interval": "0 * * * *"},
                "full":        {"enabled": True, "interval": "0 3 * * 0"},
            }
        }
    )

    return {
        "tenant_id":    tenant_id,
        "connector_id": f"{tenant_id}-sharepoint",
        "index":        f"search-kb-{tenant_id}",
        "api_key_id":   key_resp["id"],
    }
```

### Monitoring

Monitor Graph API throttling via sync job error messages:

```json
GET .elastic-connector-sync-jobs/_search
{
  "query": {
    "bool": {
      "filter": [
        { "term": { "status": "failed" } },
        { "match": { "error": "throttled" } }
      ]
    }
  }
}
```

Monitor unexpected full syncs (delta token expiry indicator):

```json
GET .elastic-connector-sync-jobs/_search
{
  "query": {
    "bool": {
      "filter": [
        { "term": { "job_type": "full" } },
        { "range": { "started_at": { "gte": "now-7d" } } }
      ]
    }
  },
  "aggs": {
    "by_connector": {
      "terms": { "field": "connector.id" }
    }
  }
}
```

---

## Technical Q&A

<details>
<summary><strong>How does delta query handle the case where a file is moved between SharePoint libraries — is it treated as a delete + create or as an update?</strong></summary>

When a file is moved between libraries within the same SharePoint site, the Graph API delta query returns two entries: a `deleted` entry for the item's old location (in the source library's delta feed) and a `created` entry for the new location (in the destination library's delta feed). The connector processes these independently per drive — so the old document is deleted from the Elasticsearch index and a new document is indexed at the new URL.

This means moving files between libraries causes a brief period (until next sync) where the document appears in search with its old URL. It also generates a new Elasticsearch `_id` (based on the new SharePoint item ID) so there is no document update — it's a delete and re-index. The practical impact for knowledge base use cases is minimal since moves are rare.

Moving files within the same library (renaming a folder) is handled differently — the delta query returns a `modified` entry with the updated `parentReference.path`, so it's processed as an update and the `url` field is refreshed.

</details>

<details>
<summary><strong>What happens when the Azure AD client secret expires mid-sync? Is there a graceful degradation?</strong></summary>

No graceful degradation. The MSAL token request fails immediately with `AADSTS7000215: Invalid client secret provided`. The sync job is marked `failed` with the authentication error. All subsequent scheduled syncs also fail until the secret is renewed.

The connector does not cache a previously acquired token across sync cycles — it requests a fresh token at the start of each sync. So there's no grace window where cached tokens keep working.

The operational requirement is a calendar reminder set 30 days before secret expiry. When renewing: generate a new secret in Azure Portal, update the `client_secret` field via the Connector API (`PUT /_connector/{id}/_configuration`), then trigger a manual sync to confirm authentication works before the old secret expires. Keep the old secret active for 24 hours as a rollback option.

</details>

<details>
<summary><strong>Graph API has a complex throttling model — exactly what limits apply and how does the connector handle them?</strong></summary>

Microsoft Graph throttling for SharePoint is service-specific and not always well-documented. The known limits:

- **Per-app per-tenant:** 10,000 requests per 10 minutes (application-level)
- **Per-resource:** Additional per-site, per-drive limits may apply during heavy load
- **Retry-After header:** When throttled, Graph returns `429 Too Many Requests` with a `Retry-After` header specifying seconds to wait

The Elastic SharePoint connector handles `429` responses by reading the `Retry-After` header and sleeping for that duration before retrying. This is built into the connector's HTTP client layer and is transparent to the sync job.

The throttling concern is mainly during initial full sync of large tenants. A library with 50,000 documents at 100 items per Graph API page = 500 listing requests + 50,000 content download requests = 50,500 requests, which spans 5+ throttling windows at 10,000/10min. Expect a full sync of a large library to take 60–90 minutes due to throttling pauses. Incremental syncs of typical knowledge base churn (20–100 changed items per hour) never approach the throttling limit.

</details>

<details>
<summary><strong>If a SharePoint document is checked out by a user, does the connector index the checked-out version or the last published version?</strong></summary>

The connector always indexes the **last published (major) version** — the version visible to users with read access. A checked-out document has its changes in a draft/minor version that is not accessible to the application's `Files.Read.All` permission unless the app is also granted access to draft versions.

This is actually the correct behaviour for a knowledge base use case — agents should see approved, published content, not in-progress drafts. If a document is checked out and not published, the connector continues to index the previous published version until the author checks in and publishes.

The implication: if a knowledge base author checks out a document, makes significant changes, and leaves it checked out for several days, agents are searching against potentially stale content. This is a process issue, not a connector issue — knowledge base governance should require timely check-in.

</details>

<details>
<summary><strong>Does the connector support SharePoint's version history — can we index previous versions of a document?</strong></summary>

No. The connector indexes the current published version only. SharePoint's version history is accessible via `GET /drives/{drive_id}/items/{item_id}/versions` but the connector does not call this endpoint.

Indexing version history would require a custom connector fork. For compliance use cases where historical document versions need to be searchable, the recommended approach is to use SharePoint's export-to-S3 functionality to archive versions, then use the S3 connector to index the archive.

</details>

<details>
<summary><strong>How does the connector handle SharePoint content types and custom metadata columns?</strong></summary>

Standard SharePoint metadata columns (single-line text, date, person fields) that are part of the item's `listItem.fields` are available in the Graph API response. However, the connector's default field mapping only extracts the standard fields listed in the document schema section.

Custom metadata columns are NOT automatically indexed. To index custom columns, you need to add an ingest pipeline processor that extracts additional fields from the raw document. The connector passes the full Graph API item response through the pipeline, so custom fields are accessible at pipeline processing time.

Example: If your SharePoint library has a custom `Department` column, add a `set` processor in the ingest pipeline:

```json
{
  "set": {
    "field": "department",
    "value": "{{_source.listItem.fields.Department}}"
  }
}
```

</details>

---

*Connector version: Elastic 8.x · Last updated: 2025 · Genesys AI-KB internal reference*
