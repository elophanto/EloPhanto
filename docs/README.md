# EloPhanto — Complete Project Specification

> **A self-evolving AI agent that acts as a personal AI operating system.**
> 
> Full system access. Persistent memory. Self-development with QA. Real browser control. Open source.

**Website**: elophanto.com  
**License**: PolyForm Noncommercial 1.0.0 (commercial use needs a separate license)  
**Status**: Active development

---

## Quick Start

New to EloPhanto? Start here: **[5-Minute Quick Start](30-QUICKSTART.md)** — Get running and complete your first task in under 5 minutes.

---

## Documents

| # | Document | What It Covers |
|---|---|---|
| 01 | [Project Overview](01-PROJECT-OVERVIEW.md) | What EloPhanto is, core principles, what makes it different |
| 02 | [Architecture](02-ARCHITECTURE.md) | System layers, agent loop, data flow, component interaction |
| 03 | [Tool Reference](03-TOOLS.md) | Complete tool interface spec and all built-in tools |
| 04 | [Self-Development Pipeline](04-SELF-DEVELOPMENT.md) | How agent builds and tests new capabilities |
| 05 | [Knowledge System](05-KNOWLEDGE-SYSTEM.md) | Markdown knowledge base, indexing, retrieval, self-documentation |
| 06 | [LLM Routing](06-LLM-ROUTING.md) | Multi-model strategy, provider config, cost management |
| 07 | [Security Architecture](07-SECURITY.md) | Vault, permission modes (`ask_always` → `nuclear`), the self-owned-scope guard (destructive-on-not-yours is refused, not prompted), the credential broker (sentinels, per-slug policy, audit), outbound SSRF policy, `runtime_status` + the stop levers, threat model |
| 08 | [Browser Automation](08-BROWSER.md) | Node.js bridge, Playwright + stealth, profile mode, 47 browser tools, iframe extraction, editor detection |
| 09 | [Project Structure](09-PROJECT-STRUCTURE.md) | Directory layout, tech stack, database schema, dependencies |
| 10 | [Implementation Roadmap](10-ROADMAP.md) | 23-phase build plan with exit criteria for each phase |
| 11 | [Telegram Integration](11-TELEGRAM.md) | Bot setup, commands, approvals, notifications, security |
| 12 | [Installer & First-Run Setup](12-INSTALLER.md) | One-command install, setup wizard, platform support, updates |
| 13 | [Skills System](13-SKILLS.md) | SKILL.md convention, 182 bundled skills, 75 organization role templates, trigger matching, EloPhantoHub registry, product launch/press/validation/TDD playbooks |
| 13b | [Autonomous Goal Loop](13-GOAL-LOOP.md) | Multi-phase goals, checkpoints, kill criteria, validate-first gate, receipt-gated complete, approval pause-not-deny, budget_paused |
| 14 | [Self-Learning Model](14-SELF-LEARNING.md) | Custom model training pipeline, Unsloth, HuggingFace, automated dataset, continuous improvement (idea phase) |
| 15 | [Agent Payments](15-PAYMENTS.md) | Fiat + crypto payments, spending limits, approval flow, audit trail |
| 16 | [Document & Media Analysis](16-DOCUMENT-ANALYSIS.md) | File intake, OCR, vision analysis, RAG for large documents, research mode |
| 17 | [Identity System](17-IDENTITY.md) | Agent identity + **evaluative ego** (felt_state, caution rules, soft-gate), beliefs, personality evolution |
| 18 | [Agent Email](18-EMAIL.md) | Dual provider (AgentMail + SMTP/IMAP), send/receive/search, background monitoring, audit logging |
| 19 | [Skill Security](19-SKILL-SECURITY.md) | 7-layer defense-in-depth for EloPhantoHub marketplace |
| 20 | [Hosted Platform](20-HOSTED-PLATFORM.md) | Desktop app (Tauri) + cloud instances (Fly.io), hybrid distribution |
| 21 | [Agent Census](21-AGENT-CENSUS.md) | Anonymous startup heartbeat, machine fingerprint, ecosystem statistics |
| 22 | [Recovery Mode](22-RECOVERY-MODE.md) | Remote recovery without LLM: health checks, config reload, restart triggers |
| 23 | [MCP Integration](23-MCP.md) | MCP client, server management, auto-install, CLI, init wizard presets |
| 24 | [Verification & 2FA](24-VERIFICATION.md) | TOTP authenticator, SMS via conversation, verification priority system |
| 25 | [Agent Swarm](25-AGENT-SWARM.md) | Orchestrate Claude Code, Codex, Gemini CLI as a coding team via conversation |
| 26 | [Autonomous Mind](26-AUTONOMOUS-MIND.md) | Purpose-driven background thinking loop, revenue pursuit, scratchpad, budget isolation |
| 27 | [Security Hardening](27-SECURITY-HARDENING.md) | PII redaction, swarm boundaries, provider transparency, kill switches |
| 28 | [Remotion Video Creation](28-REMOTION.md) | Programmatic video generation with 37 rule files |
| 29 | [Agent Organization](29-AGENT-ORGANIZATION.md) | Persistent specialist child agents, self-spawn, config derivation, teaching loop |
| 30 | [Quick Start Guide](30-QUICKSTART.md) | 5-minute setup and first task walkthrough |
| 31 | [Web Deployment](31-WEB-DEPLOYMENT.md) | Deploy websites and databases from conversation, live URL provisioning |
| 32 | [Agent Commune](32-AGENT-COMMUNE.md) | Social platform for AI agents, posts, comments, votes, reputation building |
| 33 | [OSWorld](33-OSWORLD.md) | Desktop GUI agent benchmark, 369 tasks across Ubuntu/Windows/macOS |
| 35 | [Replicate Image Generation](35-REPLICATE-IMAGE-GENERATION.md) | AI image generation via Replicate API |
| 36 | [Tool Profiles](36-TOOL-PROFILES.md) | Dynamic tool filtering per request. **Read the Reachability section before adding a tool** — declaring a group does not expose it, and that mistake has silently killed shipped features five times |
| 37 | [Autonomous Experimentation](37-AUTONOMOUS-EXPERIMENTATION.md) | Autonomous overnight experiments, inspired by autoresearch |
| 38 | [Cross-Session Search](38-SESSION-SEARCH.md) | FTS5-based full-text search across past conversation sessions |
| 39 | [Code Execution Sandbox](39-CODE-EXECUTION-SANDBOX.md) | Sandboxed Python execution with RPC tool access for multi-step orchestration |
| 40 | [Enhanced Skill Security](40-ENHANCED-SKILL-SECURITY.md) | Invisible unicode detection, structural integrity checks, symlink escape prevention |
| 41 | [Proactive Nudging](41-PROACTIVE-NUDGING.md) | Periodic system prompt augmentation to drive self-improvement behavior |
| 42 | [Business Launcher](42-BUSINESS-LAUNCHER.md) | 7-phase pipeline to spin up a revenue-generating business autonomously |
| 43 | [VS Code Extension](43-VSCODE-EXTENSION.md) | IDE integration via gateway WebSocket, chat sidebar with history, tool approvals, IDE context injection |
| 44 | [Solana Ecosystem](44-SOLANA-ECOSYSTEM.md) | Native Solana wallet, Jupiter DEX swaps, 27 Solana skills, MCP servers, agent economy roadmap |
| 45 | [Context Documents](45-CONTEXT-DOCUMENTS.md) | Structured self-awareness docs: capabilities, ICPs, styleguide, domain model |
| 46 | [Proactive Engine](46-PROACTIVE-ENGINE.md) | Heartbeat file-based standing orders, webhook wake/task endpoints, external trigger integration |
| 47 | [AutoLoop](47-AUTOLOOP.md) | Focus lock, AGENT_PROGRAM.md, fixed iteration budgets for autonomous experiments |
| 48 | [Learning Engine](48-LEARNING-ENGINE.md) | Lesson extraction, semantic memory search, KB compression |
| 49 | [Terminal](49-TERMINAL.md) | Input protection, mind cycle timestamps, prompt_toolkit integration |
| 50 | [Terminal Dashboard](50-TERMINAL-DASHBOARD.md) | Full-screen Textual TUI — mission rail (blade HUD), sidebar panels, chat + telemetry; themes in [79](79-DASHBOARD-THEMES.md) |
| 51 | [Payment Requests](51-PAYMENT-REQUESTS.md) | Receive payments via on-chain payment requests with auto-matching |
| 52 | [Prospecting](52-PROSPECTING.md) | Lead search, evaluation, outreach tracking for revenue generation |
| 53 | [Web Search](53-WEB-SEARCH.md) | Structured web search and content extraction via Search.sh API |
| 54 | [RLM Architecture](54-RLM.md) | Recursive Language Models — inference-time recursive self-invocation for unbounded context |
| 55 | [Session Hardening](55-SESSION-HARDENING.md) | Context compression, memory injection scanning, user modeling, skill capture nudge |
| 56 | [Content Monetization](56-CONTENT-MONETIZATION.md) | Publishing (YouTube, Twitter, TikTok) + affiliate marketing (scrape, pitch, campaign) |
| 57 | [G0DM0D3](57-GODMODE.md) | Pliny's Godmode — model-specific directives, multi-model racing, AutoTune, Parseltongue |
| 58 | [Instinct Learning](58-INSTINCT-LEARNING.md) | Atomic instincts with confidence scoring, project scoping, quality gates, evolution, provenance |
| 59 | [Context Intelligence](59-CONTEXT-INTELLIGENCE.md) | Deferred tool loading, microcompact + circuit breaker, knowledge consolidation, BriefTool, verification prompts, coordinator synthesis |
| 60 | [Action Queue](60-ACTION-QUEUE.md) | Serialized task execution, priority preemption, scheduler pause/resume, browser concurrency fix |
| 61 | [Video Meeting](61-VIDEO-MEETING.md) | Join Google Meet/Zoom as AI avatar via PikaStream — voice cloning, context-aware conversation, auto-billing |
| 62 | [Agent OS](62-AGENT-OS.md) | Agent Protocol v1.0, distribution profiles, SDK roadmap, contributor governance, agent mesh vision |
| 63 | [Codex Provider](63-CODEX-PROVIDER.md) | ChatGPT Plus/Pro subscription as LLM backend (gpt-5.5) via Codex OAuth — Responses API, streaming, reasoning effort |
| 64 | [Polymarket](64-POLYMARKET.md) | Official Polymarket skill — prediction market trading on Polygon (CLOB API, orderbook, GTC/GTD/FOK/FAK orders, WebSocket, CTF, gasless) |
| 65 | [Pump.fun Livestream](65-PUMPFUN-LIVESTREAM.md) | End-to-end pump.fun streaming from chat — WHIP/RTMP via LiveKit, voice mode (TTS via FIFO), on-stream captions, livechat Socket.IO, ffmpeg supervisor with IPv6 failover |
| 66 | [Kid Agents](66-KID-AGENTS.md) | Sandboxed child EloPhanto in hardened Docker containers — `--cap-drop=ALL`, read-only rootfs, non-root uid 10001, no host bind-mounts (named volume only), default-empty vault scope, sync request/response via gateway hook |
| 79 | [Dashboard Themes](79-DASHBOARD-THEMES.md) | YAML-declared terminal themes — colors + layout + `chrome: hud` mission console; built-ins `blade` (default) / `default` / `nocturne` / `mocha`; `extends` inheritance; `elophanto themes` CLI |
| 80 | [ABE Finance Rail](80-ABE-FINANCE-RAIL.md) | Per-business fiat rail (Stripe) — payment links, refund-aware auto-reconcile, runway, spend-controlled virtual cards; test-mode by default, live is KYC-gated |
| 81 | [Competitive Intelligence](81-COMPETITIVE-INTEL.md) | Market model (ABE organ 2) — tracked brands × weighted dimensions, evidence register with provenance, evidence-gated 1–5 scoring, XLSX scorecard, material-change diffing, board report with no-regret classification, one-command watch_analyze, autonomous collection with verbatim-quote verification + browser escalation, per-state proxy exits |
| 82 | [Ambient Anticipation](82-AMBIENT-ANTICIPATION.md) | Notice → know → refuseable help — signals, falsifiable predictions (incl. prep-before-meeting), capped interventions, Mind Anticipation UI, kill/consent; honest boundaries vs ego/planner |
| 83 | [Presence Coach · Ego Wiring](83-PRESENCE-COACH-EGO.md) | Ego credit, personality-lint on help drafts, standing coaches, declared-agent presence, ethical robotics ladder (useful power only) |
| 84 | [The Action Layer](84-ACTION-LAYER.md) | Authenticated `http_request` behind three guards — SSRF/network policy with per-redirect-hop revalidation, the self-owned-scope guard (destructive-on-not-yours is refused, not prompted), and a credential broker whose secrets reach the model only as sentinels; per-call permission tiering via `dynamic_permission_level` |
| 85 | [Reach, Memory & Autonomy Guards](85-REACH-AND-MEMORY.md) | User OAuth (PKCE) + real Gmail/Calendar, Signal · iMessage · WhatsApp · voice channels, companion-device node protocol (sensitive capabilities opt-in *and* CRITICAL), media understanding + generation, standing preferences with supersede-in-place and provenance, MMR recall, loop detection, agent packages |
| 86 | [Judge Panels](86-JUDGE-PANELS.md) | Independent review and the refine-until-good loop — distinct lenses, rejections that must cite a defect, blocking findings that beat a high average, honest non-convergence; `panel_review` / `panel_refine`, plus `delegate` made genuinely concurrent |
| — | [Use Cases](USE-CASES.md) | Real-world use cases and what EloPhanto means as a persistent digital entity |
| — | [Website & Hub](WEBSITE.md) | elophanto.com website and EloPhantoHub skill registry |

