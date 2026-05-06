# SharePoint Hybrid Search — Dev Tools Walkthrough

A single, copy-paste-ready Kibana Dev Tools script that reproduces, end-to-end, every Elasticsearch action taken to stand up the SharePoint hybrid-search vertical slice.

**How to use this file**

1. Open Kibana → **Dev Tools → Console**
2. Paste each numbered block in order
3. Run with the green ▶ button on each request
4. The two-character `//` lines are Dev Tools comments and are ignored by ES — they document what each request does

The same pattern (drop duplicates, strip leaked metadata, copy `body` → `semantic_body`, set `final_pipeline`, hybrid retrievers, optional reranker, optional LTR) is what we will replicate for **S3, Salesforce, ServiceNow, and Confluence**. Only the duplicate predicate and the strip prefix change per source.

---

## Section 0 — Conventions

```
Index name           : content-sharepoint-jina-v5-small
Pipeline name        : genesys-sharepoint-v5-pipeline
Embedding model      : .jina-embeddings-v5-text-small  (1024-dim, cosine, 119 langs)
Reranker model       : .jina-reranker-v2-base-multilingual
LTR model id         : genesys-ltr-v1
LTR lab index        : content-sharepoint-ltr-lab
```

Replace `YOUR_CONNECTOR_ID` with the connector_id Kibana shows after step 4.

---

## Section 1 — Inference Endpoints (verify or create)

```
// 1.1  Verify the Jina v5 Small embedding endpoint exists (Elastic Cloud has it pre-provisioned)
GET _inference/text_embedding/.jina-embeddings-v5-text-small
```

```
// 1.2  Only run on self-managed if 1.1 returned 404
PUT _inference/text_embedding/.jina-embeddings-v5-text-small
{
  "service": "elastic",
  "service_settings": {
    "model_id": "jina-embeddings-v5-text-small"
  }
}
```

```
// 1.3  Verify the Jina v2 Multilingual reranker endpoint exists
GET _inference/rerank/.jina-reranker-v2-base-multilingual
```

---

## Section 2 — The Ingest Pipeline (the centerpiece)

This is the pipeline that solves both problems we explained:
- **Problem 1 — duplicate ingest**: the SharePoint connector emits both `drive_item` (file content) and `list_item` (metadata row) for every file. Without filtering, a 7,000-file library lands as ~14,000 indexed docs. Processor #1 drops the `list_item`s before they ever reach the index.
- **Problem 2 — leaked OAuth tokens**: the connector includes `@microsoft.graph.downloadUrl` which contains a live `tempauth` OAuth token. Processor #5 strips all `@microsoft.*` and `@odata.*` flat keys via a Painless script (the standard `remove` processor cannot handle flat dot-notation keys).

