# Jina Embeddings - Technical Reference

> **Vendor:** Jina AI (acquired by Elastic) · **Integration:** Native Elasticsearch Inference Service (EIS) + self-managed ML node · **Current model in Enterprise AI-KB:** jina-embeddings-v3 · **Latest model:** jina-embeddings-v5-text

---

## Table of Contents

- [What is Jina AI](#what-is-jina-ai)
- [The Model Family](#the-model-family)
  - [jina-embeddings-v3 (current this deployment)](#jina-embeddings-v3-current-enterprise-deployment)
  - [jina-embeddings-v4 (multimodal)](#jina-embeddings-v4-multimodal)
  - [jina-embeddings-v5-text (latest)](#jina-embeddings-v5-text-latest)
  - [Model Comparison Matrix](#model-comparison-matrix)
- [Core Concepts](#core-concepts)
  - [Dense vs Sparse Vectors](#dense-vs-sparse-vectors)
  - [Task-Specific LoRA Adapters](#task-specific-lora-adapters)
  - [Matryoshka Representation Learning (MRL)](#matryoshka-representation-learning-mrl)
  - [Late Chunking](#late-chunking)
  - [Asymmetric Retrieval](#asymmetric-retrieval)
- [How Jina Works Inside Elasticsearch](#how-jina-works-inside-elasticsearch)
  - [Deployment Options](#deployment-options)
  - [Inference Endpoint Setup](#inference-endpoint-setup)
  - [semantic_text Field Type](#semantic_text-field-type)
  - [The Full Ingest Pipeline Flow](#the-full-ingest-pipeline-flow)
  - [Query-Time Embedding](#query-time-embedding)
- [Hybrid Search with Jina v3 + BM25 + RRF](#hybrid-search-with-jina-v3--bm25--rrf)
- [Performance Benchmarks](#performance-benchmarks)
- [Configuration Reference](#configuration-reference)
- [Known Limitations](#known-limitations)
- [Enterprise AI-KB Deployment Notes](#enterprise-ai-kb-deployment-notes)
  - [Current Architecture](#current-architecture)
  - [Migration Path to v5](#migration-path-to-v5)
- [Technical Q&A](#technical-qa)

---

## What is Jina AI

Jina AI is a search foundation company founded in 2020, focused on building open-source embedding models, rerankers, and small language models for retrieval and RAG applications. In early 2026, **Jina AI was acquired by Elastic**, making Jina models a first-party component of the Elastic stack.

Practically, this means:

- Jina models run natively inside Elasticsearch via the **Elastic Inference Service (EIS)** - no external API key, no third-party latency
- `semantic_text` field type in Elasticsearch now defaults to Jina embeddings on EIS
- Jina models are the Elastic-recommended path for multilingual semantic search, replacing ELSER for most use cases
- Model updates come through Elastic's release cycle

For this deployment, this is significant: the embedding model powering your hybrid search is no longer a third-party dependency - it's part of the Elastic platform you're already paying for.

### Licensing for Active Elastic Customers

> **Confirmed April 2026 by Jina AI:** If Enterprise is an active Elastic customer, commercial use of Jina models (v3, v5) is **included** - no separate license purchase or API key required. They can start using the models directly through Elastic's inference infrastructure.

This applies to:
- `jina-embeddings-v3` - included ✅
- `jina-embeddings-v5-text-small` - included ✅
- `jina-embeddings-v5-text-nano` - included ✅
- `jina-embeddings-v4` - **excluded** ❌ (non-commercial model-level restriction applies regardless of customer status)

---

## The Model Family

### jina-embeddings-v3 (current this deployment)

Released September 2024. The model currently deployed in the Enterprise AI-KB architecture.

**Architecture:** XLM-RoBERTa backbone with 24 transformer layers + 5 task-specific LoRA adapters. 570 million parameters total.

| Specification | Value |
|---|---|
| Parameters | 570M |
| Context window | 8,192 tokens (~6,000 words) |
| Output dimensions | 1,024 (default), truncatable to 64 via MRL |
| Languages | 89 languages (32 primary) |
| Tasks | Retrieval, classification, clustering, text-matching |
| License | Included for active Elastic customers - no separate license required (confirmed April 2026) |
| MTEB English score | 65.52 (vs OpenAI text-embedding-3-large: 64.6) |
| Self-managed | ONNX INT8 quantized - runs on ML node |
| EIS | ✅ Available |

**Why v3 was chosen for this deployment:** At the time of architecture design, v3 was Elastic's default for `semantic_text` on EIS, with the best balance of multilingual quality, 8K context window (covers most KB articles without chunking), and operational simplicity via ONNX INT8 deployment on self-managed ML nodes.

---

### jina-embeddings-v4 (multimodal)

Released June 2025. A significant architectural shift - v4 is a multimodal model handling both text and images.

**Architecture:** Qwen2.5-VL-3B-Instruct backbone. 3.8 billion parameters. Images are converted to token sequences and processed through the same pathway as text - no separate vision encoder tower (unlike CLIP-style models).

| Specification | Value |
|---|---|
| Parameters | 3.8B |
| Context window | 32,768 tokens |
| Output dimensions | 2,048 (single-vector), or 128 per token (multi-vector) |
| Output modes | Single-vector (dense) + multi-vector (late interaction) |
| Languages | 30+ languages |
| Tasks | Text retrieval, image retrieval, cross-modal retrieval, code search |
| License | Qwen Research License - **non-commercial only** |
| MTEB English retrieval | Comparable to v3 on text; significantly better on visual documents |
| Self-managed | Available via Hugging Face / GGUF quantization |
| EIS | ✅ Available (free, due to non-commercial license) |

> **Important:** v4 is free via API due to its non-commercial Qwen Research License. Unlike v3 and v5 (which are included for active Elastic customers), v4's non-commercial restriction applies at the model level regardless of Elastic customer status. For this deployment's production deployment, use v3 (current) or v5 (upgrade path). v4 is appropriate for research, evaluation, and prototyping only.

**When v4 makes sense:** If customers have knowledge bases containing charts, diagrams, screenshots, or visually rich PDFs (e.g. product spec sheets with embedded tables), v4's multimodal capability could significantly improve retrieval for those document types.

---

### jina-embeddings-v5-text (latest)

Released February 2026. Two sizes: `v5-text-small` (677M parameters) and `v5-text-nano` (239M parameters).

**Architecture:** Built on Qwen3-0.6B-Base (v5-small) and EuroBERT-210M (v5-nano). Trained using a novel combination of embedding distillation from Qwen3-Embedding-4B and task-specific contrastive losses.

| Specification | v5-text-small | v5-text-nano |
|---|---|---|
| Parameters | 677M | 239M |
| Context window | 32,768 tokens | 8,192 tokens |
| Output dimensions | 1,024 (default) | 768 (default) |
| Languages | 119+ | 119+ |
| MTEB English v2 | 71.7 | 71.0 |
| MMTEB (multilingual) | 67.7 | 65.5 |
| License | Commercial (via Elastic) | Commercial (via Elastic) |
| EIS | ✅ Default on EIS | ✅ Available on EIS |
| Self-managed | ONNX available | ONNX available |

**Key improvements over v3:**
- 32K token context window (v5-small) vs 8,192 - removes chunking requirement for almost all KB documents
- 119+ languages vs 89 - better coverage for this deployment's LATAM, MENA, APAC regions
- Higher MTEB scores (71.7 vs 65.52) - measurably better retrieval quality
- `semantic_text` on EIS now defaults to v5 - if you create a new deployment today, v5 is what you get automatically

> **Note for this deployment:** v5-text-small is the recommended upgrade path for quality. v5-text-nano is specifically worth evaluating for the multi-region self-managed deployment - at 239M parameters it has a significantly smaller hardware footprint than v3 (570M) or v5-small (677M), which could reduce ML node sizing requirements per region. Jina AI confirmed nano as "the strongest candidate if they need to minimize hardware footprint across 20 regions." See [Migration Path to v5](#migration-path-to-v5).

---

### Model Comparison Matrix

| | v3 | v4 | v5-text-small | v5-text-nano |
|---|---|---|---|---|
| **Text retrieval quality** | Good | Better | Best | Best (sub-500M) |
| **Multimodal (images)** | ❌ | ✅ | ❌ | ❌ |
| **Context window** | 8K | 32K | 32K | 8K |
| **Parameters** | 570M | 3.8B | 677M | 239M |
| **Commercial use** | ✅ (Elastic customer) | ❌ (research only, model-level restriction) | ✅ (Elastic customer) | ✅ (Elastic customer) |
| **EIS available** | ✅ | ✅ (free) | ✅ (default) | ✅ |
| **Self-managed ONNX** | ✅ | Via GGUF | ✅ | ✅ |
| **Enterprise AI-KB fit** | Current (deployed) | Evaluation / visually rich docs | Recommended upgrade (quality) | Recommended upgrade (multi-region hardware footprint) |

---

## Core Concepts

### Dense vs Sparse Vectors

Elasticsearch supports two types of vector search. Understanding the difference explains why Jina (dense) is used alongside BM25, not instead of it.

**Sparse vectors (ELSER):**
- Expand a query or document into thousands of weighted tokens
- Very good at exact term matching with semantic understanding
- Output: `{token: weight}` dict - e.g. `{"bank": 0.8, "financial": 0.6, "river": 0.1}`
- Good for English, less optimal for multilingual

**Dense vectors (Jina):**
- Map text to a fixed-size floating-point vector (1,024 numbers for v3)
- Capture semantic meaning in geometric space - similar meaning → similar vector direction
- Output: `[0.023, -0.14, 0.87, ...]` - 1,024 floats
- Excellent for multilingual and cross-lingual retrieval

**Why you need both (hybrid search):**
A keyword search for "reset password" finds documents containing those exact words. A semantic search finds documents about "credential recovery" or "account access issues" even if they don't use the word "password." Combining both via RRF gives you coverage of exact terms AND semantic intent simultaneously - which is why the this deployment uses BM25 + Jina kNN + RRF fusion.

---

### Task-Specific LoRA Adapters

LoRA (Low-Rank Adaptation) is a technique for specialising a neural network for different tasks without retraining the entire model. Jina v3 ships with 5 LoRA adapters - each one optimises the same base model for a different task.

```
Base model (XLM-RoBERTa, 570M parameters)
    │
    ├── retrieval.query adapter    ← queries going INTO search
    ├── retrieval.passage adapter  ← documents being INDEXED
    ├── separation adapter         ← clustering tasks
    ├── classification adapter     ← sentiment, content moderation
    └── text-matching adapter      ← semantic similarity, STS
```

**Why this matters for this deployment:**

You must use the **correct adapter for each operation**:

```python
# WRONG - same adapter for both query and document
query_embedding   = model.encode("how do I reset my password", task="text-matching")
doc_embedding     = model.encode("password recovery steps...", task="text-matching")

# CORRECT - asymmetric retrieval adapters
query_embedding   = model.encode("how do I reset my password", task="retrieval.query")
doc_embedding     = model.encode("password recovery steps...", task="retrieval.passage")
```

Using the wrong adapter silently degrades retrieval quality. The `retrieval.query` adapter is optimised for short queries (typically <50 tokens). The `retrieval.passage` adapter is optimised for longer documents. Using `text-matching` for both is a common mistake - it works but underperforms asymmetric retrieval by 5-10% on typical KB benchmarks.

In the Elasticsearch ingest pipeline, `retrieval.passage` is used automatically when indexing. At query time, the `semantic_text` query or kNN query uses `retrieval.query`.

---

### Matryoshka Representation Learning (MRL)

Jina v3 supports MRL - a training technique that allows the embedding vector to be **truncated to a smaller size** with minimal quality loss. Named after Russian nesting dolls: the information is structured so the most important dimensions come first.

```python
# Full 1,024 dimensions - maximum quality
embedding_full = model.encode(text, dimensions=1024)

# Truncated to 512 - slight quality reduction, 50% storage saving
embedding_512 = model.encode(text, dimensions=512)

# Truncated to 256 - meaningful quality reduction, 75% storage saving
embedding_256 = model.encode(text, dimensions=256)
```

**Quality vs storage tradeoff for v3 (MTEB scores):**

| Dimensions | MTEB Score | Storage vs 1024d | Recommended for |
|---|---|---|---|
| 1,024 | 65.52 | 1× (baseline) | Production (default) |
| 512 | 64.8 | 0.5× | High-volume, cost-sensitive |
| 256 | 63.1 | 0.25× | Low-latency scenarios |
| 128 | 60.4 | 0.125× | Experimental only |
| 64 | 56.2 | 0.063× | Not recommended for production |

For this deployment at 5,000 documents per tenant × 50 tenants × multi-region = 5.25M documents: using 512d instead of 1024d saves ~10 GB of vector storage globally with a <1% quality drop. Worth evaluating for cost optimisation.

---

### Late Chunking

> **Availability:** Late chunking is supported by **jina-embeddings-v3 only**. It is not available in v4 or v5. This is one of the key reasons v3 remains the production-recommended model for knowledge base retrieval use cases where chunking context matters. Confirmed by Jina AI directly (April 2026).

Late chunking is one of v3's most important features for knowledge base retrieval, and it directly addresses the chunking strategy question raised during the Enterprise call.

**Traditional (naive) chunking:**
```
Document → split into chunks → embed each chunk independently
Problem: each chunk loses context from surrounding content
```

**Late chunking:**
```
Document → embed ENTIRE document as one sequence → extract chunk 
embeddings from token-level representations at the end
Result: each chunk embedding retains full document context
```

In practice: if a document says "The company was founded in Berlin. It later expanded to New York." and you chunk after the first sentence, naive chunking embeds "The company was founded in Berlin" without knowing what "the company" refers to in context. Late chunking processes both sentences together first, so "Berlin" chunk knows it's about a company, not a city generally.

```python
# Late chunking via Jina API
response = requests.post("https://api.jina.ai/v1/embeddings", json={
    "model": "jina-embeddings-v3",
    "task": "retrieval.passage",
    "late_chunking": True,   # ← enables late chunking
    "input": [
        "The company was founded in Berlin.",
        "It later expanded to New York.",
        "Today it operates in 50 countries."
    ]
})
# Returns 3 embeddings, each contextualised by the full sequence
```

**When to enable:** For any document longer than ~500 tokens where you are splitting into multiple chunks. The quality improvement is most pronounced for documents with anaphoric references ("it", "this", "the above") across chunk boundaries.

**Limitation:** Late chunking requires the entire document to fit within the 8,192 token context window to be processed as one sequence. For documents exceeding 8,192 tokens, you must chunk first before applying late chunking to each chunk group.

**v5 and late chunking:** v5's 32K context window means most documents no longer need chunking at all - they can be embedded as a single unit. This is a different (and in many cases better) solution to the same problem late chunking addresses. If late chunking is a core requirement, stay on v3. If eliminating chunking complexity entirely is the goal, v5-small is the upgrade path.

---

### Asymmetric Retrieval

Standard semantic search assumes query and document are in the same semantic space - this works for document similarity but performs poorly for question-answer retrieval where a short question ("how do I reset my password?") should match a long document section ("To reset your account credentials, navigate to...").

Jina v3 implements **asymmetric retrieval** - different representations for queries vs documents:

```
Query:     "how do I reset my password"  →  retrieval.query adapter  →  query vector
Document:  "To reset your password..."   →  retrieval.passage adapter →  doc vector
```

These two adapters are trained jointly so their output vectors are comparable (dot product works correctly between them) but each is optimised for its role. The query adapter produces vectors that "ask a question" - they're tuned to match against answer passages rather than similar-sounding questions.

**The practical implication for this deployment:** When building the retrieval query, always specify the task as `retrieval.query`. When indexing documents, always specify `retrieval.passage`. Getting this wrong is a common silent failure - the search returns results but quality is measurably worse.

---

## How Jina Works Inside Elasticsearch

### Deployment Options

There are three ways to run Jina models in an Elasticsearch cluster. The right choice depends on your deployment constraints.

| Option | How it works | Best for | Enterprise fit |
|---|---|---|---|
| **Elastic Inference Service (EIS)** | Models run on Elastic's GPU infrastructure, accessed via API | Elastic Cloud, managed deployments | ⚠️ Requires Cloud Connect for self-managed |
| **Self-managed ML node** | ONNX model downloaded and served by Elasticsearch ML node on your own hardware | Self-managed clusters (no cloud dependency) | ✅ **Current this deployment** |
| **External Jina API** | Elasticsearch calls out to api.jina.ai per inference request | Prototyping, small scale | ❌ Not suitable for production (external dependency, latency, per-token cost) |

For this deployment's self-managed AWS EC2 deployment (no Kubernetes, no Docker), the **self-managed ML node with ONNX INT8 model** is the correct architecture. The ONNX INT8 quantized model runs on `c6i.4xlarge` ML nodes (16 vCPU, 32 GB RAM) without requiring GPU hardware.

---

### Inference Endpoint Setup

An inference endpoint is the Elasticsearch abstraction that connects a model to your indexing and search pipeline. You create one per model/task combination.

**For self-managed deployment (Enterprise architecture):**

```bash
# Step 1: Download the ONNX INT8 model to ML node
# The model is pulled from Elastic's model registry, not Hugging Face directly
PUT _ml/trained_models/jinaai__jina-embeddings-v3
{
  "input": { "field_names": ["text_field"] }
}

# Step 2: Deploy the model on ML nodes
POST _ml/trained_models/jinaai__jina-embeddings-v3/deployment/_start
{
  "number_of_allocations": 2,
  "threads_per_allocation": 4
}

# Step 3: Create inference endpoint pointing to the deployed model
PUT _inference/text_embedding/enterprise-jina-v3
{
  "service": "elasticsearch",
  "service_settings": {
    "model_id": "jinaai__jina-embeddings-v3",
    "num_allocations": 2,
    "num_threads": 4
  },
  "chunking_settings": {
    "strategy": "sentence",
    "max_chunk_size": 250,
    "sentence_overlap": 1
  }
}
```

**For EIS (Cloud / future Enterprise migration):**

```bash
PUT _inference/text_embedding/enterprise-jina-v3
{
  "service": "elastic",
  "service_settings": {
    "model_id": "jina-embeddings-v3"
  }
}
```

---

### semantic_text Field Type

`semantic_text` is Elasticsearch's highest-level abstraction for semantic search. When you declare a field as `semantic_text`, Elasticsearch automatically:

1. Chunks the text at index time using the inference endpoint's `chunking_settings`
2. Generates an embedding for each chunk
3. Stores both the raw text and the chunk embeddings as nested objects in the same document
4. At query time, embeds the query and runs kNN across all chunk embeddings
5. Returns the parent document with the best-matching chunk identified

```json
PUT /search-kb-tenant-123
{
  "mappings": {
    "properties": {
      "body": {
        "type": "semantic_text",
        "inference_id": "enterprise-jina-v3"
      },
      "title": {
        "type": "text"
      }
    }
  }
}
```

**What gets stored internally:**

```json
{
  "body": "To reset your password, click on the Forgot Password link...",
  "body_semantic": {
    "inference": {
      "inference_id": "enterprise-jina-v3",
      "model_settings": { "task_type": "text_embedding", "dimensions": 1024 }
    },
    "chunks": [
      {
        "text": "To reset your password, click on the Forgot Password link...",
        "embeddings": [0.023, -0.14, 0.87, ...]
      }
    ]
  }
}
```

> **Note for this deployment:** `semantic_text` with the self-managed ONNX model handles chunking automatically, which is exactly why Shankar told Amanda during the call that "you don't need to worry about the chunking strategy." The chunking is configured once in the inference endpoint and applied to every document automatically at index time.

---

### The Full Ingest Pipeline Flow

When a connector syncs a document and posts it to Elasticsearch, here is the exact sequence:

```
1. Connector posts document via _bulk API with pipeline parameter:
   POST /_bulk
   {"index": {"_index": "search-kb-tenant-123", "pipeline": "kb-ingest-tenant-123"}}
   {"title": "Password Reset Guide", "body": "To reset your password..."}

2. Ingest pipeline executes processors in order:
   a. attachment processor (if binary - already done for connector docs)
   b. set processor (add source, tenant_id metadata)
   c. inference processor → calls enterprise-jina-v3 inference endpoint
      → body text sent to ML node
      → ML node runs ONNX INT8 model
      → returns 1,024-dim float32 vector
      → stored as body_embedding dense_vector field
   d. (optional) PII redaction processor
   e. (optional) GeoIP enrichment

3. Document written to tenant index with:
   - original body text (BM25 searchable)
   - body_embedding dense_vector (kNN searchable)
   - all metadata fields
```

**Pipeline configuration:**

```json
PUT _ingest/pipeline/kb-ingest-tenant-123
{
  "processors": [
    {
      "inference": {
        "model_id": "enterprise-jina-v3",
        "input_output": [
          {
            "input_field":  "body",
            "output_field": "body_embedding"
          }
        ]
      }
    },
    {
      "set": {
        "field":  "tenant_id",
        "value":  "tenant-123"
      }
    }
  ]
}
```

---

### Query-Time Embedding

For hybrid search, the user's query also needs to be embedded before the kNN part of the query runs. There are two approaches:

**Option A - Embed at query time via Elasticsearch (adds latency):**

```json
GET /search-kb-tenant-123/_search
{
  "knn": {
    "field": "body_embedding",
    "query_vector_builder": {
      "text_embedding": {
        "model_id":    "enterprise-jina-v3",
        "model_text":  "how do I reset my password"
      }
    },
    "k": 10,
    "num_candidates": 50
  },
  "query": {
    "match": { "body": "reset password" }
  }
}
```

**Option B - Pre-compute query embedding at application layer (lower latency):**

```python
# Application embeds the query before calling Elasticsearch
import requests

def embed_query(query_text: str, inference_endpoint: str) -> list:
    resp = requests.post(
        f"https://es-host:9200/_inference/text_embedding/{inference_endpoint}",
        json={"input": query_text},
        headers={"Authorization": f"ApiKey {api_key}"}
    )
    return resp.json()["text_embedding"]["predicted_value"]

query_vector = embed_query("how do I reset my password", "enterprise-jina-v3")

# Then pass pre-computed vector to Elasticsearch - no ML node call in query path
es.search(index=f"search-kb-tenant-123", knn={
    "field": "body_embedding",
    "query_vector": query_vector,   # pre-computed - bypasses ML node at query time
    "k": 10,
    "num_candidates": 50
})
```

**Recommendation for this deployment:** Option B. Pre-computing the query embedding at the application layer keeps the ML node load predictable and removes it from the critical query latency path. At 140 QPS, each `query_vector_builder` call adds ~50ms to the query from the ML node - pre-computing moves this to the application tier where it can be parallelised or cached.

---

## Hybrid Search with Jina v3 + BM25 + RRF

The full hybrid search query combining BM25 (keyword) + kNN (semantic) + RRF (fusion):

```json
GET /search-kb-tenant-123/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        {
          "standard": {
            "query": {
              "match": {
                "body": {
                  "query": "reset password",
                  "fuzziness": "AUTO"
                }
              }
            }
          }
        },
        {
          "knn": {
            "field": "body_embedding",
            "query_vector": [0.023, -0.14, 0.87, ...],
            "k": 10,
            "num_candidates": 50
          }
        }
      ],
      "rank_window_size": 50,
      "rank_constant": 60
    }
  },
  "size": 5,
  "_source": ["title", "body", "url", "tenant_id"]
}
```

**How RRF works:** Each retriever (BM25 and kNN) independently ranks all documents. RRF combines the rankings using the formula:

```
RRF_score(d) = Σ 1 / (rank_constant + rank(d))

Where rank(d) is the document's position in each retriever's results.
rank_constant (default 60) controls how much top-rank advantage matters.
```

A document that ranks #1 in BM25 and #3 in kNN will outscore a document that only appears in one ranking. This means a perfectly keyword-matched document still competes with one that is semantically similar but uses different terminology.

---

## Performance Benchmarks

### MTEB Benchmark Results (jina-embeddings-v3)

MTEB (Massive Text Embedding Benchmark) is the standard benchmark for embedding models. Higher is better.

| Task | jina-v3 | OpenAI text-embedding-3-large | Cohere multilingual-v3 | Microsoft E5-large |
|---|---|---|---|---|
| English retrieval | **65.52** | 64.6 | 64.01 | 64.41 |
| Multilingual retrieval | **61.2** | 54.9 | 58.8 | 58.0 |
| Classification | **82.58** | 75.45 | N/A | 77.56 |
| Clustering | **73.4** | 72.1 | N/A | 71.8 |
| STS (semantic similarity) | **83.5** | 81.9 | 80.3 | 82.1 |

> **Note:** Jina AI confirmed (April 2026) that they do not have published hardware throughput benchmarks for self-hosted deployments. The figures below are estimates based on ONNX INT8 inference characteristics on c6i.4xlarge hardware. Treat as directional guidance - validate against your actual cluster during the POC phase.

### Latency Profile (self-managed, c6i.4xlarge, ONNX INT8, estimated)

| Operation | Latency (p50) | Latency (p99) | Notes |
|---|---|---|---|
| Single document ingest embedding | ~80ms | ~150ms | Per document at index time |
| Batch ingest (100 docs) | ~400ms total | ~800ms | ~4ms/doc in batch |
| Query-time embedding (single query) | ~40ms | ~80ms | When embedded via ML node |
| kNN search (10K docs) | ~5ms | ~12ms | After embedding computed |
| kNN search (500K docs) | ~15ms | ~35ms | HNSW index, 1024d |

### Throughput (2× c6i.4xlarge ML nodes, Enterprise spec)

| Load | Throughput | Notes |
|---|---|---|
| Ingest (steady state) | ~60 docs/sec | With Jina v3 ONNX INT8 |
| Ingest (burst, 2 ML nodes) | ~120 docs/sec | Short burst ceiling |
| Query embedding | ~240 queries/sec | Across 2 nodes |
| Hybrid queries end-to-end | ~140 QPS target | Includes BM25 + kNN + RRF |

---

## Configuration Reference

### Inference Endpoint Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `num_allocations` | integer | 1 | Number of model instances across ML nodes. Increase for higher throughput. |
| `num_threads` | integer | 1 | Threads per allocation for ONNX inference. Set to `4` for c6i.4xlarge (diminishing returns above 4 for ONNX). |
| `queue_capacity` | integer | 1024 | Max queued inference requests. Increase if you see 429 errors during sync bursts. |
| `chunking_settings.strategy` | string | `sentence` | `sentence` (respects sentence boundaries) or `word` (fixed word count). |
| `chunking_settings.max_chunk_size` | integer | 250 | Max tokens per chunk. Increase to 512 for better semantic coverage on longer passages. |
| `chunking_settings.sentence_overlap` | integer | 1 | Number of sentences to overlap between chunks. |

### Recommended Configuration for this deployment

```json
PUT _inference/text_embedding/enterprise-jina-v3
{
  "service": "elasticsearch",
  "service_settings": {
    "model_id": "jinaai__jina-embeddings-v3",
    "num_allocations": 2,
    "num_threads": 4,
    "queue_capacity": 2000
  },
  "chunking_settings": {
    "strategy": "sentence",
    "max_chunk_size": 512,
    "sentence_overlap": 1
  }
}
```

> Increasing `max_chunk_size` from the default 250 to 512 tokens improves semantic quality for longer KB articles at the cost of ~2× more storage per chunked document. For this deployment's typical 500-2,000 word KB articles, 512 tokens per chunk means most articles produce 1-3 chunks - a good balance.

### Index Mapping (dense vector approach)

```json
PUT /search-kb-tenant-123
{
  "settings": {
    "number_of_shards":   2,
    "number_of_replicas": 1
  },
  "mappings": {
    "properties": {
      "body": {
        "type": "text",
        "analyzer": "english"
      },
      "body_embedding": {
        "type":       "dense_vector",
        "dims":        1024,
        "index":       true,
        "similarity":  "cosine",
        "index_options": {
          "type":               "hnsw",
          "m":                  16,
          "ef_construction":    100
        }
      },
      "title":       { "type": "text" },
      "url":         { "type": "keyword" },
      "tenant_id":   { "type": "keyword" },
      "last_modified": { "type": "date" },
      "source":      { "type": "keyword" }
    }
  }
}
```

### HNSW Parameters

kNN uses HNSW (Hierarchical Navigable Small World) as the approximate nearest neighbor algorithm.

| Parameter | Default | Description | Enterprise recommendation |
|---|---|---|---|
| `m` | 16 | Number of bidirectional links per node. Higher = better recall, more memory. | 16 (default is fine) |
| `ef_construction` | 100 | Candidates evaluated during index build. Higher = better index quality, slower build. | 100 (default is fine) |
| `num_candidates` at query time | 100 | Candidates evaluated per shard during search. Higher = better recall, slower query. | 50 for <50K docs/tenant |

---

## Known Limitations

| Limitation | Severity | Impact | Mitigation |
|---|---|---|---|
| ONNX INT8 quantization quality loss | Low | ~1% quality reduction vs full float32. Generally not perceptible in search results. | Accept - the throughput gain (3-4× faster inference) outweighs the marginal quality loss. |
| 8,192 token context limit (v3) | Medium | Documents exceeding ~6,000 words require chunking before embedding. | Pre-ingest chunking pipeline for large documents. Or upgrade to v5 (32K context). |
| Late chunking requires full doc in context | Medium | Documents >8,192 tokens cannot use late chunking as a single sequence. | Split into sections of <8K tokens first, then apply late chunking per section. |
| Task adapter must be specified correctly | Medium | Wrong adapter (e.g. `text-matching` instead of `retrieval.query`) silently degrades quality. | Enforce `retrieval.passage` in ingest pipeline config. Enforce `retrieval.query` in query template. |
| ML node memory pressure during sync burst | Medium | 70 docs/sec burst × 80ms/doc = 5.6 concurrent inference requests per ML node. Queue depth may build up. | Two ML nodes + `queue_capacity: 2000`. Monitor `ml.inference.queue_time` metric. |
| Model version drift on upgrade | High | Changing the Jina model version changes the embedding space. Old indexed vectors are incompatible with new query vectors. | Pin `model_id` explicitly. Test on a shadow index before upgrading. Full re-index required when changing models. |
| v4 non-commercial license | High | jina-embeddings-v4 has a model-level non-commercial restriction (Qwen Research License) that applies regardless of Elastic customer status. Cannot be used in production. | Use v3 (current) or v5 (upgrade) for production. v4 for research/prototyping only. |
| Cross-lingual retrieval quality | Low | While v3 supports 89 languages, retrieval quality varies significantly for low-resource languages. LATAM Spanish and Brazilian Portuguese perform well; some African languages perform below English baseline. | Test retrieval quality on a language sample before deploying for a new language region. |

---

## Enterprise AI-KB Deployment Notes

### Current Architecture

```
Connector sync → Ingest pipeline → inference processor
                                        │
                                        ▼
                              enterprise-jina-v3 endpoint
                                        │
                                        ▼
                              ML node (c6i.4xlarge × 2)
                              ONNX INT8 jina-embeddings-v3
                              1,024-dim float32 output
                                        │
                                        ▼
                              body_embedding dense_vector field
                              stored in tenant index
```

At query time:
```
User query → application layer → embed via enterprise-jina-v3 endpoint
                                          │
                                          ▼
                                  query_vector (1,024-dim)
                                          │
                                          ▼
                          Elasticsearch hybrid search:
                          BM25(body, query_text) + kNN(body_embedding, query_vector)
                                          │
                                          ▼
                                  RRF fusion → top-k results
```

### Migration Path to v5

When Enterprise is ready to upgrade from v3 to v5, follow this process to avoid breaking production search:

```
1. Deploy v5 inference endpoint (alongside existing v3):
   PUT _inference/text_embedding/enterprise-jina-v5
   { "service_settings": { "model_id": "jina-embeddings-v5-text-small" } }

2. Create shadow index with v5 mapping:
   PUT /search-kb-tenant-123-v5
   { "mappings": { "properties": {
       "body_embedding_v5": { "type": "dense_vector", "dims": 1024 }
   }}}

3. Re-index from v3 index to v5 index:
   POST _reindex
   { "source": {"index": "search-kb-tenant-123"},
     "dest":   {"index": "search-kb-tenant-123-v5", "pipeline": "kb-ingest-v5"} }

4. Run A/B quality evaluation on a query sample (compare v3 vs v5 results)

5. Switch alias:
   POST _aliases
   { "actions": [
       {"remove": {"index": "search-kb-tenant-123",    "alias": "kb-tenant-123"}},
       {"add":    {"index": "search-kb-tenant-123-v5", "alias": "kb-tenant-123"}}
   ]}

6. Monitor for 24h, then decommission v3 index
```

> **Warning:** Do NOT re-use the same index when upgrading models. v3 and v5 embeddings live in different vector spaces - mixing them in the same `dense_vector` field produces broken kNN results. Always re-index into a fresh index.

---

## Technical Q&A

<details>
<summary><strong>Why does Elasticsearch use HNSW for kNN instead of exact nearest neighbor - and what is the actual recall in this deployment's scale?</strong></summary>

Exact nearest neighbor (brute-force) computes the dot product between the query vector and every single indexed vector. For this deployment with 5,000 docs × 50 tenants = 250,000 vectors per cluster, brute-force at 140 QPS would require 250,000 × 1,024 multiplications × 140 times/second = 35.8 billion multiply-add operations per second - computationally expensive.

HNSW (Hierarchical Navigable Small World) is an approximate nearest neighbor algorithm that builds a multi-layer graph where each node connects to its nearest neighbors. Search navigates this graph rather than scanning all vectors, giving sub-millisecond search at the cost of occasionally missing the true top-k results.

At the customer's scale (250K vectors per tenant), HNSW with default parameters (`m=16`, `ef_construction=100`) achieves approximately **97-99% recall@10** - meaning for a top-10 query, HNSW returns 9-10 of the same results that brute-force would return. The 1-3% it misses are typically marginal results (ranked 8-10) that don't affect the quality of the top-3 results shown to agents.

As tenant scale grows (e.g. 300+ tenants, 1.5M+ vectors), recall can degrade. Mitigate by increasing `num_candidates` at query time from 50 to 100 - this instructs HNSW to evaluate more candidates, improving recall at a small latency cost.

</details>

<details>
<summary><strong>What exactly happens inside the ONNX INT8 model - what is quantization and does it actually affect search quality?</strong></summary>

The Jina v3 model's neural network weights are stored as 32-bit floating-point numbers (float32) in the original model. Each weight takes 4 bytes. INT8 quantization converts these to 8-bit integers - each weight takes 1 byte. This reduces model size by ~4× and speeds up inference by 3-4× because modern CPUs have highly optimised integer arithmetic units.

The accuracy impact: during quantization, each float32 weight is mapped to the nearest integer on a scale of -128 to 127. The mapping introduces rounding errors - small but nonzero. For embedding models, this translates to approximately 0.5-1.5% lower MTEB scores compared to full float32. In practice, for knowledge base retrieval tasks, this difference is not perceptible in the quality of search results.

The ONNX format (Open Neural Network Exchange) is a standardised model representation that allows the model to run on Elasticsearch's ML node using the ONNX Runtime library - without requiring Python, PyTorch, or GPU hardware. This is why the this deployment runs Jina v3 on CPU-only `c6i.4xlarge` instances rather than GPU instances, keeping infrastructure cost significantly lower.

</details>

<details>
<summary><strong>If a tenant has documents in multiple languages, does a single query in one language retrieve documents in other languages correctly?</strong></summary>

Yes - this is one of Jina v3's core design goals. The model maps semantically similar text to nearby vectors regardless of language. A query in English about "password reset" will retrieve documents in French about "réinitialisation du mot de passe" because both phrases map to similar positions in the shared multilingual vector space.

However, there are important caveats:

**Cross-lingual retrieval quality is not uniform.** High-resource languages (English, Spanish, French, German, Chinese, Japanese) have strong cross-lingual alignment. Low-resource languages (some African languages, regional dialects) have weaker alignment because the training data was less balanced.

**BM25 (the keyword component of hybrid search) is language-specific.** A BM25 query in English does NOT match French documents because BM25 is based on exact term overlap. This means the hybrid search result for a cross-lingual query is dominated by the kNN (Jina) component for cross-language matches, while BM25 only contributes for same-language matches.

**Practical recommendation for this deployment:** If a tenant has a primarily Spanish knowledge base and agents query in Spanish, the hybrid search performs excellently. If agents occasionally query in English against a Spanish KB, the kNN component still retrieves relevant results but BM25 precision for those results is near-zero. The RRF fusion handles this gracefully - kNN results still surface correctly, just without the BM25 rank boost.

</details>

<details>
<summary><strong>How does the semantic_text field type store chunk embeddings internally - does it create child documents or store nested objects?</strong></summary>

`semantic_text` uses nested objects - specifically a `nested` field type internally under the hood. This is important because it means all chunks of a document are stored within the same Elasticsearch document (no separate child documents), but kNN search can still target individual chunks.

The internal structure after indexing a document with `semantic_text`:

```json
{
  "_id": "doc-123",
  "body": "Full article text here...",
  "_inference_fields": {
    "body": {
      "inference_id": "enterprise-jina-v3",
      "chunks": [
        {
          "text":       "First chunk of the article...",
          "embeddings": [0.023, -0.14, 0.87, ...]
        },
        {
          "text":       "Second chunk continues here...",
          "embeddings": [0.041, -0.09, 0.76, ...]
        }
      ]
    }
  }
}
```

When you run a `semantic` query or kNN against a `semantic_text` field, Elasticsearch's kNN implementation iterates over the nested chunk embeddings and scores each chunk independently. The parent document's score is the maximum score across all its chunks (max-pooling). This means a document where only one section matches the query semantically still surfaces with a high score - and the matched chunk text is returned in the response for highlighting.

The practical implication: with `semantic_text`, you do NOT need to implement parent-child retrieval manually (the pattern described in the chunking strategies doc). The `semantic_text` field handles it natively.

</details>

<details>
<summary><strong>Jina v3 was released in 2024 and v5 is already out in 2026 - should Enterprise be planning to upgrade, and what triggers the decision?</strong></summary>

The honest answer: yes, v5 is meaningfully better and the upgrade path is well-defined. The question is when, not whether.

**Arguments for upgrading to v5 now:**
- 71.7 MTEB vs 65.52 for v3 - a real quality improvement that agents would notice in search relevance
- 32K token context window eliminates the chunking complexity for long documents
- 119+ language support improves coverage for LATAM/MENA/APAC agent populations
- `semantic_text` now defaults to v5 on EIS - new Elastic deployments get v5 automatically

**Arguments for staying on v3 for now:**
- v3 is working, deployed, and producing acceptable results
- A model upgrade requires full re-indexing of all ~5.25M documents across multi-region - significant operational work without Kubernetes to orchestrate it
- The quality improvement may not be perceptible enough to justify the migration effort until you have baseline quality metrics from the production deployment

**Practical recommendation:** Run v3 for the initial production deployment. Measure retrieval quality with real agent feedback (thumbs up/down on knowledge suggestions). Once you have a quality baseline, run a parallel evaluation of v5 on a subset of tenants. If the improvement is measurable in agent satisfaction metrics, schedule the migration during a low-traffic window using the re-indexing procedure described in [Migration Path to v5](#migration-path-to-v5).

</details>

<details>
<summary><strong>What is the exact formula for how Jina's retrieval.query adapter differs from retrieval.passage - are they trained differently or just fine-tuned on different data?</strong></summary>

Both adapters share the same XLM-RoBERTa base model (570M parameters). The LoRA adapters add ~17M additional parameters (< 3% of total) as low-rank matrices that modify specific attention layers' weight matrices at inference time.

The `retrieval.passage` adapter is trained using contrastive learning on (query, positive_passage, negative_passages) triplets - it learns to produce vectors that are "answer-shaped": positioned in the embedding space to be close to short questions that the passage answers.

The `retrieval.query` adapter is trained with the inverse objective - it learns to produce vectors that are "question-shaped": positioned to be close to passages that would answer the question.

The asymmetry is critical: without separate adapters, a short query like "reset password" produces a vector close to other short phrases about passwords, not close to long passages about password procedures. The passage adapter shifts the document vectors toward a region of the space where query vectors naturally land, and the query adapter ensures query vectors land in that region.

In numerical terms: a query vector produced by `retrieval.query` will have a higher cosine similarity against a passage vector produced by `retrieval.passage` (for a truly relevant pair) than two vectors produced by `text-matching` for the same content. The improvement is typically 5-10 points on retrieval benchmarks (nDCG@10) - meaningful for production systems.

</details>

---

*Last updated: April 2026 · Based on jina-embeddings-v3 (current) and v5 (latest) · Elastic 9.x + Jina AI (Elastic acquisition) · Enterprise AI-KB internal reference*
