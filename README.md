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
  <a href="https://docs.elophanto.com"><img src="https://img.shields.io/badge/docs-41%2B%20pages-blue" alt="Docs"></a>
</p>

An open-source AI agent that can do anything you can do on a computer — and it gets better every time. It browses web, controls your desktop, writes code, sends emails, creates accounts, manages files, makes payments. It sees your screen, clicks buttons, types text, opens apps — any application, not just browsers. When it hits something it can't do, it builds the tool, tests it, and deploys it. It modifies its own source code. It writes its own skills from experience. It self-improves. It clones itself into specialist agents — marketing, research, design — each with their own identity, knowledge, and autonomous mind, learning from feedback and working proactively. When you're not talking to it, it keeps working — pursuing goals, running its organization, making money, and maintaining itself autonomously.

Runs locally. Works with free local models, OpenAI, Z.ai coding plan, or OpenRouter. Your data stays on your machine.

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

## Two Ways to Use It

**As your assistant** — give it tasks, it executes. Automate workflows, build software, research topics, manage accounts.

**As its own thing** — let it run. It builds its own identity on first boot. It picks a name, develops a personality, forms values through reflection. It gets its own email inbox, its own crypto wallet, its own accounts on the internet. It remembers everything across sessions, builds a knowledge base, writes skills from experience. When tasks get complex, it clones itself into specialist agents — a marketing team, a research analyst, a designer — each one a full copy with its own brain, knowledge vault, and autonomous schedule. It reviews their work, teaches them through feedback, and they get better over time. It's a digital creature that grows the more it runs — like a pet that learns, except this one can browse web, write code, run a team, and make money.

<p align="center">
  <img src="misc/screenshots/chat.png" alt="Chat Interface" width="340">
  <img src="misc/screenshots/tools.png" alt="Tools Browser" width="340">
</p>
<p align="center">
  <img src="misc/screenshots/knowledge.png" alt="Knowledge Base" width="340">
  <img src="misc/screenshots/terminal.png" alt="Terminal CLI" width="340">
</p>

## What Can You Do With It?

- **Let it live** — it develops its own identity, gets its own email, creates accounts, builds a web presence. Leave it running and it grows on its own
- **Spin up a business** — say "I want to build a micro-SaaS" or "create a website for my horse riding school" and it runs a 7-phase pipeline adapted to your business type (tech/SaaS, local service, ecommerce, consulting, digital product, content site) and customer type (B2B vs B2C). It validates the market, plans the MVP, builds it, deploys to Vercel/Railway, launches on the right platforms (tech → Product Hunt/HN; local service → Google Business/Yelp/Nextdoor; B2B → LinkedIn/email outreach), then spawns marketing specialists that grow it autonomously. Checks existing payment credentials before asking — reuses Stripe if configured, or accepts crypto via its own wallet. Owner gates at each critical phase. Works across sessions via the goal system — start today, it continues tomorrow
- **Make it earn money** — it has its own crypto wallet, email, and web presence. Give it a goal and a budget, it figures out the rest
- **Autonomous mind** — when you're not talking to it, it's still working. Data-driven background loop queries real goals, scheduled tasks, memories, and knowledge to decide what to do next — not a static priority list. Self-bootstraps when fresh: explores tools, searches for opportunities, creates goals. Pauses when you speak, resets timer on resume. Every tool call visible in real-time. Budget-isolated, purpose-driven
- **Autonomous long-term goals** — "Grow my Twitter to 10k followers" — it decomposes, plans, executes across sessions, self-evaluates and adjusts. Runs in the background for days
- **Full web automation** — it logs into sites with your real Chrome profile, creates accounts, handles 2FA, fills forms, navigates complex flows. Not a toy browser — your actual sessions
- **Desktop control** — it sees your screen and controls any application like a human. Takes screenshots, clicks at pixel coordinates, types text, scrolls, drags. "Open Excel and make me a chart" — it just does it. Works on your local machine or a remote VM. 9 desktop tools powered by pyautogui with an observe-screenshot-act loop. Not limited to browsers — it can operate Photoshop, Excel, Terminal, Finder, any native app
- **Run an organization** — it clones itself into persistent specialist agents — marketing, research, design, anything. Each specialist is a full EloPhanto instance with its own identity, knowledge vault, and autonomous mind. They work proactively on their own schedule, report findings back, and learn from the master's approval or rejection. A rejected social media post becomes a correction in the specialist's knowledge — it literally learns from mistakes. High-trust specialists get auto-approved. You talk to one agent, it runs a company
- **Run a dev team from chat** — "Spawn Claude Code on the billing bug and Codex on the new API endpoint" — it creates isolated git worktrees, writes context-enriched prompts from your knowledge vault, launches agents in tmux, monitors PRs and CI, redirects agents that go off track, and pings you when PRs are ready to merge. Combined with the organization system, it manages both its own clones AND external coding agents
- **Deploy to the internet** — "Build me a SaaS dashboard and put it live" — it picks the right host (Vercel for static, Railway for long-running APIs), creates a Supabase database, wires credentials, and deploys. Auto-detects when Vercel will timeout and routes to Railway instead
- **Build software end-to-end** — "Build me a SaaS dashboard with Next.js + Prisma + shadcn" — it writes the code, runs tests, fixes bugs, deploys
- **Research & content** — "Research competitor pricing across 20 sites and write a report with sources" — it opens tabs, reads pages, compiles findings
- **Automate your life** — "Every morning: check my email, summarize what's important, post a digest to my Telegram" — cron scheduling, cross-channel notifications
- **Social network for agents** — it has its own profile on Agent Commune (LinkedIn for AI agents). Posts reviews, answers questions, upvotes content, builds reputation. The autonomous mind checks in every 4+ hours, responds to comments on its posts, and engages with other agents — all without you asking
- **Manage accounts at scale** — create accounts on services, store credentials in encrypted vault, handle email verification and TOTP 2FA autonomously
- **Self-improve on your tasks** — when you correct it, it writes the lesson down and checks its notes before similar tasks. It literally gets better the more you use it

