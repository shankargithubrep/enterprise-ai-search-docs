# SharePoint Online — Hybrid Search Framework

> **Embedding model:** Jina v5 Small (1024 dims, cosine) · **Search:** BM25 + Semantic + RRF fusion · **Pipeline:** Duplicate elimination + auth token stripping + semantic enrichment · **Connector:** Elastic SharePoint Online (Microsoft Graph API)

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Step 1 — Create the Inference Endpoint](#step-1--create-the-inference-endpoint)
- [Step 2 — Create the Ingest Pipeline](#step-2--create-the-ingest-pipeline)
  - [Pipeline Processors Explained](#pipeline-processors-explained)
  - [Why final_pipeline Instead of default_pipeline](#why-final_pipeline-instead-of-default_pipeline)
- [Step 3 — Create the Index](#step-3--create-the-index)
- [Step 4 — Connect the SharePoint Online Connector](#step-4--connect-the-sharepoint-online-connector)
- [Step 5 — Trigger a Sync and Verify](#step-5--trigger-a-sync-and-verify)
- [Duplicate Avoidance — How and Why](#duplicate-avoidance--how-and-why)
- [Auth Token Stripping — Security](#auth-token-stripping--security)
- [Hybrid Search Queries — Dev Tools Reference](#hybrid-search-queries--dev-tools-reference)
  - [1. Hybrid RRF Search (Recommended Default)](#1-hybrid-rrf-search-recommended-default)
  - [2. Pure Semantic Search](#2-pure-semantic-search)
  - [3. Pure BM25 Keyword Search](#3-pure-bm25-keyword-search)
  - [4. Cross-Lingual Semantic Search](#4-cross-lingual-semantic-search)
  - [5. Filtered Hybrid Search](#5-filtered-hybrid-search)
  - [6. Hybrid Search with Highlighting](#6-hybrid-search-with-highlighting)
  - [7. Index Composition Audit](#7-index-composition-audit)
  - [8. Duplicate Detection Query](#8-duplicate-detection-query)
  - [9. Auth Token Leak Check](#9-auth-token-leak-check)
  - [10. Sync Health Check](#10-sync-health-check)
- [Sync Strategy](#sync-strategy)
- [Replicating This Framework for a New Tenant](#replicating-this-framework-for-a-new-tenant)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
SharePoint Online (document libraries)
        │
        ▼
Microsoft Graph API (delta query — cursor-based incremental sync)
        │
        ▼
Elastic Connector Process (Python 3.10+ / bare process / systemd)
        │
        ▼
Elasticsearch Bulk API with pipeline=search-default-ingestion
        │
        ▼
search-default-ingestion pipeline (connector-managed)
  → Apache Tika text extraction
  → Whitespace cleanup
  → Meta field removal
        │
        ▼
final_pipeline: genesys-sharepoint-v5-pipeline
  → Drop list_items (duplicate elimination)
  → Drop empty-body docs (folders)
  → Tag source_type=sharepoint
  → Copy name → title
  → Strip @microsoft auth tokens
  → Copy body → semantic_body
        │
        ▼
semantic_text auto-processing
  → Sentence-level chunking (max 250 tokens, 1-sentence overlap)
  → Jina v5 Small embedding (1024-dim, cosine)
  → Chunk embeddings stored as nested objects
        │
        ▼
Index: content-sharepoint-jina-v5-small
  → BM25 searchable (body, title)
  → kNN searchable (semantic_body chunks)
  → Hybrid RRF query combines both
```

**Two pipelines, two purposes:**

| Pipeline | Managed by | Runs | Purpose |
|---|---|---|---|
| `search-default-ingestion` | Connector framework | First (request-level) | Binary extraction (Tika), whitespace cleanup |
| `genesys-sharepoint-v5-pipeline` | You | Second (final_pipeline) | Deduplication, enrichment, semantic embedding prep |

The connector sets `pipeline=search-default-ingestion` on every bulk request. This overrides `default_pipeline` but NOT `final_pipeline`. That is why the custom pipeline must be set as `final_pipeline` on the index — it guarantees execution regardless of what the connector does.

---

## Step 1 — Create the Inference Endpoint

Jina v5 Small is pre-provisioned on Elastic Cloud via the Elastic Inference Service (EIS). Verify it exists:

```json
GET _inference/text_embedding/.jina-embeddings-v5-text-small
```

Expected response:

```json
{
  "endpoints": [{
    "inference_id": ".jina-embeddings-v5-text-small",
    "task_type": "text_embedding",
    "service": "elastic",
    "service_settings": {
      "model_id": "jina-embeddings-v5-text-small",
      "similarity": "cosine",
      "dimensions": 1024
    },
    "chunking_settings": {
      "strategy": "sentence",
      "max_chunk_size": 250,
      "sentence_overlap": 1
    }
  }]
}
```

If it does not exist (self-managed deployments), create it:

```json
PUT _inference/text_embedding/.jina-embeddings-v5-text-small
{
  "service": "elastic",
  "service_settings": {
    "model_id": "jina-embeddings-v5-text-small"
  }
}
```

**Key specifications:**

| Property | Value |
|---|---|
| Dimensions | 1024 |
| Similarity | Cosine |
| Context window | 32,768 tokens (~24,000 words) |
| Languages | 119+ |
| Chunking | Sentence-level, max 250 tokens, 1-sentence overlap |
| License | Included for active Elastic customers |

---

## Step 2 — Create the Ingest Pipeline

```json
PUT _ingest/pipeline/genesys-sharepoint-v5-pipeline
{
  "description": "Genesys KB SharePoint: drop duplicate list_items, strip auth tokens, enrich for hybrid search (Jina v5 Small)",
  "processors": [
    {
      "drop": {
        "description": "Drop list_items and structural metadata — only keep drive_items (actual file content)",
        "if": "ctx.object_type != null && ctx.object_type != \"drive_item\""
      }
    },
    {
      "drop": {
        "description": "Drop drive_items with no text content (empty files, folders)",
        "if": "ctx.body == null || ctx.body.isEmpty()"
      }
    },
    {
      "set": {
        "description": "Tag source type for multi-source filtering",
        "field": "source_type",
        "value": "sharepoint"
      }
    },
    {
      "set": {
        "description": "Normalize filename into title for consistent cross-source search",
        "field": "title",
        "copy_from": "name",
        "ignore_empty_value": true
      }
    },
    {
      "script": {
        "description": "Strip Graph API URLs with embedded OAuth tempauth tokens + OData metadata",
        "source": "def keysToRemove = ctx.keySet().stream().filter(k -> k.startsWith('@microsoft') || k.startsWith('@odata')).collect(Collectors.toList()); for (def key : keysToRemove) { ctx.remove(key); }"
      }
    },
    {
      "set": {
        "description": "Copy body to semantic_body for Jina v5 Small embedding via semantic_text",
        "field": "semantic_body",
        "copy_from": "body",
        "ignore_empty_value": true
      }
    }
  ]
}
```

### Pipeline Processors Explained

| # | Processor | What it does | Why |
|---|---|---|---|
| 1 | `drop` (non-drive_item) | Silently discards any document where `object_type` is not `drive_item` | SharePoint connector indexes both `drive_item` (actual file content) and `list_item` (metadata row) for every file. Without this, your index has 2× the documents — half are duplicates with no searchable content. See [Duplicate Avoidance](#duplicate-avoidance--how-and-why). |
| 2 | `drop` (empty body) | Discards documents with null or empty `body` | Folders and empty files pass Tika extraction but have no text. They waste vector storage and add noise to search results. |
| 3 | `set` (source_type) | Adds `source_type: "sharepoint"` | When you add additional connectors (Confluence, Salesforce, S3), this field lets you filter results by source in hybrid search queries. |
| 4 | `set` (title) | Copies `name` → `title` | SharePoint stores the filename in `name`. Normalizing to `title` provides a consistent field name across all connector sources for search and display. |
| 5 | `script` (@microsoft, @odata) | Strips Microsoft Graph API metadata fields | The `@microsoft.graph.downloadUrl` field contains a live OAuth `tempauth` token that grants file download access. If indexed, this token is searchable and exposable via API. A script processor is required because the connector stores these as flat dot-notation keys (not nested objects) — the standard `remove` processor interprets dots as path separators and misses them. See [Auth Token Stripping](#auth-token-stripping--security). |
| 6 | `set` (semantic_body) | Copies `body` → `semantic_body` | The `semantic_body` field is mapped as `semantic_text` with Jina v5 Small inference. Keeping it separate from `body` means BM25 searches `body` (standard `text` field) while semantic search targets `semantic_body` (auto-chunked, auto-embedded). This separation allows independent tuning. |

### Why final_pipeline Instead of default_pipeline

The Elastic connector framework sets `pipeline=search-default-ingestion` as a **request-level pipeline parameter** on every `_bulk` API call. In Elasticsearch's pipeline precedence:

```
Request-level pipeline (connector sets this)
  → OVERRIDES default_pipeline
  → Does NOT override final_pipeline
```

If you set your custom pipeline as `default_pipeline`, the connector's request-level parameter silently overrides it — your processors never run. Using `final_pipeline` guarantees execution after the connector's pipeline, regardless of what the connector does.

This is not obvious from the documentation and is the most common failure mode when adding custom processing to connector-managed indices.

---

## Step 3 — Create the Index

```json
PUT content-sharepoint-jina-v5-small
{
  "settings": {
    "index.final_pipeline": "genesys-sharepoint-v5-pipeline",
    "number_of_shards": 2,
    "number_of_replicas": 1
  },
  "mappings": {
    "properties": {
      "body": {
        "type": "text"
      },
      "semantic_body": {
        "type": "semantic_text",
        "inference_id": ".jina-embeddings-v5-text-small"
      },
      "title": {
        "type": "text",
        "fields": {
          "keyword": {
            "type": "keyword",
            "ignore_above": 256
          }
        }
      },
      "source_type": {
        "type": "keyword"
      },
      "object_type": {
        "type": "keyword"
      },
      "name": {
        "type": "text",
        "fields": {
          "keyword": {
            "type": "keyword",
            "ignore_above": 256
          }
        }
      },
      "description": {
        "type": "text"
      },
      "webUrl": {
        "type": "keyword"
      },
      "size": {
        "type": "long"
      },
      "createdDateTime": {
        "type": "date"
      },
      "lastModifiedDateTime": {
        "type": "date"
      },
      "createdBy": {
        "properties": {
          "user": {
            "properties": {
              "displayName": { "type": "keyword" },
              "email": { "type": "keyword" },
              "id": { "type": "keyword" }
            }
          }
        }
      },
      "lastModifiedBy": {
        "properties": {
          "user": {
            "properties": {
              "displayName": { "type": "keyword" },
              "email": { "type": "keyword" },
              "id": { "type": "keyword" }
            }
          }
        }
      },
      "file": {
        "properties": {
          "fileExtension": { "type": "keyword" },
          "mimeType": { "type": "keyword" }
        }
      },
      "parentReference": {
        "properties": {
          "driveId": { "type": "keyword" },
          "driveType": { "type": "keyword" },
          "path": {
            "type": "text",
            "fields": {
              "keyword": { "type": "keyword", "ignore_above": 512 }
            }
          },
          "siteId": { "type": "keyword" }
        }
      },
      "contentType": {
        "properties": {
          "name": { "type": "keyword" }
        }
      },
      "id": { "type": "keyword" },
      "_timestamp": { "type": "date" }
    }
  }
}
```

**Mapping design decisions:**

| Field | Type | Why |
|---|---|---|
| `body` | `text` | Standard BM25 full-text search. Analyzer defaults to `standard` (no language-specific stemming — appropriate for multilingual KB content). |
| `semantic_body` | `semantic_text` | Auto-chunks at sentence boundaries, auto-embeds via Jina v5 Small, stores chunk vectors as nested objects. Enables semantic + cross-lingual search. |
| `title` | `text` + `keyword` subfield | Full-text search on title with boosting (`title^2` in queries). Keyword subfield for exact match and aggregations. |
| `source_type` | `keyword` | Filter by data source (sharepoint, confluence, salesforce). Set by pipeline. |
| `object_type` | `keyword` | Drive item type. Always `drive_item` after pipeline filtering. Useful for auditing. |
| `webUrl` | `keyword` | SharePoint URL for linking back to the original document. Not analyzed. |
| `createdBy`, `lastModifiedBy` | `keyword` | User identity fields. Keyword for exact match and faceting. |
| `file.fileExtension` | `keyword` | File type filter (.md, .docx, .pdf). |
| `parentReference.path` | `text` + `keyword` | Folder path. Text for searching within paths, keyword for exact filtering. |

---

## Step 4 — Connect the SharePoint Online Connector

### Option A — Kibana UI (recommended for initial setup)

1. Navigate to **Search → Content → Connectors → New Connector**
2. Select **SharePoint Online**
3. Choose **Connector Only** (self-managed)
4. Name the connector (e.g., `Tenant A - SharePoint Online`)
5. Set the index name to your pre-created index: `content-sharepoint-jina-v5-small`
6. Generate an API key — copy the `connector_id` and `api_key`
7. Configure the connector with your Azure AD credentials:

| Field | Value |
|---|---|
| Tenant ID | Your Azure AD tenant GUID |
| Tenant Name | Your SharePoint tenant prefix (e.g., `gsystest` for `gsystest.sharepoint.com`) |
| Client ID | Azure AD app registration client ID |
| Client Secret | Azure AD app client secret |
| Site Collections | Comma-separated list of site URLs to crawl (empty = all sites) |

> **Common mistake:** The `Tenant Name` field expects ONLY the prefix — `gsystest`, not `gsystest.onmicrosoft.com` or `gsystest.sharepoint.com`. Using the full domain causes authentication failures.

### Option B — Connector API (programmatic)

```json
PUT _connector/tenant-a-sharepoint
{
  "index_name": "content-sharepoint-jina-v5-small",
  "name": "Tenant A - SharePoint Online",
  "service_type": "sharepoint_online",
  "configuration": {
    "tenant_id":     { "value": "YOUR-AZURE-TENANT-GUID" },
    "tenant_name":   { "value": "gsystest" },
    "client_id":     { "value": "YOUR-APP-CLIENT-ID" },
    "client_secret": { "value": "YOUR-CLIENT-SECRET" },
    "site_collections": { "value": [] },
    "use_document_level_security": { "value": false }
  },
  "scheduling": {
    "incremental": { "enabled": true, "interval": "0 */6 * * *" },
    "full":        { "enabled": true, "interval": "0 3 * * 0" }
  }
}
```

### Self-Managed Connector Process

The connector runs as a bare Python process on an EC2 VM — no Docker, no Kubernetes.

```bash
# Clone the connector framework
git clone https://github.com/elastic/connectors.git
cd connectors
git checkout v9.0.0  # match your Elasticsearch version

# Create virtual environment
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp config.yml.example config.yml
# Edit config.yml with connector_id, api_key, elasticsearch host
```

**config.yml:**

```yaml
connectors:
  - connector_id: YOUR_CONNECTOR_ID
    service_type: sharepoint_online
    api_key: YOUR_BASE64_API_KEY

elasticsearch.host: https://YOUR_DEPLOYMENT.us-east-2.aws.elastic-cloud.com:443
elasticsearch.api_key: YOUR_BASE64_API_KEY
elasticsearch.ssl: true
elasticsearch.verify_certs: true

service.log_level: INFO
service.idling: 30
```

**systemd unit file** (`/etc/systemd/system/elastic-connector.service`):

```ini
[Unit]
Description=Elastic Connector Service
After=network.target

[Service]
Type=simple
User=elastic-connector
WorkingDirectory=/opt/elastic-connectors
ExecStart=/opt/elastic-connectors/.venv/bin/python -m connectors.service
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable elastic-connector
sudo systemctl start elastic-connector
sudo journalctl -u elastic-connector -f  # watch logs
```

---

## Step 5 — Trigger a Sync and Verify

### Trigger sync via Kibana

Navigate to **Search → Content → Connectors → [your connector]** → click **Sync → Full content sync**.

### Trigger sync via API

```json
POST _connector/_sync_job
{
  "id": "YOUR_CONNECTOR_ID",
  "job_type": "full"
}
```

### Verify after sync

Run these queries in **Dev Tools** to confirm everything is working:

```json
// 1. Check document count
GET content-sharepoint-jina-v5-small/_count

// 2. Verify only drive_items (no duplicates)
GET content-sharepoint-jina-v5-small/_search
{
  "size": 0,
  "aggs": {
    "object_types": {
      "terms": { "field": "object_type", "size": 10 }
    }
  }
}

// 3. Verify semantic embeddings exist
GET content-sharepoint-jina-v5-small/_search
{
  "size": 0,
  "aggs": {
    "has_semantic": {
      "filter": { "exists": { "field": "semantic_body" } }
    },
    "missing_semantic": {
      "filter": {
        "bool": { "must_not": { "exists": { "field": "semantic_body" } } }
      }
    }
  }
}

// 4. Quick hybrid search test
POST content-sharepoint-jina-v5-small/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        {
          "standard": {
            "query": {
              "multi_match": {
                "query": "how to reset password",
                "fields": ["title^2", "body"]
              }
            }
          }
        },
        {
          "standard": {
            "query": {
              "semantic": {
                "field": "semantic_body",
                "query": "how to reset password"
              }
            }
          }
        }
      ],
      "rank_window_size": 50,
      "rank_constant": 60
    }
  },
  "size": 3,
  "_source": ["title", "source_type"]
}
```

---

## Duplicate Avoidance — How and Why

### The Problem

The Elastic SharePoint Online connector indexes **two document types** for every file in a document library:

| Object Type | What It Is | Content |
|---|---|---|
| `drive_item` | The actual file | Full text extracted by Tika — the content you want to search |
| `list_item` | The SharePoint list metadata row | Field names, column values, no file content |

Without filtering, a library with 7,000 files produces ~14,000 indexed documents — half of which are metadata-only duplicates that dilute search quality, waste storage, and inflate vector embedding costs.

### The Solution

The first processor in the pipeline drops everything that is not a `drive_item`:

```json
{
  "drop": {
    "if": "ctx.object_type != null && ctx.object_type != \"drive_item\""
  }
}
```

The `drop` processor silently discards the document before it reaches the index. It never appears in the index, never gets embedded, never consumes storage.

### How to Detect Duplicates

If you suspect duplicates in an existing index (before the pipeline was applied):

```json
GET YOUR_INDEX/_search
{
  "size": 0,
  "aggs": {
    "by_object_type": {
      "terms": { "field": "object_type.keyword", "size": 10 }
    }
  }
}
```

If you see both `drive_item` and `list_item` buckets, duplicates are present.

### How to Clean Up Existing Duplicates

```json
POST YOUR_INDEX/_delete_by_query
{
  "query": {
    "bool": {
      "must_not": {
        "term": { "object_type.keyword": "drive_item" }
      },
      "must": {
        "exists": { "field": "object_type" }
      }
    }
  }
}
```

Then set the pipeline on the index to prevent future duplicates:

```json
PUT YOUR_INDEX/_settings
{
  "index.final_pipeline": "genesys-sharepoint-v5-pipeline"
}
```

---

## Auth Token Stripping — Security

### The Problem

The SharePoint connector's raw document includes a field `@microsoft.graph.downloadUrl` containing a Microsoft Graph download URL with an embedded OAuth `tempauth` token:

```
https://tenant.sharepoint.com/_layouts/15/download.aspx?UniqueId=...&tempauth=v1.eyJzaXRlaWQiOi...
```

This token grants temporary file download access. If indexed in Elasticsearch, anyone with search API access can extract these tokens from the `_source` of search results. The tokens are short-lived (~1 hour) but are regenerated on every sync — meaning every sync cycle indexes fresh, valid download tokens.

### The Solution

The pipeline uses a **script processor** (not the standard `remove` processor) to strip these fields:

```json
{
  "script": {
    "description": "Strip Graph API URLs with embedded OAuth tempauth tokens + OData metadata",
    "source": "def keysToRemove = ctx.keySet().stream().filter(k -> k.startsWith('@microsoft') || k.startsWith('@odata')).collect(Collectors.toList()); for (def key : keysToRemove) { ctx.remove(key); }"
  }
}
```

**Why a script processor instead of `remove`?** The SharePoint connector stores these fields as **flat dot-notation keys** in the document JSON (e.g., `"@microsoft.graph.downloadUrl": "..."`), not as nested objects. The standard `remove` processor interprets dots as path separators — it looks for `@microsoft` → `graph` → `downloadUrl` as a nested path, which doesn't exist. The script processor accesses the document context map directly (`ctx.keySet()`) and matches flat keys by prefix, correctly removing all `@microsoft.*` and `@odata.*` entries regardless of nesting convention.

### How to Verify Tokens Are Stripped

```json
GET content-sharepoint-jina-v5-small/_search
{
  "size": 1,
  "_source": ["@microsoft.graph.downloadUrl", "@microsoft"],
  "query": {
    "bool": {
      "should": [
        { "exists": { "field": "@microsoft.graph.downloadUrl" } },
        { "exists": { "field": "@microsoft" } }
      ]
    }
  }
}
```

Expected: 0 hits. If documents are returned, the pipeline is not attached or not functioning — check `index.final_pipeline` setting:

```json
GET content-sharepoint-jina-v5-small/_settings/index.final_pipeline
```

---

## Hybrid Search Queries — Dev Tools Reference

Copy these queries into **Kibana Dev Tools** to test search quality. Each query demonstrates a different search capability.

### 1. Hybrid RRF Search (Recommended Default)

Combines BM25 keyword matching with Jina v5 Small semantic matching. This is the query pattern to use in production — it handles both exact term matches and paraphrase/conceptual queries.

```json
POST content-sharepoint-jina-v5-small/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        {
          "standard": {
            "query": {
              "multi_match": {
                "query": "how to reset password",
                "fields": ["title^2", "body"]
              }
            }
          }
        },
        {
          "standard": {
            "query": {
              "semantic": {
                "field": "semantic_body",
                "query": "how to reset password"
              }
            }
          }
        }
      ],
      "rank_window_size": 50,
      "rank_constant": 60
    }
  },
  "size": 5,
  "_source": ["title", "source_type", "webUrl"]
}
```

**How RRF works:** Each retriever independently ranks all matching documents. RRF combines the rankings:

```
RRF_score(doc) = Σ  1 / (rank_constant + rank_position)
```

A document ranked #1 by BM25 and #3 by semantic scores higher than a document appearing in only one ranking.

**Tuning parameters:**

| Parameter | Default | Effect |
|---|---|---|
| `rank_window_size` | 50 | How many top results from each retriever to consider. Higher = more candidates but slower. |
| `rank_constant` | 60 | Controls how sharply rank advantage decays. Lower = top-ranked results dominate more. |
| `title^2` | — | Boosts title matches 2× over body matches in BM25 scoring. |

---

### 2. Pure Semantic Search

Finds documents by meaning — no keyword overlap required. Use this to demonstrate the value of vector embeddings versus BM25 alone.

```json
POST content-sharepoint-jina-v5-small/_search
{
  "size": 5,
  "_source": ["title", "source_type", "webUrl"],
  "query": {
    "semantic": {
      "field": "semantic_body",
      "query": "what are the rules about customer data privacy and compliance"
    }
  }
}
```

**Why this matters:** A BM25 search for "data privacy compliance" only matches documents containing those exact words. Semantic search also finds documents titled "About compliance" or "What procedures do you have in place to keep customer data strictly confidential" — because the *meaning* matches even when the *words* do not.

---

### 3. Pure BM25 Keyword Search

Traditional keyword search — fast, deterministic, no ML inference. Use for exact term lookups.

```json
POST content-sharepoint-jina-v5-small/_search
{
  "size": 5,
  "_source": ["title", "source_type"],
  "query": {
    "multi_match": {
      "query": "Genesys Cloud CX",
      "fields": ["title^2", "body"]
    }
  }
}
```

---

### 4. Cross-Lingual Semantic Search

Jina v5 Small supports 119+ languages. A query in one language finds documents in another — because both are mapped to the same 1024-dimensional vector space.

```json
// Spanish query against English documents
POST content-sharepoint-jina-v5-small/_search
{
  "size": 5,
  "_source": ["title", "source_type"],
  "query": {
    "semantic": {
      "field": "semantic_body",
      "query": "como configurar la integracion del telefono"
    }
  }
}
```

This demonstrates a key POC success criterion: **cross-lingual retrieval EN+ES without a separate index**.

---

### 5. Filtered Hybrid Search

Combine hybrid search with metadata filters. Useful for scoping results to specific file types, time ranges, or authors.

```json
// Only search .md files about routing
POST content-sharepoint-jina-v5-small/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        {
          "standard": {
            "query": {
              "bool": {
                "must": [
                  { "multi_match": { "query": "agent routing", "fields": ["title^2", "body"] } }
                ],
                "filter": [
                  { "term": { "file.fileExtension": ".md" } }
                ]
              }
            }
          }
        },
        {
          "standard": {
            "query": {
              "bool": {
                "must": [
                  { "semantic": { "field": "semantic_body", "query": "how does agent routing work" } }
                ],
                "filter": [
                  { "term": { "file.fileExtension": ".md" } }
                ]
              }
            }
          }
        }
      ],
      "rank_window_size": 50,
      "rank_constant": 60
    }
  },
  "size": 5,
  "_source": ["title", "source_type", "file.fileExtension"]
}
```

**Other useful filters:**

```json
// By date range
{ "range": { "lastModifiedDateTime": { "gte": "2024-01-01" } } }

// By author
{ "term": { "createdBy.user.displayName": "John Smith" } }

// By folder path
{ "wildcard": { "parentReference.path.keyword": "*KnowledgeBase*" } }
```

---

### 6. Hybrid Search with Highlighting

Returns highlighted snippets showing why each document matched — useful for building search UIs.

```json
POST content-sharepoint-jina-v5-small/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        {
          "standard": {
            "query": {
              "multi_match": {
                "query": "workforce management scheduling",
                "fields": ["title^2", "body"]
              }
            }
          }
        },
        {
          "standard": {
            "query": {
              "semantic": {
                "field": "semantic_body",
                "query": "how to schedule agents and manage workforce"
              }
            }
          }
        }
      ],
      "rank_window_size": 50,
      "rank_constant": 60
    }
  },
  "size": 5,
  "_source": ["title", "source_type"],
  "highlight": {
    "fields": {
      "body": {
        "fragment_size": 150,
        "number_of_fragments": 2
      }
    }
  }
}
```

---

### 7. Index Composition Audit

Verify the index contains only the expected document types and sources.

```json
GET content-sharepoint-jina-v5-small/_search
{
  "size": 0,
  "aggs": {
    "file_types": {
      "terms": { "field": "file.fileExtension", "size": 20 }
    },
    "source_types": {
      "terms": { "field": "source_type", "size": 10 }
    },
    "object_types": {
      "terms": { "field": "object_type", "size": 10 }
    },
    "docs_with_semantic": {
      "filter": { "exists": { "field": "semantic_body" } }
    },
    "docs_without_semantic": {
      "filter": {
        "bool": { "must_not": { "exists": { "field": "semantic_body" } } }
      }
    }
  }
}
```

**Expected results:**
- `object_types`: only `drive_item`
- `source_types`: only `sharepoint`
- `docs_with_semantic`: equals total doc count
- `docs_without_semantic`: 0

---

### 8. Duplicate Detection Query

Check if any duplicates slipped through the pipeline.

```json
// Check for list_items (should be 0)
GET content-sharepoint-jina-v5-small/_count
{
  "query": {
    "bool": {
      "must_not": {
        "term": { "object_type": "drive_item" }
      }
    }
  }
}
```

---

### 9. Auth Token Leak Check

Verify no OAuth tokens are indexed.

```json
GET content-sharepoint-jina-v5-small/_search
{
  "size": 1,
  "_source": ["@microsoft.graph.downloadUrl"],
  "query": {
    "exists": { "field": "@microsoft.graph.downloadUrl" }
  }
}
```

Expected: 0 hits.

---

### 10. Sync Health Check

Monitor connector sync status and detect failures.

```json
// Latest sync jobs for this connector
GET .elastic-connector-sync-jobs/_search
{
  "size": 5,
  "sort": [{ "started_at": "desc" }],
  "query": {
    "term": { "connector.id": "YOUR_CONNECTOR_ID" }
  },
  "_source": ["status", "job_type", "started_at", "completed_at",
              "indexed_document_count", "deleted_document_count", "error"]
}

// Failed syncs in last 7 days
GET .elastic-connector-sync-jobs/_search
{
  "query": {
    "bool": {
      "filter": [
        { "term": { "status": "error" } },
        { "range": { "started_at": { "gte": "now-7d" } } }
      ]
    }
  }
}
```

---

## Sync Strategy

### Incremental vs Full Sync

| | Incremental | Full |
|---|---|---|
| **How it works** | Delta query — asks Microsoft Graph "what changed since last cursor?" | Full crawl — lists all files, compares against index |
| **Speed** | Proportional to changes (20 changed files = 20 API calls) | Proportional to total files (7,000 files = 7,000+ API calls) |
| **When to use** | Primary sync method — run every 6 hours | Weekly safety net + first sync + delta token expiry recovery |
| **Deletion handling** | Deletes flagged by delta query are processed | Full diff against index detects orphaned documents |

### Recommended Schedule

```json
{
  "scheduling": {
    "incremental": {
      "enabled": true,
      "interval": "0 */6 * * *"
    },
    "full": {
      "enabled": true,
      "interval": "0 3 * * 0"
    }
  }
}
```

- **Incremental every 6 hours** — catches new/modified/deleted documents with minimal API calls
- **Full weekly (Sunday 3 AM)** — catches any drift that incremental missed, rebuilds delta token

### Manual Sync Trigger

For on-demand content updates (e.g., after a bulk document upload):

```json
POST _connector/_sync_job
{
  "id": "YOUR_CONNECTOR_ID",
  "job_type": "full"
}
```

---

## Replicating This Framework for a New Tenant

To add a new SharePoint tenant to the system, repeat these steps:

### 1. Create a new index

Replace `TENANT_NAME` with the tenant identifier:

```json
PUT content-sharepoint-TENANT_NAME
{
  "settings": {
    "index.final_pipeline": "genesys-sharepoint-v5-pipeline",
    "number_of_shards": 2,
    "number_of_replicas": 1
  },
  "mappings": {
    // ... same mapping as Step 3 above
  }
}
```

The pipeline (`genesys-sharepoint-v5-pipeline`) is shared across all tenants — create it once, reference it from every index.

### 2. Create a new connector

```json
PUT _connector/TENANT_NAME-sharepoint
{
  "index_name": "content-sharepoint-TENANT_NAME",
  "name": "TENANT_NAME - SharePoint Online",
  "service_type": "sharepoint_online",
  "configuration": {
    "tenant_id":     { "value": "AZURE_TENANT_GUID" },
    "tenant_name":   { "value": "SHAREPOINT_PREFIX" },
    "client_id":     { "value": "APP_CLIENT_ID" },
    "client_secret": { "value": "APP_CLIENT_SECRET" },
    "site_collections": { "value": [] }
  },
  "scheduling": {
    "incremental": { "enabled": true, "interval": "0 */6 * * *" },
    "full":        { "enabled": true, "interval": "0 3 * * 0" }
  }
}
```

### 3. Add connector to the connector service config

Add a new entry to the `connectors` array in `config.yml` on the VM:

```yaml
connectors:
  - connector_id: EXISTING_CONNECTOR_ID
    service_type: sharepoint_online
    api_key: EXISTING_API_KEY
  - connector_id: NEW_CONNECTOR_ID
    service_type: sharepoint_online
    api_key: NEW_API_KEY
```

Restart the connector service: `sudo systemctl restart elastic-connector`

### 4. Create a Kibana data view

```json
POST /api/data_views/data_view
{
  "data_view": {
    "title": "content-sharepoint-TENANT_NAME",
    "name": "SharePoint - TENANT_NAME",
    "timeFieldName": "lastModifiedDateTime"
  }
}
```

### 5. Trigger initial sync and verify

Follow [Step 5](#step-5--trigger-a-sync-and-verify) above.

---

## Troubleshooting

### Connector shows "Connected" but sync fails

Check the sync job error:

```json
GET .elastic-connector-sync-jobs/_search
{
  "size": 1,
  "sort": [{ "started_at": "desc" }],
  "query": { "term": { "connector.id": "YOUR_CONNECTOR_ID" } },
  "_source": ["status", "error"]
}
```

Common causes:
- **`AADSTS700016: Application not found`** — wrong `client_id` or wrong Azure AD tenant
- **`AADSTS7000215: Invalid client secret`** — client secret expired or incorrectly entered
- **`Access denied`** — API permissions not granted admin consent in Azure Portal
- **`Tenant not found`** — `tenant_name` uses full domain instead of prefix

### Index has double the expected document count

Duplicates from `list_item` + `drive_item`. See [Duplicate Avoidance](#duplicate-avoidance--how-and-why). Fix: apply the pipeline and run delete_by_query.

### Semantic search returns no results

Check that `semantic_body` is populated:

```json
GET content-sharepoint-jina-v5-small/_search
{
  "size": 1,
  "query": { "exists": { "field": "semantic_body" } }
}
```

If 0 hits, the pipeline's `set` processor for `semantic_body` is not running — verify `final_pipeline` is set on the index.

### Semantic search is slow (>500ms)

Check inference endpoint health:

```json
GET _inference/text_embedding/.jina-embeddings-v5-text-small
```

On EIS (Elastic Cloud), inference is managed — if latency is high, it may be transient ML node load. On self-managed, check ML node CPU and queue depth.

### Documents larger than 10MB are missing

Apache Tika (used by the connector) silently skips files larger than 10MB. Check sync job stats for `total_document_count` vs expected count. Large files need to be chunked before upload or accepted as a gap.

---

*Framework version: 1.0 · Embedding model: Jina v5 Small · Elasticsearch 9.x · Last updated: April 2026*
