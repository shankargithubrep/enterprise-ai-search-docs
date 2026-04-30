# Enterprise AI Search — Technical Reference

> Technical reference for the Enterprise AI Knowledge Retrieval platform.
> Covers hybrid search framework, Elastic connectors, embedding models, deployment orchestration, and search testing scenarios.
> **Deployment:** Multi-tenant, multi-region, self-managed AWS EC2 (no Docker / Kubernetes).
> **Search:** BM25 + Jina v5 Small semantic + RRF fusion.

---

## Hybrid Search Framework

| Guide | Description | Status |
|---|---|---|
| [SharePoint Hybrid Search Framework](docs/framework/sharepoint-hybrid-search.md) | End-to-end guide: index creation, ingest pipeline (duplicate elimination + auth token stripping), Jina v5 Small embeddings, hybrid RRF queries, Jina Reranker v2 Multilingual, XGBoost LTR, 4-pipeline architecture, sync strategy, tenant replication, troubleshooting | ✅ Complete |

## Search Testing Scenarios

| Guide | Description | Status |
|---|---|---|
| [Search Testing Scenarios](docs/queries/search-testing-scenarios.md) | 28 copy-paste scenarios for Kibana Dev Tools: hybrid RRF, pure semantic, pure BM25, cross-lingual, filtered search, highlighting, aggregations, pipeline verification, sync health + advanced ranking (RRF + Reranker, BM25 + LTR, 4-pipeline comparison, latency profiling) | ✅ Complete |

## Deployment & Operations

| Guide | Description | Status |
|---|---|---|
| [VM Hosting & Scaling](docs/deployment/vm-hosting-scaling.md) | VM sizing (m6i.xlarge), systemd service, multi-connector single VM, horizontal/vertical/regional scaling, staggered sync, health monitoring, secret management, OS hardening | ✅ Complete |
| [Orchestration & Failover](docs/deployment/orchestration-failover.md) | Ansible role skeleton, Kibana alerting (stale connector check-in), failover runbook (VM down, crash loop, secret expired), upgrade procedure, disaster recovery | ✅ Complete |

## Connectors

| Connector | Sync Mode | Auth | Status |
|---|---|---|---|
| [AWS S3](docs/connectors/s3.md) | Poll-based (incremental + full) | IAM Roles / Access Keys | ✅ Complete |
| [SharePoint Online](docs/connectors/sharepoint.md) | Delta query (MS Graph API) | OAuth 2.0 / Azure AD app | ✅ Complete |
| [Salesforce](docs/connectors/salesforce.md) | High-watermark timestamp | OAuth 2.0 | ✅ Complete |
| [ServiceNow](docs/connectors/servicenow.md) | High-watermark timestamp | Basic / OAuth | ✅ Complete |
| [Confluence](docs/connectors/confluence.md) | Timestamp-based | API token / OAuth | ✅ Complete |
| [Elastic Web Crawler](docs/connectors/web-crawler.md) | Scheduled crawl | None (public) / HTTP auth | ✅ Complete |
| [Custom Web Crawler](docs/connectors/custom-crawler.md) | Configurable | Custom | ✅ Complete |

## Embedding Models

| Guide | Description | Status |
|---|---|---|
| [Jina Embeddings](docs/embeddings/jina.md) | Complete reference — v3, v4 (multimodal), v5 (latest). LoRA adapters, late chunking, asymmetric retrieval, HNSW, ONNX INT8, migration path v3 → v5 | ✅ Complete |

## Chunking Strategies

| Guide | Description | Status |
|---|---|---|
| [Chunking Strategies](docs/chunking/strategies.md) | Fixed-window, recursive, semantic, parent-child, sentence window — with Jina v3, LangChain, LlamaIndex, and Elasticsearch native `semantic_text` | ✅ Complete |

---

## Deployment Context

| Parameter | Value |
|---|---|
| Platform | Genesys Cloud CX — Contact Center as a Service |
| Use case | Multi-tenant AI knowledge retrieval — agent assist, self-service bots |
| Deployment | Self-managed AWS EC2 — no Docker / Kubernetes |
| Regions | Multi-region worldwide, one Elasticsearch cluster per region |
| Tenants | ~50 per region (1,200+ globally across 21 regions) |
| ES version | 9.x (latest stable) |
| Embedding model | **Jina v5 Small** (1024 dims, cosine, 119+ languages, 32K context) |
| Connector sources | SharePoint Online · Salesforce · ServiceNow · Confluence · S3 |
| Connector VM | `m6i.xlarge` — 1 VM per 10-15 tenants, systemd-managed bare Python process |
| Search | BM25 + Jina v5 Small semantic + RRF rank fusion + Jina Reranker v2 Multilingual + XGBoost LTR |

---

## Repository Structure

```
.
├── README.md
├── docs/
│   ├── framework/
│   │   └── sharepoint-hybrid-search.md   ← Start here
│   ├── queries/
│   │   └── search-testing-scenarios.md   ← 28 Dev Tools scenarios
│   ├── deployment/
│   │   ├── vm-hosting-scaling.md
│   │   └── orchestration-failover.md
│   ├── connectors/
│   │   ├── s3.md
│   │   ├── sharepoint.md
│   │   ├── salesforce.md
│   │   ├── servicenow.md
│   │   ├── confluence.md
│   │   ├── web-crawler.md
│   │   └── custom-crawler.md
│   ├── embeddings/
│   │   └── jina.md
│   └── chunking/
│       └── strategies.md
├── scripts/
│   └── ltr-training/                    ← XGBoost LTR model training & deployment
└── .github/
    └── PULL_REQUEST_TEMPLATE.md
```

---

## Quick Start

1. Read [SharePoint Hybrid Search Framework](docs/framework/sharepoint-hybrid-search.md) — covers the full pipeline from connector setup to hybrid search
2. Open **Kibana → Dev Tools** and run the [Search Testing Scenarios](docs/queries/search-testing-scenarios.md) to verify search quality
3. For production deployment, follow [VM Hosting & Scaling](docs/deployment/vm-hosting-scaling.md) and [Orchestration & Failover](docs/deployment/orchestration-failover.md)

---

*Maintained by Elastic Solutions Architecture*