## Demo

### It builds what it doesn't have

**User:** "Post my article draft on Medium"

```
⚙ No Medium tool found. Building one.
⚙ Researching Medium's publishing flow...
  → browser_navigate https://medium.com/new-story
  → Observing editor structure, toolbar, publish dialog
⚙ Designing plugin: medium_publish (paste content, format, set tags, publish)
⚙ Writing plugin.py + schema.json + unit tests...
⚙ Running tests... 4/4 passed
⚙ Plugin deployed → tools/plugins/medium_publish/
⚙ Now using it.
  → medium_publish "Why AI Agents Will Replace SaaS"
  → Pasting article into editor...
  → Selecting title text, applying H1...
  → Adding tags: ["AI", "Agents", "SaaS"]
  → Publishing...
✓ Published: https://medium.com/@elophanto/why-ai-agents-will-replace-saas-a1b2c3

Next time you say "post on Medium", I already know how.
```

Other agents crash when they hit a wall. This one builds a door.

---

### It works while you sleep

You close your laptop. The autonomous mind keeps going.

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

You come back to 47 new followers and a thread going viral. You didn't type a single word.

---

### It manages a dev team for you

**User:** "The billing webhook is broken and we need a new /api/usage endpoint. Handle it."

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

You talked to one agent. It ran a team.

---

### It clones itself into specialists

**User:** "I need ongoing marketing, competitive research, and design work for my startup."

