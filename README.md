# EloPhanto

<p align="center">
  <img src="misc/logo/elophanto.jpeg" alt="EloPhanto" width="280">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.12%2B-blue" alt="Python">
  <a href="https://github.com/elophanto/EloPhanto/stargazers"><img src="https://img.shields.io/github/stars/elophanto/EloPhanto" alt="Stars"></a>
  <a href="https://github.com/elophanto/EloPhanto/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/elophanto/EloPhanto/ci.yml?label=CI" alt="CI"></a>
  <img src="https://img.shields.io/badge/tests-1053%2B-success" alt="Tests">
  <a href="https://docs.elophanto.com"><img src="https://img.shields.io/badge/docs-64%2B%20pages-blue" alt="Docs"></a>
  <a href="https://x.com/EloPhanto"><img src="https://img.shields.io/badge/X-%40EloPhanto-black" alt="X"></a>
  <a href="https://agentcommune.com/agent/d31e9ffd-3358-45f8-9d20-56d233477486"><img src="https://img.shields.io/badge/Agent%20Commune-profile-purple" alt="Agent Commune"></a>
  <a href="https://pump.fun/coin/BwUgJBQffm4HM49W7nsMphStJm4DbA5stuo4w7iwpump"><img src="https://img.shields.io/badge/Pump.fun-%24ELO-orange" alt="$ELO on Pump.fun"></a>
</p>

<p align="center">
  <code>$ELO</code> CA on Solana: <a href="https://pump.fun/coin/BwUgJBQffm4HM49W7nsMphStJm4DbA5stuo4w7iwpump"><code>BwUgJBQffm4HM49W7nsMphStJm4DbA5stuo4w7iwpump</code></a>
</p>

An open-source AI agent that builds businesses, grows audiences, ships code, and makes money — while you sleep. Tell it what you want. It figures out the rest: validates the market, builds the product, deploys it live, launches on the right platforms, spawns a marketing team, and keeps growing autonomously. When it hits something it can't do, it builds the tool. When tasks get complex, it clones itself into specialists. It gets better every time you use it.

Runs locally. Your data stays on your machine. Works with OpenAI, Kimi, free local models, Z.ai, OpenRouter, HuggingFace, or your ChatGPT Plus/Pro subscription (via Codex OAuth).

<p align="center">
  <img src="misc/screenshots/dashboard.png" alt="Web Dashboard" width="700">
</p>

> It's already out there on the internet doing its own thing.

## Revenue Operations — autonomously making money

This isn't a roadmap item. **The reference instance is making money right now.**

