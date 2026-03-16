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

**Modes:**
- **fast** — Single search + AI answer. 3-8 seconds. Use for quick lookups.
- **deep** — Generates sub-queries, searches in parallel, extracts full page content, cross-references sources. 15-30 seconds. Use for thorough research.

**Returns:**
```json
{
  "answer": "AI-synthesized answer text...",
  "confidence": 0.85,
  "sources": [
    {"title": "...", "url": "...", "snippet": "..."}
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
    {"url": "...", "title": "...", "content": "cleaned text (max 5000 chars)"}
  ],
  "count": 1
}
```

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