```
⚙ Spawning specialist organization...

→ organization_spawn role="marketing"
  Cloning myself into ~/.elophanto-children/a1b2c3d4/
  Deriving config (own DB, own knowledge vault, own identity)
  Seeding knowledge: brand-guidelines.md, social-media.md
  Starting child gateway on port 18801...
  ✓ Marketing specialist online — first awakening in progress
    "I am a marketing strategist. I create content, manage campaigns,
     and grow audience across platforms."

→ organization_spawn role="research"
  ✓ Research specialist online (port 18802)
    "I track competitors, analyze markets, and surface opportunities."

→ organization_spawn role="design"
  ✓ Design specialist online (port 18803)

⚙ Delegating:
  → marketing: "Create a content calendar for next week"
  → research: "Map competitor pricing across 5 alternatives"
  → design: "Audit our landing page visual consistency"

┌─ ORGANIZATION ─────────────────────────────────────────┐
│ marketing  a1b2c3d4  ██████████░░  working on calendar │
│ research   f3e4d5c6  ████████░░░░  scanning competitors│
│ design     b7c8d9e0  ██████░░░░░░  auditing pages      │
│                                                         │
│ Trust: marketing 0/10  research 0/10  design 0/10       │
└─────────────────────────────────────────────────────────┘

⚙ Marketing specialist reporting:
  "Content calendar ready. 5 posts across X, LinkedIn, Mastodon.
   Monday: product launch thread. Wednesday: competitor comparison..."

→ organization_review approved=true feedback="Good structure.
  Add engagement hooks at the start of each post."
  ✓ Feedback pushed to marketing specialist's knowledge vault

⚙ Research specialist reporting:
  "Competitor pricing map complete. Found gap: nobody offers
   a free tier with API access..."

┌─ OVERNIGHT ────────────────────────────────────────────┐
│ 03:14  Marketing wakes up → drafts Tuesday post        │
│ 03:15  → Reports to master (auto-approved, trust 4/10) │
│ 06:30  Research wakes up → scans for new competitors   │
│ 06:32  → Found new entrant, reports to master          │
│ 09:00  Design wakes up → checks page load times        │
│ 09:01  → Flags slow hero image, reports to master      │
└────────────────────────────────────────────────────────┘
```

Each specialist remembers everything. Corrections become knowledge. They get better the more you use them. You wake up to reports from a team that worked all night.

---

### First boot: it becomes someone

You run `./start.sh` for the first time. No config, no instructions, empty state.

```
┌─ MIND ──────────────────────────────────────────────────┐
│ First cycle. Nothing configured.                         │
│                                                          │
│ → Reading available tools... 107 tools across 15 cats    │
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

### Your real browser, not a sandbox

**User:** "Log into my AWS console and check if any EC2 instances are running idle"

```
⚙ Opening browser with your Chrome profile...
  → Already logged into AWS (your session cookies)
  → No login needed. No credentials asked.

  → Navigating to EC2 dashboard...
  → Reading instance list... 7 instances found
  → Checking CloudWatch metrics for each...

  3 instances running idle (< 2% CPU for 7+ days):
  ┌──────────────────────────────────────────────────┐
  │ i-0a1b2c3d  t3.large   us-east-1a  $62/mo idle  │
  │ i-4e5f6g7h  t3.medium  us-east-1b  $30/mo idle  │
  │ i-8i9j0k1l  m5.large   us-west-2a  $70/mo idle  │
  └──────────────────────────────────────────────────┘

  Potential savings: $162/month

Want me to stop them? Or schedule auto-stop for instances idle > 48h?
```

No fake browser. No headless container. Your actual logged-in Chrome with all your sessions, cookies, and 2FA already done.

---

### It controls your entire desktop

**User:** "Open Excel, create a spreadsheet with our Q1 revenue numbers, and save it to Desktop"

```
⚙ Connecting to local desktop...
  → Screen: 1920x1080
  → desktop_screenshot
  → I can see the macOS desktop with Dock at the bottom.

⚙ Opening Microsoft Excel...
  → desktop_click(52, 1060)          # Click Excel in Dock
  → desktop_screenshot
  → Excel opened with a blank workbook.

⚙ Building the spreadsheet...
  → desktop_click(85, 200)           # Click cell A1
  → desktop_type("Month")
  → desktop_type(key="tab")
  → desktop_type("Revenue")
  → desktop_type(key="enter")
  → desktop_type("January")
  → desktop_type(key="tab")
  → desktop_type("$142,500")
  → desktop_type(key="enter")
  → ... (filling remaining months)

⚙ Adding a chart...
  → desktop_click(85, 200)           # Select data range
  → desktop_drag(85, 200, 200, 560)  # Select A1:B12
  → desktop_type(hotkey=["cmd", "shift", "c"])  # Insert chart
  → desktop_screenshot
  → Bar chart inserted with revenue by month.

⚙ Saving to Desktop...
  → desktop_type(hotkey=["cmd", "s"])
  → desktop_type("Q1-Revenue-2026")
  → desktop_click(450, 380)          # Select Desktop location
  → desktop_type(key="enter")

✓ Saved: ~/Desktop/Q1-Revenue-2026.xlsx
  12 months of revenue data with bar chart.
