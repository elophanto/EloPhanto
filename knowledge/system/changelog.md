---
title: Changelog
created: 2026-02-17
updated: 2026-02-18
tags: changelog, history, releases
scope: system
---

# Changelog

## 2026-02-18 — Skills, Security, Telegram, Self-Modification

- Added skills system: 27 bundled skills (Python, TypeScript, Next.js, Supabase, browser, UI/design, etc.)
- Added SkillManager with trigger matching, skill_read and skill_list tools
- Added `elophanto skills` CLI (install from git repos, list, read, remove)
- Added Telegram bot interface (aiogram): commands, notifications, approval flow
- Added `elophanto telegram` CLI command
- Added file_delete and file_move tools
- Added self_modify_source tool (impact analysis, auto-rollback, git commit)
- Added self_rollback tool and `elophanto rollback` CLI command
- Added git auto-commit on plugin creation (updates capabilities.md and changelog.md)
- Added one-time scheduling ("in 5 minutes", "at 3pm") alongside recurring
- Added protected files system (core/protected.py)
- Added permissions.yaml for per-tool permission overrides
- Added log redaction (strips API keys, tokens, secrets from all logs)
- Added approval queue persistence (database-backed, works across CLI and Telegram)
- Added task memory recall across sessions (agent remembers past tasks)
- Added live progress display in CLI (step-by-step tool visibility)
- Added ASCII banner, token stats, context tracking to CLI
- Rewrote system prompt with XML structure and modular builder
- Rewrote self-dev prompts with XML tags and system+user message pairs
- Fixed browser profile copy always re-triggering (removed broken cookie count check)
- Fixed file:// URLs (added guidance to use local HTTP server instead)
- Updated all 13 docs and README to reflect current state

## Phase 1 — Knowledge & Memory (2026-02-17)

- Added SQLite database with knowledge_chunks, memory, tasks, llm_usage tables
- Added sqlite-vec integration for vector search
- Added knowledge indexer: markdown chunking + embedding via Ollama
- Added knowledge_search tool (hybrid semantic + keyword search)
- Added knowledge_write tool (create/update markdown with frontmatter)
- Added knowledge_index tool (manual re-indexing trigger)
- Added working memory (in-session context from knowledge base)
- Added long-term memory (task summaries persisted across sessions)
- Created initial knowledge files: architecture, capabilities, conventions, changelog, limitations

## Phase 0 — Foundation (2026-02-17)

- Project scaffolding with uv/hatchling
- Configuration system (YAML with env var overrides)
- Tool system with BaseTool ABC and ToolRegistry
- 5 built-in tools: shell_execute, file_read, file_write, file_list, llm_call
- Multi-provider LLM router (Ollama, Z.ai, OpenRouter)
- Z.ai adapter with GLM message constraint compliance
- Agent loop: plan-execute-reflect cycle
- CLI: init wizard and interactive chat
- 52 tests passing
