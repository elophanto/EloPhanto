---
name: search-sh
description: "Search engine for AI agents — structured JSON results with AI answers, citations, confidence scores, and sources via Search.sh API"
triggers:
  - search the web
  - web search
  - research online
  - find information
  - look up
  - what is
  - market research
  - competitor analysis
  - find out about
---

# Search.sh — Web Search for Agents

Search.sh is a search engine built for AI agents. Use the `web_search` and `web_extract` tools to query the web and get structured results.

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

Search the web and get an AI-synthesized answer with sources.

```
web_search query="best vector databases 2026" mode="fast"
web_search query="comparison of Next.js vs Remix for production apps" mode="deep"
```

**Modes:**
- `fast` (default) — single search + AI answer. 3-8 seconds. Use for quick lookups.
- `deep` — generates sub-queries, searches in parallel, extracts full page content. 15-30 seconds. Use for thorough research.

**Returns:** answer, sources (title + URL + snippet + `published_at` / `modified_at` / `date_confidence`), citations with attribution, `conflicts` (sources that disagree across time, newer first), confidence score (0-1), related queries.

**Dates and recency:**
- `since="2026-01-15"` — only pages the engine dates on/after that day. `recency="past_month"` (`past_day|past_week|past_month|past_year`) — the same, relative. `freshness_boost=true` — newer pages ranked higher, older ones kept.
- Check the dates before trusting a fact: a `modified_at` whose `date_sources.modified_at` is `http:last-modified` is the site's deploy time, not an update.
- When `conflicts` is non-empty, do not average the two claims: prefer the `newer` side when `dated` is true, mention the date in anything you pass on, and re-query with `since` set just before the older source's date if you need corroboration.

```
web_search query="studios powering <brand> lobby" since="2026-03-01" freshness_boost=true
```

### web_extract

Extract clean text from URLs. Use after `web_search` to read full content from specific sources.

```
web_extract urls=["https://example.com/article"]
```

Returns cleaned text (scripts/nav/footer removed), max 5000 chars per page, plus the page's own date (`published_at`, `modified_at`, `date_confidence`, `date_sources`). Up to 10 URLs per call.

## Research Pattern

For thorough research:

1. `web_search` with mode="deep" to get an overview + sources
2. `web_extract` on the most relevant source URLs for full content
3. `knowledge_write` to save findings for future reference

## Setup

Requires a Search.sh API key:

```
vault_set key=search_sh_api_key value=sk-sh_your_key_here
```

Get your key at https://search.sh/dashboard. Prepaid credits: fast search = $0.01, deep search = $0.05, extract = $0.01/URL.

## Verify

- The intended other agent / tool / channel actually received the message; an ack, message ID, or response payload is captured
- Identity, scopes, and permissions used by the call were the minimum required; over-permissioned tokens are called out
- Failure handling was exercised: at least one retry/timeout/permission-denied path is shown to behave as designed
- Hand-off context passed to the next actor is complete enough that the receiver could act without a follow-up question
- Any state mutated (config, memory, queue, file) is listed with before/after values, not just 'updated'
- Sensitive material (keys, tokens, PII) was redacted from logs/transcripts shared in the verification evidence
