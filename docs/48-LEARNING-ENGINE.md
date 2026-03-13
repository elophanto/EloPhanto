# Phase 15 — Learning Engine

## Overview

EloPhanto's Learning Engine turns completed tasks into compounding knowledge. Three mechanisms work together:

1. **Lesson Extraction** — after each successful task, an LLM call distills 0-2 generalizable lessons into `knowledge/learned/lessons/`. These are indexed and retrieved by future tasks via the knowledge system.
2. **Semantic Memory Search** — task memory (goal + summary) is embedded with the same vector model used for the knowledge base. Past tasks are retrieved by meaning, not keyword — "check my email" finds "log into ProtonMail and read inbox".
3. **KB Write Compression** — when `compress: true` is passed to `knowledge_write`, verbose content (scraped pages, long summaries) is compressed to ~40% of its original size before storage. The same information density is retrieved in fewer tokens.

Together these raise the effective intelligence ceiling not by changing the LLM, but by ensuring the agent arrives at each task with better context about what it already knows and what worked before.

## Why It Matters

| Before | After |
|--------|-------|
| Memory search: SQL `LIKE %keyword%` | Memory search: cosine similarity on embeddings |
| Lesson from task: lost after session ends | Lesson from task: stored in KB, retrieved next time |
| KB content: raw verbose prose | KB content: optional dense compression |
| Agent re-discovers patterns every session | Agent builds on prior discoveries |

## Architecture

```
Task completes
     │
     ├──► store_task_memory()        ← persists goal/summary/outcome in SQLite
     │         └──► embed(goal+summary) → insert into memory_vec
     │
     └──► LessonExtractor.extract_and_store()   [fire-and-forget]
               └──► LLM call: extract 0-2 lessons
               └──► write to knowledge/learned/lessons/<slug>.md
               └──► indexer.index_file() → available for future retrieval

Future task starts
     │
     └──► _auto_retrieve(goal)
               ├──► knowledge_search(goal, limit=3)    ← includes lesson files
               └──► search_memory(goal, limit=3)
                         ├──► embed(goal) → memory_vec KNN search   [if embedder]
                         └──► LIKE keyword fallback                  [if no embedder]
```

## Lesson Extraction (`core/learner.py`)

### Extraction Prompt

Conservative prompt — returns empty for routine tasks, max 2 per task:

```
You extract reusable, generalizable lessons from completed AI agent tasks.
Only extract if ALL of: generalizable, actionable, novel.
Return {"lessons": []} if the task was routine or the lesson is obvious.
```

### Lesson Format

Each lesson is a markdown file at `knowledge/learned/lessons/<slug>.md` with `scope=learned`:

```markdown
---
title: ProtonMail login requires security key bypass
scope: learned
tags: browser-automation, login, protonmail
created: 2026-03-13
---

# ProtonMail login requires security key bypass

## When This Applies
When automating login to ProtonMail with 2FA enabled

## Lesson
The security key dialog appears before the password field on ProtonMail.
Use browser_click on the "Use password instead" link first, then proceed
with the standard username/password flow. The selector is stable across sessions.

## Source
First learned from: log into ProtonMail and check for new messages
```

If a lesson file for the same slug already exists, a new `## Observation` section is appended — the file grows richer over time rather than being overwritten.

### Compression (`compress_content`)

`LessonExtractor.compress_content(content)` is also used by `knowledge_write` when `compress=true`:

```python
# Agent calls:
knowledge_write(path="learned/scraped.md", content=raw_page, compress=True)
# → LLM reduces verbose HTML-extracted text to dense facts
# → ~40% of original length stored and indexed
```

Fallback: if the LLM call fails or returns longer text, the original content is stored unchanged.

## Semantic Memory Search (`core/memory.py`)

### Storage

Every `store_task_memory()` call now also:
1. Embeds `f"{goal} {summary}"[:1000]` using the same embedding model as the KB
2. Inserts into `memory_vec` (sqlite-vec virtual table) with `rowid = memory.id`

### Retrieval

`search_memory(query)` tries semantic first:
```python
embedding = await embedder.embed(query)
rows = await db.search_memory_vec(embedding, limit=5)
# Falls back to LIKE keyword matching if embedder unavailable
```

The `memory_vec` KNN search returns memories ordered by cosine distance — so "check email account" retrieves "log into ProtonMail inbox" even without a keyword match.

## Database Changes (`core/database.py`)

Two new methods:

| Method | Purpose |
|--------|---------|
| `create_memory_vec_table(dimensions)` | Create `memory_vec` virtual table with correct dims — called after embedding model is detected |
| `insert_memory_vec(memory_id, vector)` | Insert embedding into `memory_vec` — called from `store_task_memory` |
| `search_memory_vec(vector, limit)` | KNN search returning memory rows joined with embeddings |

The `memory_vec` table is created lazily (same pattern as `vec_chunks`) — if no embedder is available, it is never created and all memory search falls back to keyword matching.

## Configuration

```yaml
learner:
  enabled: true          # master switch for lesson extraction
  compress_enabled: true # allow compress=true in knowledge_write
```

Config section is optional — defaults to `enabled: true`.

## Integration Points

| Component | Change |
|-----------|--------|
| `core/learner.py` | New: `LessonExtractor` with `extract_and_store()` and `compress_content()` |
| `core/memory.py` | `MemoryManager.set_embedder()`, `search_memory()` with semantic fallback, `store_task_memory()` embeds on write |
| `core/database.py` | `create_memory_vec_table()`, `insert_memory_vec()`, `search_memory_vec()` |
| `core/agent.py` | Init `LessonExtractor` after knowledge setup; fire extraction in `_store_task_memory`; set embedder on `MemoryManager` after embedding model detected |
| `tools/knowledge/writer.py` | `compress: bool` param; `_learner` injected; calls `compress_content()` when set |
| `core/config.py` | `LearnerConfig` dataclass; `learner:` parsed from YAML |

## Token Flow

Without the learning engine, every task starts cold. With it:

```
Task N:   "scrape pricing from competitor.com"
  → lesson stored: "competitor.com blocks scrapers — use requests with UA header"

Task N+5: "get updated pricing from competitor.com"
  → _auto_retrieve finds lesson file
  → agent reads: "use UA header" before starting
  → no rediscovery needed, task completes faster
```

The compounding effect grows with usage: each task makes future similar tasks cheaper and more reliable.

## Files

| File | Description |
|------|-------------|
| `core/learner.py` | `LessonExtractor` — extraction + compression |
| `knowledge/learned/lessons/` | Lesson files written by extractor |
| `core/memory.py` | Semantic memory search via `MemoryManager` |
| `core/database.py` | `memory_vec` table + helpers |
| `core/agent.py` | Wiring: init, injection, fire-and-forget calls |
| `tools/knowledge/writer.py` | `compress` param support |
| `core/config.py` | `LearnerConfig` |