```
// 2.1  Create / replace the pipeline
PUT _ingest/pipeline/genesys-sharepoint-v5-pipeline
{
  "description": "Genesys KB SharePoint: drop duplicate list_items, strip auth tokens, enrich for hybrid search (Jina v5 Small)",
  "processors": [
    {
      "drop": {
        "description": "Drop list_items and structural metadata - only keep drive_items (actual file content)",
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

```
// 2.2  Confirm the pipeline persisted
GET _ingest/pipeline/genesys-sharepoint-v5-pipeline
```

> **Why `final_pipeline` not `default_pipeline` (set on the index in Section 3):** the connector framework passes `pipeline=search-default-ingestion` as a request-level parameter on every `_bulk` call, which overrides `default_pipeline` but **not** `final_pipeline`. Using `final_pipeline` guarantees these processors run regardless of what the connector does.

---

## Section 3 — The Index (mappings + final_pipeline binding)

```
// 3.1  Create the target index. semantic_body is the magic field -
//      semantic_text auto-chunks at sentence boundaries and auto-embeds via Jina v5 Small.
PUT content-sharepoint-jina-v5-small
{
  "settings": {
    "index.final_pipeline": "genesys-sharepoint-v5-pipeline",
    "number_of_shards": 2,
    "number_of_replicas": 1
  },
  "mappings": {
    "properties": {
      "body":          { "type": "text" },
      "semantic_body": { "type": "semantic_text", "inference_id": ".jina-embeddings-v5-text-small" },
      "title":         { "type": "text", "fields": { "keyword": { "type": "keyword", "ignore_above": 256 } } },
      "source_type":   { "type": "keyword" },
      "object_type":   { "type": "keyword" },
      "name":          { "type": "text", "fields": { "keyword": { "type": "keyword", "ignore_above": 256 } } },
      "description":   { "type": "text" },
      "webUrl":        { "type": "keyword" },
      "size":          { "type": "long" },
      "createdDateTime":      { "type": "date" },
      "lastModifiedDateTime": { "type": "date" },
      "createdBy": {
        "properties": {
          "user": {
            "properties": {
              "displayName": { "type": "keyword" },
              "email":       { "type": "keyword" },
              "id":          { "type": "keyword" }
            }
          }
        }
      },
      "lastModifiedBy": {
        "properties": {
          "user": {
            "properties": {
              "displayName": { "type": "keyword" },
              "email":       { "type": "keyword" },
              "id":          { "type": "keyword" }
            }
          }
        }
      },
      "file": {
        "properties": {
          "fileExtension": { "type": "keyword" },
          "mimeType":      { "type": "keyword" }
        }
      },
      "parentReference": {
        "properties": {
          "driveId":   { "type": "keyword" },
          "driveType": { "type": "keyword" },
          "path": {
            "type": "text",
            "fields": { "keyword": { "type": "keyword", "ignore_above": 512 } }
          },
          "siteId":    { "type": "keyword" }
        }
      },
      "contentType": {
        "properties": { "name": { "type": "keyword" } }
      },
      "id":         { "type": "keyword" },
      "_timestamp": { "type": "date" }
    }
  }
}
```

```
// 3.2  Confirm final_pipeline binding stuck
GET content-sharepoint-jina-v5-small/_settings/index.final_pipeline
```

---

## Section 4 — Connector Registration

The connector itself runs as a self-managed Python process on EC2 (no Docker, no Kubernetes). Kibana UI is the recommended path for the initial registration; this API form is the equivalent and useful for replicating across tenants.

```
// 4.1  Register the SharePoint Online connector against the index above
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

> **Common pitfall** — `tenant_name` is the prefix only (`gsystest`), **not** `gsystest.sharepoint.com` and **not** `gsystest.onmicrosoft.com`. Using the full domain causes auth failures.

---

## Section 5 — Trigger a Sync

```
// 5.1  Kick off a full sync (or use Kibana UI: Connectors -> Sync -> Full content sync)
POST _connector/_sync_job
{
  "id": "YOUR_CONNECTOR_ID",
  "job_type": "full"
}
```

---

## Section 6 — Post-Sync Verification (run after sync completes)

```
// 6.1  How many documents landed?
GET content-sharepoint-jina-v5-small/_count
```

```
// 6.2  Are duplicates gone? Should see ONLY drive_item bucket.
//      If list_item shows up, the pipeline is not bound or processor #1 is misconfigured.
GET content-sharepoint-jina-v5-small/_search
{
  "size": 0,
  "aggs": {
    "object_types": { "terms": { "field": "object_type", "size": 10 } }
  }
}
```

```
// 6.3  Did the embeddings get generated? has_semantic should equal _count.
GET content-sharepoint-jina-v5-small/_search
{
  "size": 0,
  "aggs": {
    "has_semantic":     { "filter": { "exists": { "field": "semantic_body" } } },
    "missing_semantic": { "filter": { "bool": { "must_not": { "exists": { "field": "semantic_body" } } } } }
  }
}
```

