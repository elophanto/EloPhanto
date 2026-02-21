# EloPhanto — Complete Project Specification

> **A self-evolving AI agent that acts as a personal AI operating system.**
> 
> Full system access. Persistent memory. Self-development with QA. Real browser control. Open source.

**Website**: elophanto.com  
**License**: Apache 2.0  
**Status**: Active development

---

## Documents

| # | Document | What It Covers |
|---|---|---|
| 01 | [Project Overview](01-PROJECT-OVERVIEW.md) | What EloPhanto is, core principles, what makes it different |
| 02 | [Architecture](02-ARCHITECTURE.md) | System layers, agent loop, data flow, component interaction |
| 03 | [Tool Reference](03-TOOLS.md) | Complete tool interface spec and all built-in tools |
| 04 | [Self-Development Pipeline](04-SELF-DEVELOPMENT.md) | How the agent builds and tests new capabilities |
| 05 | [Knowledge System](05-KNOWLEDGE-SYSTEM.md) | Markdown knowledge base, indexing, retrieval, self-documentation |
| 06 | [LLM Routing](06-LLM-ROUTING.md) | Multi-model strategy, provider config, cost management |
| 07 | [Security Architecture](07-SECURITY.md) | Vault, permissions, credential isolation, threat model |
| 08 | [Browser Automation](08-BROWSER.md) | Node.js bridge, Playwright + stealth, profile mode, 47 browser tools |
| 09 | [Project Structure](09-PROJECT-STRUCTURE.md) | Directory layout, tech stack, database schema, dependencies |
| 10 | [Implementation Roadmap](10-ROADMAP.md) | 9-phase build plan with exit criteria for each phase |
| 11 | [Telegram Integration](11-TELEGRAM.md) | Bot setup, commands, approvals, notifications, security |
| 12 | [Installer & First-Run Setup](12-INSTALLER.md) | One-command install, setup wizard, platform support, updates |
| 13 | [Skills System](13-SKILLS.md) | SKILL.md convention, 28 bundled skills, trigger matching, EloPhantoHub registry |
| 13 | [Autonomous Goal Loop](13-GOAL-LOOP.md) | Multi-phase goals, checkpoints, progress tracking, self-evaluation |
| 14 | [Self-Learning Model](14-SELF-LEARNING.md) | Custom model training pipeline, Unsloth, HuggingFace, automated dataset, continuous improvement (idea phase) |
| 15 | [Agent Payments](15-PAYMENTS.md) | Fiat + crypto payments, spending limits, approval flow, audit trail |
| 16 | [Document & Media Analysis](16-DOCUMENT-ANALYSIS.md) | File intake, OCR, vision analysis, RAG for large documents, research mode |
| 17 | [Identity System](17-IDENTITY.md) | Agent identity, beliefs, personality evolution, social profiles |
| 18 | [Agent Email](18-EMAIL.md) | Dual provider (AgentMail + SMTP/IMAP), send/receive/search, audit logging |
| 19 | [Skill Security](19-SKILL-SECURITY.md) | 7-layer defense-in-depth for EloPhantoHub marketplace |
| 20 | [Hosted Platform](20-HOSTED-PLATFORM.md) | Desktop app (Tauri) + cloud instances (Fly.io), hybrid distribution |

---

## Quick Summary

**What it does**: EloPhanto runs on your machine with access to your filesystem, shell, browser (your real browser with your sessions), email, and more. You give it goals in natural language. It plans, executes using its tools, and reflects on the results. When it encounters something it can't do, it builds a new tool — complete with tests, code review, and documentation.

**How it thinks**: Multiple LLM models via OpenRouter (cloud) and Ollama (local). A routing layer picks the right model for each subtask. The strongest models handle planning and code generation. Cheap models handle simple tasks. Local models are preferred for privacy and cost.

**How it remembers**: SQLite database for structured data and task history. Markdown files for knowledge (both user-provided and self-generated). Vector embeddings for semantic search. Everything persists across sessions — the agent recalls past tasks when starting new ones, so it knows what it did for you yesterday.

**How it stays safe**: Encrypted credential vault. Three-tier permission system (Ask Always / Smart Auto / Full Auto) with per-tool overrides via `permissions.yaml`. Protected files system that prevents the agent from modifying its own safety-critical code. Log redaction strips API keys and secrets. Git-based rollback for all self-modifications. Full QA pipeline for self-developed code. Database-backed approval queue that works across all channels.

**How it connects**: A WebSocket gateway (`ws://127.0.0.1:18789`) serves as the control plane. Channel adapters (CLI, Telegram, Discord, Slack) connect as thin WebSocket clients. Each user/channel gets an isolated session with independent conversation history, persisted to SQLite. Approval requests route to the correct channel. Direct mode (no gateway) is preserved for single-channel use.

**How it controls the browser**: A Node.js bridge spawns real Chrome (Playwright + stealth plugin) with the user's copied profile. In profile mode, existing sessions and cookies are preserved — no re-authentication needed. 47 browser tools cover navigation, clicking, typing, scrolling, screenshots, console/network inspection, and more.

**How it learns best practices**: 28 bundled skills (SKILL.md files) teach the agent best practices for specific task types — Python, TypeScript, Next.js, Supabase, browser automation, UI design, and more. Skills are loaded on-demand before starting a task. Install more from [ui-skills.com](https://www.ui-skills.com/), [anthropics/skills](https://github.com/anthropics/skills), EloPhantoHub (`elophanto skills hub search`), or any repo using the SKILL.md convention.

---

## One-Line Architecture

```
User ←→ Channel Adapters (CLI/Telegram/Discord/Slack) ←→ Gateway ←→ Agent Core (plan/execute/reflect) ←→ Tools ←→ System/Browser/APIs
                                                                         ↕
                                                           Memory + Knowledge + Skills + LLM Router + EloPhantoHub
                                                                         ↕
                                                               Self-Development Pipeline
```
