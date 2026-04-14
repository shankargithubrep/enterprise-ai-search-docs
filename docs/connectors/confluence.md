# Confluence Connector

> **Connector type:** Native Elastic · **Protocol:** Confluence REST API v1/v2 · **Sync:** Timestamp-based (space-level) · **Auth:** API token (Cloud) / Basic auth (Data Center)

---

## Table of Contents

- [Overview](#overview)
- [How It Works](#how-it-works)
  - [Incremental Sync - Step by Step](#incremental-sync--step-by-step)
  - [Content Hierarchy - Spaces, Pages, Blog Posts](#content-hierarchy--spaces-pages-blog-posts)
  - [Full Sync vs Incremental Sync](#full-sync-vs-incremental-sync)
  - [Deletion Detection](#deletion-detection)
- [When to Use / When Not to Use](#when-to-use--when-not-to-use)
- [Configuration Reference](#configuration-reference)
  - [Core Parameters](#core-parameters)
  - [Confluence Cloud vs Data Center](#confluence-cloud-vs-data-center)
  - [Sync Schedule](#sync-schedule)
  - [Programmatic Provisioning](#programmatic-provisioning)
- [Supported Content Types & Field Mapping](#supported-content-types--field-mapping)
- [Known Limitations](#known-limitations)
- [Enterprise AI-KB Deployment Notes](#enterprise-ai-kb-deployment-notes)
- [Technical Q&A](#technical-qa)

---

## Overview

The Elastic Confluence Connector synchronises pages, blog posts, and attachments from Confluence into Elasticsearch. It supports both **Confluence Cloud** (Atlassian Cloud SaaS) and **Confluence Data Center** (self-managed). Change detection uses a per-space timestamp watermark - the connector queries each space for content modified after the stored timestamp.

In the Enterprise AI-KB architecture, the Confluence connector indexes internal team knowledge - runbooks, product documentation, onboarding guides, and process wikis that contact centre agents reference during customer interactions.

```
Confluence (Cloud or Data Center)
  Spaces → Pages → Child Pages → Attachments
        │
        ▼
Confluence REST API v2 (Cloud) / v1 (Data Center)
        │
        ▼
Connector Process (Python 3.10+ / atlassian-python-api)
        │
        ▼
Elasticsearch Bulk API ──► Ingest Pipeline (Jina v3 embedding)
        │
        ▼
Tenant Index (BM25 + kNN searchable)
```

| Component | Technology | Role |
|---|---|---|
| Connector process | Python 3.10+ / `atlassian-python-api` | Authenticates, paginates spaces/pages, downloads content |
| Content extractor | Apache Tika (embedded) | Extracts text from attachments; Confluence page HTML stripped inline |
| Sync state | `.elastic-connectors` `sync_cursor` (per space) | Last sync timestamp per space |
| Ingest pipeline | Elasticsearch ingest node | Jina v3 embedding, field normalisation |

---

## How It Works

### Incremental Sync - Step by Step

1. **Schedule trigger** - Reads cron from `.elastic-connectors`. Default: `0 * * * *`.

2. **Authentication** - For Cloud: HTTP Basic auth with email + API token. For Data Center: HTTP Basic auth with username + password. Token sent as Base64-encoded header on every request.

3. **Space enumeration** - Calls `GET /wiki/rest/api/space?limit=50` to list all spaces accessible to the account. Filters by `space_keys` allowlist if configured.

4. **Per-space content query** - For each space, calls:

   ```
   GET /wiki/rest/api/content
     ?spaceKey=KB
     &type=page
     &status=current
     &lastModified={watermark_timestamp}
     &limit=50
     &start=0
     &expand=body.storage,history,ancestors,children.page
   ```

5. **Page content extraction** - Confluence returns page body as **Confluence Storage Format** (a subset of XHTML). The connector passes this through a lightweight HTML stripper to extract plain text - Tika is not used for page content (only for attachments).

6. **Attachment processing** - For each page, calls `GET /wiki/rest/api/content/{page_id}/child/attachment` to list attachments, then downloads each and passes to Tika.

7. **Child page traversal** - The connector recursively fetches child pages if `expand=children.page` returns sub-pages. Depth is configurable.

8. **Blog posts** - Separate query with `type=blogpost` for blog post content.

9. **Field mapping** - Content mapped to Elastic document schema.

10. **Bulk indexing** - Documents sent to `_bulk` API with ingest pipeline.

11. **Watermark update** - Per-space watermark updated in `sync_cursor` on completion.

---

### Content Hierarchy - Spaces, Pages, Blog Posts

Understanding Confluence's content hierarchy is important for configuring the connector correctly:

```
Confluence Instance
├── Space: "KB" (Knowledge Base)
│   ├── Page: "Product Overview"
│   │   ├── Child Page: "Feature A"
│   │   ├── Child Page: "Feature B"
│   │   └── Attachment: "architecture-diagram.pdf"
│   └── Page: "Troubleshooting"
│       └── Child Page: "Common Issues"
├── Space: "Engineering"
│   └── ...
└── Blog Posts (space-level, not page-level)
```

Each page, child page, and blog post becomes a **separate Elasticsearch document**. Attachments become separate documents linked to their parent page via a `parent_id` field.

---

### Full Sync vs Incremental Sync

| | Incremental | Full |
|---|---|---|
| **Content filter** | `lastModified >= watermark` per space | All content regardless of modification date |
| **Space enumeration** | Every sync (space list may change) | Every sync |
| **Pagination** | Offset-based, proportional to changed content | Offset-based, proportional to total content |
| **Deletion detection** | Archived/trashed pages separate query | Full diff against ES index |

---

### Deletion Detection

Confluence "deletes" pages by moving them to the Trash (status = `trashed`). These remain accessible via API for 60 days before permanent deletion.

The connector queries for trashed content:
```
GET /wiki/rest/api/content
  ?spaceKey=KB
  &status=trashed
  &lastModified={watermark}
```

Permanently deleted content (purged from Trash) is only detectable via full sync diff. Weekly full sync is the safety net.

---

## When to Use / When Not to Use

| Scenario | Verdict | Reason |
|---|---|---|
| Confluence Cloud knowledge base spaces | ✅ Use | Primary use case. Well-supported, API v2 gives clean change detection. |
| Confluence Data Center (self-managed) | ✅ Use | Supported. Uses REST API v1. Same connector, different auth and endpoint format. |
| Internal wikis with structured product documentation | ✅ Use | Pages with structured content (headers, tables, procedures) extract well. |
| Spaces with mostly image/diagram content (no text) | ⚠️ Partial | Pages that are primarily diagrams (draw.io embeds, Gliffy, etc.) extract no meaningful text. Body will be sparse. |
| Confluence Server (legacy, EOL 2024) | ⚠️ Check | Confluence Server reached EOL. API compatibility may vary. Test connector against your specific Server version. |
| Confluence with Jira-linked content | ✅ Use | Jira issue links in Confluence pages are extracted as text references - useful context for KB search. |
| Spaces used as project tracking (Kanban boards, sprint pages) | ❌ Don't index | Project tracking content clutters the knowledge base. Use space key allowlist to exclude. |
| Personal spaces (user home pages) | ❌ Don't index | Personal spaces contain user-specific content irrelevant to KB search. Exclude from `space_keys`. |

---

## Configuration Reference

### Core Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | string | required | Confluence instance URL. Cloud: `https://yourcompany.atlassian.net`. Data Center: `https://confluence.yourcompany.com`. |
| `username` | string | required | **Cloud:** Atlassian account email address. **Data Center:** Username. |
| `password` | secret | required | **Cloud:** Atlassian API token (NOT your Atlassian password). **Data Center:** User password. |
| `space_keys` | list | `[]` (all spaces) | Allowlist of space keys to sync. Empty = all accessible spaces. **Strongly recommend setting this for production.** |
| `index_labels` | boolean | `false` | Include Confluence page labels as a searchable field. Adds API calls - enable only if label-based filtering is needed. |
| `index_restrictions` | boolean | `false` | Enable document-level security based on Confluence page restrictions. Requires additional API calls per page. |

---

### Confluence Cloud vs Data Center

| | Confluence Cloud | Confluence Data Center |
|---|---|---|
| **Auth** | Email + API token | Username + password |
| **API version** | v2 (preferred) + v1 fallback | v1 |
| **API token creation** | https://id.atlassian.com/manage-profile/security/api-tokens | Admin-generated or user-generated |
| **Rate limits** | Atlassian Cloud rate limits apply (429 with Retry-After) | Depends on Data Center configuration |
| **URL format** | `https://{org}.atlassian.net` | `https://confluence.{company}.com` |

For Confluence Cloud, create the API token at:
```
https://id.atlassian.com/manage-profile/security/api-tokens
→ Create API token
→ Label: enterprise-elastic-connector
→ Copy token (shown once)
```

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
      "interval": "0 5 * * 0"
    }
  }
}
```

---

### Programmatic Provisioning

```python
def provision_confluence_connector(
    tenant_id: str,
    confluence_url: str,
    username: str,
    api_token: str,
    space_keys: list,
    es_host: str,
    admin_key: str
) -> dict:

    es = Elasticsearch(f"https://{es_host}:9200", api_key=admin_key)

    es.connector.put(
        connector_id=f"{tenant_id}-confluence",
        body={
            "index_name":   f"search-kb-{tenant_id}",
            "service_type": "confluence",
            "name":         f"Tenant {tenant_id} - Confluence",
            "configuration": {
                "url":          {"value": confluence_url},
                "username":     {"value": username},
                "password":     {"value": api_token},
                "space_keys":   {"value": space_keys},
                "index_labels": {"value": False},
                "index_restrictions": {"value": False},
            },
            "scheduling": {
                "incremental": {"enabled": True, "interval": "0 * * * *"},
                "full":        {"enabled": True, "interval": "0 5 * * 0"},
            }
        }
    )
```

---

## Supported Content Types & Field Mapping

### Pages and Blog Posts

| Elasticsearch field | Confluence field | Notes |
|---|---|---|
| `_id` | Page `id` | Confluence numeric page ID |
| `body` | `body.storage.value` | Confluence Storage Format → HTML stripped to plain text |
| `title` | `title` | Page title |
| `url` | `_links.webui` | Full web URL to the page |
| `created_at` | `history.createdDate` | |
| `last_modified` | `version.when` | Last edit timestamp - used as watermark |
| `author` | `history.createdBy.displayName` | Page author |
| `space` | `space.key` + `space.name` | Space the page belongs to |
| `type` | `type` | `page` or `blogpost` |
| `ancestors` | `ancestors[].title` | Breadcrumb path - useful for context |

### Attachments

| Elasticsearch field | Source | Notes |
|---|---|---|
| `_id` | Attachment `id` | |
| `body` | Tika-extracted text from attachment binary | 10 MB limit applies |
| `title` | Attachment filename | |
| `url` | Attachment download URL | |
| `parent_id` | Parent page `id` | Links attachment back to its page |
| `mime_type` | Attachment `mediaType` | |

---

## Known Limitations

| Limitation | Severity | Impact | Mitigation |
|---|---|---|---|
| 10 MB Tika limit on attachments | High | Large attached PDFs, DOCX silently skipped. | Pre-ingest chunking pipeline for attachment content. |
| Confluence macros not rendered | Medium | Content inside Confluence macros (Table of Contents, Include Page, Excerpt) is not rendered - macro markup appears as raw text or is stripped. | Accept for most KB content. For Include Page macros, the included content is in the source page's own document anyway. |
| draw.io / Gliffy diagrams produce empty body | Medium | Diagram-heavy pages return empty body - no text to search. | Accept. These pages rank low in text-based search but their titles and space context remain searchable. |
| Offset-based pagination (same as ServiceNow) | Medium | Record shifts during large syncs may cause occasional double-index or skip. | Watermark filter minimises the working set. Weekly full sync catches stragglers. |
| Atlassian Cloud rate limiting | Medium | Cloud instances apply rate limits (typically 429 with `Retry-After`). Large initial syncs may be throttled. | Schedule initial full syncs off-peak. Connector handles `Retry-After` automatically. |
| API token rotation (Cloud) | Medium | Atlassian API tokens do not expire by default but can be revoked. No automatic rotation. | Rotate annually. Update `.elastic-connectors` via Connector API when renewed. |
| Confluence Data Center with SSO / SAML | Medium | If the Data Center instance requires SSO login, Basic auth with username+password may not work. | Create a local (non-SSO) service account in Confluence Data Center specifically for the connector. |
| Page restrictions not enforced in search | Medium | Pages with viewer restrictions are indexed and returned in search results regardless of the querying user's permissions. | Use `index_restrictions: true` + document-level security if per-user access control in search is required. |

---

## Enterprise AI-KB Deployment Notes

For this deployment, each enterprise customer uses either Confluence Cloud or their own Confluence Data Center instance. The connector handles both, but the auth and URL format differ.

**Recommended space key allowlist per customer onboarding:**

Work with the customer to identify which Confluence spaces contain knowledge base content. Typical allowlist for a customer:

```python
space_keys = [
    "KB",          # Main knowledge base
    "PROD",        # Product documentation
    "SUPPORT",     # Support runbooks
    "TRAINING",    # Agent training materials
]
# Explicitly exclude:
# - Personal spaces (user/* prefix)
# - Archive spaces
# - Project tracking spaces
```

**Filter best practices:**

The connector does not support server-side filtering by label or category in the API query - filtering happens at the connector level after fetching. For large Confluence instances with many irrelevant spaces, the `space_keys` allowlist is the most important performance optimisation.

---

## Technical Q&A

<details>
<summary><strong>Confluence Storage Format is not standard HTML - how does the connector extract clean text from it, and what gets lost?</strong></summary>

Confluence Storage Format (CSF) is an XML-based format that looks like XHTML but includes Confluence-specific macro tags (`<ac:structured-macro>`, `<ac:parameter>`, etc.). The connector does not use Tika for page content extraction - it uses a lightweight HTML/XML tag stripper that removes all tags and returns the text content of text nodes.

What is preserved: All visible text - paragraph text, list items, table cell content, heading text, link text.

What is lost: Macro content (Jira issue lists, page includes, dynamic content), formatting context (bold/italic status), table structure (flattened to space-separated cell values), code block content (stripped as regular text), image alt text.

For knowledge base use cases, this is generally acceptable - the semantic content of the text is preserved. The main edge case is code blocks in technical documentation: `<ac:structured-macro ac:name="code">` macro content is stripped differently depending on connector version. Test code-heavy technical pages against a sample to confirm the body content is usable.

</details>

<details>
<summary><strong>How does the connector handle the Include Page macro - does it index the included content?</strong></summary>

No. The Include Page macro (`<ac:structured-macro ac:name="include">`) is a reference to another page - it renders the included page's content at display time, but the stored CSF contains only the macro reference tag, not the actual content.

The connector sees the macro tag, strips it (since it's not text), and does not follow the reference to fetch the included page's content. The included page IS indexed separately as its own document (since the connector crawls all pages in the space). So the content is in the index - just not duplicated in the including page's document.

This means a search for terms that appear only in an included page will return the included page's document, not the page that includes it. This is generally the correct behaviour - you want to surface the authoritative source, not every page that includes it.

</details>

<details>
<summary><strong>What is the actual API call count for a Confluence space with 1,000 pages and 200 attachments during an incremental sync where 30 pages changed?</strong></summary>

Incremental sync (30 pages changed):

1. Space enumeration: 1 call (lists all accessible spaces)
2. Content query for the space (30 results, fits in 1 page of 50): 1 call
3. For each of 30 pages - fetch full content with body: 0 additional calls (body included in `expand=body.storage`)
4. Attachment list for 30 changed pages: 30 calls (1 per page)
5. Attachment download for changed attachments (assume 10 of 30 pages have changed attachments): 10 calls

**Total: ~42 API calls for this incremental sync.**

Full sync (1,000 pages, 200 attachments):
1. Space enumeration: 1 call
2. Content queries: ceil(1000/50) = 20 calls
3. Attachment lists: 1,000 calls (1 per page)
4. Attachment downloads: 200 calls

**Total: ~1,221 API calls for a full sync.**

Atlassian Cloud's documented rate limit for REST API is approximately 10 requests/second per OAuth app. At this rate, a full sync of 1,000 pages takes roughly 2 minutes, well within acceptable windows for a weekly full sync.

</details>

<details>
<summary><strong>Confluence Cloud recently deprecated API v1 in favour of v2 - which version does the connector use and what breaks if the deprecation completes?</strong></summary>

The Elastic Confluence connector uses API v1 (`/wiki/rest/api/`) as its primary interface, with some v2 (`/wiki/api/v2/`) calls for specific operations in newer connector versions. As of Elastic 9.x, v1 is still the primary path.

Atlassian has announced a phased v1 deprecation but as of 2025 v1 remains fully functional for Confluence Cloud. When Atlassian eventually removes v1 endpoints, the connector will require an update to use v2 endpoints for the affected operations.

The migration risk: v2 uses different pagination (cursor-based vs offset-based), different field names, and a slightly different content model. A v1→v2 migration in the connector would require a full re-sync since `_id` generation may change.

Mitigation: Track Elastic connector release notes for Confluence v2 migration. Before Atlassian's v1 removal deadline, ensure you're on a connector version that uses v2. The Elastic connector team typically updates connectors before deprecation deadlines.

</details>

---

*Connector version: Elastic 9.x · Last updated: 2025 · Enterprise AI-KB internal reference*