```
// 6.4  Smoke-test hybrid search (BM25 + Semantic + RRF)
POST content-sharepoint-jina-v5-small/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        { "standard": { "query": { "multi_match": { "query": "how to reset password", "fields": ["title^2", "body"] } } } },
        { "standard": { "query": { "semantic":    { "field": "semantic_body", "query": "how to reset password" } } } }
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

## Section 7 — Security & Quality Audits (run anytime)

```
// 7.1  Index composition snapshot - run once after every sync
GET content-sharepoint-jina-v5-small/_search
{
  "size": 0,
  "aggs": {
    "file_types":    { "terms": { "field": "file.fileExtension", "size": 20 } },
    "source_types":  { "terms": { "field": "source_type",       "size": 10 } },
    "object_types":  { "terms": { "field": "object_type",       "size": 10 } },
    "docs_with_semantic":    { "filter": { "exists": { "field": "semantic_body" } } },
    "docs_without_semantic": { "filter": { "bool": { "must_not": { "exists": { "field": "semantic_body" } } } } }
  }
}
```

```
// 7.2  Duplicate detection - count of anything that is NOT a drive_item.
//      Expected: 0. If non-zero, the pipeline is not running.
GET content-sharepoint-jina-v5-small/_count
{
  "query": {
    "bool": {
      "must_not": { "term": { "object_type": "drive_item" } }
    }
  }
}
```

```
// 7.3  OAuth token leak check - any documents still carrying @microsoft.graph.downloadUrl.
//      Expected: 0 hits. If any, the script processor in step 2.1 was modified or removed.
GET content-sharepoint-jina-v5-small/_search
{
  "size": 1,
  "_source": ["@microsoft.graph.downloadUrl"],
  "query": { "exists": { "field": "@microsoft.graph.downloadUrl" } }
}
```

---

## Section 8 — Hybrid Search Demo Queries

Each block below targets a different demo scenario. Run them in order during the customer walkthrough to show the search-quality progression.

### 8.1  Pipeline B — Pure RRF (the default production query)

```
POST content-sharepoint-jina-v5-small/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        { "standard": { "query": { "multi_match": { "query": "how to reset password", "fields": ["title^2", "body"] } } } },
        { "standard": { "query": { "semantic":    { "field": "semantic_body", "query": "how to reset password" } } } }
      ],
      "rank_window_size": 50,
      "rank_constant": 60
    }
  },
  "size": 5,
  "_source": ["title", "source_type", "webUrl"]
}
```

### 8.2  Pure Semantic — show the value of vectors over BM25 alone

```
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

### 8.3  Pure BM25 — for the contrast slide

```
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

### 8.4  Cross-Lingual Semantic — Spanish query, English documents

```
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

### 8.5  Filtered Hybrid — RRF + metadata filter (e.g., file extension)

