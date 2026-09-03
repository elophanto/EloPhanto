# 53 — Web Search (Search.sh)

Structured web search and content extraction via [Search.sh](https://search.sh) — a search engine built for AI agents.

## Overview

Two tools replace browser-based Google searches with structured, citation-rich results:

- **`web_search`** — Search the web and get an AI-synthesized answer with ranked sources, citations, and confidence score
- **`web_extract`** — Extract clean text content from URLs (scripts/nav/footer removed)

Both tools are in the `data` tool group and have `SAFE` permission level.

## When to Use

Use `web_search` instead of `browser_navigate` for:
- Research tasks (market research, competitor analysis, trend tracking)
- Fact-checking and verification
- Finding current information (prices, news, releases)
- Any task that starts with "find", "research", "look up", "what is"

Use `browser_navigate` only when you need to:
- Interact with a website (click, type, login)
- Take screenshots
- Access authenticated content
- Post content to platforms

## Tools

### web_search

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search query (max 500 chars) |
| `mode` | string | No | `fast` (3-8s, default) or `deep` (15-30s) |
| `region` | string | No | ISO country code (default: `us`) |
| `max_results` | integer | No | 1-20 (default: 10) |
| `since` | string | No | ISO date: only pages the engine dates on/after this day (a filter) |
| `recency` | string | No | `past_day`, `past_week`, `past_month`, `past_year`; with `since`, the tighter bound wins |
| `freshness_boost` | boolean | No | Rank newer pages higher without excluding older ones; undated pages are not moved |

**Modes:**
- **fast** — Single search + AI answer. 3-8 seconds. Use for quick lookups.
- **deep** — Generates sub-queries, searches in parallel, extracts full page content, cross-references sources. 15-30 seconds. Use for thorough research.

**Returns:**
```json
{
  "answer": "AI-synthesized answer text...",
  "confidence": 0.85,
  "sources": [
    {"title": "...", "url": "...", "snippet": "...",
     "published_at": "2026-02-11T09:00:00.000Z", "modified_at": "2026-06-30T14:12:00.000Z",
     "date_confidence": "high",
     "date_sources": {"published_at": "article:published_time", "modified_at": "json-ld:dateModified"}}
  ],
  "conflicts": [
    {"summary": "...", "dated": true,
     "newer": {"claim": "...", "source_url": "...", "source_title": "...", "date": "2026-07-14T08:00:00.000Z"},
     "older": {"claim": "...", "source_url": "...", "source_title": "...", "date": "2024-03-02"}}
  ],
  "citations": ["..."],
  "related_queries": ["..."],
  "mode": "deep",
  "sub_queries": ["..."],
  "duration_ms": 16000
}
```

### web_extract

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `urls` | array[string] | Yes | URLs to extract (max 10 per request) |

**Returns:**
```json
{
  "pages": [
    {"url": "...", "title": "...", "content": "cleaned text (max 5000 chars)",
     "published_at": null, "modified_at": "2026-02-11T03:14:00.000Z",
     "date_confidence": "high", "date_sources": {"modified_at": "json-ld:dateModified"}}
  ],
  "count": 1
}
```

## Dates, recency and conflicts (2026-09-03)

Facts change; a search that cannot say *when* a source said something
cannot say whether it is still true. Search.sh dates every source and
extracted page (`published_at`, `modified_at`, `date_confidence`:
`high` from the page's structured markup, `medium` from visible "Last
updated" text or the engine's own label, `low` from the HTTP
`Last-Modified` header — a deploy time, an upper bound on the page's age,
never an update date; check `date_sources` before trusting `modified_at`).

Three request controls: `since` (filter, ISO date), `recency` (filter,
relative window) and `freshness_boost` (ranking bias only). Without any,
news-like queries get an automatic one-year window.

`conflicts[]` lists pairs of sources that disagree across time, newer
first; `dated: true` means both sides carry dates and the order was
verified server-side. **When it is non-empty, do not average the claims:
prefer the newer side when `dated` is true, carry the date along, and
re-query with `since` set just before the older source's date if the
change needs corroborating.** The same pairs appear on the affected
`citations[].conflict`.

The watch organ's research (`core/watch_observe.search_web_dated`) sends
`since` and `freshness_boost`, reads the source dates into its ranking,
and reports the engine's conflicts per brand and kind (docs/89, "How old
is the page").

## Research Pattern

For thorough research, chain the tools:

1. `web_search` with `mode="deep"` to get an overview + sources
2. `web_extract` on the most relevant source URLs for full content
3. `knowledge_write` to save findings for future reference

## Setup

Requires a Search.sh API key stored in the vault:

```
vault_set key=search_sh_api_key value=sk-sh_your_key_here
```

Or via CLI:

```bash
elophanto vault set search_sh_api_key sk-sh_your_key_here
```

Get your key at [search.sh/dashboard](https://search.sh/dashboard).

**Pricing:** fast search = $0.01, deep search = $0.05, extract = $0.01/URL.

## Implementation

- **Tools**: `tools/data/web_search.py` — `WebSearchTool` and `WebExtractTool`
- **Skill**: `skills/search-sh/SKILL.md`
- **Registration**: `core/registry.py`
- **Vault injection**: `core/agent.py` → `_inject_vault_deps()`
- **API**: `https://search.sh/api/search` and `https://search.sh/api/extract`
- **Timeout**: 65 seconds (API timeout is 60s)
- **Parallel-safe**: Both tools are in `_PARALLEL_SAFE_TOOLS`