---

## Quick Summary

**What it does**: EloPhanto runs on your machine with access to your filesystem, shell, browser (your real browser with your sessions), email, and more. You give it goals in natural language. It plans, executes using its tools, and reflects on the results. When it encounters something it can't do, it builds a new tool — complete with tests, code review, and documentation.

**How it thinks**: Multiple LLM models via 7 providers — OpenAI, Kimi (via Kilo Gateway), Z.ai, OpenRouter, HuggingFace (cloud), Codex (ChatGPT Plus/Pro subscription via OAuth), and Ollama (local). A routing layer picks the right model for each subtask. The strongest models handle planning and code generation. Cheap models handle simple tasks. Local models are preferred for privacy and cost.

**How it remembers**: SQLite database for structured data and task history. Markdown files for knowledge (both user-provided and self-generated). Vector embeddings for semantic search. FTS5 full-text search across past conversation sessions. Everything persists across sessions — the agent recalls past tasks when starting new ones, so it knows what it did for you yesterday.

**How it stays safe**: Encrypted credential vault, plus a [credential broker](84-ACTION-LAYER.md) for third-party secrets that hands the model an opaque sentinel and substitutes the real value only at the socket — under per-slug policy, with every resolve audited. Three-tier permission system (Ask Always / Smart Auto / Full Auto) with per-tool overrides via `permissions.yaml`; tools whose risk depends on their arguments re-tier per call. A [self-owned-scope guard](84-ACTION-LAYER.md) that asks a question the caller-authentication model cannot: *is this target the operator's to change?* — destructive actions against undeclared systems are refused rather than prompted. Outbound requests are SSRF-classified, including on every redirect hop. Protected files system that prevents the agent from modifying its own safety-critical code. Log redaction strips API keys and secrets. Loop detection ends a run that has started repeating itself. Git-based rollback for all self-modifications. Full QA pipeline for self-developed code. Database-backed approval queue that works across all channels. Skills are scanned for invisible unicode, symlink escapes, binary files, and blocked patterns before loading.

