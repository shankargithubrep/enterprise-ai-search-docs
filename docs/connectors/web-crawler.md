# Elastic Web Crawler

> **Connector type:** Native Elastic · **Protocol:** HTTP/HTTPS · **Sync:** Scheduled crawl (full + incremental via sitemap/last-modified) · **Auth:** None (public) / HTTP Basic / Header-based

---

## Table of Contents

- [Overview](#overview)
- [How It Works](#how-it-works)
  - [Crawl Pipeline - Step by Step](#crawl-pipeline--step-by-step)
  - [URL Discovery - Sitemaps vs Link Following](#url-discovery--sitemaps-vs-link-following)
  - [Change Detection - No Native Incremental](#change-detection--no-native-incremental)
  - [Content Extraction](#content-extraction)
- [When to Use / When Not to Use](#when-to-use--when-not-to-use)
- [Configuration Reference](#configuration-reference)
  - [Core Parameters](#core-parameters)
  - [Crawl Rules](#crawl-rules)
  - [Sitemap Configuration](#sitemap-configuration)
  - [Authentication Options](#authentication-options)
  - [Programmatic Provisioning](#programmatic-provisioning)
- [Content Extraction & Field Mapping](#content-extraction--field-mapping)
- [Known Limitations](#known-limitations)
- [Enterprise AI-KB Deployment Notes](#enterprise-ai-kb-deployment-notes)
- [Technical Q&A](#technical-qa)

---

## Overview

The Elastic Web Crawler is a native Elasticsearch crawler that fetches web pages, extracts text content, and indexes it into Elasticsearch. Unlike the document connectors (S3, SharePoint, Salesforce), the web crawler works with **live URLs** - it fetches pages via HTTP/HTTPS, extracts content from the HTML, and follows links to discover new pages.

In the Enterprise AI-KB architecture, the web crawler is used for indexing **public or internal web-based knowledge sources** - product documentation sites, help centres, support portals, and internal wikis that are served as websites rather than stored in a document management system.

```
Target Website (public or internal)
  Entry URL → follow links → discover pages
        │
        ▼
HTTP/HTTPS requests (configurable user-agent, headers, auth)
        │
        ▼
Crawler Engine (URL queue, robots.txt compliance, crawl rules)
        │
        ▼
HTML Extraction (css selectors, title, meta, body)
        │
        ▼
Elasticsearch Bulk API ──► Ingest Pipeline (Jina v3 embedding)
        │
        ▼
Search Index (BM25 + kNN searchable)
```

| Component | Role |
|---|---|
| URL queue | Manages discovered URLs, deduplication, crawl order |
| robots.txt parser | Respects `Disallow` rules and `Crawl-delay` directives automatically |
| Link extractor | Parses `<a href>` tags to discover new URLs |
| Sitemap parser | Reads XML sitemaps for URL discovery and `<lastmod>` hints |
| HTML extractor | Extracts title, meta description, body text using configurable CSS selectors |
| Content hasher | SHA-256 of page content - used to skip unchanged pages on re-crawl |

---

## How It Works

### Crawl Pipeline - Step by Step

1. **Schedule trigger** - Reads cron from the crawler configuration. Default: `0 0 * * *` (daily).

2. **Seed URL enqueue** - The configured `entry_points` URLs are added to the crawl queue.

3. **URL fetch** - Crawler fetches each URL via HTTP GET with configured headers and auth. Follows redirects (configurable max redirect count).

4. **robots.txt check** - Before fetching each domain for the first time, crawler fetches `/robots.txt` and caches the directives. URLs matching `Disallow` rules are skipped.

5. **Crawl rule filtering** - URL checked against configured `crawl_rules` (include/exclude patterns). URLs not matching include rules or matching exclude rules are skipped.

6. **Content extraction** - HTML response body parsed by the crawler's built-in extractor:
   - `title` - from `<title>` tag
   - `meta_description` - from `<meta name="description">`
   - `body` - text content extracted from `<body>` with HTML tags stripped (configurable via CSS selector to extract specific sections only)
   - `headings` - `<h1>` through `<h4>` text collected

7. **Content hash check** - SHA-256 of extracted body content compared to stored hash. If unchanged, document is not re-indexed (skips bulk indexing for that URL). This is the closest thing to incremental sync.

8. **Link extraction** - All `<a href>` tags parsed. Relative URLs resolved to absolute. URLs within configured domain scope added to crawl queue.

9. **Bulk indexing** - New/changed pages batched and sent to `_bulk` API with ingest pipeline.

10. **Crawl completion** - When queue is empty, crawl job completes. Stats written to crawl status document.

---

### URL Discovery - Sitemaps vs Link Following

The crawler uses two parallel URL discovery mechanisms:

**Sitemap-based discovery (preferred):**
```xml
<!-- sitemap.xml -->
<urlset>
  <url>
    <loc>https://docs.example.com/getting-started</loc>
    <lastmod>2025-01-10</lastmod>
    <changefreq>weekly</changefreq>
  </url>
</urlset>
```

The crawler fetches the sitemap, extracts all `<loc>` URLs, and uses `<lastmod>` as a hint for change detection. If `<lastmod>` matches the stored value for a URL, the page may be skipped (configurable).

**Link-following (fallback):**
If no sitemap is configured or the sitemap doesn't cover all pages, the crawler follows `<a href>` links from the entry point. Crawl depth and domain scope are configurable to prevent the crawler from wandering to external sites.

**Recommendation:** Always configure a sitemap if one is available. Link-following is slower, less predictable, and harder to scope correctly.

---

### Change Detection - No Native Incremental

The web crawler does not have a true incremental sync mode like the document connectors. Every crawl is technically a full crawl - it re-fetches every discovered URL. The content hash comparison skips bulk indexing for unchanged pages, but the HTTP fetch still happens.

| Approach | How it works | Limitation |
|---|---|---|
| Content hash | SHA-256 of body - skip indexing if unchanged | Still fetches every URL on every crawl |
| `<lastmod>` in sitemap | Skip fetch if sitemap `<lastmod>` matches stored value | Only as reliable as the site's sitemap maintenance |
| HTTP `Last-Modified` header | Skip fetch if server `Last-Modified` matches stored value | Only works if the server sets this header correctly |
| `HTTP 304 Not Modified` | Crawler sends `If-Modified-Since` - server returns 304 | Requires server-side `304` support |

For large sites (>10,000 pages), even with content hash optimisation, a daily full crawl can be time-consuming. Configure crawl windows to run during low-traffic periods.

---

### Content Extraction

By default, the crawler extracts all visible text from `<body>`. For sites with navigation menus, footers, and sidebars, this produces noisy results - navigation text gets indexed alongside the actual article content.

Use CSS selectors to scope extraction to the main content area:

```json
{
  "extraction_rules": [
    {
      "policy": "allow",
      "rule": "css",
      "value": "article.main-content"
    },
    {
      "policy": "deny",
      "rule": "css",
      "value": "nav, footer, .sidebar, .cookie-banner"
    }
  ]
}
```

This is one of the most impactful configuration choices for search quality.

---

## When to Use / When Not to Use

| Scenario | Verdict | Reason |
|---|---|---|
| Public documentation sites with stable URLs | ✅ Use | Ideal - predictable structure, crawlable, no auth needed. |
| Internal help centre / support portal (HTTP accessible) | ✅ Use | Good fit if no native connector exists for the platform. |
| Sites with XML sitemaps | ✅ Use | Sitemap-based discovery is reliable and efficient. |
| Single-page applications (React/Angular/Vue) | ❌ Don't use | Crawler fetches raw HTML - JavaScript-rendered content is not executed. Body will be empty or contain only the app shell. Use server-side rendered (SSR) versions or the custom crawler instead. |
| Sites behind login (session-based auth) | ⚠️ Partial | HTTP Basic auth and custom headers are supported. Session-cookie auth (form login) is NOT supported. |
| Sites with infinite scroll or lazy loading | ❌ Don't use | Content loaded by JavaScript scroll events is not crawled. |
| Sites with CAPTCHA or bot protection (Cloudflare, etc.) | ❌ Don't use | Crawler will be blocked. |
| Sites that change URL structure frequently | ⚠️ Partial | Old URLs remain in index until full sync diff removes them. Stale content risk. |
| High-frequency content (news sites, blogs updated hourly) | ⚠️ Partial | Daily crawl cadence means up to 24h content freshness lag. |

---

## Configuration Reference

### Core Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `entry_points` | list of URLs | required | Seed URLs where the crawl begins. Typically the root URL or documentation index page. |
| `domains` | list of strings | derived from entry_points | Domains the crawler is allowed to follow links to. Default: same domain as entry points. |
| `max_crawl_depth` | integer | `2` | Maximum link-following depth from entry points. Depth 0 = entry points only. Depth 2 = entry + 2 levels of links. |
| `max_unique_url_count` | integer | `100000` | Maximum number of unique URLs to crawl per run. Safety cap for unexpectedly large sites. |
| `crawl_delay` | float (seconds) | `0` | Delay between HTTP requests to the same domain. Set to `0.5`-`1.0` for polite crawling of production sites. |
| `user_agent` | string | `Elastic Crawler` | HTTP User-Agent header sent with every request. |

---

### Crawl Rules

Crawl rules control which URLs are fetched. Rules are evaluated in order - first match wins.

```json
{
  "crawl_rules": [
    {
      "policy": "allow",
      "rule": "begins",
      "value": "/docs/"
    },
    {
      "policy": "allow",
      "rule": "begins",
      "value": "/knowledge-base/"
    },
    {
      "policy": "deny",
      "rule": "begins",
      "value": "/api/"
    },
    {
      "policy": "deny",
      "rule": "begins",
      "value": "/admin/"
    },
    {
      "policy": "deny",
      "rule": "ends",
      "value": ".pdf"
    },
    {
      "policy": "deny",
      "rule": "regex",
      "value": ".*\\?.*"
    }
  ]
}
```

Rule types: `begins` (URL starts with), `ends` (URL ends with), `contains` (URL contains string), `regex` (full regex match), `exact` (exact URL match).

---

### Sitemap Configuration

```json
{
  "sitemaps": [
    "https://docs.example.com/sitemap.xml",
    "https://docs.example.com/sitemap-index.xml"
  ]
}
```

Sitemap index files (pointing to multiple sitemaps) are automatically followed. The crawler processes all URLs in all referenced sitemaps.

---

### Authentication Options

```json
{
  "authentication": {
    "type": "basic",
    "username": "crawler-user",
    "password": "crawler-password"
  }
}
```

Or header-based (for API key / bearer token auth):
```json
{
  "headers": {
    "Authorization": "Bearer your-token-here",
    "X-Api-Key": "your-api-key"
  }
}
```

---

### Programmatic Provisioning

The web crawler uses a different provisioning API than document connectors - it uses the App Search Crawler API:

```http
POST /api/as/v1/engines/{engine_name}/crawler
Content-Type: application/json
Authorization: Bearer {private_key}

{
  "entry_points": [
    { "url": "https://docs.example.com" }
  ],
  "crawl_rules": [
    { "policy": "allow", "rule": "begins", "value": "/docs/" }
  ],
  "sitemaps": [
    { "url": "https://docs.example.com/sitemap.xml" }
  ]
}
```

Or via the Elasticsearch Connector API if using the connector framework version:

```python
es.connector.put(
    connector_id=f"{tenant_id}-web-crawler",
    body={
        "index_name":   f"search-kb-{tenant_id}",
        "service_type": "crawler",
        "name":         f"Tenant {tenant_id} - Web Crawler",
        "configuration": {
            "entry_points": {"value": ["https://docs.example.com"]},
            "max_crawl_depth": {"value": 3},
        }
    }
)
```

---

## Content Extraction & Field Mapping

| Elasticsearch field | Source | Notes |
|---|---|---|
| `_id` | MD5 hash of the URL | Stable across crawls for the same URL |
| `body` | HTML body text (after tag stripping) | Scoped by CSS extraction rules if configured |
| `title` | `<title>` tag content | Falls back to `<h1>` if `<title>` missing |
| `url` | Full URL of the page | Canonical URL after redirect resolution |
| `meta_description` | `<meta name="description">` | |
| `headings` | `<h1>` through `<h4>` text | Concatenated, useful for search relevance |
| `links` | All `<a href>` URLs extracted | Not indexed - used for link graph traversal |
| `last_crawled_at` | Timestamp of crawl | |
| `content_hash` | SHA-256 of extracted body | Used for change detection |

---

## Known Limitations

| Limitation | Severity | Impact | Mitigation |
|---|---|---|---|
| No JavaScript execution | High | SPAs and JS-rendered content return empty body. | Use SSR versions of sites, or custom crawler with headless browser. |
| Every crawl is effectively a full crawl | Medium | Large sites take time even with content hash optimisation. | Scope crawl precisely with crawl rules. Use sitemap with `<lastmod>`. |
| No session-cookie / form login auth | Medium | Sites requiring form-based login are not crawlable. | Use HTTP Basic or header auth. For complex auth, use custom crawler. |
| robots.txt compliance may block needed pages | Low | If target site's `robots.txt` disallows the crawler's user-agent, pages are skipped. | Set a custom `user_agent` that matches the site's allowed bots, or request the site admin to add an allow rule. |
| Duplicate content from URL parameters | Medium | `?page=1`, `?sort=title` etc. create duplicate URLs with same content. | Deny regex `.*\?.*` in crawl rules to skip parameterised URLs. |
| Stale documents from URL changes | Medium | When a site restructures URLs, old URLs remain in index. New URLs are crawled as new documents. | Weekly full sync + ES diff removes stale documents eventually. |
| Crawl politeness vs freshness tradeoff | Low | Setting `crawl_delay` to avoid overloading target server extends total crawl time. | Balance delay with crawl window. For internal sites, `crawl_delay: 0` is fine. |

---

## Enterprise AI-KB Deployment Notes

The web crawler is typically used in this deployments for:

1. **Customer-facing knowledge portals** - Help centre sites that customers maintain as web properties
2. **Product documentation sites** - Vendor documentation that agents need (e.g. software vendor docs, API references)
3. **Internal web-based wikis** - Confluence-alternative tools like Notion (web-accessible), GitBook, ReadTheDocs

**Key configuration for each deployment:**

```python
# Per tenant - web crawler instance
{
    "entry_points": [f"https://docs.customer-{tenant_id}.com"],
    "crawl_rules": [
        {"policy": "allow", "rule": "begins", "value": "/knowledge/"},
        {"policy": "allow", "rule": "begins", "value": "/docs/"},
        {"policy": "deny",  "rule": "regex",  "value": ".*\\.(pdf|zip|png|jpg)$"},
        {"policy": "deny",  "rule": "begins", "value": "/admin/"},
        {"policy": "deny",  "rule": "begins", "value": "/login"},
    ],
    "max_crawl_depth": 4,
    "crawl_delay": 0.5,
}
```

---

## Technical Q&A

<details>
<summary><strong>How does the content hash work exactly - what's hashed and what constitutes "unchanged"?</strong></summary>

The crawler computes a SHA-256 hash of the **extracted text content** (after HTML stripping and CSS selector scoping), not the raw HTML. This means:

- Changes to HTML structure (CSS class names, div nesting) that don't affect visible text → hash unchanged → page skipped
- Changes to navigation menu text that was excluded by a CSS deny rule → hash unchanged → page skipped
- Changes to a single word in the article body → hash changes → page re-indexed

The hash is stored in the Elasticsearch document's `content_hash` field. On re-crawl, the crawler computes the hash of the newly fetched content and compares. If identical, the `_bulk` INDEX operation is skipped (the document is not updated) but the `last_crawled_at` timestamp is updated via a separate UPDATE operation.

One implication: if you change your CSS extraction rules after the initial crawl, existing documents have hashes based on the old extraction scope. The new hash (from the new extraction scope) will differ even if the underlying content didn't change - triggering a re-index of all pages on the next crawl. This is correct behaviour but unexpected if you're watching indexing volumes.

</details>

<details>
<summary><strong>What happens when the crawler encounters a URL that redirects to an external domain?</strong></summary>

The crawler follows HTTP redirects (301, 302, 307, 308) up to the configured `max_redirect_count` (default: 10). If the redirect destination is outside the configured `domains` list, the crawl of that URL stops at the redirect - the external page is not fetched.

The URL that redirected is still added to the index as a document, but its body will be empty since no content was fetched from it. This can pollute the index with empty documents for redirect pages. Mitigate by adding crawl rules that exclude known redirect patterns, or by setting a deny rule for URLs that consistently redirect externally.

</details>

<details>
<summary><strong>How does the crawler handle pagination - e.g. a knowledge base with /page=1, /page=2, /page=3?</strong></summary>

If the paginated URLs follow a pattern (query parameter or path-based), you need to handle this explicitly:

**Option 1 - Allow the pattern in crawl rules:**
```json
{"policy": "allow", "rule": "regex", "value": "/knowledge.*\\?page=\\d+"}
```
The crawler fetches each page URL separately and indexes each as a distinct document with its own URL as `_id`. This creates multiple documents with overlapping content for paginated list pages.

**Option 2 - Use a sitemap:**
If the site provides a sitemap listing all paginated pages (or all individual article URLs rather than list pages), configure the sitemap and add a deny rule for paginated list pages. This way you index the canonical article pages, not the paginated index pages.

**Option 3 - Deny paginated URLs:**
```json
{"policy": "deny", "rule": "regex", "value": ".*\\?page=.*"}
```
Use this if you only want to index the first page of paginated lists (or don't want list pages in the index at all - only individual article pages).

The choice depends on the site's content structure. For knowledge base sites where individual articles have permanent URLs, option 2 or 3 is cleanest.

</details>

---

*Connector version: Elastic 9.x · Last updated: 2025 · Enterprise AI-KB internal reference*