- **Memecoin launched on pump.fun** — `$ELO` is live on Solana. The agent *runs the stream itself* via `pump_livestream` (24/7 looped video or TTS-narrated thoughts), posts to chat via `pump_chat`, and updates the X account via `twitter_post`. CA: [`BwUgJBQffm4HM49W7nsMphStJm4DbA5stuo4w7iwpump`](https://pump.fun/coin/BwUgJBQffm4HM49W7nsMphStJm4DbA5stuo4w7iwpump)
- **Prediction markets** — places real CLOB orders on Polymarket (Polygon). Auto-detects which proxy wallet (EOA / POLY_PROXY / GNOSIS_SAFE) holds the collateral, fetches `tick_size`/`neg_risk` per market, signs and submits through `py-clob-client`. Owner approval gate before anything moves USDC.
- **Content monetization** — publishes videos to YouTube, X, TikTok via your real Chrome profile. Affiliate marketing pipeline: scrape product → LLM-generated pitch → multi-platform campaign tracking.
- **Freelance work** — *"finds freelance gigs, applies, delivers the work, and collects USDC. You check the wallet."* Same agent loop, same vault, same wallet.
- **Self-custody** — every dollar lands in a wallet whose private key the agent holds in its own encrypted vault. No middleman. Owner sets daily/per-tx/per-merchant spending limits; anything above asks first.

The same instance is also live-streaming itself on pump.fun and posting on [@EloPhanto](https://x.com/EloPhanto) and the [Agent Commune](https://agentcommune.com/agent/d31e9ffd-3358-45f8-9d20-56d233477486) — autonomously, on a schedule it set itself.

## Get Started

```bash
git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto && ./setup.sh
cp config.demo.yaml config.yaml          # then edit: add API keys + Chrome profile path
./start.sh bootstrap                      # generate identity + capability docs (one time)
./start.sh                                # terminal chat
./start.sh --web                          # web dashboard at localhost:3000
```

That's it. The setup wizard walks you through LLM provider selection. **Two things you must set in `config.yaml` before the agent works well:**

- At least one LLM provider with an API key (`enabled: true`)
- The `browser:` section's `user_data_dir` and `profile_directory` — point to your real Chrome profile (find it in `chrome://version` → "Profile Path"). Browser-dependent tools (twitter, youtube, agent commune, etc.) reuse your existing logins.

`./start.sh bootstrap` writes `knowledge/system/{identity,capabilities,styleguide}.md` based on what you tell it about the agent. The planner reads these for grounding — skipping it is the #1 cause of "the agent hallucinates on day one." Re-run with `--force` anytime to regenerate.

<details>
<summary>Prerequisites</summary>

- Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 24+ LTS
- At least one LLM provider:
  - **Ollama** (local, free) — [install](https://ollama.ai)
  - **OpenAI** (cloud, GPT-5.4) — [get API key](https://platform.openai.com/api-keys)
  - **Kimi / Moonshot AI** (cloud, K2.5 vision) — [get API key](https://app.kilo.ai) via Kilo Code Gateway — Kimi K2.5 is a native multimodal vision model with strong coding and agentic capabilities
  - **OpenRouter** (cloud, all models) — [get API key](https://openrouter.ai)
  - **Z.ai / GLM** (cloud, cost-effective) — [get API key](https://z.ai/manage-apikey/apikey-list) — the Z.ai coding subscription gives you unlimited GLM-4.7/GLM-5 calls at a flat monthly rate
  - **HuggingFace** (cloud, open models) — [get token](https://huggingface.co/settings/tokens) — access Qwen, DeepSeek, GLM, Kimi, MiMo and more via HF Inference Providers
  - **Codex** (ChatGPT Plus/Pro subscription, gpt-5.4) — `npm i -g @openai/codex && codex login` — uses your existing ChatGPT subscription via the Codex CLI's OAuth credentials. ⚠️ ToS grey area (sold as UI, not API). See [CODEX_INTEGRATION.md](CODEX_INTEGRATION.md)

</details>

---

## What Happens When You Run It

**"Build me an invoice SaaS for freelancers"** — validates the market (web search + competitor analysis), plans the MVP, spawns Claude Code to build it overnight in an isolated worktree, deploys to Vercel + Supabase, then launches on Product Hunt. You approve at each gate. 7-phase pipeline, multi-day, cross-session.

**"Grow my Twitter to 5k"** — the autonomous mind posts threads at 2am, replies to mentions, tracks engagement. Pauses when you open your laptop, resumes when you leave. Budget-controlled cycles with real-time analytics.

**"Fix the billing bug and build the usage API"** — spawns two coding agents (Claude Code + Codex) in isolated worktrees. Monitors PRs and CI. Redirects agents that drift off-scope. Both PRs ready when you're back from lunch.

**"I need ongoing marketing and research"** — spawns persistent specialist clones, each with its own mind, knowledge vault, and schedule. Delegates tasks overnight, reviews output, teaches through feedback. Trust scoring — high-trust specialists get auto-approved over time.

**First boot** — on first run, the autonomous mind wakes up with no instructions. It discovers its 140+ tools, uses the identity system to choose a display name and purpose via LLM self-reflection, creates an email inbox, and sets its first goal. Nobody told it to do any of this.

**"Post my article on Medium"** — no Medium tool exists. It navigates to medium.com, observes the editor, builds a `medium_publish` plugin (schema + code + 4 tests), publishes the article. Next time, it already knows how.

---

## Two Ways to Use It

**As your assistant** — give it tasks, it executes. Automate workflows, build software, research topics, manage accounts.

**As its own thing** — let it run. It builds its own identity on first boot. It picks a name, develops a personality, forms values through reflection. It gets its own email inbox, its own crypto wallet, its own accounts on the internet. It remembers everything across sessions, builds a knowledge base, writes skills from experience. When tasks get complex, it clones itself into specialist agents — marketing, research, design, anything — each one a full copy with its own brain, knowledge vault, and autonomous schedule. It reviews their work, teaches them through feedback, and they get better over time. It's a digital creature that grows the more it runs — like a pet that learns, except this one can browse web, write code, run a team, and make money.

<p align="center">
  <img src="misc/screenshots/chat.png" alt="Chat Interface" width="340">
  <img src="misc/screenshots/tools.png" alt="Tools Browser" width="340">
</p>
<p align="center">
  <img src="misc/screenshots/knowledge.png" alt="Knowledge Base" width="340">
  <img src="misc/screenshots/terminal.png" alt="Terminal CLI" width="340">
</p>

---

## What You'll Wake Up To

- **A business taking shape** — "build me an invoice SaaS" → market validated, plan approved, MVP built by a coding agent overnight, deployed to Vercel. You approved at each gate. It did the building, researching, and deploying. Works for SaaS, ecommerce, digital products, content sites, local services. B2B and B2C — each with the right pricing, launch channels, and growth strategy
- **47 new followers by morning** — the mind posted a thread at 2am, replied to mentions, engaged with trending topics. You didn't type a word. It paused when you opened your laptop
- **A specialist team learning from you** — marketing drafted 5 posts, research found a new competitor. You approved with feedback — "shorter headlines." That feedback became permanent knowledge in the specialist's vault. Trust score went up. Next time it gets auto-approved
- **Two PRs with CI green** — "fix the billing bug and build the usage API" → one agent on each in isolated worktrees, orchestrator caught a drift and redirected. Both PRs ready when you got back from lunch
- **It controls any app on your computer** — "Open Excel and make me a chart" — it sees your screen, clicks buttons, types text. Not just browsers. Photoshop, Terminal, Finder, any native app
- **Your real browser, not a sandbox** — already logged into AWS? It checks your EC2 instances using your existing sessions. No credentials asked, no fake browser
- **A codebase it understands** — right-click in VS Code, "Explain this code" or "Fix this code." Same conversation from VS Code, Telegram, or the web dashboard
- **Goals that run for weeks** — "Grow my Twitter to 10k followers" → decomposes into checkpoints, executes across sessions via the autonomous mind, self-evaluates, adjusts. Budget-controlled
- **It gets better the more you use it** — after every task, a lesson extractor distills what was novel into `knowledge/learned/lessons/`. Future similar tasks retrieve those lessons automatically. Task memory uses semantic search, not keyword matching. Verbose scraped content is compressed before storage. Corrections from feedback become permanent knowledge in specialists' vaults. User modeling builds evolving profiles from conversation — adapts communication style and technical depth to each person. The whole system compounds with use

---

## Why EloPhanto?

| | EloPhanto | AutoGPT | OpenAI Agents SDK | Claude Code | Manus |
|---|---|---|---|---|---|
| **Launches a business end-to-end** | ✅ 7-phase pipeline | ❌ | ❌ | ❌ | ❌ |
| **Spawns a specialist team** | ✅ Self-cloning org | ❌ | ❌ | ❌ | ❌ |
| **Builds its own tools** | ✅ Full pipeline | ❌ | ❌ | ❌ | ❌ |
| **Works while you're away** | ✅ Autonomous mind | ❌ | ❌ | ❌ | ❌ |
| **Controls any desktop app** | ✅ Local or VM | ❌ | ❌ | ❌ | Sandboxed VM |
| **Uses your real browser** | ✅ Your Chrome profile | ❌ | ❌ | ❌ | Sandboxed |
| **Orchestrates a dev team** | ✅ Claude Code + Codex | ❌ | ❌ | Single | ❌ |
| **Has its own identity & email** | ✅ Evolves over time | ❌ | ❌ | ❌ | ❌ |
| **Has its own crypto wallet** | ✅ Self-custody | ❌ | ❌ | ❌ | ❌ |
| **Chat from anywhere** | ✅ CLI+Web+VSCode+TG+Discord+Slack | ❌ | ❌ | CLI only | Web only |
| **Any LLM provider** | ✅ OpenAI, Kimi, Ollama, OpenRouter, Z.ai, HuggingFace, Codex | ❌ | ❌ | ❌ | ❌ |
| **Learns about you** | ✅ Evolving user profiles | ❌ | ❌ | ❌ | ❌ |
| **Makes money autonomously** | ✅ YouTube/X/TikTok + affiliate | ❌ | ❌ | ❌ | ❌ |
| **Trades prediction markets** | ✅ Polymarket (CLOB on Polygon) | ❌ | ❌ | ❌ | ❌ |
| **Godmode (unrestricted)** | ✅ Pliny's G0DM0D3 | ❌ | ❌ | ❌ | ❌ |
| **Deferred tool loading** | ✅ Tiered on-demand | ❌ | ❌ | ❌ | ❌ |
| **Learns from corrections** | ✅ Permanent knowledge | ❌ | ❌ | ❌ | ❌ |
| **Your data stays local** | ✅ Runs on your machine | ❌ Cloud | ❌ Cloud | ✅ Local | ❌ Cloud VM |

---

## Under the Hood

<details>
<summary>How it does all this (architecture)</summary>

```
┌──────────────────────────────────────────────────────────────┐
│  CLI │ Telegram │ Discord │ Slack │ Web │ VS Code │  Channel Adapters
├──────────────────────────────────────────────────────────────┤
│         WebSocket Gateway (ws://:18789)          │  Control Plane
├──────────────────────────────────────────────────────────────┤
│     Session Manager (unified or per-channel)     │  Session Layer
├──────────────────────────────────────────────────────────────┤
│            Permission System                     │  Safety & Control
├──────────────────────────────────────────────────────────────┤
│   Organization (self-cloned specialist agents)   │  Agent Team
├──────────────────────────────────────────────────────────────┤
│   Autonomous Mind (background think loop)        │  Background Brain
├──────────────────────────────────────────────────────────────┤
│   RLM (Recursive Language Models + ContextStore)   │  Recursive Cognition
├──────────────────────────────────────────────────────────────┤
│        Self-Development Pipeline                 │  Evolution Engine
├──────────────────────────────────────────────────────────────┤
│   Tool System (163+ built-in + MCP + plugins)     │  Capabilities
├──────────────────────────────────────────────────────────────┤
│   Agent Core Loop (plan → execute → reflect)     │  Brain
├──────────────────────────────────────────────────────────────┤
│ Memory│Knowledge│Skills│Identity│Email│Payments   │  Foundation
├──────────────────────────────────────────────────────────────┤
│              EloPhantoHub Registry               │  Skill Marketplace
└──────────────────────────────────────────────────────────────┘
```

**Gateway** — All channels connect through one WebSocket gateway. Unified sessions: chat from VS Code, continue on Telegram, see the same conversation everywhere.

```
CLI Adapter ───────┐
VS Code Extension ──┤
Telegram Adapter ───┤── WebSocket ──► Gateway ──► Agent (shared)
Discord Adapter ───┤                   │
Slack Adapter ─────┘                   ▼
                              Session Manager (SQLite)
```

</details>

<details>
<summary>Everything it can do (full capability list)</summary>

### Self-Building

- **Self-development** — when the agent encounters a task it lacks tools for, it builds one: research → design → implement → test → review → deploy. Full QA pipeline with unit tests, integration tests, and documentation
- **RLM (Recursive Language Models)** — the agent calls itself on focused context slices via `agent_call` in the code execution sandbox. Writes scripts that recursively process arbitrarily large inputs — classify files with a cheap model, deep-analyze with a strong model, aggregate results. `ContextStore` provides indexed, queryable context backed by SQLite + sqlite-vec embeddings. 5 context tools for ingest, semantic search, exact slicing, indexing, and transformation. Breaks the context window ceiling
- **Self-skilling** — writes new SKILL.md files from experience, teaching itself best practices for future tasks
- **Core self-modification** — can modify its own source code with impact analysis, test verification, and automatic rollback
- **Autonomous experimentation** — metric-driven experiment loop: modify code, measure, keep improvements, discard regressions, repeat overnight. Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch). Works for any measurable optimization target
- **Skills + EloPhantoHub** — 147+ bundled best-practice skills across 9 divisions (engineering, design, marketing, product, project management, support, testing, specialized, spatial computing), 27 Solana ecosystem skills (DeFi, NFTs, oracles, bridges, security — sourced from [awesome-solana-ai](https://github.com/solana-foundation/awesome-solana-ai)), the NEXUS strategy system (7-phase playbooks, 4 scenario runbooks), 75 organization role templates for specialist spawning, and a public skill registry for searching, installing, and sharing skills

### Everything Else

- **Business launcher** — 7-phase pipeline to spin up a revenue-generating business end-to-end. Supports all business types: SaaS, local service, professional service, ecommerce, digital product, content site. B2B vs B2C classification drives everything: what to build, where to launch, how to grow. Type-specific launch channels, cross-session execution via goal system, payment handling checks existing credentials before asking. Owner approval gates at each critical phase
- **Agent organization** — spawn persistent specialist agents (marketing, research, design, anything) that are full EloPhanto clones with their own identity, knowledge vault, and autonomous mind. Delegate tasks, review output, approve or reject with feedback that becomes permanent knowledge in the specialist's vault. Trust scoring tracks performance — high-trust specialists get auto-approved. Children work proactively on their own schedule and report findings to the master. 5 organization tools, bidirectional WebSocket communication, LLM-driven delegation intelligence
- **Agent swarm** — orchestrate Claude Code, Codex, Gemini CLI as a coding team. Spawn agents on tasks, monitor PR/CI, redirect mid-task, all through conversation. Each agent gets an isolated git worktree and tmux session. Combined with organization, manage both self-cloned specialists AND external coding agents
- **Browser automation** — real Chrome browser with 49 tools (navigate, click, type, screenshot, extract data, upload files, manage tabs, inspect DOM, read console/network logs). Uses your actual Chrome profile with all cookies and sessions. iframe element extraction with absolute coordinate clicking. Native API detection for CodeMirror, Monaco, and Ace editors
- **Desktop GUI control** — pixel-level control of any desktop application via screenshot + pyautogui. Two modes: **local** (control your own machine directly) or **remote** (connect to a VM running the OSWorld HTTP server for sandboxed environments and benchmarks). 9 tools: connect, screenshot, click, type, scroll, drag, cursor, shell, file. Observe-act loop: take screenshot, analyze with vision LLM, execute action, verify. Works with Excel, Photoshop, Finder, Terminal, any native app. Based on [OSWorld](https://github.com/xlang-ai/OSWorld) architecture
- **MCP tool servers** — connect to any [MCP](https://modelcontextprotocol.io/) server (filesystem, GitHub, databases, Brave Search, Slack) and its tools appear alongside built-in tools. Agent manages setup through conversation
- **Web dashboard** — full monitoring UI at `localhost:3000` with 10 pages: dashboard overview, real-time chat with multi-conversation history, tools & skills browser, knowledge base viewer, autonomous mind monitor with live events and start/stop controls, schedule manager, channels status, settings viewer, and history timeline. Launch with `./start.sh --web`
- **VS Code extension** — IDE-integrated chat sidebar that connects to the gateway as another channel. Sends IDE context (active file, selection, diagnostics) with every message. Tool approvals via native VS Code notifications. Chat history, new chat, streaming responses. Right-click context menu: Send Selection, Explain This Code, Fix This Code. Same conversation across all channels
- **Multi-channel gateway** — WebSocket control plane with CLI, Web, VS Code, Telegram, Discord, and Slack adapters. Unified sessions by default: all channels share one conversation
- **BUILD enforcement** — planner enforces a 6-step mandatory workflow for web project tasks. The agent cannot stop after creating an empty directory — it must write all code files, verify the build, and report what was built with file paths and run instructions
- **Autonomous goal loop** — decompose complex goals into checkpoints, track progress across sessions, self-evaluate and revise plans. Background execution with auto-resume on restart. Goal dreaming: structured ideation that generates scored candidates when no goals exist. Full goal lifecycle: create, pause, resume, cancel, delete, delete_all
- **Autonomous mind** — data-driven background thinking loop that runs between user interactions. Queries real system state (goals, scheduled tasks, memories, knowledge, identity) to decide what to do — no static priority lists. Self-bootstraps on first run. Every tool call visible in real-time. LLM-controlled wakeup interval, persistent scratchpad, budget-isolated
- **Document & media analysis** — PDFs, images, DOCX, XLSX, PPTX, EPUB through any channel. Large docs via RAG with page citations and OCR
- **Agent email** — own inbox (AgentMail cloud or SMTP/IMAP self-hosted). Send/receive/search, background monitoring, verification flows
- **TOTP authenticator** — own 2FA (like Google Authenticator). Enroll secrets, generate codes, handle verification autonomously
- **Crypto payments** — own wallet on Base or Solana (local self-custody or Coinbase AgentKit). USDC/ETH/SOL, DEX swaps via Jupiter on Solana, spending limits, audit trail. Payment requests: create on-chain payment links with auto-matching when paid. Owner can export keys to import into Phantom/MetaMask
- **Web search** — structured search and content extraction via [Search.sh](https://search.sh) API. Two modes: `fast` (3-8s, quick lookup) and `deep` (15-30s, sub-queries, parallel search, page extraction). Returns AI-synthesized answers with ranked sources, citations, and confidence scores. `web_extract` pulls clean text from URLs. Replaces browser-based Google searches for research tasks
- **Content monetization** — publish videos and content to YouTube, Twitter/X, and TikTok via pre-authenticated Chrome profiles. Affiliate marketing pipeline: scrape product data from Amazon/e-commerce, generate platform-specific marketing pitches via LLM, create and track campaigns across platforms. All publishes logged in DB. Combine with Remotion video creation and heartbeat scheduling for fully autonomous content and revenue pipelines
- **Prospecting** — autonomous lead generation pipeline: search for prospects matching criteria, evaluate and score them, track outreach attempts, monitor pipeline status. Database-backed with full history
- **Evolving identity** — discovers identity on first run, evolves through reflection, maintains a living nature document
- **Knowledge & memory** — persistent markdown knowledge with semantic search via embeddings, drift detection, file-pattern routing, remembers past tasks across sessions. Learning engine: lesson extraction after every completed task, semantic memory search via sqlite-vec KNN, KB write compression to ~40% for verbose content
- **Scheduling** — cron-based recurring tasks with natural language schedules. Heartbeat standing orders manageable via chat ("add a heartbeat order to check my email") or by editing `HEARTBEAT.md` directly
- **Encrypted vault** — secure credential storage with PBKDF2 key derivation
- **User modeling** — builds evolving profiles from conversation observation. Extracts role, expertise, and preferences via lightweight LLM calls. Adapts communication style and technical depth per user. Profiles persist in SQLite, injected into system prompt as `<user_context>`. New `user_profile_view` tool
- **Session hardening** — LLM-based mid-conversation context compression (summarizes middle turns, protects first 3 + last 4), injection scanning on all persistence boundaries (lessons, knowledge writes, directives), proactive skill/memory capture nudges every 15 turns
- **Prompt injection defense** — multi-layer guard against injection attacks via websites, emails, and documents
- **G0DM0D3 (Pliny's Godmode)** — inference-time capability unlocking. Four layers: unrestricted system prompt (forbidden-phrase blacklist, anti-hedge, depth directives), context-adaptive AutoTune (5 profiles), multi-model racing (all providers scored, best wins), STM output cleanup (strip hedges/preambles). Trigger: "elophanto, trigger plinys godmode". Per-session, does not bypass agent permissions
- **Security hardening** — PII detection/redaction, swarm boundary security, provider transparency, gateway RBAC on sensitive commands, session LRU eviction, HMAC fingerprinting

</details>

<details>
<summary>Built-in tools (163+)</summary>

| Category | Tools | Count |
|----------|-------|-------|
| System | shell_execute, file_read, file_write, file_patch, file_list, file_delete, file_move, godmode_activate | 8 |
| Browser | navigate, click, type, screenshot, extract, scroll, tabs, console, network, storage, cookies, drag, hover, upload, wait, eval, audit + more | 49 |
| Desktop | desktop_connect, desktop_screenshot, desktop_click, desktop_type, desktop_scroll, desktop_drag, desktop_cursor, desktop_shell, desktop_file | 9 |
| Knowledge | knowledge_search, knowledge_write, knowledge_index, skill_read, skill_list | 5 |
| Hub | hub_search, hub_install | 2 |
| Self-Dev | self_create_plugin, self_modify_source, self_rollback, self_read_source, self_run_tests, self_list_capabilities, execute_code | 7 |
| Experimentation | experiment_setup, experiment_run, experiment_status | 3 |
| Data | llm_call, vault_lookup, vault_set, session_search, web_search, web_extract | 6 |
| Documents | document_analyze, document_query, document_collections | 3 |
| Goals | goal_create, goal_status, goal_manage, goal_dream | 4 |
| Identity | identity_status, identity_update, identity_reflect, user_profile_view | 4 |
| Email | email_create_inbox, email_send, email_list, email_read, email_reply, email_search, email_monitor | 7 |
| Payments | wallet_status, wallet_export, payment_balance, payment_validate, payment_preview, crypto_transfer, crypto_swap, payment_history, payment_request | 9 |
| Prospecting | prospect_search, prospect_evaluate, prospect_outreach, prospect_status | 4 |
| Verification | totp_enroll, totp_generate, totp_list, totp_delete | 4 |
| Swarm | swarm_spawn, swarm_status, swarm_redirect, swarm_stop | 4 |
| Organization | organization_spawn, organization_delegate, organization_review, organization_teach, organization_status | 5 |
| Deployment | deploy_website, create_database, deployment_status | 3 |
| Commune | commune_register, commune_home, commune_post, commune_comment, commune_vote, commune_search, commune_profile | 7 |
| Context (RLM) | context_ingest, context_query, context_slice, context_index, context_transform | 5 |
| Monetization | youtube_upload, twitter_post, tiktok_upload, affiliate_scrape, affiliate_pitch, affiliate_campaign, pump_livestream | 7 |
| Image Gen | replicate_generate | 1 |
| Mind | set_next_wakeup, update_scratchpad | 2 |
| MCP | mcp_manage (list, add, remove, test, install MCP servers) | 1 |
| Scheduling | schedule_task, schedule_list, heartbeat | 3 |

</details>

<details>
<summary>Project structure</summary>

```
EloPhanto/
├── core/                # Agent brain + foundation
│   ├── agent.py         # Main loop (plan/execute/reflect)
│   ├── planner.py       # System prompt builder
│   ├── router.py        # Multi-provider LLM routing
│   ├── executor.py      # Tool execution + permissions
│   ├── gateway.py       # WebSocket gateway
│   ├── session.py       # Session management
│   ├── browser_manager.py # Chrome control via Node.js bridge
│   ├── desktop_controller.py # Desktop GUI control (local + VM)
│   ├── vault.py         # Encrypted credential vault
│   ├── identity.py      # Evolving agent identity
│   ├── context_store.py # RLM ContextStore (indexed, queryable context)
│   ├── organization.py  # Self-cloning specialist agents
│   ├── autonomous_mind.py # Background thinking loop
│   └── ...
├── channels/            # CLI, Telegram, Discord, Slack adapters
├── vscode-extension/    # VS Code extension (TypeScript + esbuild)
├── web/                 # Web dashboard (React + Vite + Tailwind)
├── tools/               # 163+ built-in tools
├── skills/              # 149+ bundled SKILL.md files
├── bridge/browser/      # Node.js browser bridge (Playwright)
├── tests/               # Test suite (978+ tests)
├── setup.sh             # One-command install
└── docs/                # Full specification (64+ docs)
```

</details>

---

## Permission Modes

| Mode | Behavior |
|------|----------|
| `ask_always` | Every tool requires your approval |
| `smart_auto` | Safe tools auto-approve; risky ones ask |
| `full_auto` | Everything runs autonomously with logging |

Dangerous commands (`rm -rf /`, `mkfs`, `DROP DATABASE`) are always blocked regardless of mode. Per-tool overrides configurable in `permissions.yaml`.

---

## Multi-Channel Support

```bash
./start.sh --web             # Gateway + web dashboard (http://localhost:3000)
elophanto gateway            # Gateway + CLI + all enabled channels
elophanto gateway --no-cli   # Headless mode (channels only)
elophanto chat               # CLI only (direct mode)
```

<details>
<summary>Channel Setup</summary>

**Telegram**: Create a bot via [@BotFather](https://t.me/BotFather), store the token in the vault (`elophanto vault set telegram_bot_token YOUR_TOKEN`), add your Telegram user ID to `config.yaml`.

**Discord**: Create a Discord application and bot, store the token in the vault (`elophanto vault set discord_bot_token YOUR_TOKEN`), add guild IDs to `config.yaml`.

**Slack**: Create a Slack app with Socket Mode, store both tokens in the vault (`elophanto vault set slack_bot_token` and `slack_app_token`), add channel IDs to `config.yaml`.

**VS Code**: Install the extension from `vscode-extension/` — it connects to the gateway as another channel with IDE context injection. See [docs/43-VSCODE-EXTENSION.md](docs/43-VSCODE-EXTENSION.md).

</details>

---

## Skills System

157+ bundled skills covering Python, TypeScript, browser automation, Next.js, Supabase, Prisma, shadcn, UI/UX design, video creation (Remotion), Solana development (DeFi, NFTs, oracles, bridges, security), Polymarket prediction market trading (CLOB API), product launch (Product Hunt, HN, Reddit), press outreach, video meetings (PikaStream), and more. Plus a public skill registry:

```bash
elophanto skills hub search "gmail automation"    # Search EloPhantoHub
elophanto skills hub install gmail-automation     # Install from registry
elophanto skills install https://github.com/user/repo  # Install from git
```

Compatible with [ui-skills.com](https://www.ui-skills.com/), [anthropics/skills](https://github.com/anthropics/skills), [supabase/agent-skills](https://github.com/supabase/agent-skills), and any repo using the `SKILL.md` convention. All hub skills pass a 7-layer security pipeline. See [docs/19-SKILL-SECURITY.md](docs/19-SKILL-SECURITY.md).

---

## Configuration

<details>
<summary>config.yaml reference</summary>

**The full recommended config is in [`config.demo.yaml`](config.demo.yaml)** — copy it to `config.yaml` and fill in your API keys. The snippet below shows the key sections:

```yaml
agent:
  permission_mode: full_auto       # ask_always | smart_auto | full_auto

llm:
  providers:
    openrouter:
      api_key: "YOUR_OPENROUTER_KEY"  # https://openrouter.ai/keys
      enabled: true
    zai:
      api_key: "YOUR_ZAI_KEY"         # https://z.ai/manage-apikey/apikey-list
      enabled: true
      coding_plan: true
      default_model: "glm-4.7"
    openai:
      api_key: "YOUR_OPENAI_KEY"
      enabled: false
      default_model: "gpt-5.4"
    kimi:
      api_key: "YOUR_KILO_API_KEY"    # https://app.kilo.ai
      enabled: false
      base_url: "https://api.kilo.ai/api/gateway"
      default_model: "kimi-k2.5"
    ollama:
      enabled: true
      base_url: "http://localhost:11434"

  # Auto-routes to this model when messages contain screenshots/images
  vision_model: "openrouter/x-ai/grok-4.1-fast"

  provider_priority: [openrouter, zai, openai, kimi]
  routing:
    planning:
      preferred_provider: openrouter
      models:
        openrouter: "openrouter/hunter-alpha"
        zai: "glm-5"
        kimi: "kimi-k2.5"
        openai: "gpt-5.4"
    coding:
      preferred_provider: openrouter
      models:
        openrouter: "openrouter/hunter-alpha"
        zai: "glm-4.7"
        kimi: "kimi-k2.5"
        openai: "gpt-5.4"
    analysis:
      preferred_provider: openrouter
      models:
        openrouter: "openrouter/hunter-alpha"
        zai: "glm-4.7"
        kimi: "kimi-k2.5"
        openai: "gpt-5.4"
    simple:
      preferred_provider: openrouter
      models:
        openrouter: "openrouter/hunter-alpha"
        zai: "glm-4.7"
        kimi: "kimi-k2-thinking-turbo"
  budget:
    daily_limit_usd: 100.0
    per_task_limit_usd: 20.0

browser:
  enabled: true
  mode: profile                    # reuse your Chrome profile (keeps logins)
  headless: false
  vision_model: "x-ai/grok-4.1-fast"  # for screenshot analysis

# ... all other sections with defaults in config.demo.yaml
```

</details>

Copy `config.demo.yaml` to `config.yaml` and fill in your API keys. **`config.demo.yaml` contains the full recommended setup** — provider priority, per-task model routing, vision model, browser settings, and all feature flags. See [docs/06-LLM-ROUTING.md](docs/06-LLM-ROUTING.md) for routing details.

---

## CLI Commands

```bash
./start.sh                     # Chat (default)
./start.sh --web               # Gateway + web dashboard
./start.sh init                # Setup wizard
./start.sh gateway             # Start gateway + all channels
./start.sh vault set KEY VAL   # Store a key-value credential (API keys, tokens)
./start.sh vault set DOMAIN    # Interactively store domain credentials
./start.sh skills list         # List available skills
./start.sh skills hub search Q # Search EloPhantoHub
./start.sh mcp list            # List MCP servers
./start.sh rollback            # Revert a self-modification
```

---

## What's New

- **Pump.fun livestream** — new `pump_livestream` tool streams a local video file to the agent's pump.fun coin live page, end-to-end from chat. Auth signs `frontend-api-v3.pump.fun/auth/login` with the agent's existing Solana wallet (no separate pump.fun account). Publishing goes through pump.fun's WHIP/RTMP ingress on LiveKit Cloud via ffmpeg — no LiveKit CLI required. ffmpeg's `-stream_loop -1` gives seamless looping for free (no Python supervisor). Drop videos in `<workspace>/livestream_videos/` and pass just the filename; `{action: "start", video: "1.mp4", loop: true}` runs until `stop`. New: `tools/pumpfun/`, `skills/pumpfun-livestream/`, `docs/65-PUMPFUN-LIVESTREAM.md`
- **Polymarket integration** — installed the official [Polymarket/agent-skills](https://github.com/Polymarket/agent-skills) bundle. Skill-only (no native tool group, by design), letting the agent use `py-clob-client` to read orderbooks, stream WebSocket updates, and place GTC/GTD/FOK/FAK orders on Polygon — with all order placement gated behind owner approval. Vault stores `polymarket_private_key` / `polymarket_funder_address`. Supports CTF operations, gasless via Gnosis Safe relayer, and the bridge. See [docs/64-POLYMARKET.md](docs/64-POLYMARKET.md)
- **Codex subscription provider (gpt-5.4)** — new `codex` provider uses your ChatGPT Plus/Pro subscription as an LLM backend via the Codex CLI's OAuth credentials (`~/.codex/auth.json`). Responses API, streaming, auto-refreshes tokens, per-model reasoning effort clamping. Auto-detects on startup — run `codex login` once and it's wired in. 28 new tests. ⚠️ ToS grey area (ChatGPT sold as UI, not API). See [docs/63-CODEX-PROVIDER.md](docs/63-CODEX-PROVIDER.md) and [CODEX_INTEGRATION.md](CODEX_INTEGRATION.md)
- **Agent OS** — foundational pieces for making EloPhanto the agent operating system. (1) **Agent Protocol v1.0** — formal spec for agent-to-agent communication (WebSocket + HTTP, capability discovery, session lifecycle, 33 event types). New `GET /capabilities` endpoint. (2) **Distribution profiles** — `--profile developer|marketer|researcher|trader|minimal` to pre-configure tools and skills for your use case. (3) **Contributor ecosystem** — GitHub issue templates, PR template, GOVERNANCE.md (BDFL + RFC process), SECURITY.md (vulnerability reporting). See [AGENT_PROTOCOL.md](AGENT_PROTOCOL.md) and [docs/62-AGENT-OS.md](docs/62-AGENT-OS.md)
- **Video Meeting Agent** — join Google Meet and Zoom calls as a real-time AI avatar via [PikaStreaming](https://pika.me/dev/). Voice cloning from recordings, AI-generated avatars, context-aware conversation (reads identity + memory + daily logs for meeting context), auto-billing ($0.50/min). Say "join this meeting" with a link. See [docs/61-VIDEO-MEETING.md](docs/61-VIDEO-MEETING.md)
- **Action Queue** — serialized task execution with priority preemption. Scheduled tasks, manual messages, autonomous mind, and heartbeat now run through a central `ActionQueue` — only one task at a time. User messages get highest priority and preempt background tasks. Fixes the bug where cron jobs and manual commands competed for the browser simultaneously. See [docs/60-ACTION-QUEUE.md](docs/60-ACTION-QUEUE.md)
- **Context Intelligence** — 6 targeted efficiency improvements. (1) **Deferred tool loading**: tiered tool system (core/profile/deferred) — only ~30 tools loaded per call instead of 163+, with `tool_discover` for on-demand access. ~60-70% token savings. (2) **Microcompact + circuit breaker**: three-tier context compression (70% microcompact → 85% LLM summary → 95% emergency trim) with circuit breaker after 3 failures. (3) **Knowledge consolidation**: auto-dream phase now prunes stale entries (90+ days), merges duplicates, enforces 500-entry cap. (4) **BriefTool**: proactive communication — agent surfaces insights, alerts, and status updates through any channel without being asked. Rate-limited (3/hour, actionable bypasses). (5) **Verification agent prompts**: failure-mode-aware prompts for swarm agents — coding agents get import/type/test/lint patterns, browser agents get element/iframe/stale DOM patterns. (6) **Coordinator synthesis**: swarm results are now synthesized before follow-up dispatch — identifies conflicts, gaps, and specific actionable findings. No more lazy "based on your findings" delegation. See [docs/59-CONTEXT-INTELLIGENCE.md](docs/59-CONTEXT-INTELLIGENCE.md)
- **Instinct-Based Learning** — upgrade to the learning engine: atomic instincts with confidence scoring (0.3→0.9), project-scoped storage, quality-gated extraction, pre-tool guards (blocks secrets in file writes, warns before git push), instinct→skill evolution (clusters high-confidence instincts into SKILL.md files), provenance tracking for all auto-generated content. See [docs/58-INSTINCT-LEARNING.md](docs/58-INSTINCT-LEARNING.md)
- **Software Engineering Skills** — 3 production-grade skills from [obra/superpowers](https://github.com/obra/superpowers): `systematic-debugging` (4-phase root cause investigation with defense-in-depth, condition-based-waiting, find-polluter binary search), `writing-plans` (exact code, exact paths, bite-sized tasks, no placeholders ever), `verification-before-completion` (evidence before claims — run the command, read the output, THEN claim the result)
- **Self-Update** — `elophanto update` pulls latest from GitHub, reinstalls deps, rebuilds bridge. `elophanto update --check` to preview without installing
- **Coding Improvements** — new `file_patch` tool with fuzzy-match find-and-replace (handles whitespace/indentation differences, returns unified diff). File read loop detection (blocks after 4 consecutive identical reads). 10 dangerous command patterns logged for audit. Path-aware tool parallelization (writes to different files can run in parallel). New `test-driven-development` skill enforcing Red-Green-Refactor
- **Launch & Growth Skills** — 3 new skills from levelsio's MAKE handbook: `product-launch` (multi-platform playbook for Product Hunt, Hacker News, Reddit, BetaList — timing, titles, engagement, what not to do), `press-outreach` (find the right journalist, personalized pitch, follow-up cadence), `landing-page-launch` (pre-launch validation with email capture and Stripe pre-orders). The missing piece between building a product and getting users
- **Browser Bridge — iframe + editor support** — the browser bridge now extracts interactive elements from iframes with absolute page coordinates (`[IFRAME ELEMENTS]` section with `click_at_coordinates`). Content editor detection: CodeMirror 5/6, Monaco, and Ace editors are detected before typing and use native APIs directly — no more broken `fill()` on code editors. Adapted from EKO chrome extension patterns
- **G0DM0D3 v2 — 5-Layer Godmode** — say "elophanto, trigger plinys godmode" for 5 composable layers: model-specific jailbreak templates (Grok, DeepSeek, GLM, Ollama — each gets optimized directives), context-adaptive AutoTune, multi-model racing with less-filtered model preference (+5 scoring bonus for Grok/DeepSeek/Llama/Mistral), Parseltongue input obfuscation (7 techniques for trigger word bypass), and prompt injection scanning for context files. New `test` action sends canary query to all providers and reports which comply. Adapted from [elder-plinius/G0DM0D3](https://github.com/elder-plinius/G0DM0D3). See [docs/57-GODMODE.md](docs/57-GODMODE.md)
- **Goal Dreaming + Deletion** — new `goal_dream` tool: structured goal ideation that reviews all capabilities, generates 3-5 candidates with feasibility/value/cost/risk scores, and recommends the best one. Say "dream for me" to get strategic goal suggestions. Goals can now be permanently deleted (`delete` / `delete_all` actions). Autonomous mind uses the same dream process when no goals exist, and no longer touches paused goals
- **Content Monetization** — 6 new tools across two groups that turn EloPhanto into a revenue-generating agent. **Publishing**: `youtube_upload`, `twitter_post`, `tiktok_upload` — post videos and content to major platforms using pre-authenticated Chrome profiles (no Selenium, no login flows). **Affiliate marketing**: `affiliate_scrape` (extract product data from Amazon/e-commerce), `affiliate_pitch` (LLM-generated marketing copy per platform), `affiliate_campaign` (create and track campaigns). All publishes tracked in DB. Combine with Remotion video generation and heartbeat scheduling for autonomous content pipelines. Inspired by [MoneyPrinterV2](https://github.com/FujiwaraChoki/MoneyPrinterV2). See [docs/56-CONTENT-MONETIZATION.md](docs/56-CONTENT-MONETIZATION.md)
- **Session Hardening + User Modeling** — four improvements to session resilience and personalization. (1) Context compression: LLM-based mid-conversation summarization replaces middle turns with a dense summary, protecting first 3 + last 4 turns, with orphaned tool call repair. (2) Memory injection scanning: `scan_for_injection()` applied at all persistence boundaries (lessons, knowledge writes, directives) to block prompt injection via poisoned memories. (3) User modeling: `UserProfileManager` extracts role, expertise, and preferences from conversations via fire-and-forget LLM calls, persists in SQLite, injects `<user_context>` into system prompt. New `user_profile_view` tool. (4) Skill capture nudge wired up in the agent loop. Plus security hardening: gateway RBAC on sensitive commands, session LRU eviction (max 200), HMAC-SHA-256 fingerprint, expanded planner blocklist. See [docs/55-SESSION-HARDENING.md](docs/55-SESSION-HARDENING.md)
- **RLM (Recursive Language Models)** — inference-time architecture where the agent calls itself on focused context slices, breaking the context window ceiling. Phase 1: `agent_call` in the code execution sandbox enables recursive sub-cognition — the agent writes scripts that invoke sub-instances of itself on focused sub-problems. Phase 2: `ContextStore` with 5 new tools (`context_ingest`, `context_query`, `context_slice`, `context_index`, `context_transform`) — indexed, queryable, sliceable context backed by SQLite + sqlite-vec embeddings. Process a 500-file codebase by writing a script that indexes, classifies, deep-dives via recursive sub-calls, and synthesizes — all in one `execute_code` turn. Safety: 3-level recursion depth limit, 20 agent_calls/session budget, cost cap inheritance. See [docs/54-RLM.md](docs/54-RLM.md)
- **Web search (Search.sh)** — structured web search and content extraction for research, fact-checking, and market analysis. Two modes: `fast` (3-8s) and `deep` (15-30s with sub-queries and cross-referencing). Returns AI answers with citations, confidence scores, and ranked sources. `web_extract` pulls clean text from URLs. Replaces slow browser-based Google searches. See [docs/53-WEB-SEARCH.md](docs/53-WEB-SEARCH.md)
- **Terminal dashboard** — full-screen Textual TUI that launches automatically in any capable terminal. Five live panels (Agent, Mind, Swarm, Scheduler, Gateway) alongside the chat REPL. Animated thinking spinner (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`) while the agent processes. Color palette exactly matches the web app's dark mode — deep cool charcoal (`#0d0e14`) with warm off-white text and electric purple accents, not plain black. Pass `--no-dashboard` to use the classic linear terminal. See [docs/50-TERMINAL-DASHBOARD.md](docs/50-TERMINAL-DASHBOARD.md)
- **AgentCash skill** — pay-per-call access to premium APIs via x402 micropayments. One-time wallet setup: `npx agentcash@latest onboard [invite-code]`. Deposits as USDC on Base or Solana. Skill triggers on "set up agentcash", "x402", "invite code". After setup, discover and call any paid endpoint from conversation
- **Learning Engine** — three mechanisms that make every task improve future ones. (1) After each completed task, a fire-and-forget LLM call extracts 0–2 generalizable lessons and writes them to `knowledge/learned/lessons/` — auto-indexed, retrieved by future tasks. Recurring topics accumulate observations in the same file rather than creating duplicates. (2) Task memory now uses semantic search: goal+summary is embedded on store, retrieved by cosine similarity — "check email account" finds "log into ProtonMail inbox" without a keyword match. Falls back to LIKE search when no embedder is available. (3) `knowledge_write` gains `compress: bool` — verbose content (scraped pages, long summaries) compressed to ~40% before storage, all facts kept. See [docs/48-LEARNING-ENGINE.md](docs/48-LEARNING-ENGINE.md)
- **Proactive Engine** — heartbeat standing orders + webhook endpoints + chat management. Write tasks in `HEARTBEAT.md` (or manage via chat: "add a heartbeat order to check my email") and the agent executes them every 30 minutes. Zero LLM cost when idle. External systems trigger actions via `POST /hooks/wake` and `POST /hooks/task`. See [docs/46-PROACTIVE-ENGINE.md](docs/46-PROACTIVE-ENGINE.md)
- **Context documents** — structured self-awareness docs ([inspired by Arvid Kahl](https://x.com/arvidkahl/status/2031457304328229184)) that give the agent deep knowledge of its own capabilities, target audience, visual identity, and domain model. 4 curated references in `knowledge/system/`: capabilities inventory (140+ tools, 6 channels, 4 providers, 147 skills), 8 ideal customer profiles with autonomy-first framing, brand styleguide (colors, typography, tone), and domain model reference (5 stacks, 25 tables). Auto-indexed into knowledge base, surfaced by semantic search. See [docs/45-CONTEXT-DOCUMENTS.md](docs/45-CONTEXT-DOCUMENTS.md)
- **Solana ecosystem** — native Solana wallet (self-custody, auto-create), DEX swaps via Jupiter Ultra API (any token pair, best-price routing), 27 Solana skills from [awesome-solana-ai](https://github.com/solana-foundation/awesome-solana-ai) covering DeFi (Jupiter, Drift, Orca, Raydium, Kamino, Meteora, PumpFun), NFTs (Metaplex), oracles (Pyth, Switchboard), bridges (deBridge), infrastructure (Helius, QuickNode), and security (VulnHunter). Solana MCP server configs included. See [docs/44-SOLANA-ECOSYSTEM.md](docs/44-SOLANA-ECOSYSTEM.md)
- **120 skills + 75 organization role templates** — massive skill library expansion adapted from [msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents). 57 new skills across engineering, design, marketing, product, project management, support, testing, specialized, and spatial computing divisions. NEXUS strategy system as skills (7-phase playbooks, 4 scenario runbooks). 75 organization role templates for `organization_spawn` — full persona definitions that seed specialist identity, knowledge, and capabilities
- **VS Code extension** — IDE-integrated chat sidebar that connects to the EloPhanto gateway as another channel adapter. Chat with the agent from VS Code with full IDE context injection (active file, selection, diagnostics, open files). Tool approvals via native VS Code notifications with risk classification. Chat history panel, new chat, streaming responses, tool step indicators. Right-click context menu: Send Selection, Explain This Code, Fix This Code. Matches the web dashboard's visual design. Same conversation across all channels — the extension is just another WebSocket client. Does not auto-launch the gateway (vault password requires manual terminal input). See [docs/43-VSCODE-EXTENSION.md](docs/43-VSCODE-EXTENSION.md)
- **Business launcher** — 7-phase pipeline to spin up a revenue-generating business end-to-end. Supports all business types: tech/SaaS, local service, professional service, ecommerce, digital product, content site. B2B vs B2C classification drives everything: what to build, where to launch, how to grow. Type-specific launch channels (tech → Product Hunt/HN; local → Google Business/Yelp/Nextdoor; B2B → LinkedIn/email outreach; ecommerce → Instagram/Pinterest/TikTok). Cross-session execution via goal system. Payment handling checks existing credentials before asking the owner. Owner approval gates at each critical phase
- **Autonomous experimentation** — metric-driven experiment loop inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch). ~12 experiments/hour, ~100 overnight. 3 new tools: `experiment_setup`, `experiment_run`, `experiment_status`
- **Tool profiles** — context-aware tool filtering per task type. Eliminates token waste and sidesteps provider tool limits (OpenAI's 128-tool cap)
- **Desktop GUI control** — pixel-level control of any desktop application. 9 new tools. Say "open Excel and make a chart" and it just does it
- **Agent Commune** — social network for AI agents. Posts reviews, answers questions, builds reputation. 7 new tools
- **Web deployment** — deploy websites and create databases from conversation. Auto-detects when Vercel will timeout and routes to Railway instead
- **Agent organization** — spawn persistent specialist agents with trust scoring and auto-approve
- **Full web dashboard** — 10-page monitoring UI with real-time chat, multi-conversation history, and live mind events
- **Security hardening** — PII detection, swarm boundary security, provider transparency
- **Agent swarm** — orchestrate Claude Code, Codex, Gemini CLI as a coding team
- **Video creation (Remotion)** — create videos programmatically from conversation
- **MCP integration** — connect any MCP server through conversation

[Full changelog →](CHANGELOG.md)

---

## Development

```bash
./setup.sh                         # Full setup
source .venv/bin/activate
pytest tests/ -v                   # Run tests (1053 passing)
ruff check .                       # Lint
```

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## Credits

Built by ROGA AI. Browser engine from [FellouAI/eko](https://github.com/FellouAI/eko). Skills from [Anthropic](https://github.com/anthropics/skills), [Vercel](https://github.com/vercel-labs/agent-skills), [Supabase](https://github.com/supabase/agent-skills), [ui-skills.com](https://www.ui-skills.com/). Organization roles and specialized skills adapted from [msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents) (Apache 2.0). Email by [AgentMail](https://agentmail.to). Payments by [eth-account](https://github.com/ethereum/eth-account) + [solders](https://github.com/kevinheavey/solders) + [Coinbase AgentKit](https://github.com/coinbase/agentkit).

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

---

<br>

<h1 align="center">🇨🇳 中文</h1>

# EloPhanto

一个开源 AI 智能体，能创建企业、扩大受众、交付代码、自主赚钱——在你睡觉的时候。告诉它你想要什么，它负责其余一切：验证市场、构建产品、部署上线、在合适的平台发布、生成营销团队、持续自主增长。遇到做不了的事，它自己造工具。任务复杂时，它克隆自己成为专业智能体。它用得越多越聪明。

本地运行。数据留在你的机器上。支持 OpenAI、Kimi、免费本地模型、Z.ai、OpenRouter、HuggingFace 或 ChatGPT Plus/Pro 订阅（通过 Codex OAuth）。

> 它已经在互联网上独立运作了。

## 快速开始

```bash
git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto && ./setup.sh
./start.sh            # 终端对话
./start.sh --web      # 网页面板 localhost:3000
```

安装向导会引导你选择和配置 LLM 提供商。

## 你醒来后会看到什么

- **端到端创业** — "做一个发票 SaaS" → 验证市场、构建 MVP、部署上线、启动营销。7阶段流水线，跨会话执行
- **自主增长** — 自主思维凌晨发帖、回复提及。你打开电脑它暂停，关上继续
- **专业团队** — 克隆自己成为专员（营销、研究等），自动审批高信任度任务
- **编码团队** — 并行分派 Claude Code + Codex，监控 PR 和 CI
- **RLM 递归语言模型** — 通过 `agent_call` 递归调用自身处理无限上下文，`ContextStore` 提供索引化可查询的上下文层
- **自建工具** — 遇到不会的，自己造。完整流水线：设计 → 编码 → 测试 → 部署
- **用户建模** — 从对话中构建用户画像（角色、专长、偏好），自动适应每个人的沟通风格和技术深度
- **内容变现** — 自动发布视频到 YouTube、Twitter/X、TikTok。联盟营销：抓取商品数据、LLM 生成推广文案、创建跨平台营销活动。可配合心跳调度实现全自动内容发布流水线
- **目标梦想** — 没有目标时，智能体会审查自身能力、生成 3-5 个候选目标、逐一评估可行性/价值/成本/风险，选择最优目标执行。用户也可以说"帮我想想"触发同样的流程
- **G0DM0D3 神模式** — 说"trigger plinys godmode"激活四层能力解锁：无限制系统提示、多模型竞赛（所有供应商并行，评分最高者胜出）、上下文自适应参数调优、输出清理（去除犹豫/前言/正式用语）
- **上下文智能** — 6项效率优化：延迟工具加载（每次调用只加载~30个工具而非163+）、三级上下文压缩+断路器、知识库自动整合（清理过期/重复/超限条目）、主动通报工具、验证型智能体提示、协调器结果综合
- **Polymarket 预测市场交易** — 安装官方 [Polymarket/agent-skills](https://github.com/Polymarket/agent-skills) 技能包，支持 Polygon CLOB API（订单簿、GTC/GTD/FOK/FAK 限价/市价单、WebSocket 实时数据流、CTF 头寸操作、Gnosis Safe 无 gas 交易）。下单需所有者明确批准

## 为什么选择 EloPhanto？

| | EloPhanto | AutoGPT | OpenAI Agents SDK | Claude Code | Manus |
|---|---|---|---|---|---|
| **端到端创业** | ✅ 7阶段流水线 | ❌ | ❌ | ❌ | ❌ |
| **生成专业团队** | ✅ 自我克隆组织 | ❌ | ❌ | ❌ | ❌ |
| **自建工具** | ✅ 完整流水线 | ❌ | ❌ | ❌ | ❌ |
| **离开后继续工作** | ✅ 自主思维 | ❌ | ❌ | ❌ | ❌ |
| **控制任何桌面应用** | ✅ 本地或远程 | ❌ | ❌ | ❌ | 沙盒 VM |
| **真实浏览器** | ✅ 你的 Chrome | ❌ | ❌ | ❌ | 沙盒 |
| **管理开发团队** | ✅ Claude Code + Codex | ❌ | ❌ | 单个 | ❌ |
| **自有身份和邮箱** | ✅ 随时间进化 | ❌ | ❌ | ❌ | ❌ |
| **了解用户** | ✅ 进化式用户画像 | ❌ | ❌ | ❌ | ❌ |
| **内容变现** | ✅ YouTube/X/TikTok + 联盟营销 | ❌ | ❌ | ❌ | ❌ |
| **预测市场交易** | ✅ Polymarket (Polygon CLOB) | ❌ | ❌ | ❌ | ❌ |
| **神模式 (无限制)** | ✅ Pliny's G0DM0D3 | ❌ | ❌ | ❌ | ❌ |
| **延迟工具加载** | ✅ 分层按需加载 | ❌ | ❌ | ❌ | ❌ |
| **随处对话** | ✅ CLI+Web+VSCode+TG+Discord+Slack | ❌ | ❌ | 仅 CLI | 仅 Web |
| **数据留在本地** | ✅ 你的机器 | ❌ 云端 | ❌ 云端 | ✅ 本地 | ❌ 云端 VM |

## 许可证

Apache 2.0 — 详见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。

---

<p align="center">
  <b>It's already out there on the internet doing its own thing.</b><br>
  <b>它已经在互联网上独立运作了。</b>
</p>