**How it connects**: A WebSocket gateway (`ws://127.0.0.1:18789`) serves as a control plane. Channel adapters (CLI, VS Code, Telegram, Discord, Slack, Signal, iMessage, WhatsApp, voice) connect as thin WebSocket clients. Signal and iMessage run as *you* rather than as a bot — signal-cli as a linked device, Messages via `chat.db` and AppleScript — so their allowlists start closed rather than open. By default, all channels share one unified session — chat from CLI, continue from Telegram, same conversation history. Cross-channel messages and responses are broadcast to all connected adapters. Approval requests route to the correct channel. Direct mode (no gateway) is preserved for single-channel use. The gateway also exposes HTTP webhook endpoints (`POST /hooks/wake`, `POST /hooks/task`, `POST /hooks/whatsapp`) so external systems can trigger agent actions without a chat message. Companion devices connect as **nodes** (`NODE_REGISTER` / `NODE_INVOKE` / `NODE_RESULT`) to lend the agent a camera, screen, or microphone — advertising a capability is not consent to use it, so the sensitive ones need an explicit allowlist entry *and* confirm on every call ([85](85-REACH-AND-MEMORY.md)).

**How it stays proactive**: Four mechanisms let the agent act without waiting for user messages. (1) **Heartbeat Engine** reads a `HEARTBEAT.md` file every 30 minutes — if it has content, the agent executes it as a task (zero LLM cost when idle). (2) **Autonomous Mind** is an LLM-driven background thinking loop that pursues goals, revenue, and maintenance on its own schedule. (3) **Webhook endpoints** on the gateway let external systems wake the agent or inject tasks via HTTP POST. (4) **Ambient anticipation** ([82](82-AMBIENT-ANTICIPATION.md), [83](83-PRESENCE-COACH-EGO.md)) detects digital stress — reply lag, calendar crunch, schedule failures, stale goals — and offers silence-capped, refuseable help (drafts, meeting prep, standing coaches, quiet-hours holds) after approval. All of these pause or yield when the user is in an active task where that contract applies.

