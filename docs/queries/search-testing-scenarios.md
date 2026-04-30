# Search Testing Scenarios — Dev Tools Reference

> **Indexes:** `content-sharepoint-jina-v5-small` (production), `content-sharepoint-ltr-lab` (LTR experimentation) · **Models:** Jina v5 Small (embedding), Jina Reranker v3 (cross-encoder), genesys-ltr-v1 (XGBoost LambdaMART) · **Search modes:** BM25, Semantic, Hybrid RRF, RRF + Reranker, BM25 + LTR, Cross-lingual, Filtered

Open **Kibana → Dev Tools** and paste each query block to test. Each scenario demonstrates a specific search capability with expected behavior.

---

## Table of Contents

- [Scenario 1 — Hybrid RRF: The Default Query Pattern](#scenario-1--hybrid-rrf-the-default-query-pattern)
- [Scenario 2 — Semantic Search Resolves BM25 Zero-Result Queries](#scenario-2--semantic-search-resolves-bm25-zero-result-queries)
- [Scenario 3 — Semantic Paraphrase: Different Words, Same Meaning](#scenario-3--semantic-paraphrase-different-words-same-meaning)
- [Scenario 4 — Cross-Lingual: Spanish Query Against English Docs](#scenario-4--cross-lingual-spanish-query-against-english-docs)
- [Scenario 5 — Cross-Lingual: Portuguese Query](#scenario-5--cross-lingual-portuguese-query)
- [Scenario 6 — Semantic vs BM25 Side-by-Side Comparison](#scenario-6--semantic-vs-bm25-side-by-side-comparison)
- [Scenario 7 — Conceptual Intent: No Keyword Overlap](#scenario-7--conceptual-intent-no-keyword-overlap)
- [Scenario 8 — Filtered Hybrid: By File Type](#scenario-8--filtered-hybrid-by-file-type)
- [Scenario 9 — Filtered Hybrid: By Date Range](#scenario-9--filtered-hybrid-by-date-range)
- [Scenario 10 — Filtered Hybrid: By Folder Path](#scenario-10--filtered-hybrid-by-folder-path)
- [Scenario 11 — Hybrid Search with Highlighting](#scenario-11--hybrid-search-with-highlighting)
- [Scenario 12 — Pure BM25: Exact Term Lookup](#scenario-12--pure-bm25-exact-term-lookup)
- [Scenario 13 — Aggregation: Content Audit](#scenario-13--aggregation-content-audit)
- [Scenario 14 — Pipeline Verification: No Duplicates](#scenario-14--pipeline-verification-no-duplicates)
- [Scenario 15 — Pipeline Verification: No Auth Tokens](#scenario-15--pipeline-verification-no-auth-tokens)
- [Scenario 16 — Embedding Coverage: All Docs Have Vectors](#scenario-16--embedding-coverage-all-docs-have-vectors)
- [Scenario 17 — Sync Health: Recent Sync Jobs](#scenario-17--sync-health-recent-sync-jobs)
- [Scenario 18 — Semantic Similarity: Find Similar Documents](#scenario-18--semantic-similarity-find-similar-documents)
- [Scenario 19 — Multi-Field Boosting](#scenario-19--multi-field-boosting)
- [Scenario 20 — Playground Integration](#scenario-20--playground-integration)
- [How to Interpret Results](#how-to-interpret-results)
- **Advanced Ranking Pipelines (Scenarios 21–28)**
- [Scenario 21 — Pre-Flight: Verify Jina Reranker v3 Endpoint](#scenario-21--pre-flight-verify-jina-reranker-v3-endpoint)
- [Scenario 22 — Pre-Flight: Verify LTR Model Deployment](#scenario-22--pre-flight-verify-ltr-model-deployment)
- [Scenario 23 — Pipeline A: RRF + Jina Reranker v3 (Production)](#scenario-23--pipeline-a-rrf--jina-reranker-v3-production)
- [Scenario 24 — Pipeline B: RRF Only (No Reranker)](#scenario-24--pipeline-b-rrf-only-no-reranker)
- [Scenario 25 — Pipeline C: BM25 + LTR Rescore](#scenario-25--pipeline-c-bm25--ltr-rescore)
- [Scenario 26 — Pipeline D: Plain BM25 Baseline](#scenario-26--pipeline-d-plain-bm25-baseline)
- [Scenario 27 — Side-by-Side: 4-Pipeline Comparison](#scenario-27--side-by-side-4-pipeline-comparison)
- [Scenario 28 — Latency Profiling: Measure Pipeline Overhead](#scenario-28--latency-profiling-measure-pipeline-overhead)

---

## Scenario 1 — Hybrid RRF: The Default Query Pattern

**What it tests:** Combined keyword + semantic search with RRF rank fusion. This is the recommended query pattern for production.

**Why it matters:** Hybrid search catches both exact keyword matches AND semantic/conceptual matches in a single query.

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

**Expected:** Top results should include documents like `Reset_your_password.md`, `How_do_I_change_or_reset_my_password.md`, `Reset_a_user's_password.md`. Both keyword matches (BM25 finds "password" in title) and semantic matches (Jina finds "credential recovery" content) contribute to the final ranking.

---

## Scenario 2 — Semantic Search Resolves BM25 Zero-Result Queries

**What it tests:** The core POC success criterion — semantic search finds relevant documents when BM25 keyword search returns irrelevant results.

**Step 1 — Run BM25 only:**

```json
POST content-sharepoint-jina-v5-small/_search
{
  "size": 3,
  "_source": ["title"],
  "query": {
    "multi_match": {
      "query": "credential recovery procedure",
      "fields": ["title^2", "body"]
    }
  }
}
```

**Step 2 — Run Semantic only:**

```json
POST content-sharepoint-jina-v5-small/_search
{
  "size": 3,
  "_source": ["title"],
  "query": {
    "semantic": {
      "field": "semantic_body",
      "query": "credential recovery procedure"
    }
  }
}
```

**What to observe:** BM25 matches on individual words ("credential", "recovery", "procedure") returning unrelated docs about certificates and disaster recovery. Semantic search understands the *intent* — login/password recovery — and returns documents like `Log_in_for_the_first_time.md` that are actually relevant.

---

## Scenario 3 — Semantic Paraphrase: Different Words, Same Meaning

**What it tests:** Semantic search finds documents even when the query uses completely different terminology than the document.

```json
POST content-sharepoint-jina-v5-small/_search
{
  "size": 5,
  "_source": ["title"],
  "query": {
    "semantic": {
      "field": "semantic_body",
      "query": "what are the rules about customer data privacy and compliance"
    }
  }
}
```

**Expected:** Returns documents like `About_compliance.md`, `What_is_your_privacy_policy_regarding_AI_services.md`, `What_procedures_do_you_have_in_place_to_keep_customer_data_strictly_confidential.md` — even though the query words don't exactly match the document titles.

---

## Scenario 4 — Cross-Lingual: Spanish Query Against English Docs

**What it tests:** A query in Spanish retrieves relevant English documents. Demonstrates Jina v5 Small's multilingual vector space alignment across 119+ languages.

```json
POST content-sharepoint-jina-v5-small/_search
{
  "size": 5,
  "_source": ["title"],
  "query": {
    "semantic": {
      "field": "semantic_body",
      "query": "como configurar la integracion del telefono"
    }
  }
}
```

**Expected:** Returns phone/telephony integration docs like `Configure_the_Zoom_Phone_integration.md` — the query is in Spanish ("how to configure the phone integration") but the documents are in English.

**Why this matters for the POC:** Genesys has contact center agents worldwide. An agent in Latin America querying in Spanish should find the same knowledge base articles as an English-speaking agent.

---

## Scenario 5 — Cross-Lingual: Portuguese Query

**What it tests:** Portuguese query retrieval. Tests deeper multilingual capability beyond Spanish.

```json
POST content-sharepoint-jina-v5-small/_search
{
  "size": 5,
  "_source": ["title"],
  "query": {
    "semantic": {
      "field": "semantic_body",
      "query": "regras de uso justo e limites da plataforma"
    }
  }
}
```

**Expected:** Returns documents about fair use policies and platform limits — the Portuguese query translates to "fair use rules and platform limits."

---

## Scenario 6 — Semantic vs BM25 Side-by-Side Comparison

**What it tests:** Direct comparison showing how semantic and keyword search return different (complementary) results for the same query.

**Run both queries and compare the top 3 results:**

```json
// Query A: BM25 keyword search
POST content-sharepoint-jina-v5-small/_search
{
  "size": 3,
  "_source": ["title"],
  "query": {
    "multi_match": {
      "query": "troubleshoot call quality problems and audio issues",
      "fields": ["title^2", "body"]
    }
  }
}
```

```json
// Query B: Semantic search (same query text)
POST content-sharepoint-jina-v5-small/_search
{
  "size": 3,
  "_source": ["title"],
  "query": {
    "semantic": {
      "field": "semantic_body",
      "query": "troubleshoot call quality problems and audio issues"
    }
  }
}
```

**What to observe:** BM25 matches on keywords ("troubleshoot", "call", "quality") and may return docs like `Run_the_built-in_Genesys_Cloud_WebRTC_Diagnostics_app.md`. Semantic search understands the *intent* (audio troubleshooting) and returns `Troubleshoot_the_Genesys_Cloud_WebRTC_phone.md`, `Test_your_media_settings.md` — docs that directly address the problem.

Hybrid RRF combines both, giving you the best of each.

---

## Scenario 7 — Conceptual Intent: No Keyword Overlap

**What it tests:** Semantic search understands conceptual intent — finding relevant docs even when there is zero keyword overlap between query and document.

```json
POST content-sharepoint-jina-v5-small/_search
{
  "size": 5,
  "_source": ["title"],
  "query": {
    "semantic": {
      "field": "semantic_body",
      "query": "how to handle angry customers on a call"
    }
  }
}
```

**Expected:** Returns documents like `Understand_agent_empathy_analysis.md`, `Flag_a_problematic_voice_interaction.md` — the query says "angry customers" but the documents use terms like "empathy analysis" and "problematic interaction." BM25 would miss these entirely.

---

## Scenario 8 — Filtered Hybrid: By File Type

**What it tests:** Hybrid search with metadata filters. Useful for scoping results to specific document types.

```json
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
                  { "semantic": { "field": "semantic_body", "query": "how does agent routing work in the contact center" } }
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
  "_source": ["title", "file.fileExtension"]
}
```

**Expected:** Only returns `.md` files. Results include `Direct_routing_overview.md`, `Advanced_routing_overview.md`.

---

## Scenario 9 — Filtered Hybrid: By Date Range

**What it tests:** Hybrid search scoped to recently modified documents. Useful for finding up-to-date content.

```json
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
                  { "multi_match": { "query": "AI copilot", "fields": ["title^2", "body"] } }
                ],
                "filter": [
                  { "range": { "lastModifiedDateTime": { "gte": "2024-01-01" } } }
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
                  { "semantic": { "field": "semantic_body", "query": "AI copilot for agents" } }
                ],
                "filter": [
                  { "range": { "lastModifiedDateTime": { "gte": "2024-01-01" } } }
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
  "_source": ["title", "lastModifiedDateTime"]
}
```

**Expected:** Returns AI Copilot docs modified after January 2024, like `Create_a_new_Genesys_Agent_Copilot.md`, `About_Genesys_Agent_Copilot.md`.

---

## Scenario 10 — Filtered Hybrid: By Folder Path

**What it tests:** Scope search to specific SharePoint folder hierarchies.

```json
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
                  { "multi_match": { "query": "setup configuration", "fields": ["title^2", "body"] } }
                ],
                "filter": [
                  { "wildcard": { "parentReference.path.keyword": "*Shared Documents*" } }
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
                  { "semantic": { "field": "semantic_body", "query": "initial setup and configuration steps" } }
                ],
                "filter": [
                  { "wildcard": { "parentReference.path.keyword": "*Shared Documents*" } }
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
  "_source": ["title", "parentReference.path"]
}
```

---

## Scenario 11 — Hybrid Search with Highlighting

**What it tests:** Returns highlighted text snippets showing the matching passage. Essential for building search UIs that show context.

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
  "_source": ["title"],
  "highlight": {
    "fields": {
      "body": {
        "fragment_size": 200,
        "number_of_fragments": 2,
        "pre_tags": ["<mark>"],
        "post_tags": ["</mark>"]
      }
    }
  }
}
```

**Expected:** Each result includes a `highlight.body` array with text fragments. Matched keywords are wrapped in `<mark>` tags. This is the snippet your search UI would display under each result title.

---

## Scenario 12 — Pure BM25: Exact Term Lookup

**What it tests:** Fast, deterministic keyword search. No ML inference — sub-10ms latency.

```json
POST content-sharepoint-jina-v5-small/_search
{
  "size": 5,
  "_source": ["title"],
  "query": {
    "multi_match": {
      "query": "Genesys Cloud CX",
      "fields": ["title^2", "body"]
    }
  }
}
```

**When to use BM25 alone:** When the user types an exact product name, error code, or known identifier. No semantic interpretation needed.

---

## Scenario 13 — Aggregation: Content Audit

**What it tests:** Index composition — verify all documents are properly tagged and have semantic embeddings.

```json
GET content-sharepoint-jina-v5-small/_search
{
  "size": 0,
  "aggs": {
    "total_docs": {
      "value_count": { "field": "object_type" }
    },
    "file_types": {
      "terms": { "field": "file.fileExtension", "size": 20 }
    },
    "source_types": {
      "terms": { "field": "source_type", "size": 10 }
    },
    "object_types": {
      "terms": { "field": "object_type", "size": 10 }
    },
    "has_semantic_body": {
      "filter": { "exists": { "field": "semantic_body" } }
    },
    "missing_semantic_body": {
      "filter": {
        "bool": { "must_not": { "exists": { "field": "semantic_body" } } }
      }
    },
    "has_title": {
      "filter": { "exists": { "field": "title" } }
    },
    "docs_by_month": {
      "date_histogram": {
        "field": "lastModifiedDateTime",
        "calendar_interval": "month"
      }
    }
  }
}
```

**Expected results:**
- `object_types`: only `drive_item` (pipeline drops everything else)
- `source_types`: only `sharepoint`
- `has_semantic_body`: equals total doc count
- `missing_semantic_body`: 0
- `has_title`: equals total doc count

---

## Scenario 14 — Pipeline Verification: No Duplicates

**What it tests:** Confirms the pipeline's `drop` processor is eliminating `list_item` duplicates.

```json
// Should return 0 hits
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

**Expected:** `count: 0`. If any documents appear, the pipeline is not attached or the `drop` processor has a condition error.

---

## Scenario 15 — Pipeline Verification: No Auth Tokens

**What it tests:** Confirms OAuth `tempauth` tokens from Microsoft Graph download URLs are stripped.

```json
// Should return 0 hits
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

**Expected:** 0 hits. If documents are returned, the pipeline's script processor for auth token removal is not functioning.

---

## Scenario 16 — Embedding Coverage: All Docs Have Vectors

**What it tests:** Every document in the index has a semantic embedding. Documents without embeddings are invisible to semantic search.

```json
// Documents WITHOUT semantic embeddings (should be 0)
GET content-sharepoint-jina-v5-small/_count
{
  "query": {
    "bool": {
      "must_not": {
        "exists": { "field": "semantic_body" }
      }
    }
  }
}
```

**Expected:** `count: 0`. If any documents lack `semantic_body`, they were indexed before the pipeline was attached or the `set` processor for `semantic_body` failed.

---

## Scenario 17 — Sync Health: Recent Sync Jobs

**What it tests:** Connector sync job status — confirms syncs are completing successfully.

```json
// Latest 5 sync jobs (replace YOUR_CONNECTOR_ID)
GET .elastic-connector-sync-jobs/_search
{
  "size": 5,
  "sort": [{ "started_at": "desc" }],
  "_source": [
    "status", "job_type", "started_at", "completed_at",
    "indexed_document_count", "deleted_document_count", "error"
  ]
}
```

**Expected:** Latest jobs show `status: completed`. Check `indexed_document_count` matches expected numbers. Any `status: error` jobs should be investigated — check the `error` field for details.

```json
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
  },
  "_source": ["connector.id", "error", "started_at"]
}
```

---

## Scenario 18 — Semantic Similarity: Find Similar Documents

**What it tests:** Given a known document, find other documents that are semantically similar. Useful for "related articles" features.

```json
// Step 1: Get the semantic body of a known document
POST content-sharepoint-jina-v5-small/_search
{
  "size": 1,
  "_source": ["title", "body"],
  "query": {
    "term": { "title.keyword": "About_Genesys_Agent_Copilot.md" }
  }
}

// Step 2: Use the body text as the semantic query
POST content-sharepoint-jina-v5-small/_search
{
  "size": 5,
  "_source": ["title"],
  "query": {
    "semantic": {
      "field": "semantic_body",
      "query": "Genesys Agent Copilot provides AI-powered assistance to agents during customer interactions"
    }
  }
}
```

**Expected:** Returns documents related to Agent Copilot, AI assistance, agent tools — the semantic neighborhood of the original document.

---

## Scenario 19 — Multi-Field Boosting

**What it tests:** Different boost weights on title vs body fields change result ranking. Title matches are more likely to be directly relevant.

```json
// High title boost (title^5) — favor title matches
POST content-sharepoint-jina-v5-small/_search
{
  "size": 3,
  "_source": ["title"],
  "query": {
    "multi_match": {
      "query": "ACD routing",
      "fields": ["title^5", "body"]
    }
  }
}
```

```json
// No title boost — equal weight
POST content-sharepoint-jina-v5-small/_search
{
  "size": 3,
  "_source": ["title"],
  "query": {
    "multi_match": {
      "query": "ACD routing",
      "fields": ["title", "body"]
    }
  }
}
```

**What to observe:** With high title boost, docs with "ACD" in the title rank higher. Without boost, docs that mention "ACD" many times in the body can outrank title matches. Choose the boost level based on whether title relevance or content depth matters more for your use case.

---

## Scenario 20 — Playground Integration

**What it tests:** Using the Kibana Playground feature with the hybrid search index.

### Setup in Kibana Playground

1. Navigate to **Search → Playground**
2. Select index: `content-sharepoint-jina-v5-small`
3. Select the following fields for context:
   - `title` — document title
   - `body` — full document text (for RAG context)
   - `semantic_body` — enables semantic retrieval
4. Set retrieval mode to **Hybrid (ELSER + dense)** or configure manually
5. Test with natural language questions

### Playground API Query (for custom integration)

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
                "query": "YOUR_QUESTION_HERE",
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
                "query": "YOUR_QUESTION_HERE"
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
  "_source": ["title", "body", "webUrl"],
  "highlight": {
    "fields": {
      "body": {
        "fragment_size": 300,
        "number_of_fragments": 3
      }
    }
  }
}
```

The `body` field in `_source` provides the full document text for LLM context (RAG). The `highlight` provides focused snippets for the UI.

---

## How to Interpret Results

### RRF Scores

RRF scores are not absolute confidence values — they are relative rankings. A score of `0.033` is the mathematical output of the RRF formula, not a "3.3% match." Compare scores within a single result set, not across queries.

### Semantic Scores

Semantic scores (cosine similarity) range from 0 to 1:
- `> 0.85`: Strong match — the document directly addresses the query
- `0.75-0.85`: Good match — the document is relevant but may not be a direct answer
- `0.65-0.75`: Partial match — some topical overlap
- `< 0.65`: Weak match — may be noise

### BM25 Scores

BM25 scores are unbounded (higher is better). They depend on term frequency, document length, and corpus statistics. Not comparable across different queries or indices.

### Hit Count

- `hits.total.value` in **BM25** queries shows all documents containing any query term — typically high (thousands). This is normal.
- `hits.total.value` in **semantic** queries is capped by `rank_window_size` (default 50) or the number of chunks that exceed the similarity threshold — typically 10-50. This is normal.
- `hits.total.value` in **RRF** queries shows the union of both retrievers' candidates.

---

---

## Advanced Ranking Pipelines (Scenarios 21–28)

> **Why this section exists:** Scenarios 1–20 cover the core hybrid search stack — BM25, semantic, RRF fusion, filters, and index health. Scenarios 21–28 extend that with two production-grade ranking layers:
>
> - **Jina Reranker v3** — a cross-encoder model that reads the full query+document pair and produces a fine-grained relevance score. Unlike embedding-based retrieval (which compares compressed vectors), cross-encoders see the actual text and catch nuances that vector similarity misses.
> - **Learning to Rank (LTR)** — an XGBoost LambdaMART model trained on multi-signal features (BM25 score, semantic score, rank positions, document size). Deployed to ES and applied as a rescore pass over BM25 results.
>
> **Important ES constraint:** Elasticsearch does not allow combining the `retriever` API (used by RRF) with `rescore` (used by LTR) in the same request. This means RRF+Reranker and BM25+LTR are separate pipeline options — you choose one or the other based on your use case.
>
> **Recommended sequence:** Run scenarios 21–22 first (pre-flight checks), then 23–26 (individual pipelines), then 27–28 (comparison and profiling). Each scenario builds on the previous understanding.

---

### Indexes Used in This Section

| Index | Purpose | Doc Count |
|---|---|---|
| `content-sharepoint-jina-v5-small` | Production index — supports RRF, Reranker, and baseline queries | ~6,858 |
| `content-sharepoint-ltr-lab` | LTR experimentation — duplicate of production with `genesys-ltr-v1` model deployed | ~6,858 |

The LTR lab index is a full copy of the production index, created specifically so LTR experiments never affect production search quality. All Pipeline C (LTR) queries target this index.

---

## Scenario 21 — Pre-Flight: Verify Jina Reranker v3 Endpoint

**What it tests:** Confirms the Jina Reranker v3 cross-encoder inference endpoint is deployed and healthy. This endpoint powers Pipeline A (RRF + Reranker). If this check fails, Pipeline A queries will return errors.

**Why run this first:** The reranker is an ML model running on Elastic's inference infrastructure. It can be unavailable if the deployment was deleted, the ML node is overloaded, or the endpoint name changed. Always verify before running reranker queries.

```json
GET _inference/rerank/.jina-reranker-v3
```

**What to look for in the response:**

```json
{
  "endpoints": [{
    "inference_id": ".jina-reranker-v3",
    "task_type": "rerank",
    "service": "elastic",
    "service_settings": {
      "model_id": "jina-reranker-v3"
    }
  }]
}
```

- `task_type` must be `rerank` (not `text_embedding`)
- `service` should be `elastic` (Elastic Inference Service — managed, no infra to maintain)
- If you get a 404, the endpoint needs to be created — see the framework doc for setup instructions

**Also check the other available rerankers** (useful to know what's deployed):

```json
GET _inference/rerank
```

This lists all rerank endpoints. You may see `.jina-reranker-v2-base-multilingual` and `.rerank-v1-elasticsearch` alongside v3. We use v3 for best quality.

---

## Scenario 22 — Pre-Flight: Verify LTR Model Deployment

**What it tests:** Confirms the XGBoost LambdaMART ranking model `genesys-ltr-v1` is deployed to Elasticsearch's ML infrastructure. This model powers Pipeline C (BM25 + LTR rescore). If this check fails, Pipeline C queries will return errors.

**Why run this first:** The LTR model is uploaded via eland and stored as a trained model in ES. Unlike inference endpoints (which are managed services), trained models can be accidentally deleted, fail to load, or have mismatched feature names. This check verifies the full deployment chain.

```json
GET _ml/trained_models/genesys-ltr-v1
```

**What to look for in the response:**

```json
{
  "trained_model_configs": [{
    "model_id": "genesys-ltr-v1",
    "inference_config": {
      "learning_to_rank": {
        "feature_extractors": [...]
      }
    },
    "input": {
      "field_names": [
        "bm25_score",
        "semantic_score",
        "bm25_rank",
        "semantic_rank",
        "doc_size"
      ]
    }
  }]
}
```

- `inference_config` must contain `learning_to_rank` (not `regression` or `classification`)
- `field_names` must list exactly 5 features in this order — these must match the feature extractors
- `feature_extractors` should have 5 entries, one per feature
- If the model is missing, it needs to be retrained and deployed — see `scripts/ltr-training/train_and_deploy_ltr.py`

**Check model stats** (memory usage, inference count):

```json
GET _ml/trained_models/genesys-ltr-v1/_stats
```

This shows whether the model has been loaded into memory and how many inference requests it has served. A model with `inference_count: 0` has been deployed but never used.

---

## Scenario 23 — Pipeline A: RRF + Jina Reranker v3 (Production)

**What it tests:** The full production-recommended search pipeline. First, RRF fuses BM25 keyword results and Jina v5 Small semantic results into a combined ranking. Then, the Jina Reranker v3 cross-encoder rescores the top candidates by reading the actual query-document text pairs.

**Why this is the best pipeline:** RRF provides broad recall (catching both keyword and semantic matches). The reranker provides precision — it reads the full document text against the query and can detect subtle relevance signals that neither BM25 nor vector similarity captures. The tradeoff is latency: the reranker adds ~200-500ms per query (tunable via `rank_window_size`).

**How the query works step by step:**
1. The outer `text_similarity_reranker` retriever wraps the inner `rrf` retriever
2. RRF runs both BM25 and semantic retrievers, each returning up to `rank_window_size: 50` candidates
3. RRF merges the two lists using rank fusion (`RRF_score = Σ 1/(60 + rank)`)
4. The reranker takes the top 20 RRF results (`rank_window_size: 20`) and rescores them using Jina Reranker v3
5. Final results are ordered by the cross-encoder relevance score

```json
POST content-sharepoint-jina-v5-small/_search
{
  "retriever": {
    "text_similarity_reranker": {
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
      "field": "body",
      "inference_id": ".jina-reranker-v3",
      "inference_text": "how to reset password",
      "rank_window_size": 20
    }
  },
  "size": 5,
  "_source": ["title", "webUrl"]
}
```

**Critical constraint — `rank_window_size` alignment:**
The reranker's `rank_window_size` (20) must be **less than or equal to** the inner RRF's `rank_window_size` (50). If the reranker requests more candidates than RRF produces, ES returns a validation error. This is a common mistake.

**Tuning the reranker:**

| Parameter | Current | Effect of increasing |
|---|---|---|
| Reranker `rank_window_size` | 20 | More candidates rescored → better quality but higher latency |
| RRF `rank_window_size` | 50 | Broader candidate pool for RRF → must be ≥ reranker window |
| `size` | 5 | Final results returned to the user |

**Expected results:** Password reset documents should dominate the top positions, with the reranker promoting the most directly relevant docs (like `Reset_your_password.md`) above tangentially related ones.

---

## Scenario 24 — Pipeline B: RRF Only (No Reranker)

**What it tests:** Hybrid search with RRF fusion but without the reranker pass. This is the same query from Scenario 1, included here for direct comparison with Pipeline A.

**When to use this pipeline:** When latency is critical (sub-100ms target) and you cannot afford the reranker's ~200-500ms overhead. RRF alone provides good quality for most queries — the reranker adds marginal improvement for ambiguous or nuanced queries.

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
  "_source": ["title", "webUrl"]
}
```

**How to compare with Pipeline A:** Run both Scenario 23 and Scenario 24 with the same query. Compare the ordering of the top 5 results. For straightforward queries like "how to reset password," the results may be identical. For ambiguous queries like "how to handle agent issues" (is this about contact center agents or software agents?), the reranker will produce noticeably better ordering.

---

## Scenario 25 — Pipeline C: BM25 + LTR Rescore

**What it tests:** Traditional BM25 keyword search enhanced by a machine-learned ranking model. BM25 retrieves the initial candidate set, then the LTR model rescores the top 50 candidates using 5 features: `bm25_score`, `semantic_score`, `bm25_rank`, `semantic_rank`, and `doc_size`.

**Why this is a different architecture:** This pipeline uses ES's `rescore` API instead of the `retriever` API. The `rescore` approach runs a second scoring pass over the top N results from the primary query. This is fundamentally different from RRF (which merges two retriever rankings) — here, BM25 does all the retrieval, and the LTR model reorders the results.

**Important:** This query targets `content-sharepoint-ltr-lab` (the LTR experimentation index), not the production index.

```json
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
      "params": {
        "query_string": "how to reset password"
      }
    },
    "window_size": 50
  },
  "size": 5,
  "_source": ["title", "webUrl"]
}
```

**How the LTR rescore works step by step:**
1. BM25 retrieves all documents matching the query terms, scored by term frequency and document length
2. The `rescore` pass takes the top 50 results (`window_size: 50`)
3. For each of those 50 documents, ES runs the 5 feature extractors defined in the model:
   - `bm25_score`: re-runs `match` on `body` field to get BM25 score
   - `semantic_score`: runs `match` on `title` field
   - `bm25_rank`: function_score on `body` match
   - `semantic_rank`: function_score on `title` match
   - `doc_size`: reads the `size` field value
4. The XGBoost model takes these 5 features and produces a ranking score
5. Results are reordered by the model's output score

**`params.query_string` is required:** The LTR model's feature extractors use `{{query_string}}` as a template variable. The `params` object supplies this value at query time. Omitting it causes a template rendering error.

**Current limitations:** This model was trained on synthetic judgments (auto-labeled via BM25/semantic rank agreement). The feature extractors use simplified queries (e.g., `match` on `title` for `semantic_score`) that don't exactly replicate the training-time features. For production use, the model should be retrained with feature extractors that match the inference-time queries.

---

## Scenario 26 — Pipeline D: Plain BM25 Baseline

**What it tests:** Raw keyword search with no ML enhancement — no semantic vectors, no reranker, no LTR. This is the baseline against which all other pipelines are measured.

**Why include a baseline:** Without a baseline, you cannot quantify the improvement from semantic search, RRF fusion, reranking, or LTR. Every search quality evaluation starts with "how much better is X than plain BM25?"

```json
POST content-sharepoint-jina-v5-small/_search
{
  "query": {
    "multi_match": {
      "query": "how to reset password",
      "fields": ["title^2", "body"]
    }
  },
  "size": 5,
  "_source": ["title", "webUrl"]
}
```

**What to look for:** BM25 performs well for exact keyword queries like "reset password" — expect relevant results. Where BM25 falls short:
- **Paraphrase queries** ("credential recovery procedure") — BM25 needs exact word matches
- **Conceptual queries** ("how to handle angry customers") — BM25 cannot infer meaning
- **Cross-lingual queries** ("como configurar el telefono") — BM25 only matches the indexed language

Compare this result set against Pipelines A, B, and C using the same query. The differences reveal what each ranking layer adds.

---

## Scenario 27 — Side-by-Side: 4-Pipeline Comparison

**What it tests:** Runs the same 6 test queries across all 4 pipelines to produce a comparison matrix. This is the most important evaluation — it shows the concrete impact of each ranking layer on real queries.

**How to use this scenario:** Run each query block below in Dev Tools. For each query, record the top 3 document titles from each pipeline. Then compare:
- Do the same documents appear across pipelines? (recall overlap)
- Does the ordering change? (ranking quality)
- Which pipeline surfaces the most relevant document at position #1? (precision@1)

**Query 1 — Straightforward keyword query** (all pipelines should perform well):

```json
// Pipeline A: RRF + Reranker
POST content-sharepoint-jina-v5-small/_search
{
  "retriever": {
    "text_similarity_reranker": {
      "retriever": {
        "rrf": {
          "retrievers": [
            { "standard": { "query": { "multi_match": { "query": "how to reset password", "fields": ["title^2", "body"] } } } },
            { "standard": { "query": { "semantic": { "field": "semantic_body", "query": "how to reset password" } } } }
          ],
          "rank_window_size": 50, "rank_constant": 60
        }
      },
      "field": "body", "inference_id": ".jina-reranker-v3", "inference_text": "how to reset password", "rank_window_size": 20
    }
  },
  "size": 3, "_source": ["title"]
}

// Pipeline B: RRF only
POST content-sharepoint-jina-v5-small/_search
{
  "retriever": { "rrf": { "retrievers": [
    { "standard": { "query": { "multi_match": { "query": "how to reset password", "fields": ["title^2", "body"] } } } },
    { "standard": { "query": { "semantic": { "field": "semantic_body", "query": "how to reset password" } } } }
  ], "rank_window_size": 50, "rank_constant": 60 } },
  "size": 3, "_source": ["title"]
}

// Pipeline C: BM25 + LTR (targets LTR lab index)
POST content-sharepoint-ltr-lab/_search
{
  "query": { "multi_match": { "query": "how to reset password", "fields": ["title^2", "body"] } },
  "rescore": { "learning_to_rank": { "model_id": "genesys-ltr-v1", "params": { "query_string": "how to reset password" } }, "window_size": 50 },
  "size": 3, "_source": ["title"]
}

// Pipeline D: Plain BM25
POST content-sharepoint-jina-v5-small/_search
{
  "query": { "multi_match": { "query": "how to reset password", "fields": ["title^2", "body"] } },
  "size": 3, "_source": ["title"]
}
```

**Query 2 — Paraphrase query** (semantic pipelines should outperform BM25):

Replace the query text in all 4 pipeline blocks above with:
```
"credential recovery procedure"
```

**Query 3 — Conceptual query** (reranker should shine here):

Replace the query text with:
```
"how to handle angry customers on a call"
```

**Query 4 — Technical configuration** (BM25 and LTR may do well with specific terms):

Replace the query text with:
```
"WebRTC phone configuration settings"
```

**Query 5 — Cross-lingual Spanish** (only semantic pipelines will work):

Replace the query text with:
```
"como configurar la integracion del telefono"
```

**Query 6 — Ambiguous intent** (reranker should disambiguate best):

Replace the query text with:
```
"agent assist setup"
```

**Recording your results:**

| Query | Pipeline A (RRF+Reranker) | Pipeline B (RRF) | Pipeline C (LTR) | Pipeline D (BM25) |
|---|---|---|---|---|
| reset password | #1: ? | #1: ? | #1: ? | #1: ? |
| credential recovery | #1: ? | #1: ? | #1: ? | #1: ? |
| angry customers | #1: ? | #1: ? | #1: ? | #1: ? |
| WebRTC phone config | #1: ? | #1: ? | #1: ? | #1: ? |
| Spanish integration | #1: ? | #1: ? | #1: ? | #1: ? |
| agent assist setup | #1: ? | #1: ? | #1: ? | #1: ? |

---

## Scenario 28 — Latency Profiling: Measure Pipeline Overhead

**What it tests:** Actual query latency for each pipeline, using Elasticsearch's `profile` API. This reveals exactly where time is spent — in BM25 scoring, vector search, RRF merging, reranker inference, or LTR rescoring.

**Why latency matters:** The reranker and LTR add measurable overhead. For a real-time search UI (agent assist, self-service bot), you need to know whether the quality improvement justifies the latency cost. Typical targets:
- **Agent assist (copilot suggestions):** < 500ms acceptable, < 200ms ideal
- **Self-service portal search:** < 1s acceptable, < 500ms ideal
- **Batch analytics:** latency not critical

**Profile Pipeline A (RRF + Reranker) — highest quality, highest latency:**

```json
POST content-sharepoint-jina-v5-small/_search
{
  "profile": true,
  "retriever": {
    "text_similarity_reranker": {
      "retriever": {
        "rrf": {
          "retrievers": [
            { "standard": { "query": { "multi_match": { "query": "how to reset password", "fields": ["title^2", "body"] } } } },
            { "standard": { "query": { "semantic": { "field": "semantic_body", "query": "how to reset password" } } } }
          ],
          "rank_window_size": 50, "rank_constant": 60
        }
      },
      "field": "body", "inference_id": ".jina-reranker-v3", "inference_text": "how to reset password", "rank_window_size": 20
    }
  },
  "size": 5, "_source": ["title"]
}
```

**Profile Pipeline D (Plain BM25) — lowest latency baseline:**

```json
POST content-sharepoint-jina-v5-small/_search
{
  "profile": true,
  "query": {
    "multi_match": {
      "query": "how to reset password",
      "fields": ["title^2", "body"]
    }
  },
  "size": 5, "_source": ["title"]
}
```

**How to read the profile output:**

The response includes a `profile` object with detailed timing for each query phase. Key numbers to look at:

- `took` (top-level field): Total query time in milliseconds — this is what the user experiences
- `profile.shards[].searches[].query[].time_in_nanos`: Time spent in query execution per shard
- `profile.shards[].fetch.time_in_nanos`: Time spent fetching `_source` fields

**Expected latency ranges:**

| Pipeline | Typical Latency | What Drives It |
|---|---|---|
| D: Plain BM25 | 5–20ms | BM25 scoring only — CPU-bound, very fast |
| B: RRF only | 50–200ms | BM25 + semantic vector search + RRF merge |
| C: BM25 + LTR | 20–80ms | BM25 + XGBoost model inference (lightweight) |
| A: RRF + Reranker | 200–800ms | Everything in B + cross-encoder inference on 20 docs |

**Reducing Pipeline A latency:**
- Lower `rank_window_size` on the reranker from 20 to 10 — fewer documents rescored
- Lower RRF `rank_window_size` from 50 to 25 — fewer candidates for RRF to merge
- These changes reduce latency at the cost of recall (you might miss a relevant document outside the window)

---

*Last updated: April 2026 · Indexes: content-sharepoint-jina-v5-small, content-sharepoint-ltr-lab · Models: Jina v5 Small, Jina Reranker v3, genesys-ltr-v1 · Elasticsearch 9.x*