```
POST content-sharepoint-jina-v5-small/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        {
          "standard": {
            "query": {
              "bool": {
                "must":   [{ "multi_match": { "query": "agent routing", "fields": ["title^2", "body"] } }],
                "filter": [{ "term": { "file.fileExtension": ".md" } }]
              }
            }
          }
        },
        {
          "standard": {
            "query": {
              "bool": {
                "must":   [{ "semantic": { "field": "semantic_body", "query": "how does agent routing work" } }],
                "filter": [{ "term": { "file.fileExtension": ".md" } }]
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

### 8.6  Hybrid + Highlighting — for the search UI

```
POST content-sharepoint-jina-v5-small/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        { "standard": { "query": { "multi_match": { "query": "workforce management scheduling", "fields": ["title^2", "body"] } } } },
        { "standard": { "query": { "semantic":    { "field": "semantic_body", "query": "how to schedule agents and manage workforce" } } } }
      ],
      "rank_window_size": 50,
      "rank_constant": 60
    }
  },
  "size": 5,
  "_source": ["title", "source_type"],
  "highlight": {
    "fields": {
      "body": { "fragment_size": 150, "number_of_fragments": 2 }
    }
  }
}
```

---

## Section 9 — Pipeline A: RRF + Jina Reranker v2 Multilingual

The production-recommended pipeline for precision-critical use cases (agent assist). RRF for recall, then a cross-encoder reranks the top 10 by reading each query/document pair.

Benchmarked p50 = 607ms at 4.9 ops/s (vs RRF-only at 321ms / 9.7 ops/s) — see ES-Rally section in the framework doc.

```
// 9.1  Verify the reranker endpoint
GET _inference/rerank/.jina-reranker-v2-base-multilingual
```

```
// 9.2  Pipeline A query
POST content-sharepoint-jina-v5-small/_search
{
  "retriever": {
    "text_similarity_reranker": {
      "retriever": {
        "rrf": {
          "retrievers": [
            { "standard": { "query": { "multi_match": { "query": "how to reset password", "fields": ["title^2", "body"] } } } },
            { "standard": { "query": { "semantic":    { "field": "semantic_body", "query": "how to reset password" } } } }
          ],
          "rank_window_size": 50,
          "rank_constant": 60
        }
      },
      "field": "body",
      "inference_id": ".jina-reranker-v2-base-multilingual",
      "inference_text": "how to reset password",
      "rank_window_size": 10
    }
  },
  "size": 5,
  "_source": ["title", "webUrl"]
}
```

> **Constraint** — the reranker's `rank_window_size` (10) MUST be ≤ the inner RRF's `rank_window_size` (50). ES validates this and rejects the request otherwise.

---

## Section 10 — Pipeline C: BM25 + LTR Rescore

XGBoost LambdaMART model trained on 5 features (`bm25_score`, `semantic_score`, `bm25_rank`, `semantic_rank`, `doc_size`) deployed via eland. NDCG@5 = 0.977 on validation. Top features by importance: `semantic_rank` (0.51) and `bm25_rank` (0.30).

Model + training pipeline live in `scripts/ltr-training/`.

```
// 10.1  Verify the LTR model is deployed
GET _ml/trained_models/genesys-ltr-v1
```

```
// 10.2  BM25 + LTR rescore query (targets the LTR lab index)
POST content-sharepoint-ltr-lab/_search
{
  "query": {
    "multi_match": {
      "query": "how to reset password",
      "fields": ["title^2", "body"]
    }
  },
  "rescore": {
    "learning_to_rank": {
      "model_id": "genesys-ltr-v1",
      "params": { "query_string": "how to reset password" }
    },
    "window_size": 50
  },
  "size": 5,
  "_source": ["title", "webUrl"]
}
```

> **ES architectural constraint** — you cannot combine the `retriever` API with `rescore` in a single request. So RRF + LTR in one query is not allowed; use Pipeline A (RRF + Reranker) or do a two-stage app-level pipeline.

---

## Section 11 — Sync Health Monitoring

```
// 11.1  Latest 5 sync jobs for this connector (replace YOUR_CONNECTOR_ID)
GET .elastic-connector-sync-jobs/_search
{
  "size": 5,
  "sort": [{ "started_at": "desc" }],
  "query": { "term": { "connector.id": "YOUR_CONNECTOR_ID" } },
  "_source": ["status", "job_type", "started_at", "completed_at",
              "indexed_document_count", "deleted_document_count", "error"]
}
```

```
// 11.2  Failed syncs in the last 7 days (across ALL connectors - useful for the ops review)
GET .elastic-connector-sync-jobs/_search
{
  "query": {
    "bool": {
      "filter": [
        { "term":  { "status": "error" } },
        { "range": { "started_at": { "gte": "now-7d" } } }
      ]
    }
  }
}
```

---

## Section 12 — Cleanup of Pre-Pipeline Indices (only if duplicates already exist)

If you discover an index that was indexed **before** the pipeline was bound (Section 6.2 shows both `drive_item` and `list_item` buckets), use this to clean it up retroactively.

```
// 12.1  Delete any non-drive_item documents
POST YOUR_INDEX/_delete_by_query
{
  "query": {
    "bool": {
      "must_not": { "term": { "object_type.keyword": "drive_item" } },
      "must":     { "exists": { "field": "object_type" } }
    }
  }
}
```

```
// 12.2  Bind the pipeline so future syncs cannot recreate duplicates
PUT YOUR_INDEX/_settings
{
  "index.final_pipeline": "genesys-sharepoint-v5-pipeline"
}
```

---

## Mapping this to S3 / Salesforce / ServiceNow / Confluence

The exact same skeleton — pipeline + index + connector + sync — is what we will run for each remaining source. Only two things change per source:

| Source | Predicate for processor #1 (`drop`) | Prefixes for processor #5 (`script` strip) |
|---|---|---|
| **S3** | `ctx.Key != null && ctx.Key.endsWith('/')` (drop directory markers) + zero-byte filter | `presignedUrl`, ARN-bearing metadata keys |
| **Salesforce** | drop drafts and non-current versions: `ctx.PublishStatus != 'Online' \|\| ctx.IsLatestVersion != true` | `attributes.url`, fields the user lacks Field-Level Security on |
| **ServiceNow** | keep only `workflow_state == 'published' && latest == true` | `sys_*` audit fields, internal-only KB IDs |
| **Confluence** | drop `status == 'archived'`, `space.type == 'personal'`, comments | restricted-page bodies the user can't see; `body.editor` representations |

Everything else — the `semantic_body` copy, the index mapping, the RRF query shape, the reranker layer, the LTR rescore — is identical. That is what makes the SharePoint slice the **reference implementation** for the remaining four connectors.