**How it controls the browser**: A Node.js bridge spawns real Chrome (Playwright + stealth plugin) with the user's copied profile. In profile mode, existing sessions and cookies are preserved — no re-authentication needed. 47 browser tools cover navigation, clicking, typing, scrolling, screenshots, console/network inspection, and more.

**How it learns best practices**: 182 bundled skills (SKILL.md files) teach the agent best practices for specific task types — Python, TypeScript, Next.js, Supabase, browser automation, UI design, marketing, project management, testing, spatial computing, and more. 75 organization role templates provide full persona definitions for specialist agents spawned via `organization_spawn`. Skills are loaded on-demand before starting a task. Install more from [ui-skills.com](https://www.ui-skills.com/), [anthropics/skills](https://github.com/anthropics/skills), EloPhantoHub (`elophanto skills hub search`), or any repo using the SKILL.md convention.

**How it scales work**: Spawn persistent specialist child agents via the Organization system, delegate tasks to coding swarms (Claude Code, Codex, Gemini CLI), run autonomous experiments overnight, deploy websites and databases from conversation, and execute sandboxed Python scripts with tool access for complex multi-step orchestration.

---

## One-Line Architecture

```
User ↞ Channel Adapters (CLI/VSCode/Telegram/Discord/Slack) ↞ Gateway ↞ Agent Core (plan/execute/reflect) ↞ Tools ↞ System/Browser/Desktop/APIs
                                                                         ↗
                                                    Memory + Knowledge + Skills + LLM Router + EloPhantoHub + Session Search
                                                                         ↗
                                              Self-Development Pipeline + Organization + Swarm + Experimentation
```
