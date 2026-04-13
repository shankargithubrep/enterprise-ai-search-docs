# Genesys AI Search — Elastic Connector & Crawler Docs

> Internal technical reference for the Genesys AI Knowledge Retrieval platform.  
> Covers Elastic connectors, web crawlers, and chunking strategies for the multi-tenant hybrid search deployment (BM25 + Jina v3 semantic, 21 regions, self-managed AWS EC2).

---

## Connectors

| Connector | Sync Mode | Auth | Status |
|---|---|---|---|
| [AWS S3](docs/connectors/s3.md) | Poll-based (incremental + full) | IAM Roles / Access Keys | ✅ Draft |
| [SharePoint Online](docs/connectors/sharepoint.md) | Delta query (MS Graph API) | OAuth 2.0 / Azure AD app | 🔜 Coming soon |
| [Salesforce](docs/connectors/salesforce.md) | High-watermark timestamp | OAuth 2.0 | 🔜 Coming soon |
| [ServiceNow](docs/connectors/servicenow.md) | High-watermark timestamp | Basic / OAuth | 🔜 Coming soon |
| [Confluence](docs/connectors/confluence.md) | Timestamp-based | API token / OAuth | 🔜 Coming soon |
| [Elastic Web Crawler](docs/connectors/web-crawler.md) | Scheduled crawl | None (public) / HTTP auth | 🔜 Coming soon |
| [Custom Web Crawler](docs/connectors/custom-crawler.md) | Configurable | Custom | 🔜 Coming soon |

## Chunking Strategies

| Guide | Description | Status |
|---|---|---|
| [Chunking Strategies](docs/chunking/strategies.md) | Fixed-window, recursive, semantic, parent-child — with Jina v3 & third-party (LangChain, LlamaIndex) | 🔜 Coming soon |

---

## Deployment Context

| Parameter | Value |
|---|---|
| Platform | Genesys Contact Center as a Service |
| Use case | Multi-tenant AI knowledge retrieval — agent assist, self-service bots |
| Deployment | Self-managed AWS EC2 — no Docker / Kubernetes |
| Regions | 21 worldwide, one Elasticsearch cluster per region |
| Standard tenants | 50 per region (1,200 globally) |
| ES version | 8.x (latest stable) |
| Embedding model | Jina Embeddings v3 (ONNX INT8 quantized) |
| Connector sources | Salesforce · ServiceNow · SharePoint Online · Confluence · S3 |
| Connector agent VM | `m6i.xlarge` — 1 VM per 10–15 tenants, systemd-managed |

---

## Repository Structure

```
.
├── README.md
├── docs/
│   ├── connectors/
│   │   ├── s3.md
│   │   ├── sharepoint.md          # coming soon
│   │   ├── salesforce.md          # coming soon
│   │   ├── servicenow.md          # coming soon
│   │   ├── confluence.md          # coming soon
│   │   ├── web-crawler.md         # coming soon
│   │   └── custom-crawler.md      # coming soon
│   └── chunking/
│       └── strategies.md          # coming soon
└── .github/
    ├── workflows/
    │   ├── markdown-lint.yml
    │   ├── link-check.yml
    │   └── build-pdf.yml
    └── PULL_REQUEST_TEMPLATE.md
```

---

## Contributing

See [PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md) for the checklist when adding or updating a connector doc.

---

*Maintained by Elastic Solutions Architecture · For Genesys AI-KB deployment*
