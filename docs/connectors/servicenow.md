# ServiceNow Connector

> **Connector type:** Native Elastic · **Protocol:** ServiceNow REST API (Table API) · **Sync:** High-watermark timestamp · **Auth:** Basic auth / OAuth 2.0

---

## Table of Contents

- [Overview](#overview)
- [How It Works](#how-it-works)
  - [Incremental Sync - Step by Step](#incremental-sync--step-by-step)
  - [Table API Query Mechanics](#table-api-query-mechanics)
  - [Full Sync vs Incremental Sync](#full-sync-vs-incremental-sync)
  - [Deletion Detection](#deletion-detection)
- [When to Use / When Not to Use](#when-to-use--when-not-to-use)
- [Configuration Reference](#configuration-reference)
  - [Core Parameters](#core-parameters)
  - [ServiceNow User & Role Setup](#servicenow-user--role-setup)
  - [Sync Schedule](#sync-schedule)
  - [Programmatic Provisioning](#programmatic-provisioning)
- [Supported Tables & Field Mapping](#supported-tables--field-mapping)
- [Known Limitations](#known-limitations)
- [Enterprise AI-KB Deployment Notes](#enterprise-ai-kb-deployment-notes)
- [Technical Q&A](#technical-qa)

---

## Overview

The Elastic ServiceNow Connector synchronises records from ServiceNow tables into Elasticsearch using the **ServiceNow Table API**. Like the Salesforce connector, it uses a **high-watermark timestamp** (`sys_updated_on > last_sync_timestamp`) for incremental change detection - a SOQL-style filter native to the Table API's `sysparm_query` parameter.

In the Enterprise AI-KB architecture, the ServiceNow connector is the primary source for **IT knowledge base articles**, **incident resolutions**, and **problem records** - content that contact centre agents need when handling technical support queries.

```
ServiceNow Instance (Knowledge Base, Incidents, Problems, Changes)
        │
        ▼
ServiceNow Table API (/api/now/table/{table_name})
        │
        ▼
Connector Process (Python 3.10+ / requests)
        │
        ▼
Elasticsearch Bulk API ──► Ingest Pipeline (Jina v3 embedding)
        │
        ▼
Tenant Index (BM25 + kNN searchable)
```

---

## How It Works

### Incremental Sync - Step by Step

1. **Schedule trigger** - Reads cron from `.elastic-connectors`. Default: `0 * * * *`.

2. **Authentication** - Basic auth (username:password as Base64 header) or OAuth 2.0. Basic auth is simpler for service accounts but OAuth is preferred for production.

3. **Watermark read** - Loads `last_sync_timestamp` from `.elastic-connectors` `sync_cursor`.

4. **Table API query** - For each configured table, calls:

   ```
   GET /api/now/table/kb_knowledge
     ?sysparm_query=sys_updated_on>2025-01-15T10:00:00Z^workflow_state=published
     &sysparm_fields=sys_id,short_description,text,sys_updated_on,...
     &sysparm_limit=1000
     &sysparm_offset=0
     &sysparm_display_value=false
   ```

5. **Pagination** - ServiceNow returns up to `sysparm_limit` records per request. Connector increments `sysparm_offset` until fewer records than limit are returned (no cursor token - offset-based pagination).

6. **Attachment fetch** - For records with attachments, calls `GET /api/now/attachment/{sys_id}/file` to download binary content.

7. **Field mapping** - Record fields mapped to Elastic document schema.

8. **Bulk indexing** - Documents sent to `_bulk` API with ingest pipeline.

9. **Deletion handling** - Separate query for soft-deleted records (see [Deletion Detection](#deletion-detection)).

10. **Watermark update** - `sync_cursor` updated to `now() - 60 seconds`.

---

### Table API Query Mechanics

ServiceNow's Table API uses `sysparm_query` for filtering - a string-encoded query language called **GlideRecord query syntax**:

```
# Basic filter: updated after watermark
sys_updated_on>2025-01-15T10:00:00Z

# Compound filter: updated after watermark AND published
sys_updated_on>2025-01-15T10:00:00Z^workflow_state=published

# Multiple conditions use ^ (AND) or ^OR (OR)
sys_updated_on>2025-01-15T10:00:00Z^active=true^kb_category!=NULL
```

The connector constructs these query strings automatically based on the table configuration and watermark value.

**`sysparm_display_value=false`** - Always use `false` for the connector. Display values are the human-readable versions of reference fields (e.g. "John Smith" instead of the user sys_id). Using `false` returns raw values (sys_ids, enum codes) which are more stable for indexing. The connector maps display names separately via relationship lookups where needed.

---

### Full Sync vs Incremental Sync

| | Incremental | Full |
|---|---|---|
| **Query filter** | `sys_updated_on > watermark` | No date filter |
| **Offset pagination** | Yes - offset increments per page | Yes - same mechanism |
| **Deletion detection** | `sys_deleted_at > watermark` query | Full diff against ES index |
| **API call volume** | Low | Proportional to total record count |

---

### Deletion Detection

ServiceNow uses **soft deletes** - records deleted via the UI are marked with a `sys_deleted_at` timestamp and removed from normal table queries but remain in the database. The connector queries for these:

```
GET /api/now/table/kb_knowledge
  ?sysparm_query=sys_deleted_at>2025-01-15T10:00:00Z
  &sysparm_fields=sys_id,sys_deleted_at
```

Hard deletes (records purged from the database) are not detectable by incremental sync - only a full sync can catch them via ES index diff. ServiceNow rarely hard-deletes records except via automated purge jobs, so this is a low-frequency edge case.

---

## When to Use / When Not to Use

| Scenario | Verdict | Reason |
|---|---|---|
| ServiceNow Knowledge Base articles | ✅ Use | Primary use case. `kb_knowledge` table is well-structured for search. |
| Incident resolution notes as KB content | ✅ Use | Closed incidents with resolution notes are valuable for deflection. Filter by `state=6` (Closed). |
| Problem records and known error database (KEDB) | ✅ Use | `problem` and `kb_knowledge` (KEDB articles) are high-value for technical KB. |
| Change records / CAB notes | ⚠️ Partial | Change records can be voluminous. Filter carefully to avoid indexing all change history. |
| ServiceNow as ITSM (not KB) - just for case creation | ❌ Don't use | Use the Elastic ServiceNow integration (bi-directional ITSM) instead of the connector. |
| ServiceNow Performance Analytics data | ❌ Don't use | Use Elasticsearch's JDBC input or ServiceNow PA APIs directly. |
| ServiceNow with IP whitelisting | ⚠️ Check first | Connector VM IPs must be in ServiceNow's IP access list if the instance has IP restrictions enabled. |
| Scoped applications / custom tables | ✅ Use | Any table accessible via the Table API works. Specify table name in `serviceNow_object_types`. |

---

## Configuration Reference

### Core Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | string | required | ServiceNow instance URL (e.g. `https://mycompany.service-now.com`). Include `https://`, no trailing slash. |
| `username` | string | required | ServiceNow user login name. Use a dedicated integration user. |
| `password` | secret | required | ServiceNow user password. Stored encrypted in `.elastic-connectors`. |
| `services` | list | `["knowledge","incident","problem"]` | List of ServiceNow table names to sync. |
| `retry_count` | integer | `3` | Number of retries on API failure before marking sync as failed. |

---

### ServiceNow User & Role Setup

Create a dedicated ServiceNow integration user:

```
ServiceNow → User Administration → Users → New

User ID:      elastic-connector-svc
First name:   Elastic
Last name:    Connector
Email:        platform-team@company.com
Active:       ✅
Web service access only: ✅  ← Important: prevents UI login
```

Assign roles:

| Role | Why needed |
|---|---|
| `snc_read_only` | Read-only access to all table records |
| `knowledge` | Read access to Knowledge Base articles |
| `itil` | Read access to Incidents, Problems, Changes |

> **`web_service_access_only` flag is critical.** This prevents the service account from logging into the ServiceNow UI, which would consume a named user license. API access does not require a named user license when this flag is set (depending on ServiceNow contract - verify with your ServiceNow admin).

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
      "interval": "0 4 * * 0"
    }
  }
}
```

---

### Programmatic Provisioning

```python
def provision_servicenow_connector(
    tenant_id: str,
    snow_url: str,
    snow_username: str,
    snow_password: str,
    tables: list,
    es_host: str,
    admin_key: str
) -> dict:

    es = Elasticsearch(f"https://{es_host}:9200", api_key=admin_key)

    es.connector.put(
        connector_id=f"{tenant_id}-servicenow",
        body={
            "index_name":   f"search-kb-{tenant_id}",
            "service_type": "servicenow",
            "name":         f"Tenant {tenant_id} - ServiceNow",
            "configuration": {
                "url":      {"value": snow_url},
                "username": {"value": snow_username},
                "password": {"value": snow_password},
                "services": {"value": tables},
            },
            "scheduling": {
                "incremental": {"enabled": True, "interval": "0 * * * *"},
                "full":        {"enabled": True, "interval": "0 4 * * 0"},
            }
        }
    )
```

---

## Supported Tables & Field Mapping

### Knowledge Base (`kb_knowledge`)

| Elasticsearch field | ServiceNow field | Notes |
|---|---|---|
| `_id` | `sys_id` | ServiceNow unique record ID |
| `body` | `text` | Full article HTML body - Tika strips HTML tags |
| `title` | `short_description` | Article title |
| `url` | `https://{instance}/kb?id=kb_article&sysparm_article={number}` | Direct article URL |
| `created_at` | `sys_created_on` | |
| `last_modified` | `sys_updated_on` | Used as high-watermark |
| `author` | `author.name` | Resolved display name |
| `category` | `kb_category.label` | Knowledge category |
| `workflow_state` | `workflow_state` | Filter to `published` only |

### Incidents (`incident`)

| Elasticsearch field | ServiceNow field | Notes |
|---|---|---|
| `_id` | `sys_id` | |
| `body` | `description` + `close_notes` (concatenated) | Combined for richer search |
| `title` | `short_description` | Incident subject |
| `url` | `https://{instance}/nav_to.do?uri=incident.do?sys_id={sys_id}` | |
| `created_at` | `sys_created_on` | |
| `last_modified` | `sys_updated_on` | |
| `category` | `category` | Incident category |
| `state` | `state` | Filter to `6` (Closed) or `7` (Resolved) for KB use |

---

## Known Limitations

| Limitation | Severity | Impact | Mitigation |
|---|---|---|---|
| Offset-based pagination (no cursor) | Medium | Large tables paginated by offset - if records inserted mid-sync, offset shifts and some records may be double-indexed or skipped. | Order by `sys_updated_on ASC` + watermark filter minimises this. Weekly full sync catches stragglers. |
| 10 MB Tika limit on attachments | High | Large attached files silently skipped. | Pre-ingest chunking for known large attachment types. |
| ServiceNow rate limiting | Medium | ServiceNow instances throttle API calls during peak hours. Connector retries but sync time increases. | Schedule full syncs off-peak. Monitor sync job duration. |
| HTML in `text` field | Low | Knowledge article body is HTML. Tika strips tags but formatting context is lost. | Accept for KB use case. Pre-process if list/table structure matters. |
| `sys_display_value` vs raw values | Low | Using display values causes brittleness (user display names can change). | Always use `sysparm_display_value=false`. Resolve display names via separate lookup at ingest time if needed. |
| ServiceNow Vault encrypted fields | High | Fields encrypted with ServiceNow Vault are returned as `***` - content not accessible via API. | Confirm which fields are vault-encrypted with the customer's ServiceNow admin before configuring sync. |
| MID Server environments | Medium | Some ServiceNow instances route all API traffic through a MID Server. Connector VM must be network-accessible to the MID Server, not directly to the ServiceNow instance. | Verify network path with customer's ServiceNow team during onboarding. |

---

## Enterprise AI-KB Deployment Notes

For this deployment, each enterprise customer has their own ServiceNow instance. Standard deployment:

- **One connector instance per ServiceNow instance** (per customer)
- **Sync `kb_knowledge` + `incident` + `problem`** - configure per customer based on what knowledge content they maintain in ServiceNow
- **Filter Knowledge articles** to `workflow_state=published` only
- **Filter Incidents** to `state=6` (Closed) for resolution-based KB content
- **Filter Problems** to `known_error=true` for KEDB (Known Error Database) articles

```
# Recommended query filters per table:

kb_knowledge:
  sysparm_query: workflow_state=published^active=true

incident:
  sysparm_query: state=6^close_codeISNOTEMPTY

problem:
  sysparm_query: known_error=true^state=4
```

---

## Technical Q&A

<details>
<summary><strong>ServiceNow's offset-based pagination is a known issue - if a new record is inserted into a table while the connector is paginating through it, what exactly happens?</strong></summary>

This is the classic offset pagination consistency problem. The connector queries with `ORDER BY sys_updated_on ASC LIMIT 1000 OFFSET 0`, then `OFFSET 1000`, then `OFFSET 2000`, etc.

If a new record is inserted (or an existing record's `sys_updated_on` is updated to a newer timestamp) between page 1 and page 2:

- The new/updated record falls somewhere in the ordering sequence
- Every record after it shifts one position in the ordered result set
- The record that was at position 1000 (last item of page 1) is now at position 1001 - it appears in the OFFSET 1000 query again (duplicated) OR a different record is now at position 1000 and the original 1000th record is missed

**Net effect:** Some records may be indexed twice (harmless - same `_id` overwrites cleanly) or some records may be skipped in that sync cycle. The skipped records will be caught in the next incremental sync (their `sys_updated_on` still matches the watermark condition) or the weekly full sync.

The watermark filter (`sys_updated_on > timestamp`) significantly reduces the frequency of this issue because the working set per sync is typically small (only records changed in the last hour). The problem is most pronounced during initial full sync of large tables.

</details>

<details>
<summary><strong>How does the connector handle ServiceNow's multi-language knowledge base - articles in different languages?</strong></summary>

ServiceNow Knowledge supports multiple languages via the `kb_knowledge_translation` table. The main `kb_knowledge` record contains the base language (typically English), while translations are stored as separate records in the translation table.

The connector by default only syncs the base `kb_knowledge` table - it does not automatically traverse to `kb_knowledge_translation`. To index translated articles, add `kb_knowledge_translation` as an additional table in the `services` configuration.

Each translation record has its own `sys_id` and maps back to the base article via the `document_id` field. You can use an ingest pipeline processor to add a `parent_article_id` field linking translations to the base article, enabling language-aware search queries.

</details>

<details>
<summary><strong>Can the connector access tables in scoped applications, or only the global scope?</strong></summary>

Yes - any table accessible via the Table API is reachable by the connector, regardless of whether it's in a scoped application or the global scope. The connector calls `/api/now/table/{table_name}` where `table_name` is the full table name including scope prefix (e.g. `x_myapp_knowledge_article` for a scoped app table).

The requirement is that the integration user's roles grant read access to the scoped table. ServiceNow's scoped application architecture may restrict access - check the table's Application Access settings and ensure `Can Read` is enabled for the integration user's role.

Test table accessibility before configuring the connector:
```bash
curl -u username:password \
  "https://instance.service-now.com/api/now/table/x_myapp_custom_table?sysparm_limit=1"
```

A `200` with records confirms access. A `403` means role/permission issue.

</details>

<details>
<summary><strong>What is the actual API call sequence for a sync of the kb_knowledge table with 10,000 articles?</strong></summary>

Full sync of 10,000 knowledge articles:

1. **Auth** - 1 call (Basic auth - included as header on every request, not a separate call)
2. **Page 1:** `GET /api/now/table/kb_knowledge?sysparm_limit=1000&sysparm_offset=0` → 1,000 records
3. **Pages 2-10:** 9 more requests with offset 1000, 2000, ..., 9000
4. **Page 11:** `sysparm_offset=10000` → fewer than 1,000 records → sync complete
5. **Attachment download:** If 20% of articles have attachments → 2,000 `GET /api/now/attachment?sysparm_query=table_sys_id={id}` + content download calls

**Total: ~2,012 API calls for a full sync of 10,000 articles with attachments.**

Incremental sync of the same instance (50 articles changed since last hour):
- 1 query page (50 records < 1,000 limit)
- ~10 attachment downloads (if articles have attachments)
- **Total: ~12 API calls**

ServiceNow's default rate limit is typically 10,000 requests per hour per user - both sync patterns are well within this for the Enterprise 5,000-articles-per-tenant baseline.

</details>

---

*Connector version: Elastic 8.x · Last updated: 2025 · Enterprise AI-KB internal reference*
