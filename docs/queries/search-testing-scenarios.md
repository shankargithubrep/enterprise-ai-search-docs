# Search Testing Scenarios — Dev Tools Reference

> **Index:** `content-sharepoint-jina-v5-small` · **Model:** Jina v5 Small (1024 dims) · **Search modes:** BM25, Semantic, Hybrid RRF, Cross-lingual, Filtered

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

*Last updated: April 2026 · Index: content-sharepoint-jina-v5-small · Jina v5 Small · Elasticsearch 9.x*
