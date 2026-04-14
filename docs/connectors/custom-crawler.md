# Custom Web Crawler

> **Type:** Custom connector implementation · **Protocol:** HTTP/HTTPS + headless browser (optional) · **Use when:** Elastic's native web crawler cannot handle the target site (SPA, auth, dynamic content, complex pagination)

---

## Table of Contents

- [Overview](#overview)
- [When You Need a Custom Crawler](#when-you-need-a-custom-crawler)
- [Architecture Options](#architecture-options)
  - [Option A — Python + requests (Static Sites)](#option-a--python--requests-static-sites)
  - [Option B — Playwright Headless Browser (SPAs / JS-rendered)](#option-b--playwright-headless-browser-spas--js-rendered)
  - [Option C — Scrapy Framework (Large Scale)](#option-c--scrapy-framework-large-scale)
- [Indexing into Elasticsearch](#indexing-into-elasticsearch)
- [Content Extraction Patterns](#content-extraction-patterns)
- [Authentication Handling](#authentication-handling)
- [Change Detection Strategies](#change-detection-strategies)
- [Known Limitations & Tradeoffs](#known-limitations--tradeoffs)
- [Enterprise AI-KB Deployment Notes](#enterprise-ai-kb-deployment-notes)
- [Technical Q&A](#technical-qa)

---

## Overview

A custom web crawler is any non-native crawler implementation that fetches web content and indexes it into Elasticsearch. You build and maintain it yourself. Elastic does not support custom crawlers — if it breaks, you fix it.

The custom crawler feeds documents directly into Elasticsearch via the `_bulk` API, targeting the same ingest pipeline as native connectors. From Elasticsearch's perspective, the source of the document doesn't matter — it only sees the bulk request.

```
Target Site (SPA / auth-required / complex pagination)
        │
        ▼
Custom Crawler (Python / Playwright / Scrapy)
  ├── HTTP fetcher or headless browser
  ├── Content extractor (BeautifulSoup / Playwright selectors)
  ├── URL discovery / queue management
  └── Change detection (timestamp / content hash)
        │
        ▼
Elasticsearch _bulk API ──► Ingest Pipeline (Jina v3 embedding)
        │
        ▼
Tenant Index
```

---

## When You Need a Custom Crawler

Use a custom crawler when the native Elastic web crawler cannot handle the target site:

| Trigger | Native Crawler | Custom Crawler |
|---|---|---|
| Site uses React/Vue/Angular (client-side rendering) | ❌ Empty body | ✅ Playwright executes JS |
| Auth requires form login / OAuth / SSO | ❌ Not supported | ✅ Handle any auth flow |
| Content behind pagination requiring JS interaction | ❌ Cannot click | ✅ Playwright simulates user |
| Infinite scroll content | ❌ Cannot scroll | ✅ Playwright triggers scroll events |
| API-based content (JSON responses, not HTML) | ❌ Cannot parse JSON | ✅ Parse JSON directly |
| Complex crawl logic (conditional, state-dependent) | ❌ Rule-based only | ✅ Full Python logic |
| Rate limiting that requires session management | ❌ Stateless | ✅ Manage sessions and cookies |
| Sites protected by Cloudflare / bot detection | ❌ Blocked | ✅ Stealth plugins, browser fingerprinting |

---

## Architecture Options

### Option A — Python + requests (Static Sites)

For server-side rendered sites where HTML is returned directly. Simplest implementation, lowest overhead.

```python
#!/usr/bin/env python3
"""
custom_crawler_static.py
Simple crawler for server-side rendered sites.
Indexes into Elasticsearch via _bulk API.
"""
import hashlib
import time
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import requests
from elasticsearch import Elasticsearch, helpers

class StaticSiteCrawler:
    def __init__(self, entry_url: str, tenant_id: str, es: Elasticsearch,
                 allowed_domains: list = None, max_pages: int = 10000):
        self.entry_url     = entry_url
        self.tenant_id     = tenant_id
        self.es            = es
        self.allowed_domains = allowed_domains or [urlparse(entry_url).netloc]
        self.max_pages     = max_pages
        self.visited       = set()
        self.queue         = [entry_url]
        self.session       = requests.Session()
        self.session.headers.update({
            "User-Agent": "Enterprise-Knowledge-Crawler/1.0",
        })

    def is_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.netloc in self.allowed_domains and \
               parsed.scheme in ("http", "https")

    def extract_content(self, url: str, html: str) -> dict:
        soup = BeautifulSoup(html, "lxml")

        # Remove navigation, footer, sidebar noise
        for tag in soup.select("nav, footer, .sidebar, .cookie-banner, script, style"):
            tag.decompose()

        # Extract from main content area (configure per site)
        main = soup.select_one("article, main, .content, #main-content")
        body_text = (main or soup.body or soup).get_text(separator=" ", strip=True)
        title     = soup.title.string.strip() if soup.title else url

        return {
            "_id":          hashlib.md5(url.encode()).hexdigest(),
            "_index":       f"search-kb-{self.tenant_id}",
            "_op_type":     "index",
            "pipeline":     f"kb-ingest-{self.tenant_id}",
            "url":          url,
            "title":        title,
            "body":         body_text,
            "content_hash": hashlib.sha256(body_text.encode()).hexdigest(),
            "source":       "web_crawler",
        }

    def extract_links(self, base_url: str, html: str) -> list:
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            href = urljoin(base_url, a["href"])
            # Strip fragments and query params
            href = href.split("#")[0].split("?")[0]
            if href and self.is_allowed(href) and href not in self.visited:
                links.append(href)
        return links

    def crawl(self, crawl_delay: float = 0.5) -> int:
        documents = []
        indexed   = 0

        while self.queue and len(self.visited) < self.max_pages:
            url = self.queue.pop(0)
            if url in self.visited:
                continue
            self.visited.add(url)

            try:
                resp = self.session.get(url, timeout=30, allow_redirects=True)
                resp.raise_for_status()

                if "text/html" not in resp.headers.get("Content-Type", ""):
                    continue

                doc   = self.extract_content(url, resp.text)
                links = self.extract_links(url, resp.text)

                documents.append(doc)
                self.queue.extend(links)

                # Batch index every 50 documents
                if len(documents) >= 50:
                    helpers.bulk(self.es, documents)
                    indexed += len(documents)
                    documents = []
                    print(f"Indexed {indexed} documents, queue: {len(self.queue)}")

                time.sleep(crawl_delay)

            except Exception as e:
                print(f"Error crawling {url}: {e}")
                continue

        # Index remaining documents
        if documents:
            helpers.bulk(self.es, documents)
            indexed += len(documents)

        print(f"Crawl complete. Total indexed: {indexed}")
        return indexed
```

---

### Option B — Playwright Headless Browser (SPAs / JS-rendered)

For sites where content is rendered by JavaScript. Playwright controls a real Chromium browser.

```python
#!/usr/bin/env python3
"""
custom_crawler_spa.py
Headless browser crawler for JavaScript-rendered sites.
Uses Playwright — install with: pip install playwright && playwright install chromium
"""
import asyncio
import hashlib
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright
from elasticsearch import AsyncElasticsearch, helpers

class SPACrawler:
    def __init__(self, entry_url: str, tenant_id: str, es: AsyncElasticsearch,
                 content_selector: str = "main, article, .content"):
        self.entry_url        = entry_url
        self.tenant_id        = tenant_id
        self.es               = es
        self.content_selector = content_selector
        self.visited          = set()
        self.queue            = [entry_url]
        self.allowed_domain   = urlparse(entry_url).netloc

    async def crawl_page(self, page, url: str) -> dict | None:
        try:
            # Navigate and wait for content to render
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # Wait for main content element if selector is configured
            try:
                await page.wait_for_selector(self.content_selector, timeout=5000)
            except:
                pass  # Proceed even if specific selector not found

            # Extract text from content area only
            content_el = await page.query_selector(self.content_selector)
            if content_el:
                body_text = await content_el.inner_text()
            else:
                body_text = await page.inner_text("body")

            title = await page.title()

            return {
                "_id":          hashlib.md5(url.encode()).hexdigest(),
                "_index":       f"search-kb-{self.tenant_id}",
                "url":          url,
                "title":        title,
                "body":         body_text.strip(),
                "content_hash": hashlib.sha256(body_text.encode()).hexdigest(),
                "source":       "custom_web_crawler_spa",
            }
        except Exception as e:
            print(f"Error on {url}: {e}")
            return None

    async def extract_links(self, page, base_url: str) -> list:
        links = await page.eval_on_selector_all(
            "a[href]",
            "els => els.map(el => el.href)"
        )
        result = []
        for href in links:
            href = href.split("#")[0]
            if urlparse(href).netloc == self.allowed_domain and href not in self.visited:
                result.append(href)
        return result

    async def crawl(self, max_pages: int = 5000) -> int:
        indexed = 0
        documents = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Enterprise-Knowledge-Crawler/1.0",
                ignore_https_errors=False,
            )
            page = await context.new_page()

            while self.queue and len(self.visited) < max_pages:
                url = self.queue.pop(0)
                if url in self.visited:
                    continue
                self.visited.add(url)

                doc = await self.crawl_page(page, url)
                if doc:
                    documents.append(doc)
                    links = await self.extract_links(page, url)
                    self.queue.extend(links)

                if len(documents) >= 20:
                    await helpers.async_bulk(self.es, documents)
                    indexed += len(documents)
                    documents = []

            if documents:
                await helpers.async_bulk(self.es, documents)
                indexed += len(documents)

            await browser.close()

        return indexed
```

---

### Option C — Scrapy Framework (Large Scale)

For large-scale crawls (100K+ pages) where you need built-in rate limiting, retries, middleware, and distributed crawling:

```python
# scrapy_spider.py
import scrapy
import hashlib
from elasticsearch import Elasticsearch

class KnowledgeCrawlerSpider(scrapy.Spider):
    name = "knowledge_crawler"
    custom_settings = {
        "DOWNLOAD_DELAY": 0.5,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 2.0,
        "ROBOTSTXT_OBEY": True,
        "USER_AGENT": "Enterprise-Knowledge-Crawler/1.0",
    }

    def __init__(self, entry_url: str, tenant_id: str, es_host: str, **kwargs):
        super().__init__(**kwargs)
        self.start_urls = [entry_url]
        self.tenant_id  = tenant_id
        self.es         = Elasticsearch(f"https://{es_host}:9200")
        self.allowed_domains = [entry_url.split("/")[2]]
        self.buffer     = []

    def parse(self, response):
        # Extract main content
        body_text = " ".join(
            response.css("article, main, .content").css("*::text").getall()
        ).strip()

        if body_text:
            doc = {
                "_id":    hashlib.md5(response.url.encode()).hexdigest(),
                "_index": f"search-kb-{self.tenant_id}",
                "url":    response.url,
                "title":  response.css("title::text").get(""),
                "body":   body_text,
            }
            self.buffer.append({"index": {"_id": doc["_id"], "_index": doc["_index"]}})
            self.buffer.append(doc)

            if len(self.buffer) >= 100:
                self.es.bulk(operations=self.buffer)
                self.buffer = []

        # Follow links
        for href in response.css("a::attr(href)").getall():
            yield response.follow(href, callback=self.parse)

    def closed(self, reason):
        if self.buffer:
            self.es.bulk(operations=self.buffer)
```

---

## Indexing into Elasticsearch

Regardless of which crawler option you use, the indexing pattern is identical:

```python
# Direct _bulk API (no connector framework — you manage everything)
es.bulk(
    operations=[
        {"index": {"_index": f"search-kb-{tenant_id}", "_id": doc_id,
                   "pipeline": f"kb-ingest-{tenant_id}"}},
        {
            "url":   "https://docs.example.com/page",
            "title": "Page Title",
            "body":  "Extracted page text...",
        }
    ]
)
```

The ingest pipeline (`kb-ingest-{tenant_id}`) handles Jina v3 embedding, GeoIP, and any normalisation — same pipeline used by native connectors.

**Important:** Custom crawlers do NOT manage `.elastic-connectors` or `.elastic-connector-sync-jobs`. You get no Kibana UI sync monitoring, no built-in scheduling — you manage these yourself (systemd timers, cron, Airflow, etc.).

---

## Content Extraction Patterns

### CSS Selector Strategy

```python
# Priority order — try each until content found
CONTENT_SELECTORS = [
    "article[role='main']",
    "main",
    "article",
    "#main-content",
    ".article-body",
    ".kb-article",
    "[role='main']",
    "div.content",
]

NOISE_SELECTORS = [
    "nav", "header", "footer", ".sidebar",
    ".breadcrumb", ".related-articles",
    ".cookie-notice", "script", "style",
    "[aria-hidden='true']",
]
```

### Structured Data Extraction (JSON-LD)

Many modern knowledge bases embed structured data. Extract it for higher quality metadata:

```python
import json

def extract_jsonld(soup) -> dict:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if data.get("@type") in ("Article", "FAQPage", "HowTo", "TechArticle"):
                return {
                    "title":        data.get("headline", ""),
                    "description":  data.get("description", ""),
                    "date_published": data.get("datePublished"),
                    "date_modified":  data.get("dateModified"),
                    "author":        data.get("author", {}).get("name"),
                }
        except (json.JSONDecodeError, AttributeError):
            continue
    return {}
```

---

## Authentication Handling

```python
# HTTP Basic auth
session.auth = ("username", "password")

# Bearer token
session.headers["Authorization"] = f"Bearer {token}"

# Cookie-based (form login)
# 1. POST to login endpoint
resp = session.post("https://site.com/login", data={
    "username": "user",
    "password": "pass",
    "_csrf_token": get_csrf_token(session, "https://site.com/login")
})
# 2. Session now has auth cookie — subsequent requests are authenticated

# OAuth 2.0 client credentials
import requests_oauthlib
oauth = requests_oauthlib.OAuth2Session(client_id, ...)
token = oauth.fetch_token(token_url, client_secret=client_secret)
# Use oauth session for all requests
```

---

## Change Detection Strategies

Since you're not using the connector framework's built-in change detection, you need to implement your own:

```python
# Store last-crawled state in Elasticsearch itself
def get_stored_hash(es: Elasticsearch, doc_id: str, index: str) -> str | None:
    try:
        resp = es.get(index=index, id=doc_id, _source=["content_hash"])
        return resp["_source"].get("content_hash")
    except:
        return None

def should_reindex(es, doc_id, index, new_hash) -> bool:
    stored = get_stored_hash(es, doc_id, index)
    return stored != new_hash  # True if new or changed

# In the crawl loop:
new_hash = hashlib.sha256(body_text.encode()).hexdigest()
if should_reindex(es, doc_id, index, new_hash):
    # Index document
    es.index(index=index, id=doc_id, document={...})
```

Or use HTTP cache headers:
```python
# Store Last-Modified per URL
last_modified_cache = {}  # Persisted to disk between crawl runs

def fetch_if_modified(session, url, last_modified=None):
    headers = {}
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    resp = session.get(url, headers=headers)
    if resp.status_code == 304:
        return None  # Not modified — skip
    return resp
```

---

## Known Limitations & Tradeoffs

| Concern | Notes |
|---|---|
| No Elastic support | Custom crawlers are fully self-maintained. Elastic cannot help debug crawl logic. |
| No Kibana sync monitoring | You don't get `.elastic-connector-sync-jobs` monitoring. Build your own monitoring (e.g. index a crawl run summary document). |
| No scheduling built-in | Use systemd timers, cron, or an orchestrator (Airflow, Prefect). |
| Playwright resource usage | Headless Chromium is heavy — 200–400 MB RAM per browser instance. On the connector VM (`m6i.xlarge`, 16 GB), run max 4 concurrent Playwright instances. |
| Scrapy not installed by default | `pip install scrapy` — ensure it's in the connector VM's Python environment. |
| Anti-bot detection | Some sites (Cloudflare Enterprise) detect and block even stealth Playwright. No guaranteed solution. |
| Content quality variability | HTML extraction quality depends entirely on your CSS selector configuration for each target site. Requires per-site tuning. |

---

## Enterprise AI-KB Deployment Notes

Custom crawlers in the this deployment are typically used for:

1. **Customer-specific web portals built as SPAs** (React/Angular)
2. **Internal tools with form-based login** (legacy intranets, custom apps)
3. **Vendor documentation sites with complex navigation** requiring JavaScript interaction

**Deployment pattern:**

- Run as a systemd service on the same connector agent VM as the native connectors
- Scheduled via systemd timer (not cron — better logging and dependency management)
- Index into the same tenant index as native connectors (documents co-exist in one index)
- Set `source: custom_web_crawler` field for operational filtering

**Systemd service example:**

```ini
# /etc/systemd/system/crawler-tenant-123.service
[Unit]
Description=Custom Web Crawler for Tenant 123
After=network.target

[Service]
Type=oneshot
User=elastic-connector
ExecStart=/opt/connectors/venv/bin/python /opt/connectors/custom_crawler.py \
  --tenant-id tenant-123 \
  --entry-url https://portal.customer123.com \
  --es-host es-us-east-1.enterprise-internal.com \
  --max-pages 5000
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/crawler-tenant-123.timer
[Unit]
Description=Run custom crawler for Tenant 123 hourly
Requires=crawler-tenant-123.service

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

---

## Technical Q&A

<details>
<summary><strong>When Playwright navigates to a page and waits for "networkidle" — what does that actually mean and when is it insufficient?</strong></summary>

`networkidle` means Playwright waits until there have been no more than 2 active network connections for at least 500 milliseconds. This is usually sufficient for SPAs to finish their initial data fetch and render.

When it's insufficient:
- **Lazy-loaded content** — content below the fold that loads on scroll. `networkidle` fires before the user would scroll, so that content is never fetched.
- **Infinite scroll** — similar to above.
- **WebSocket-based content** — WebSocket connections are persistent and don't contribute to the `networkidle` count. Content delivered via WebSocket after initial load may not be present.
- **Deferred rendering** — some SPAs render content in `requestIdleCallback` or `setTimeout` calls after `networkidle` fires.

For these cases, use a content-based wait instead:
```python
# Wait for specific content to appear
await page.wait_for_selector("h1.article-title", timeout=10000)

# Or wait for a specific text
await page.wait_for_function(
    "() => document.querySelector('main')?.innerText.length > 100"
)
```

</details>

<details>
<summary><strong>How do you handle sites that rotate or regenerate CSRF tokens on every request?</strong></summary>

CSRF tokens protect form submissions — for crawling read-only content, you typically don't need to handle CSRF unless the login form itself has one.

For login forms with CSRF:
1. GET the login page — extract the CSRF token from the hidden form field or meta tag
2. Include the token in the POST body along with credentials
3. The session now has an auth cookie for subsequent requests

```python
def get_csrf_token(session: requests.Session, login_url: str) -> str:
    resp = session.get(login_url)
    soup = BeautifulSoup(resp.text, "lxml")
    # Common CSRF token locations:
    token = (
        soup.find("input", {"name": "_csrf_token"}) or
        soup.find("input", {"name": "csrf_token"}) or
        soup.find("meta", {"name": "csrf-token"})
    )
    return token["value"] if token else ""
```

Once logged in with a session cookie, CSRF handling is only needed if you're POST-ing data (you're not — you're just crawling GET requests). Subsequent page fetches don't require CSRF tokens.

</details>

<details>
<summary><strong>What's the memory and CPU profile of running Playwright concurrently on an m6i.xlarge connector VM alongside native connectors?</strong></summary>

Playwright Chromium per instance: ~250 MB RAM at rest, spikes to 400–500 MB when rendering complex pages. CPU: 5–15% of a vCPU during page load and rendering.

An `m6i.xlarge` has 4 vCPUs and 16 GB RAM. Native connector processes (Python) use ~150 MB each. With 4 connector processes at 150 MB = 600 MB, you have ~15 GB available for Playwright.

Practical concurrent Playwright instances on `m6i.xlarge`: **2–3 maximum**, leaving headroom for the OS and other connector processes. More than 3 concurrent Playwright instances risks OOM on complex sites.

For tenants requiring concurrent SPA crawls, either:
- Run Playwright instances sequentially (one after another) within the same VM
- Or provision a separate VM (`m6i.xlarge` or `c6i.2xlarge`) dedicated to SPA crawling

Playwright also has a high cold-start overhead (~2–3 seconds to launch Chromium). Reuse a single `BrowserContext` across multiple pages within the same crawl session rather than launching a new browser per page.

</details>

---

*Implementation guide: Elastic 8.x compatible · Last updated: 2025 · Enterprise AI-KB internal reference*