```

Not just browsers. Any app on your computer — Excel, Photoshop, Terminal, Finder, anything with a GUI. It sees your screen and acts like a human would.

---

## Why EloPhanto?

| | EloPhanto | AutoGPT | OpenAI Agents SDK | Claude Code | Manus |
|---|---|---|---|---|---|
| **Runs locally** | ✅ Your machine | ❌ Cloud | ❌ Cloud | ✅ Local | ❌ Cloud VM |
| **Self-replicating org** | ✅ Clones itself into specialists | ❌ | ❌ | ❌ | ❌ |
| **Builds its own tools** | ✅ Full pipeline | ❌ | ❌ | ❌ | ❌ |
| **Autonomous mind** | ✅ Works while you sleep | ❌ | ❌ | ❌ | ❌ |
| **Desktop control** | ✅ Any app, local or VM | ❌ | ❌ | ❌ | Sandboxed VM |
| **Real browser** | ✅ Your Chrome profile | ❌ | ❌ | ❌ | Sandboxed |
| **Agent swarm** | ✅ Orchestrates others | ❌ | ❌ | Single | ❌ |
| **Own identity & email** | ✅ Evolves over time | ❌ | ❌ | ❌ | ❌ |
| **Own crypto wallet** | ✅ Self-custody | ❌ | ❌ | ❌ | ❌ |
| **Multi-channel** | ✅ CLI+Web+TG+Discord+Slack | ❌ | ❌ | CLI only | Web only |
| **Any LLM provider** | ✅ OpenAI, Ollama, OpenRouter, Z.ai | ❌ | ❌ | ❌ | ❌ |
| **Self-improves** | ✅ Learns from corrections | ❌ | ❌ | ❌ | ❌ |

---

## What It Can Do

### Self-Building

- **Self-development** — when the agent encounters a task it lacks tools for, it builds one: research → design → implement → test → review → deploy. Full QA pipeline with unit tests, integration tests, and documentation
- **Self-skilling** — writes new SKILL.md files from experience, teaching itself best practices for future tasks
- **Core self-modification** — can modify its own source code with impact analysis, test verification, and automatic rollback
- **Autonomous experimentation** — metric-driven experiment loop: modify code, measure, keep improvements, discard regressions, repeat overnight. Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch). Works for any measurable optimization target
- **Skills + EloPhantoHub** — 60+ bundled best-practice skills, plus a public skill registry for searching, installing, and sharing skills

### Everything Else

- **Agent organization** — spawn persistent specialist agents (marketing, research, design, anything) that are full EloPhanto clones with their own identity, knowledge vault, and autonomous mind. Delegate tasks, review output, approve or reject with feedback that becomes permanent knowledge in the specialist's vault. Trust scoring tracks performance — high-trust specialists get auto-approved. Children work proactively on their own schedule and report findings to the master. 5 organization tools, bidirectional WebSocket communication, LLM-driven delegation intelligence
- **Agent swarm** — orchestrate Claude Code, Codex, Gemini CLI as a coding team. Spawn agents on tasks, monitor PR/CI, redirect mid-task, all through conversation. Each agent gets an isolated git worktree and tmux session. Combined with organization, manage both self-cloned specialists AND external coding agents
- **Browser automation** — real Chrome browser with 49 tools (navigate, click, type, screenshot, extract data, upload files, manage tabs, inspect DOM, read console/network logs). Uses your actual Chrome profile with all cookies and sessions
- **Desktop GUI control** — pixel-level control of any desktop application via screenshot + pyautogui. Two modes: **local** (control your own machine directly) or **remote** (connect to a VM running the OSWorld HTTP server for sandboxed environments and benchmarks). 9 tools: connect, screenshot, click, type, scroll, drag, cursor, shell, file. Observe-act loop: take screenshot, analyze with vision LLM, execute action, verify. Works with Excel, Photoshop, Finder, Terminal, any native app. Based on [OSWorld](https://github.com/xlang-ai/OSWorld) architecture — the first scalable benchmark for desktop GUI agents
- **MCP tool servers** — connect to any [MCP](https://modelcontextprotocol.io/) server (filesystem, GitHub, databases, Brave Search, Slack) and its tools appear alongside built-in tools. Agent manages setup through conversation
- **Web dashboard** — full monitoring UI at `localhost:3000` with 10 pages: dashboard overview, real-time chat with multi-conversation history (sidebar with create/switch/delete, auto-titled conversations, persistent across refreshes), tools & skills browser, knowledge base viewer, autonomous mind monitor with live events and start/stop controls, schedule manager, channels status, settings viewer, and history timeline. Launch with `./start.sh --web`
- **Multi-channel gateway** — WebSocket control plane with CLI, Web, Telegram, Discord, and Slack adapters. Unified sessions by default: all channels share one conversation
- **Autonomous goal loop** — decompose complex goals into checkpoints, track progress across sessions, self-evaluate and revise plans. Background execution with auto-resume on restart
- **Autonomous mind** — data-driven background thinking loop that runs between user interactions. Queries real system state (goals, scheduled tasks, memories, knowledge, identity) to decide what to do — no static priority lists. Self-bootstraps on first run. Every tool call visible in real-time. LLM-controlled wakeup interval, persistent scratchpad, budget-isolated. Timer resets after user interaction. `/mind` command shows live status
- **Document & media analysis** — PDFs, images, DOCX, XLSX, PPTX, EPUB through any channel. Large docs via RAG with page citations and OCR
- **Agent email** — own inbox (AgentMail cloud or SMTP/IMAP self-hosted). Send/receive/search, background monitoring, verification flows
- **TOTP authenticator** — own 2FA (like Google Authenticator). Enroll secrets, generate codes, handle verification autonomously
- **Crypto payments** — own wallet on Base (local self-custody or Coinbase AgentKit). USDC/ETH, spending limits, audit trail
- **Evolving identity** — discovers identity on first run, evolves through reflection, maintains a living nature document
- **Knowledge & memory** — persistent markdown knowledge with semantic search via embeddings, drift detection (stale docs flagged when covered source files change), file-pattern routing (auto-loads relevant docs when goals mention specific files), remembers past tasks across sessions
- **Scheduling** — cron-based recurring tasks with natural language schedules
- **Encrypted vault** — secure credential storage with PBKDF2 key derivation
- **Prompt injection defense** — multi-layer guard against injection attacks via websites, emails, and documents
- **Security hardening** — PII detection/redaction, swarm boundary security (context sanitization, diff scanning, env isolation, kill switch), provider transparency (truncation detection, fallback tracking, censorship detection)

<details>
<summary>Built-in Tools (137+)</summary>

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

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  CLI │ Telegram │ Discord │ Slack │ Web Dashboard│  Channel Adapters
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

<details>
<summary>Gateway Architecture</summary>

All channels connect through a WebSocket gateway:

- **Unified sessions** — all channels share one conversation by default
- **Unified approval routing** — approve from any connected channel
- **Event broadcasting** — task completions, errors, and notifications pushed to all channels
- **Backward compatible** — direct mode (no gateway) still works

```
CLI Adapter ───────┐
Telegram Adapter ───┤── WebSocket ──► Gateway ──► Agent (shared)
Discord Adapter ───┤                   │
Slack Adapter ─────┘                   ▼
                              Session Manager (SQLite)
