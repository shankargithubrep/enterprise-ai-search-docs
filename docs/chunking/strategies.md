# Chunking Strategies

> **Context:** Enterprise AI-KB hybrid search deployment · **Embedding model:** Jina Embeddings v3 (8,192 token context window) · **Search type:** BM25 + kNN ANN with RRF fusion

---

## Table of Contents

- [Why Chunking Matters](#why-chunking-matters)
- [Jina v3 Context Window — What It Changes](#jina-v3-context-window--what-it-changes)
- [Chunking Strategies](#chunking-strategies-1)
  - [Fixed-Window (Character / Token)](#1-fixed-window-character--token)
  - [Recursive Character Splitter](#2-recursive-character-splitter)
  - [Semantic Chunking](#3-semantic-chunking)
  - [Sentence Window Chunking](#4-sentence-window-chunking)
  - [Parent-Child (Hierarchical) Chunking](#5-parent-child-hierarchical-chunking)
  - [Document Summary Index](#6-document-summary-index)
- [Third-Party Implementations](#third-party-implementations)
  - [LangChain](#langchain)
  - [LlamaIndex](#llamaindex)
- [Elasticsearch-Native Chunking (semantic_text)](#elasticsearch-native-chunking-semantic_text)
- [Chunking for Specific Document Types](#chunking-for-specific-document-types)
- [Performance & Tradeoffs Matrix](#performance--tradeoffs-matrix)
- [Enterprise AI-KB Recommended Configuration](#enterprise-ai-kb-recommended-configuration)
- [Technical Q&A](#technical-qa)

---

## Why Chunking Matters

Most documents are too long to embed as a single vector. The embedding model converts text to a fixed-size vector — if the document exceeds the model's context window, content is truncated and lost. Even within the context window, long documents produce coarse-grained vectors that average the semantic content of many topics — reducing retrieval precision.

**The problem chunking solves:**

```
Document: "FAQ: Resetting your password (2,000 words)"
          ├── Section 1: How to reset via email (300 words)
          ├── Section 2: How to reset via SMS  (300 words)
          ├── Section 3: What to do if email not received (400 words)
          └── Section 4: Contact support (200 words)

Query: "I'm not getting the password reset email"

Without chunking:
  - One vector for the entire document
  - Vector is a blend of all 4 sections
  - Precision: LOW — section 3 is the relevant answer but the vector
    represents the whole document

With chunking (by section):
  - 4 separate vectors, one per section
  - Section 3 vector closely matches the query
  - Precision: HIGH — exactly the right chunk is returned
```

---

## Jina v3 Context Window — What It Changes

Most earlier embedding models (BERT, sentence-transformers, OpenAI ada-002) have **512 token** context windows. This forced aggressive chunking — 256–512 token chunks were mandatory.

Jina Embeddings v3 supports **8,192 tokens** (~6,000 words). This changes the chunking calculus significantly:

| Model | Context window | Max chunk size | Implication |
|---|---|---|---|
| BERT / MiniLM | 512 tokens | ~380 words | Must chunk aggressively |
| OpenAI ada-002 | 8,192 tokens | ~6,000 words | Larger chunks possible |
| Jina v3 | **8,192 tokens** | ~6,000 words | Most KB articles fit in ONE chunk |
| Jina v3 (ColBERT mode) | 8,192 tokens | ~6,000 words | Late interaction — different tradeoffs |

**Practical implication for this deployment:**

A typical knowledge base article of 500–2,000 words fits comfortably within Jina v3's 8,192 token window **without chunking**. Chunking is only necessary for:

1. Documents exceeding ~6,000 words (long policy documents, comprehensive manuals)
2. Documents where sub-section precision matters more than full-document context
3. The Elasticsearch 10 MB extraction limit (must chunk before connector sees the file)

---

## Chunking Strategies

### 1. Fixed-Window (Character / Token)

**What it is:** Split document into equal-sized chunks by character count or token count, with optional overlap.

```python
def fixed_window_chunks(text: str, chunk_size: int = 1000,
                         overlap: int = 200) -> list[str]:
    chunks = []
    start  = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap  # overlap creates context continuity
    return chunks
```

**Parameters for Jina v3:**

```python
# For Jina v3 (8,192 token window):
chunk_size    = 4000  # characters (~800 tokens) — well within window, good precision
overlap       = 400   # 10% overlap — continuity across chunk boundaries

# For shorter, more targeted retrieval:
chunk_size    = 1500  # characters (~300 tokens) — FAQ-style precision
overlap       = 150
```

**When to use:**
- ✅ Simple to implement, predictable behaviour
- ✅ Good baseline for most document types
- ✅ Predictable storage overhead (chunk_count = ceil(doc_length / (chunk_size - overlap)))

**When not to use:**
- ❌ Splits mid-sentence — semantically incomplete chunks
- ❌ Doesn't respect document structure (headings, paragraphs)
- ❌ For structured documents (SOPs, procedures) where step boundaries matter

---

### 2. Recursive Character Splitter

**What it is:** Attempts to split on natural boundaries in priority order: `\n\n` (paragraph), `\n` (line), `. ` (sentence), ` ` (word), `` (character). Falls back to smaller separators only when needed to hit the target chunk size.

```python
from langchain.text_splitter import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size      = 1000,   # target chunk size in characters
    chunk_overlap   = 200,
    separators      = ["\n\n", "\n", ". ", "? ", "! ", " ", ""],
    length_function = len,
)

chunks = splitter.split_text(document_text)
```

**Manual implementation (no LangChain dependency):**

```python
def recursive_split(text: str, chunk_size: int = 1000,
                    overlap: int = 200,
                    separators: list = None) -> list[str]:
    separators = separators or ["\n\n", "\n", ". ", " ", ""]

    def split_on_separator(text, sep):
        return text.split(sep) if sep else list(text)

    for sep in separators:
        parts = split_on_separator(text, sep)
        if all(len(p) <= chunk_size for p in parts):
            # All parts fit — join with overlap
            return _merge_with_overlap(parts, sep, chunk_size, overlap)

    # Last resort: character split
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size - overlap)]

def _merge_with_overlap(parts, sep, chunk_size, overlap):
    chunks, current = [], ""
    for part in parts:
        candidate = current + sep + part if current else part
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # Start new chunk with overlap from previous
            current = current[-overlap:] + sep + part if current else part
    if current:
        chunks.append(current)
    return chunks
```

**When to use:**
- ✅ Better semantic quality than fixed-window — respects paragraph/sentence boundaries
- ✅ Good default for mixed document types (articles, SOPs, FAQs)
- ✅ LangChain and LlamaIndex both implement this — no need to write from scratch

**When not to use:**
- ❌ Still content-agnostic — doesn't understand document structure (headers, sections)
- ❌ Documents with very long paragraphs still get split mid-paragraph

---

### 3. Semantic Chunking

**What it is:** Embeds individual sentences, then groups sentences into chunks based on embedding similarity. When the semantic similarity between consecutive sentences drops below a threshold, a chunk boundary is created.

```python
from sentence_transformers import SentenceTransformer
import numpy as np

def semantic_chunks(text: str, model_name: str = "jinaai/jina-embeddings-v3",
                    threshold: float = 0.7, max_chunk_tokens: int = 512) -> list[str]:
    # Split into sentences
    sentences = [s.strip() for s in text.replace("\n", " ").split(". ") if s.strip()]

    # Embed all sentences
    model = SentenceTransformer(model_name, trust_remote_code=True)
    embeddings = model.encode(sentences, normalize_embeddings=True)

    # Find chunk boundaries where similarity drops
    chunks, current_sents = [], [sentences[0]]

    for i in range(1, len(sentences)):
        similarity = float(np.dot(embeddings[i-1], embeddings[i]))

        if similarity < threshold:
            # Semantic break detected — close current chunk
            chunks.append(". ".join(current_sents))
            current_sents = [sentences[i]]
        else:
            current_sents.append(sentences[i])

    if current_sents:
        chunks.append(". ".join(current_sents))

    return chunks
```

**When to use:**
- ✅ Highest semantic coherence per chunk — each chunk is about one topic
- ✅ Ideal for long documents covering multiple topics (policy manuals, comprehensive guides)
- ✅ Retrieval precision is meaningfully higher than fixed-window for complex documents

**When not to use:**
- ❌ Computationally expensive — requires embedding every sentence during pre-processing
- ❌ Threshold tuning required per document type — wrong threshold produces too few or too many chunks
- ❌ Overkill for short FAQ articles that fit in one chunk anyway
- ❌ Not suitable for real-time chunking — use offline pre-processing pipeline

---

### 4. Sentence Window Chunking

**What it is:** Index individual sentences as the unit for retrieval, but when a sentence is retrieved, expand the context window to include surrounding sentences (typically ±2 or ±3) before passing to the LLM or response generation.

```python
def sentence_window_index(text: str, window_size: int = 3) -> list[dict]:
    sentences = [s.strip() for s in text.split(". ") if s.strip()]
    docs = []

    for i, sentence in enumerate(sentences):
        # Context window around this sentence
        start = max(0, i - window_size)
        end   = min(len(sentences), i + window_size + 1)
        context = ". ".join(sentences[start:end])

        docs.append({
            "sentence":   sentence,    # Indexed and embedded for retrieval
            "context":    context,     # Returned with the result for full context
            "sentence_idx": i,
            "doc_id":     "parent-doc-id",
        })

    return docs
```

**Elasticsearch mapping for sentence window:**

```json
PUT /search-kb-tenant-123
{
  "mappings": {
    "properties": {
      "sentence":       { "type": "text" },
      "sentence_vector":{ "type": "dense_vector", "dims": 1024 },
      "context":        { "type": "text", "index": false },
      "sentence_idx":   { "type": "integer" },
      "doc_id":         { "type": "keyword" }
    }
  }
}
```

**When to use:**
- ✅ High retrieval precision (sentence-level matching)
- ✅ Context-rich responses (surrounding sentences provided)
- ✅ Good for Q&A use cases where the answer is a specific sentence

**When not to use:**
- ❌ Storage overhead is high — each sentence is a separate document
- ❌ For enterprise KB (5,000 docs × avg 100 sentences = 500K sentence documents per tenant) — significantly increases index size and shard count
- ❌ BM25 at sentence level loses document-level term frequency context

---

### 5. Parent-Child (Hierarchical) Chunking

**What it is:** Index documents at two levels: small chunks for retrieval precision (child), full sections or full documents for context (parent). Retrieval uses child chunk embeddings; the returned result includes the parent document/section for full context.

```python
def hierarchical_chunks(document: dict, chunk_size: int = 400,
                         overlap: int = 50) -> tuple[dict, list[dict]]:
    """
    Returns (parent_doc, [child_chunks])
    Parent: full document stored but not embedded for retrieval
    Children: small chunks embedded for kNN retrieval, linked to parent
    """
    text = document["body"]
    doc_id = document["_id"]

    # Parent — store full content, no embedding
    parent = {
        "_id":        doc_id,
        "title":      document["title"],
        "url":        document["url"],
        "body":       text,
        "doc_type":   "parent",
        # No embedding — parent not retrieved directly
    }

    # Children — small chunks, each linked to parent
    chunks = recursive_split(text, chunk_size=chunk_size, overlap=overlap)
    children = []

    for i, chunk_text in enumerate(chunks):
        children.append({
            "_id":       f"{doc_id}_chunk_{i:04d}",
            "parent_id": doc_id,
            "chunk_idx": i,
            "body":      chunk_text,
            "title":     document["title"],
            "url":        document["url"],
            "doc_type":  "chunk",
            # body_embedding added by ingest pipeline
        })

    return parent, children
```

**Elasticsearch retrieval pattern:**

```python
# Step 1: kNN on child chunks
knn_results = es.search(index=f"search-kb-{tenant_id}", knn={
    "field": "body_embedding",
    "query_vector": query_embedding,
    "k": 10,
    "num_candidates": 50,
    "filter": {"term": {"doc_type": "chunk"}}
})

# Step 2: Fetch parent documents for the matched children
parent_ids = [hit["_source"]["parent_id"] for hit in knn_results["hits"]["hits"]]
parent_docs = es.mget(index=f"search-kb-{tenant_id}", ids=parent_ids)

# Return: matched chunk (for context of match) + full parent (for response generation)
```

**When to use:**
- ✅ Best balance of retrieval precision and response context richness
- ✅ Recommended for Enterprise AI-KB — most KBs have medium-length documents (1-10 pages)
- ✅ Efficient storage — parents stored once, children are small

**When not to use:**
- ❌ Requires two-phase retrieval (adds latency vs single-index lookup)
- ❌ More complex index mapping and query logic
- ❌ Not needed for very short documents (<400 words) that don't benefit from splitting

---

### 6. Document Summary Index

**What it is:** For each document, generate a summary and embed the summary. Retrieve documents based on summary similarity, then use the full document text for response generation.

```python
# Requires an LLM to generate summaries — use Elasticsearch's inference API
# or a separate summarisation step in the ingest pipeline

summary_ingest_pipeline = {
    "processors": [
        {
            "inference": {
                "model_id": "summary-model",
                "input_output": [
                    {"input_field": "body", "output_field": "summary"}
                ]
            }
        },
        {
            "inference": {
                "model_id": "enterprise-jina-v3",
                "input_output": [
                    {"input_field": "summary", "output_field": "summary_embedding"}
                ]
            }
        }
    ]
}
```

**When to use:**
- ✅ Long documents where full embedding loses document topic signal
- ✅ When you want high-level topic matching (what is this document about?)

**When not to use:**
- ❌ Requires summarisation model — additional infrastructure
- ❌ Summary may miss specific facts (e.g. exact error codes, step-by-step procedures) that are important for retrieval
- ❌ Overkill for typical KB article lengths (<3,000 words)

---

## Third-Party Implementations

### LangChain

LangChain provides production-ready text splitters that integrate with Elasticsearch:

```python
from langchain.text_splitter import (
    RecursiveCharacterTextSplitter,
    TokenTextSplitter,
    MarkdownTextSplitter,
    HTMLHeaderTextSplitter,
)
from langchain_elasticsearch import ElasticsearchStore

# Recommended for enterprise KB:
splitter = RecursiveCharacterTextSplitter(
    chunk_size      = 1000,
    chunk_overlap   = 200,
    separators      = ["\n## ", "\n### ", "\n\n", "\n", ". ", " ", ""],
)

# HTML-aware splitting (preserves header context in each chunk):
html_splitter = HTMLHeaderTextSplitter(
    headers_to_split_on = [
        ("h1", "header_1"),
        ("h2", "header_2"),
        ("h3", "header_3"),
    ]
)
md_docs = html_splitter.split_text(html_content)
# Each chunk now includes the header breadcrumb as metadata

# Connect to Elasticsearch
vector_store = ElasticsearchStore(
    es_url          = "https://es-host:9200",
    index_name      = f"search-kb-{tenant_id}",
    embedding       = JinaEmbeddings(model="jinaai/jina-embeddings-v3"),
    es_api_key      = tenant_api_key,
    strategy        = ElasticsearchStore.SparseVectorRetrievalStrategy(),
)

# Index chunks
vector_store.add_documents(md_docs)
```

**LangChain splitter selection guide:**

| Splitter | Use when |
|---|---|
| `RecursiveCharacterTextSplitter` | General purpose — best default |
| `TokenTextSplitter` | When you need precise token count control |
| `MarkdownTextSplitter` | Markdown documents (Confluence exports, GitHub wikis) |
| `HTMLHeaderTextSplitter` | HTML content where header structure matters |
| `SentenceTransformersTokenTextSplitter` | When using sentence-transformers models |

---

### LlamaIndex

LlamaIndex provides tighter integration with vector stores and more sophisticated chunking pipelines:

```python
from llama_index.core import Document, VectorStoreIndex, Settings
from llama_index.core.node_parser import (
    SentenceSplitter,
    SemanticSplitterNodeParser,
    HierarchicalNodeParser,
    MarkdownNodeParser,
)
from llama_index.embeddings.jinaai import JinaEmbedding
from llama_index.vector_stores.elasticsearch import ElasticsearchStore

# Configure embedding model
Settings.embed_model = JinaEmbedding(
    api_key    = None,       # Use local ONNX model via Elasticsearch ML node
    model_name = "jinaai/jina-embeddings-v3",
)
Settings.chunk_size    = 1024
Settings.chunk_overlap = 200

# Node parsers (LlamaIndex's term for chunkers):

# 1. Standard sentence splitter
sentence_splitter = SentenceSplitter(
    chunk_size    = 1024,
    chunk_overlap = 200,
)

# 2. Semantic splitter (uses embedding similarity between sentences)
semantic_splitter = SemanticSplitterNodeParser(
    embed_model             = Settings.embed_model,
    breakpoint_percentile_threshold = 95,  # Higher = fewer, larger chunks
)

# 3. Hierarchical (parent-child)
hierarchical_parser = HierarchicalNodeParser.from_defaults(
    chunk_sizes = [2048, 512, 128]  # Parent → intermediate → leaf
)

# 4. Markdown-aware (for Confluence/GitBook exports)
markdown_parser = MarkdownNodeParser()

# Connect to Elasticsearch
vector_store = ElasticsearchStore(
    index_name = f"search-kb-{tenant_id}",
    es_url     = "https://es-host:9200",
    es_api_key = tenant_api_key,
)

# Index documents
index = VectorStoreIndex.from_documents(
    documents,
    vector_store  = vector_store,
    transformations = [semantic_splitter],
)
```

**LlamaIndex vs LangChain for this deployment:**

| | LangChain | LlamaIndex |
|---|---|---|
| Chunking flexibility | Good | Excellent |
| Elasticsearch integration | Official package | Official package |
| Jina v3 integration | Via community package | Official `JinaEmbedding` class |
| Production maturity | High | High |
| Overhead | Lower | Higher (more abstractions) |
| Best for | Pipelines, agents | RAG-specific workflows |

---

## Elasticsearch-Native Chunking (`semantic_text`)

Elasticsearch 8.11+ introduced `semantic_text` field type which handles chunking natively at index time — no external chunking pipeline needed.

```json
PUT /search-kb-tenant-123
{
  "mappings": {
    "properties": {
      "body": {
        "type": "semantic_text",
        "inference_id": "enterprise-jina-v3"
      },
      "title": { "type": "text" }
    }
  }
}
```

**How it works:**
1. Document is indexed with full text in `body`
2. Elasticsearch's ML node automatically chunks the text (using the default chunking config for the inference endpoint)
3. Each chunk is embedded with the configured model
4. Chunk embeddings stored as nested objects under the parent document
5. At query time, `semantic_text` query embeds the query and performs kNN across all chunks, returning the parent document with the best-matching chunk highlighted

**Default chunking config for `semantic_text`:**

```json
PUT _inference/text_embedding/enterprise-jina-v3
{
  "service": "elasticsearch",
  "service_settings": {
    "model_id": ".multilingual-e5-small"
  },
  "chunking_settings": {
    "strategy":    "sentence",
    "max_chunk_size": 250,
    "sentence_overlap": 1
  }
}
```

**Advantages:**
- ✅ Zero external preprocessing — simplest possible architecture
- ✅ Chunking handled automatically at index time
- ✅ Built-in parent-child management — no two-phase retrieval needed
- ✅ Chunk highlighting in search results

**Limitations:**
- ⚠️ Less control over chunk size and strategy vs external chunking
- ⚠️ Default chunk size (250 tokens) may be too small for some use cases
- ⚠️ Increased index size — multiple chunk embeddings per document
- ⚠️ Requires Elasticsearch ML node configured with inference endpoint

---

## Chunking for Specific Document Types

### PDF Documents

```python
# PDF chunking via pdfplumber — preserves page structure
import pdfplumber

def chunk_pdf(pdf_path: str, chunk_size: int = 1000) -> list[dict]:
    chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue  # Skip image-only pages

            # Use page as natural chunk boundary
            # Split further if page is very long
            if len(text) <= chunk_size * 2:
                chunks.append({
                    "body":     text,
                    "page":     page_num + 1,
                    "chunk_type": "page",
                })
            else:
                # Split long pages with recursive splitter
                sub_chunks = recursive_split(text, chunk_size, overlap=100)
                for i, sub in enumerate(sub_chunks):
                    chunks.append({
                        "body":       sub,
                        "page":       page_num + 1,
                        "chunk_idx":  i,
                        "chunk_type": "page_split",
                    })
    return chunks
```

### Markdown / Confluence Exports

```python
from langchain.text_splitter import MarkdownHeaderTextSplitter

# Split on headers — each section becomes a chunk with header context
splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on = [
        ("#",   "h1"),
        ("##",  "h2"),
        ("###", "h3"),
    ]
)

chunks = splitter.split_text(markdown_text)
# Each chunk includes metadata: {"h1": "Overview", "h2": "Installation"}
# This metadata is included as a prefix in the chunk text for embedding context
```

### HTML (Connector output)

```python
from langchain.text_splitter import HTMLHeaderTextSplitter

splitter = HTMLHeaderTextSplitter(
    headers_to_split_on = [
        ("h1", "section"),
        ("h2", "subsection"),
    ]
)

chunks = splitter.split_text(html_content)
```

---

## Performance & Tradeoffs Matrix

| Strategy | Retrieval Precision | Storage Overhead | Implementation Complexity | Best Doc Type |
|---|---|---|---|---|
| No chunking (full doc) | Medium | Low | None | Short articles (<2K words) |
| Fixed-window | Medium | Medium | Low | Any |
| Recursive character | Medium-High | Medium | Low | General prose |
| Semantic chunking | High | Medium | High | Long multi-topic docs |
| Sentence window | High | High | Medium | Q&A, precise fact retrieval |
| Parent-child | High | Medium | Medium | Medium-length docs (1-10 pages) |
| `semantic_text` (native) | High | Medium-High | None (native) | Any — simplest deployment |

---

## Enterprise AI-KB Recommended Configuration

Based on the this deployment parameters (50 tenants × 5,000 docs × 1 MB avg, Jina v3 8,192 token window):

**For documents under 3,000 words (~4,000 tokens):**

```python
# No chunking needed — fits within Jina v3 context window
# Index the full document as a single Elasticsearch document
# Use semantic_text field type — handles it automatically
```

**For documents 3,000–15,000 words (compliance manuals, policy docs):**

```python
splitter = RecursiveCharacterTextSplitter(
    chunk_size    = 2000,   # ~400 tokens — good granularity for Jina v3
    chunk_overlap = 300,    # 15% overlap
    separators    = ["\n## ", "\n### ", "\n\n", "\n", ". ", " "],
)
```

**For PDF documents with known large file issue (10 MB limit bypass):**

```python
# Pre-processing pipeline BEFORE connector
# 1. Detect large PDFs (>5 MB) at upload to S3/SharePoint
# 2. Extract text with pdfplumber (page-by-page)
# 3. Apply recursive splitter (chunk_size=1500, overlap=200)
# 4. Upload chunks as separate text files to S3 prefix
# 5. Connector indexes the text files (no Tika extraction needed — already plain text)
```

**For HTML content from web crawler / Confluence:**

```python
# Use HTMLHeaderTextSplitter to preserve section context
# Each chunk includes its header breadcrumb as a prefix
# This significantly improves embedding quality for hierarchical content
```

**Overall recommendation: Use Elasticsearch `semantic_text` field type** where possible — it's the simplest path, handles chunking automatically, and integrates natively with the Jina v3 inference endpoint already configured in the cluster. Only implement custom external chunking for documents exceeding the 10 MB Tika limit (must chunk before ingest) or when you need precise control over chunk boundaries for specific content types.

---

## Technical Q&A

<details>
<summary><strong>What is the exact chunking algorithm used by Elasticsearch's semantic_text field, and how does it compare to LangChain's RecursiveCharacterTextSplitter?</strong></summary>

Elasticsearch's `semantic_text` uses a **sentence-based chunking strategy** by default:

- Splits on sentence boundaries (period + space, question mark, exclamation mark)
- Target chunk size: 250 tokens (configurable via `max_chunk_size` in the inference endpoint's `chunking_settings`)
- Overlap: 1 sentence between adjacent chunks (configurable via `sentence_overlap`)

Compared to LangChain's RecursiveCharacterTextSplitter:

| | Elasticsearch semantic_text | LangChain RecursiveCharacterTextSplitter |
|---|---|---|
| Split unit | Sentences | Characters (with natural boundary preference) |
| Chunk size control | Tokens | Characters |
| Overlap | Sentence count | Character count |
| Respect for headers | No | No (use HTMLHeaderTextSplitter for that) |
| Configuration location | Inference endpoint `chunking_settings` | Splitter constructor parameters |

For enterprise KB content, the default `semantic_text` sentence chunking with `max_chunk_size: 250` tokens produces chunks of ~1,500–2,000 characters — comparable to `RecursiveCharacterTextSplitter(chunk_size=1500)`. The main practical difference is that `semantic_text` guarantees sentence-complete chunks while recursive character splitting may split mid-sentence when a paragraph is very long.

</details>

<details>
<summary><strong>What chunk size and overlap values produce the best hybrid search results with Jina v3 specifically?</strong></summary>

Jina AI's own benchmarking for jina-embeddings-v3 on retrieval tasks suggests:

- Optimal chunk size: **256–512 tokens** for precise factual retrieval (Q&A, troubleshooting)
- Optimal chunk size: **512–1024 tokens** for context-rich retrieval (explanatory content, procedures)
- Overlap: **10–15% of chunk size** — beyond 20% overlap produces diminishing returns and inflates index size

For enterprise KB content (mix of FAQ articles, SOPs, and longer policy documents):

```python
# FAQ / troubleshooting content:
chunk_size = 400   # tokens ≈ 1,600 characters
overlap    = 60    # tokens = 15%

# SOP / procedure content:
chunk_size = 700   # tokens ≈ 2,800 characters
overlap    = 100   # tokens ≈ 14%

# Policy / compliance documents:
chunk_size = 1000  # tokens ≈ 4,000 characters
overlap    = 150   # tokens = 15%
```

The intuition: smaller chunks improve precision (the retrieved chunk is more likely to contain exactly the answer) but hurt recall (the answer context may span chunk boundaries). The overlap bridges chunk boundaries so that a sentence split between two chunks appears in both, ensuring neither chunk loses its context.

Test empirically against your specific corpus — the numbers above are starting points, not universal optima.

</details>

<details>
<summary><strong>How does chunk overlap interact with RRF (Reciprocal Rank Fusion) in hybrid search — does overlap cause duplicate retrieval that inflates RRF scores?</strong></summary>

Yes, this is a real consideration. With overlapping chunks, a query that matches content in the overlap zone between chunk N and chunk N+1 will retrieve both chunks. RRF combines BM25 and kNN rankings — if both chunks appear in both rankings, they both receive RRF scores.

The effect: overlapping content is effectively up-ranked in the final RRF result because two documents are competing for the same information retrieval slot. This is generally benign (you want to surface relevant content) but can cause apparent "duplicates" in search results.

Mitigations:

1. **Post-retrieval deduplication** — after RRF, deduplicate results where `parent_id` is the same AND `chunk_idx` values differ by 1. Keep the higher-scoring chunk.

2. **Use parent-child chunking** — retrieve at the child chunk level for precision but return the parent document. Duplicate chunks from the same parent collapse to one result.

3. **Reduce overlap** — if duplicate retrieval is a visible UX problem, reduce overlap from 15% to 5%. Precision drops slightly but duplicate results are less frequent.

4. **Accept it** — for enterprise KB (knowledge retrieval for agent assist), the top-1 or top-3 results are what matters. Duplicate chunks in positions 4–10 of the result set don't affect agent experience.

</details>

<details>
<summary><strong>How do you handle multilingual documents in the this deployment — does chunking strategy change for non-English content?</strong></summary>

Jina v3 is natively multilingual — trained on data in 89 languages. Chunking strategy is largely language-agnostic for the semantic embedding step.

Language-specific chunking considerations:

**Sentence boundary detection:** Simple period-based sentence splitting works poorly for languages without period-space boundaries (Chinese, Japanese, Thai). Use a proper sentence tokeniser:

```python
import nltk
nltk.download("punkt_tab")

# Language-aware sentence tokenisation
from nltk.tokenize import sent_tokenize
sentences = sent_tokenize(text, language="french")  # or "german", "spanish", etc.

# For CJK (Chinese/Japanese/Korean) — use a specialised tokeniser
import jieba  # Chinese word segmentation
```

**Character vs token counting:** Languages with multi-byte characters (CJK, Arabic, Hebrew) have different characters-per-token ratios. Chinese text has ~1.5 characters per token vs ~4 characters per token for English. A `chunk_size=1000` characters is ~700 tokens for English but only ~150 tokens for Chinese. Use token-based chunking (via tiktoken or sentencepiece) for consistent chunk sizes across languages.

**this deployment:** If customers have multilingual knowledge bases, use `TokenTextSplitter` with explicit `encoding_name="cl100k_base"` (OpenAI's tokeniser — close enough for cross-language token count estimation) and set `chunk_size=512` tokens regardless of language.

</details>

---

*Last updated: 2025 · Enterprise AI-KB internal reference · Elastic 8.x + Jina Embeddings v3*
