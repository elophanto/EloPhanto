---
title: EloPhanto Architecture
created: 2026-02-17
updated: 2026-02-18
tags: architecture, system, design, agent
scope: system
---

# Architecture

EloPhanto is a layered system with five tiers.

## Interface Layer

- **CLI**: `elophanto chat` (interactive REPL with Rich UI, live progress, token/context stats), `elophanto init`, `elophanto vault`, `elophanto schedule`, `elophanto skills`, `elophanto rollback`, `elophanto telegram`
- **Telegram Bot**: Full conversational interface via aiogram. Commands: /status, /tasks, /approve, /deny, /plugins, /mode, /budget, /help. Notifications for task completion, errors, approvals, scheduled results. Start with `elophanto telegram`.

## Permission & Safety Layer

Three permission modes (ask_always, smart_auto, full_auto) with per-tool overrides via `permissions.yaml`. Protected files system prevents modification of safety-critical code (core/executor.py, core/vault.py, etc.). Database-backed approval queue survives restarts and works across CLI and Telegram.

## Self-Development Layer

Full pipeline: research → design → implement → test → review → deploy → git commit. Creates plugins in plugins/ directory. Core self-modification via `self_modify_source` with impact analysis, full test suite, and auto-rollback on failure. Git integration: every change is committed with [self-create-plugin] or [self-modify] prefix. Rollback via `self_rollback` tool or `elophanto rollback` CLI.

## Agent Brain

The agent loop follows a plan-execute-reflect cycle:
1. User provides a goal
2. Task memory from previous sessions is automatically recalled
3. Relevant knowledge and skills are loaded into working memory
4. The planner sends the goal + context + available tools to the LLM
5. If the LLM returns tool calls, the executor runs each tool (with permission check)
6. Tool results are fed back to the LLM via conversation history
7. The loop repeats until the LLM responds with text (task complete) or stagnation is detected

## Tool System

85+ tools across 10 categories: system (6), browser (47), knowledge & skills (5), self-development (6), scheduling (2), data (3), documents (3), goals (3), identity (3), payments (7). All implement the BaseTool ABC with name, description, input_schema, permission_level, and async execute().

## Foundation

- **Memory**: Working memory (in-session) + long-term task memory (SQLite, recalled across sessions)
- **Knowledge**: Markdown files indexed with embeddings for semantic search (sqlite-vec)
- **Skills**: 27 SKILL.md best-practice guides, trigger-matched and loaded before tasks
- **LLM Router**: Multi-provider routing (Ollama, Z.ai, OpenRouter) with task-type-based model selection and cost tracking
- **Vault**: Encrypted credential storage (Fernet + PBKDF2)
- **Scheduler**: APScheduler for recurring (cron) and one-time (delay) task execution
- **Payments**: Crypto wallet via Coinbase AgentKit (Base chain, gasless), spending limits, audit trail