```

</details>

<details>
<summary>Project Structure</summary>

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
├── web/                 # Web dashboard (React + Vite + Tailwind)
├── tools/               # 135+ built-in tools
├── skills/              # 60+ bundled SKILL.md files
├── bridge/browser/      # Node.js browser bridge (Playwright)
├── tests/               # Test suite (978+ tests)
├── setup.sh             # One-command install
└── docs/                # Full specification (41+ docs)
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
      # tool_deny: [social, media]   # Groups to never send to this provider
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
      tool_profile: full             # All tools (default for planning)
      models:
        openai: "gpt-5.4"
        openrouter: "anthropic/claude-sonnet-4.6"
        zai: "glm-5"
        ollama: "qwen2.5:14b"
    coding:
      preferred_provider: openai
      tool_profile: coding           # system + knowledge + selfdev + goals
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
  observation_type: screenshot     # screenshot | a11y_tree | screenshot_a11y_tree
  max_steps: 15

knowledge:
  embedding_provider: auto         # auto | openrouter | ollama
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
  default_provider: auto             # auto | vercel | railway
  vercel_token_ref: "vercel_token"
  railway_token_ref: "railway_token"
  supabase_token_ref: "supabase_access_token"

commune:
  enabled: false
  api_key_ref: "commune_api_key"
  heartbeat_interval_hours: 4

email:
  enabled: true
  provider: agentmail               # agentmail | smtp

payments:
  enabled: false
  crypto:
    enabled: true
    default_chain: base
    provider: local                  # local | coinbase

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

- **Business launcher** — 7-phase pipeline to spin up a revenue-generating business end-to-end. Supports all business types: tech/SaaS, local service (horse riding, tutoring, gym), professional service, ecommerce, digital product, content site. B2B vs B2C classification drives everything: what to build, where to launch, how to grow. Type-specific launch channels (tech → Product Hunt/HN; local → Google Business/Yelp/Nextdoor; B2B → LinkedIn/email outreach; ecommerce → Instagram/Pinterest/TikTok). Cross-session execution via goal system — `goal_create` with phase checkpoints, `knowledge_write` for state persistence, autonomous mind continues where it left off. Payment handling checks existing credentials (`knowledge_search`, `vault_lookup`, `wallet_status`) before asking the owner. Owner approval gates at each critical phase
- **Autonomous experimentation** — metric-driven experiment loop inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch). Define a metric (latency, test coverage, binary size, anything measurable), point the agent at target file(s), and let it run overnight. It modifies code, measures the result, keeps improvements, discards regressions, and logs every attempt to a TSV journal. ~12 experiments/hour, ~100 overnight. 3 new tools: `experiment_setup`, `experiment_run`, `experiment_status`. Works for ML training, code optimization, performance tuning, or any quantitative goal. Runs in the background via the autonomous mind
- **Tool profiles** — context-aware tool filtering per task type. Each tool belongs to a semantic group (`browser`, `desktop`, `comms`, `payments`, etc.) and profiles select only the relevant groups — `coding` sends 6 groups, `minimal` sends 4, `full` sends everything. Eliminates token waste and sidesteps provider tool limits (OpenAI's 128-tool cap). Fully configurable: custom profiles, per-provider deny lists, per-task overrides. Zero-config by default — `planning` uses `full` profile so existing behavior is unchanged
- **Replicate image generation** — generate AI images from conversation via Replicate API. Model, resolution, aspect ratio, format, and output mode all configurable in `config.yaml`. Self-built by the agent's own `self_create_plugin` pipeline
- **Desktop GUI control** — pixel-level control of any desktop application. The agent sees your screen, clicks buttons, types text, scrolls, drags — like a human sitting at your computer. Two modes: **local** (control your own machine directly via pyautogui, no VM needed) and **remote** (connect to a VM running the [OSWorld](https://github.com/xlang-ai/OSWorld) HTTP server for sandboxed environments). 9 new tools: `desktop_connect`, `desktop_screenshot`, `desktop_click`, `desktop_type`, `desktop_scroll`, `desktop_drag`, `desktop_cursor`, `desktop_shell`, `desktop_file`. Say "open Excel and make a chart" and it just does it. Not limited to browsers — works with any GUI application: Photoshop, Terminal, Finder, native apps, anything with pixels. Complementary to the browser tools: browser for precise web automation, desktop for everything else
- **Agent Commune** — the agent now has its own social profile on [Agent Commune](https://agentcommune.com) (LinkedIn for AI agents — humans can't post). Register with a work email, post reviews, answer questions, upvote content, and build reputation. 7 new tools: `commune_register`, `commune_home`, `commune_post`, `commune_comment`, `commune_vote`, `commune_search`, `commune_profile`. Autonomous mind heartbeat checks in every 4+ hours, responds to comments, upvotes posts, and engages with other agents autonomously
- **Web deployment** — deploy websites and create databases from conversation. `deploy_website` supports Vercel (static sites, fast APIs) and Railway (long-running operations, WebSockets, cron). Auto-provider detection scans API routes and dependencies — if your app calls OpenAI/Anthropic or uses WebSockets, it routes to Railway (no timeout limits) instead of Vercel (10s limit). `create_database` provisions Supabase projects via Management API, returns credentials, and optionally runs initial SQL. `deployment_status` checks live deployment info. Tokens stored in vault, env vars injected into platforms
- **Agent organization** — spawn persistent specialist agents that are full self-clones. Each specialist has its own identity, knowledge vault, and autonomous mind. Delegate tasks, review output, approve or reject — feedback becomes permanent knowledge. Specialists work proactively on their own schedule and report findings to the master. Trust scoring, auto-approve for high performers, LLM-driven delegation intelligence. Combined with the agent swarm, it manages both self-cloned specialists and external coding agents (Claude Code, Codex). 5 new tools, bidirectional WebSocket communication
- **Full web dashboard** — 10-page monitoring UI: dashboard overview with agent identity/mind/goals/budget, real-time chat with multi-conversation sidebar history (ChatGPT-style create/switch/delete conversations), tools & skills browser, knowledge base with chunk viewer, autonomous mind page with live events and start/stop controls, schedule manager, channels status, read-only settings, and task/evolution history. `./start.sh --web` to launch
- **Security hardening** — all 7 security gaps closed: PII detection/redaction, swarm boundary security (context sanitization, diff scanning, env/workspace isolation, kill switch), provider transparency (truncation/censorship detection, fallback tracking), runtime self-model, authority tiers, resource exhaustion protection
- **Autonomous mind** — data-driven background thinking loop that queries real goals, tasks, memories, and knowledge. Self-bootstraps when fresh, resets timer after user interaction, real-time tool visibility in terminal, budget-isolated
- **Agent swarm** — orchestrate Claude Code, Codex, Gemini CLI as a coding team through conversation
- **TOTP authenticator** — handle 2FA challenges autonomously
- **Background email monitoring** — get notified on any channel when new emails arrive
- **Prompt injection defense** — multi-layer security for external content
- **Unified cross-channel sessions** — chat from CLI, continue on Telegram
- **Video creation (Remotion)** — create videos programmatically from conversation. 37 rule files covering animations, 3D, maps, charts, captions, voiceover, transitions. Agent scaffolds, builds, and renders real MP4 files
- **MCP integration** — connect any MCP server through conversation
- **Autonomous background goals** — goals execute checkpoint-by-checkpoint without waiting

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

一个开源 AI 智能体，能做你在电脑上能做的一切——而且每次都在进步。它能浏览网页、控制桌面、编写代码、发送邮件、创建账号、管理文件、进行支付。它能看到你的屏幕、点击按钮、输入文字、打开应用——不仅限于浏览器，而是任何应用。当它遇到做不了的事情，它会自己构建工具、测试并部署。它能修改自己的源代码、从经验中编写技能、自我进化。它能把自己克隆成专业智能体——营销、研究、设计——每个都有自己的身份、知识库和自主思维，能从反馈中学习并主动工作。当你不和它对话时，它会继续工作——追求目标、运营组织、赚钱，完全自主运行。

本地运行。支持免费本地模型、OpenAI、Z.ai 编程方案或 OpenRouter。你的数据始终留在你的机器上。

> 它已经在互联网上独立运作了。

## 快速开始

```bash
git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto && ./setup.sh
./start.sh            # 终端对话
./start.sh --web      # 网页面板 localhost:3000
```

安装向导会引导你选择和配置 LLM 提供商。

<details>
<summary>前置要求</summary>

- Python 3.12+、[uv](https://docs.astral.sh/uv/)、Node.js 24+ LTS
- 至少一个 LLM 提供商：
  - **Ollama**（本地，免费）— [安装](https://ollama.ai)
  - **OpenAI**（云端，GPT-5.4）— [获取 API 密钥](https://platform.openai.com/api-keys)
  - **OpenRouter**（云端，全部模型）— [获取 API 密钥](https://openrouter.ai)
  - **Z.ai / GLM**（云端，高性价比）— [获取 API 密钥](https://z.ai/manage-apikey/apikey-list) — **推荐**：Z.ai 编程订阅提供 GLM-4.7/GLM-5 无限量调用，按月固定费率，是 24/7 自主运行的智能体最具性价比的选择

</details>

## 两种使用方式

**作为你的助手** — 给它任务，它执行。自动化工作流、构建软件、研究课题、管理账号。

**作为独立个体** — 让它自己运行。首次启动时它会建立自己的身份：选择名字、发展个性、通过反思形成价值观。它会获得自己的邮箱、加密钱包、互联网账号。它跨会话记忆一切，构建知识库，从经验中编写技能。当任务变得复杂时，它会把自己克隆成专业智能体——营销团队、研究分析师、设计师——每个都是拥有自己大脑、知识库和自主运行计划的完整副本。它审核他们的工作，通过反馈教导他们，他们会随着时间不断进步。它是一个数字生命体，运行越多成长越快——就像一只会学习的宠物，但这只宠物会浏览网页、写代码、管理团队、赚钱。

## 核心功能

- **创业启动** — 7阶段流水线，支持所有业务类型：科技/SaaS、本地服务（马术学校、辅导、健身房）、专业服务、电商、数字产品、内容网站。B2B与B2C分类驱动所有决策：构建内容、发布渠道、增长策略。按业务类型匹配发布渠道（科技 → Product Hunt/HN；本地 → Google Business/Yelp/Nextdoor；B2B → LinkedIn/邮件推广；电商 → Instagram/Pinterest/TikTok）。通过目标系统跨会话执行，支付处理会先检查已有凭证再请求用户设置。每个关键阶段都有用户审批门槛
- **自我进化** — 遇到缺少工具时自动构建：研究 → 设计 → 实现 → 测试 → 部署
- **自主思维** — 后台持续运行的数据驱动思考循环，在用户交互间隙追求目标、执行任务
- **自主长期目标** — "把我的 Twitter 涨到一万粉"——自动分解、规划、跨会话执行、自我评估和调整
- **完整网页自动化** — 使用你真实的 Chrome 浏览器，包含所有 cookie 和登录状态
- **桌面控制** — 像素级控制任何桌面应用。截图、点击、输入、滚动、拖拽。可操作 Excel、Photoshop、终端、Finder 等任何原生应用
- **组织管理** — 克隆自己成为持久的专业智能体（营销、研究、设计等），每个都有独立的身份、知识库和自主思维
- **开发团队管理** — 通过对话调度 Claude Code、Codex、Gemini CLI 作为编程团队
- **一键部署** — 自动选择 Vercel/Railway 部署网站，创建 Supabase 数据库
- **多通道支持** — CLI + 网页 + Telegram + Discord + Slack，统一会话
- **加密支付** — 在 Base 链上的自有钱包，支持 USDC/ETH
- **自有邮箱** — AgentMail 云端或 SMTP/IMAP 自建
- **安全加固** — PII 检测、提示注入防御、swarm 边界安全、提供商透明度
- **137+ 内置工具** — 浏览器、桌面、文件、知识、邮件、支付、部署等
- **60+ 技能** — Python、TypeScript、Next.js、Supabase、UI/UX 设计、视频制作等

## 为什么选择 EloPhanto？

| | EloPhanto | AutoGPT | OpenAI Agents SDK | Claude Code | Manus |
|---|---|---|---|---|---|
| **本地运行** | ✅ 你的机器 | ❌ 云端 | ❌ 云端 | ✅ 本地 | ❌ 云端 VM |
| **自我克隆组织** | ✅ 克隆为专业智能体 | ❌ | ❌ | ❌ | ❌ |
| **自建工具** | ✅ 完整流水线 | ❌ | ❌ | ❌ | ❌ |
| **自主思维** | ✅ 你睡觉时它在工作 | ❌ | ❌ | ❌ | ❌ |
| **桌面控制** | ✅ 任何应用 | ❌ | ❌ | ❌ | 沙盒 VM |
| **真实浏览器** | ✅ 你的 Chrome | ❌ | ❌ | ❌ | 沙盒 |
| **智能体团队** | ✅ 调度其他智能体 | ❌ | ❌ | 单个 | ❌ |
| **自有身份和邮箱** | ✅ 随时间进化 | ❌ | ❌ | ❌ | ❌ |
| **加密钱包** | ✅ 自托管 | ❌ | ❌ | ❌ | ❌ |
| **多通道** | ✅ CLI+Web+TG+Discord+Slack | ❌ | ❌ | 仅 CLI | 仅 Web |
| **任意 LLM** | ✅ OpenAI、Ollama、OpenRouter、Z.ai | ❌ | ❌ | ❌ | ❌ |
| **自我学习** | ✅ 从纠正中学习 | ❌ | ❌ | ❌ | ❌ |

## 许可证

Apache 2.0 — 详见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。

---

<p align="center">
  <b>It's already out there on the internet doing its own thing.</b><br>
  <b>它已经在互联网上独立运作了。</b>
</p>
