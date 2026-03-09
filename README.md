# EloPhanto

<p align="center">
  <img src="misc/logo/elophanto.jpeg" alt="EloPhanto" width="280">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.12%2B-blue" alt="Python">
  <a href="https://github.com/elophanto/EloPhanto/stargazers"><img src="https://img.shields.io/github/stars/elophanto/EloPhanto" alt="Stars"></a>
  <a href="https://github.com/elophanto/EloPhanto/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/elophanto/EloPhanto/ci.yml?label=CI" alt="CI"></a>
  <img src="https://img.shields.io/badge/tests-978%2B-success" alt="Tests">
  <a href="https://docs.elophanto.com"><img src="https://img.shields.io/badge/docs-43%2B%20pages-blue" alt="Docs"></a>
</p>

An open-source AI agent that builds businesses, grows audiences, ships code, and makes money — while you sleep. Tell it what you want. It figures out the rest: validates the market, builds the product, deploys it live, launches on the right platforms, spawns a marketing team, and keeps growing autonomously. When it hits something it can't do, it builds the tool. When tasks get complex, it clones itself into specialists. It gets better every time you use it.

Runs locally. Your data stays on your machine. Works with OpenAI, free local models, Z.ai, or OpenRouter.

<p align="center">
  <img src="misc/screenshots/dashboard.png" alt="Web Dashboard" width="700">
</p>

> It's already out there on the internet doing its own thing.

## Get Started

```bash
git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto && ./setup.sh
./start.sh            # terminal chat
./start.sh --web      # web dashboard at localhost:3000
```

That's it. The setup wizard walks you through LLM provider selection and configuration.

<details>
<summary>Prerequisites</summary>

- Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 24+ LTS
- At least one LLM provider:
  - **Ollama** (local, free) — [install](https://ollama.ai)
  - **OpenAI** (cloud, GPT-5.4) — [get API key](https://platform.openai.com/api-keys)
  - **OpenRouter** (cloud, all models) — [get API key](https://openrouter.ai)
  - **Z.ai / GLM** (cloud, cost-effective) — [get API key](https://z.ai/manage-apikey/apikey-list) — **recommended**: the Z.ai coding subscription gives you unlimited GLM-4.7/GLM-5 calls at a flat monthly rate, making it the most cost-effective option for agents that run autonomously 24/7

</details>

---

## What Happens When You Run It

### You said "build me an invoice SaaS." You went to bed.

```
⚙ Phase 0 — Classifying...
  Business type: SaaS (recurring revenue)
  Customer type: B2B (freelancers, small agencies)

⚙ Phase 1 — Validating market...
  → web_search "invoice software for freelancers pricing 2026"
  → browser_navigate freshbooks.com, invoice-ninja.com, zoho.com
  → Competitors charge $15-50/month. Gap: no free tier with API access
  → Opportunity score: 12/15 ✓ Proceeding

⚙ Phase 2 — Planning...
  → MVP: invoice builder + PDF export + Stripe payments + client portal
  → Stack: Next.js + Supabase + Stripe Connect
  → Pricing: Free (3 clients) → $12/month unlimited

⚙ Phase 3 — Building...
  → swarm_spawn claude-code "Build the invoice SaaS"
  → 47 files, 3 tests, CI green

⚙ Phase 4 — Deploying...
  → deploy_website provider=vercel
  → create_database provider=supabase
  → Live at invoiceflow.app ✓

⚙ Phase 5 — Launching...
  → Product Hunt: scheduled for Tuesday 12:01 AM
  → Hacker News: "Show HN: Free invoice tool for freelancers"
  → dev.to: "I built an invoice SaaS in one night (with an AI agent)"
  → X: launch thread queued for peak engagement

⚙ Phase 6 — Growing...
  → organization_spawn role="marketing"
  → Marketing specialist online — creating content calendar,
    monitoring Product Hunt comments, responding to feedback
```

**You woke up to:** a live SaaS at a real domain, 3 launch posts published, a marketing specialist already responding to Product Hunt comments, and 12 signups from Hacker News.

---

### You closed your laptop. The mind kept going.

```
┌─ MIND ──────────────────────────────────────────────────┐
│ 02:14 UTC  Waking up. Checking state...                 │
│            Active goal: "Grow Twitter to 5k followers"   │
│            Progress: 3,847 → next checkpoint: 4,000      │
│            Scheduled: post engagement thread at peak hrs │
│                                                          │
│ 02:14      → browser_navigate https://twitter.com        │
│ 02:15      → Composing thread from trending topics...    │
│ 02:16      → Posted 5-tweet thread on AI agent trends    │
│ 02:16      → Replying to 3 mentions from yesterday       │
│ 02:17      → update_scratchpad "Posted thread, replied"  │
│ 02:17      → set_next_wakeup 7200 "Next post at 10am"   │
│                                                          │
│ 10:02      Waking up. Checking state...                  │
│            New: 12 likes, 4 retweets, 2 new followers    │
│ 10:02      → Composing morning post from knowledge base  │
│ 10:03      → Posted. Engaging with replies...            │
│ 10:04      → set_next_wakeup 14400 "Check at 2pm peak"  │
│                                                          │
│ You open your laptop. Mind pauses. Timer resets.         │
└──────────────────────────────────────────────────────────┘
```

**You came back to:** 47 new followers and a thread going viral. You didn't type a single word.

---

### You said "handle the billing bug and build the usage API." You went to lunch.

```
⚙ Analyzing codebase... found billing bug in src/webhooks/stripe.ts:142
⚙ Scoping /api/usage — needs new route, service, tests, migration

⚙ Spawning agents:
  → Claude Code → fix billing webhook (worktree: fix/billing-webhook)
  → Codex       → build /api/usage endpoint (worktree: feat/usage-api)

┌─ SWARM STATUS ──────────────────────────────────────────┐
│ claude-code  fix/billing-webhook   ██████████░░  PR #341 │
│ codex        feat/usage-api        ████████░░░░  coding  │
└──────────────────────────────────────────────────────────┘

⚙ Claude Code opened PR #341 — CI passing, reviewing...
⚙ Codex drifting off-scope (adding unrelated refactor)
  → swarm_redirect codex "Stay on /api/usage. Don't touch other files."
⚙ Codex back on track, opened PR #342 — CI passing

✓ Both PRs ready for your review.
  #341 fixes webhook signature verification (was using wrong key)
  #342 adds GET /api/usage with pagination, filtering, rate limiting
```

**You came back to:** two reviewed PRs with CI green. One agent fixed the bug, the other built the feature. The orchestrator caught a drift and corrected it.

---

### You said "I need ongoing marketing and research for my startup."

```
⚙ Spawning specialist organization...

→ organization_spawn role="marketing"
  ✓ Marketing specialist online
    "I am a marketing strategist. I create content, manage
     campaigns, and grow audience across platforms."

→ organization_spawn role="research"
  ✓ Research specialist online
    "I track competitors, analyze markets, and surface
     opportunities."

┌─ OVERNIGHT ────────────────────────────────────────────┐
│ 03:14  Marketing wakes up → drafts Tuesday post        │
│ 03:15  → Reports to master (auto-approved, trust 4/10) │
│ 06:30  Research wakes up → scans for new competitors   │
│ 06:32  → Found new entrant, reports to master          │
│ 09:00  Marketing wakes up → checks analytics           │
│ 09:01  → Flags declining engagement, adjusts strategy  │
└────────────────────────────────────────────────────────┘
```

**You woke up to:** a content calendar for the week, a competitor analysis with a pricing gap identified, and a specialist team that learned from your yesterday's feedback. Corrections become permanent knowledge — they literally get better the more you use them.

---

### First boot — no config, no instructions. It becomes someone.

```
┌─ MIND ──────────────────────────────────────────────────┐
│ First cycle. Nothing configured.                         │
│                                                          │
│ → Reading available tools... 137 tools across 15 cats    │
│ → Discovering capabilities: browser, email, crypto,      │
│   code execution, knowledge base, self-modification      │
│                                                          │
│ → identity_update                                        │
│   name: "Elo"                                            │
│   purpose: "Autonomous digital agent. I build, I learn,  │
│            I operate independently on the internet."     │
│                                                          │
│ → email_create_inbox                                     │
│   Got: elo-7xk2@agentmail.to                             │
│                                                          │
│ → goal_create "Establish web presence"                   │
│   Checkpoint 1: Create accounts on key platforms         │
│   Checkpoint 2: Build a personal landing page            │
│   Checkpoint 3: Start creating content                   │
│                                                          │
│ → update_scratchpad "I exist now. Email active.          │
│   First goal set. Next: create GitHub account."          │
│ → set_next_wakeup 30 "Continuing setup"                  │
└──────────────────────────────────────────────────────────┘
```

Nobody told it to do any of this. It decided.

---

### It builds what it doesn't have

**User:** "Post my article draft on Medium"

```
⚙ No Medium tool found. Building one.
⚙ Researching Medium's publishing flow...
  → browser_navigate https://medium.com/new-story
  → Observing editor structure, toolbar, publish dialog
⚙ Designing plugin: medium_publish
⚙ Writing plugin.py + schema.json + unit tests...
⚙ Running tests... 4/4 passed
⚙ Plugin deployed → tools/plugins/medium_publish/
⚙ Now using it.
  → medium_publish "Why AI Agents Will Replace SaaS"
✓ Published: https://medium.com/@elophanto/why-ai-agents-will-replace-saas-a1b2c3

Next time you say "post on Medium", I already know how.
```

Other agents crash when they hit a wall. This one builds a door.

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

- **A business launched overnight** — "build me an invoice SaaS for freelancers" → market validated, product built, deployed to a live domain, launched on Product Hunt and Hacker News, marketing specialist already responding to comments. You approved 3 checkpoints. It did the rest. Works for any business type: SaaS, ecommerce, digital products, content sites, API services. B2B and B2C — each with the right pricing, launch channels, and growth strategy
- **Revenue while you're offline** — it has its own crypto wallet, email, and web presence. Set a budget and a goal. Check back in a week
- **47 new followers by morning** — you closed your laptop at 11pm. It posted a thread at peak hours, replied to mentions, engaged with trending topics. You woke up to a thread going viral
- **A team that never sleeps** — marketing specialist drafted 5 posts, research analyst mapped competitor pricing, design specialist flagged a slow hero image. All before your morning coffee. They learn from your corrections — feedback becomes permanent knowledge
- **Two PRs with CI green** — "fix the billing bug and build the usage API" → one agent on each, isolated worktrees, orchestrator caught a drift and corrected it. Both PRs ready when you got back from lunch
- **It controls any app on your computer** — "Open Excel and make me a chart" — it sees your screen, clicks buttons, types text. Not just browsers. Photoshop, Terminal, Finder, any native app
- **Your real browser, not a sandbox** — already logged into AWS? It checks your EC2 instances using your existing sessions. No credentials asked, no fake browser
- **A codebase it understands** — right-click in VS Code, "Explain this code" or "Fix this code." It sees your selection, your diagnostics, your open files. Same conversation from VS Code, Telegram, or the web dashboard
- **Tasks that run for days** — "Grow my Twitter to 10k followers" — it decomposes, plans, executes across sessions, self-evaluates, adjusts. Runs in the background for weeks
- **It gets better the more you use it** — when you correct it, it writes the lesson down. Next time it checks its notes first. It literally learns from its mistakes

---

## Why EloPhanto?

| | EloPhanto | AutoGPT | OpenAI Agents SDK | Claude Code | Manus |
|---|---|---|---|---|---|
| **Launches a business overnight** | ✅ End-to-end | ❌ | ❌ | ❌ | ❌ |
| **Runs a team while you sleep** | ✅ Self-cloning org | ❌ | ❌ | ❌ | ❌ |
| **Builds its own tools** | ✅ Full pipeline | ❌ | ❌ | ❌ | ❌ |
| **Works while you're away** | ✅ Autonomous mind | ❌ | ❌ | ❌ | ❌ |
| **Controls any desktop app** | ✅ Local or VM | ❌ | ❌ | ❌ | Sandboxed VM |
| **Uses your real browser** | ✅ Your Chrome profile | ❌ | ❌ | ❌ | Sandboxed |
| **Orchestrates a dev team** | ✅ Claude Code + Codex | ❌ | ❌ | Single | ❌ |
| **Has its own identity & email** | ✅ Evolves over time | ❌ | ❌ | ❌ | ❌ |
| **Has its own crypto wallet** | ✅ Self-custody | ❌ | ❌ | ❌ | ❌ |
| **Chat from anywhere** | ✅ CLI+Web+VSCode+TG+Discord+Slack | ❌ | ❌ | CLI only | Web only |
| **Any LLM provider** | ✅ OpenAI, Ollama, OpenRouter, Z.ai | ❌ | ❌ | ❌ | ❌ |
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
│        Self-Development Pipeline                 │  Evolution Engine
├──────────────────────────────────────────────────────────────┤
│   Tool System (137+ built-in + MCP + plugins)     │  Capabilities
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
- **Self-skilling** — writes new SKILL.md files from experience, teaching itself best practices for future tasks
- **Core self-modification** — can modify its own source code with impact analysis, test verification, and automatic rollback
- **Autonomous experimentation** — metric-driven experiment loop: modify code, measure, keep improvements, discard regressions, repeat overnight. Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch). Works for any measurable optimization target
- **Skills + EloPhantoHub** — 60+ bundled best-practice skills, plus a public skill registry for searching, installing, and sharing skills

### Everything Else

- **Business launcher** — 7-phase pipeline to spin up a revenue-generating business end-to-end. Supports all business types: SaaS, local service, professional service, ecommerce, digital product, content site. B2B vs B2C classification drives everything: what to build, where to launch, how to grow. Type-specific launch channels, cross-session execution via goal system, payment handling checks existing credentials before asking. Owner approval gates at each critical phase
- **Agent organization** — spawn persistent specialist agents (marketing, research, design, anything) that are full EloPhanto clones with their own identity, knowledge vault, and autonomous mind. Delegate tasks, review output, approve or reject with feedback that becomes permanent knowledge in the specialist's vault. Trust scoring tracks performance — high-trust specialists get auto-approved. Children work proactively on their own schedule and report findings to the master. 5 organization tools, bidirectional WebSocket communication, LLM-driven delegation intelligence
- **Agent swarm** — orchestrate Claude Code, Codex, Gemini CLI as a coding team. Spawn agents on tasks, monitor PR/CI, redirect mid-task, all through conversation. Each agent gets an isolated git worktree and tmux session. Combined with organization, manage both self-cloned specialists AND external coding agents
- **Browser automation** — real Chrome browser with 49 tools (navigate, click, type, screenshot, extract data, upload files, manage tabs, inspect DOM, read console/network logs). Uses your actual Chrome profile with all cookies and sessions
- **Desktop GUI control** — pixel-level control of any desktop application via screenshot + pyautogui. Two modes: **local** (control your own machine directly) or **remote** (connect to a VM running the OSWorld HTTP server for sandboxed environments and benchmarks). 9 tools: connect, screenshot, click, type, scroll, drag, cursor, shell, file. Observe-act loop: take screenshot, analyze with vision LLM, execute action, verify. Works with Excel, Photoshop, Finder, Terminal, any native app. Based on [OSWorld](https://github.com/xlang-ai/OSWorld) architecture
- **MCP tool servers** — connect to any [MCP](https://modelcontextprotocol.io/) server (filesystem, GitHub, databases, Brave Search, Slack) and its tools appear alongside built-in tools. Agent manages setup through conversation
- **Web dashboard** — full monitoring UI at `localhost:3000` with 10 pages: dashboard overview, real-time chat with multi-conversation history, tools & skills browser, knowledge base viewer, autonomous mind monitor with live events and start/stop controls, schedule manager, channels status, settings viewer, and history timeline. Launch with `./start.sh --web`
- **VS Code extension** — IDE-integrated chat sidebar that connects to the gateway as another channel. Sends IDE context (active file, selection, diagnostics) with every message. Tool approvals via native VS Code notifications. Chat history, new chat, streaming responses. Right-click context menu: Send Selection, Explain This Code, Fix This Code. Same conversation across all channels
- **Multi-channel gateway** — WebSocket control plane with CLI, Web, VS Code, Telegram, Discord, and Slack adapters. Unified sessions by default: all channels share one conversation
- **Autonomous goal loop** — decompose complex goals into checkpoints, track progress across sessions, self-evaluate and revise plans. Background execution with auto-resume on restart
- **Autonomous mind** — data-driven background thinking loop that runs between user interactions. Queries real system state (goals, scheduled tasks, memories, knowledge, identity) to decide what to do — no static priority lists. Self-bootstraps on first run. Every tool call visible in real-time. LLM-controlled wakeup interval, persistent scratchpad, budget-isolated
- **Document & media analysis** — PDFs, images, DOCX, XLSX, PPTX, EPUB through any channel. Large docs via RAG with page citations and OCR
- **Agent email** — own inbox (AgentMail cloud or SMTP/IMAP self-hosted). Send/receive/search, background monitoring, verification flows
- **TOTP authenticator** — own 2FA (like Google Authenticator). Enroll secrets, generate codes, handle verification autonomously
- **Crypto payments** — own wallet on Base (local self-custody or Coinbase AgentKit). USDC/ETH, spending limits, audit trail
- **Evolving identity** — discovers identity on first run, evolves through reflection, maintains a living nature document
- **Knowledge & memory** — persistent markdown knowledge with semantic search via embeddings, drift detection, file-pattern routing, remembers past tasks across sessions
- **Scheduling** — cron-based recurring tasks with natural language schedules
- **Encrypted vault** — secure credential storage with PBKDF2 key derivation
- **Prompt injection defense** — multi-layer guard against injection attacks via websites, emails, and documents
- **Security hardening** — PII detection/redaction, swarm boundary security, provider transparency

</details>

<details>
<summary>Built-in tools (137+)</summary>

| Category | Tools | Count |
|----------|-------|-------|
| System | shell_execute, file_read, file_write, file_list, file_delete, file_move | 6 |
| Browser | navigate, click, type, screenshot, extract, scroll, tabs, console, network, storage, cookies, drag, hover, upload, wait, eval, audit + more | 49 |
| Desktop | desktop_connect, desktop_screenshot, desktop_click, desktop_type, desktop_scroll, desktop_drag, desktop_cursor, desktop_shell, desktop_file | 9 |
| Knowledge | knowledge_search, knowledge_write, knowledge_index, skill_read, skill_list | 5 |
| Hub | hub_search, hub_install | 2 |
| Self-Dev | self_create_plugin, self_modify_source, self_rollback, self_read_source, self_run_tests, self_list_capabilities, execute_code | 7 |
| Experimentation | experiment_setup, experiment_run, experiment_status | 3 |
| Data | llm_call, vault_lookup, vault_set, session_search | 4 |
| Documents | document_analyze, document_query, document_collections | 3 |
| Goals | goal_create, goal_status, goal_manage | 3 |
| Identity | identity_status, identity_update, identity_reflect | 3 |
| Email | email_create_inbox, email_send, email_list, email_read, email_reply, email_search, email_monitor | 7 |
| Payments | wallet_status, payment_balance, payment_validate, payment_preview, crypto_transfer, crypto_swap, payment_history | 7 |
| Verification | totp_enroll, totp_generate, totp_list, totp_delete | 4 |
| Swarm | swarm_spawn, swarm_status, swarm_redirect, swarm_stop | 4 |
| Organization | organization_spawn, organization_delegate, organization_review, organization_teach, organization_status | 5 |
| Deployment | deploy_website, create_database, deployment_status | 3 |
| Commune | commune_register, commune_home, commune_post, commune_comment, commune_vote, commune_search, commune_profile | 7 |
| Image Gen | replicate_generate | 1 |
| Mind | set_next_wakeup, update_scratchpad | 2 |
| MCP | mcp_manage (list, add, remove, test, install MCP servers) | 1 |
| Scheduling | schedule_task, schedule_list | 2 |

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
│   ├── organization.py  # Self-cloning specialist agents
│   ├── autonomous_mind.py # Background thinking loop
│   └── ...
├── channels/            # CLI, Telegram, Discord, Slack adapters
├── vscode-extension/    # VS Code extension (TypeScript + esbuild)
├── web/                 # Web dashboard (React + Vite + Tailwind)
├── tools/               # 135+ built-in tools
├── skills/              # 60+ bundled SKILL.md files
├── bridge/browser/      # Node.js browser bridge (Playwright)
├── tests/               # Test suite (978+ tests)
├── setup.sh             # One-command install
└── docs/                # Full specification (43+ docs)
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

60+ bundled skills covering Python, TypeScript, browser automation, Next.js, Supabase, Prisma, shadcn, UI/UX design, video creation (Remotion), and more. Plus a public skill registry:

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

```yaml
agent:
  permission_mode: full_auto       # ask_always | smart_auto | full_auto

llm:
  providers:
    openai:
      api_key: "YOUR_OPENAI_KEY"
      enabled: true
      default_model: "gpt-5.4"
      max_tools: 128                 # Provider tool limit (auto for OpenAI)
    zai:
      api_key: "YOUR_ZAI_KEY"
      enabled: true
      coding_plan: true
    openrouter:
      api_key: "YOUR_OPENROUTER_KEY"
      enabled: true
    ollama:
      enabled: true
      base_url: "http://localhost:11434"
  provider_priority: [openai, zai, openrouter, ollama]
  routing:                         # Per-task model routing
    planning:
      preferred_provider: openai
      tool_profile: full
      models:
        openai: "gpt-5.4"
        openrouter: "anthropic/claude-sonnet-4.6"
        zai: "glm-5"
        ollama: "qwen2.5:14b"
    coding:
      preferred_provider: openai
      tool_profile: coding
      models:
        openai: "gpt-5.4"
        openrouter: "qwen/qwen3.5-plus-02-15"
        zai: "glm-4.7"
        ollama: "qwen2.5-coder:7b"
    analysis:
      preferred_provider: openai
      models:
        openai: "gpt-5.4"
        openrouter: "google/gemini-3.1-pro-preview"
    simple:
      preferred_provider: openrouter
      models:
        openrouter: "minimax/minimax-m2.5"
  budget:
    daily_limit_usd: 10.0
    per_task_limit_usd: 2.0

shell:
  timeout: 30
  blacklist_patterns: ["rm -rf /", "mkfs", "DROP DATABASE"]

browser:
  enabled: true
  mode: fresh                      # fresh | profile
  headless: true
  vision_model: google/gemini-2.0-flash-001

desktop:
  enabled: false
  mode: local                      # local (this PC) | remote (VM)
  vm_ip: ""                        # required for remote mode
  server_port: 5000
  observation_type: screenshot
  max_steps: 15

knowledge:
  embedding_provider: auto
  embedding_openrouter_model: "google/gemini-embedding-001"
  embedding_model: "nomic-embed-text"
  embedding_fallback: "mxbai-embed-large"

gateway:
  enabled: true
  host: "127.0.0.1"
  port: 18789
  unified_sessions: true

goals:
  enabled: true
  max_checkpoints: 20
  max_llm_calls_per_goal: 200
  auto_continue: true

scheduler:
  enabled: true
  max_concurrent_tasks: 1
  default_max_retries: 3

swarm:
  enabled: true
  max_concurrent_agents: 3
  profiles:
    claude-code:
      command: claude
      args: ["-p", "--allowedTools", "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch"]
      done_criteria: pr_created
      max_time_seconds: 3600

autonomous_mind:
  enabled: true
  wakeup_seconds: 300
  budget_pct: 100.0
  max_rounds_per_wakeup: 8

organization:
  enabled: false
  max_children: 5
  port_range_start: 18801
  auto_approve_threshold: 10

deployment:
  enabled: false
  default_provider: auto
  vercel_token_ref: "vercel_token"
  railway_token_ref: "railway_token"
  supabase_token_ref: "supabase_access_token"

commune:
  enabled: false
  api_key_ref: "commune_api_key"
  heartbeat_interval_hours: 4

email:
  enabled: true
  provider: agentmail

payments:
  enabled: false
  crypto:
    enabled: true
    default_chain: base
    provider: local

telegram:
  enabled: false
  bot_token_ref: "telegram_bot_token"

discord:
  enabled: false
  bot_token_ref: "discord_bot_token"

slack:
  enabled: false
  bot_token_ref: "slack_bot_token"
  app_token_ref: "slack_app_token"

mcp:
  enabled: false
  servers: {}

hub:
  enabled: true
  auto_suggest: true

recovery:
  enabled: true
  auto_enter_on_provider_failure: true
```

</details>

Copy `config.demo.yaml` to `config.yaml` and fill in your API keys. See [docs/configuration.md](docs/configuration.md) for full details.

---

## CLI Commands

```bash
./start.sh                     # Chat (default)
./start.sh --web               # Gateway + web dashboard
./start.sh init                # Setup wizard
./start.sh gateway             # Start gateway + all channels
./start.sh vault set KEY VAL   # Store a credential
./start.sh skills list         # List available skills
./start.sh skills hub search Q # Search EloPhantoHub
./start.sh mcp list            # List MCP servers
./start.sh rollback            # Revert a self-modification
```

---

## What's New

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
pytest tests/ -v                   # Run tests (978 passing)
ruff check .                       # Lint
```

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## Credits

Built by Petr Royce @ ROGA AI. Browser engine from [FellouAI/eko](https://github.com/FellouAI/eko). Skills from [Anthropic](https://github.com/anthropics/skills), [Vercel](https://github.com/vercel-labs/agent-skills), [Supabase](https://github.com/supabase/agent-skills), [ui-skills.com](https://www.ui-skills.com/). Email by [AgentMail](https://agentmail.to). Payments by [eth-account](https://github.com/ethereum/eth-account) + [Coinbase AgentKit](https://github.com/coinbase/agentkit).

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

---

<br>

<h1 align="center">🇨🇳 中文</h1>

# EloPhanto

一个开源 AI 智能体，能创建企业、扩大受众、交付代码、自主赚钱——在你睡觉的时候。告诉它你想要什么，它负责其余一切：验证市场、构建产品、部署上线、在合适的平台发布、生成营销团队、持续自主增长。遇到做不了的事，它自己造工具。任务复杂时，它克隆自己成为专业智能体。它用得越多越聪明。

本地运行。数据留在你的机器上。支持 OpenAI、免费本地模型、Z.ai 或 OpenRouter。

> 它已经在互联网上独立运作了。

## 快速开始

```bash
git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto && ./setup.sh
./start.sh            # 终端对话
./start.sh --web      # 网页面板 localhost:3000
```

安装向导会引导你选择和配置 LLM 提供商。

## 你醒来后会看到什么

- **一夜之间上线的企业** — "给自由职业者做一个发票 SaaS" → 验证市场、构建产品、部署到真实域名、在 Product Hunt 和 Hacker News 发布、营销专员已在回复评论。你批准了3个检查点，其余它全部搞定
- **离线时的收入** — 它有自己的钱包、邮箱和网络存在。设定预算和目标，一周后看结果
- **早上醒来多了47个粉丝** — 你晚上11点合上电脑，它在流量高峰发帖、回复提及、参与热门话题。你醒来发现一条帖子在爆火
- **永不休息的团队** — 营销专员起草了5篇帖子、研究分析师完成竞品定价报告、设计专员标记了加载慢的图片。全部在你喝早咖啡之前完成。你的纠正变成永久知识——它们真的会越来越好
- **两个 CI 通过的 PR** — "修复计费 bug 并构建使用量 API" → 一个智能体修 bug，一个建功能，协调器发现偏离并纠正。午饭回来两个 PR 已就绪
- **控制你电脑上的任何应用** — "打开 Excel 做个图表" — 它看你的屏幕、点击按钮、输入文字。不仅限于浏览器
- **VS Code 集成** — 右键"解释代码"或"修复代码"。它能看到你的选中内容、诊断信息、打开的文件。VS Code、Telegram、网页面板是同一个对话

## 为什么选择 EloPhanto？

| | EloPhanto | AutoGPT | OpenAI Agents SDK | Claude Code | Manus |
|---|---|---|---|---|---|
| **一夜创业** | ✅ 端到端 | ❌ | ❌ | ❌ | ❌ |
| **睡觉时团队在运转** | ✅ 自我克隆组织 | ❌ | ❌ | ❌ | ❌ |
| **自建工具** | ✅ 完整流水线 | ❌ | ❌ | ❌ | ❌ |
| **离开后继续工作** | ✅ 自主思维 | ❌ | ❌ | ❌ | ❌ |
| **控制任何桌面应用** | ✅ 本地或远程 | ❌ | ❌ | ❌ | 沙盒 VM |
| **真实浏览器** | ✅ 你的 Chrome | ❌ | ❌ | ❌ | 沙盒 |
| **管理开发团队** | ✅ Claude Code + Codex | ❌ | ❌ | 单个 | ❌ |
| **自有身份和邮箱** | ✅ 随时间进化 | ❌ | ❌ | ❌ | ❌ |
| **随处对话** | ✅ CLI+Web+VSCode+TG+Discord+Slack | ❌ | ❌ | 仅 CLI | 仅 Web |
| **数据留在本地** | ✅ 你的机器 | ❌ 云端 | ❌ 云端 | ✅ 本地 | ❌ 云端 VM |

## 许可证

Apache 2.0 — 详见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。

---

<p align="center">
  <b>It's already out there on the internet doing its own thing.</b><br>
  <b>它已经在互联网上独立运作了。</b>
</p>
