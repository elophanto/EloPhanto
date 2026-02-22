# EloPhanto

A self-evolving, self-building AI agent. It runs locally as your personal AI operating system — and when it encounters something it can't do, it builds the tool for it. Full self-development pipeline with testing, code review, and deployment. Creates its own skills from experience. Modifies its own source code with automatic rollback.

Also: full system access, real Chrome browser control (47+ tools), MCP tool servers (connect any MCP server — filesystem, GitHub, databases, and more), document & media analysis, skills framework with EloPhantoHub marketplace, multi-channel gateway (CLI, Telegram, Discord, Slack), evolving identity, agent email, crypto payments, encrypted vault, and more.

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Node.js 24+ LTS (for the browser bridge)
- At least one LLM provider:
  - **Ollama** (local, free) — [install](https://ollama.ai)
  - **OpenRouter** (cloud) — [get API key](https://openrouter.ai)
  - **Z.ai / GLM** (cloud, cost-effective coding) — [get API key](https://z.ai/manage-apikey/apikey-list)

### Install

```bash
git clone https://github.com/elophanto/EloPhanto.git
cd EloPhanto
./setup.sh
```

This installs Python dependencies, builds the browser bridge, and sets up the `elophanto` command.

### Run

```bash
./start.sh              # Start chatting (activates venv automatically)
./start.sh gateway      # Start gateway + all enabled channels
./start.sh telegram     # Start Telegram bot (direct mode)
./start.sh vault list   # Any elophanto command
```

Or activate manually and use `elophanto` directly:

```bash
source .venv/bin/activate
elophanto init          # First-time configuration
elophanto chat          # Start chatting
elophanto gateway       # Start multi-channel gateway
```

Give the agent a task in natural language. It plans which tools to use, executes them (with your approval in ask-always mode), and returns results.

## What It Can Do

### Self-Building

- **Self-development** — when the agent encounters a task it lacks tools for, it builds one: research → design → implement → test → review → deploy. Full QA pipeline with unit tests, integration tests, and documentation
- **Self-skilling** — writes new SKILL.md files from experience, teaching itself best practices for future tasks
- **Core self-modification** — can modify its own source code with impact analysis, test verification, and automatic rollback
- **Skills + EloPhantoHub** — 28 bundled best-practice skills loaded before tasks, plus a public skill registry for searching, installing, and sharing skills

### Everything Else

- **MCP tool servers** — connect to any [MCP](https://modelcontextprotocol.io/) server (filesystem, GitHub, databases, Brave Search, Slack, and more) and its tools appear alongside built-in tools. Agent manages setup through conversation — installs SDK, adds servers, tests connections. Also: `elophanto mcp` CLI and init wizard presets
- **Browser automation** — control a real Chrome browser with 47 tools (navigate, click, type, screenshot, extract data, manage tabs, inspect DOM, read console/network logs)
- **Multi-channel gateway** — WebSocket control plane with channel adapters for CLI, Telegram, Discord, and Slack, all with isolated sessions
- **Autonomous goal loop** — decompose complex goals into checkpoints, track progress across sessions, auto-summarize context, self-evaluate and revise plans
- **Document & media analysis** — analyze PDFs, images, DOCX, XLSX, PPTX, EPUB through any channel; small files direct, large documents via RAG with page citations and OCR
- **Agent email** — own email inbox with dual provider support: AgentMail (cloud API, zero config) or SMTP/IMAP (your own server — Gmail, Outlook, etc.). Send/receive/search/reply, identity integration, service signup verification flows
- **Crypto payments** — agent's own wallet on Base with dual provider support: local self-custody wallet (default, zero config) or Coinbase AgentKit (managed custody, gasless, DEX swaps). USDC/ETH transfers, spending limits, full audit trail
- **Evolving identity** — discovers its own identity on first run, evolves personality/values/capabilities through task reflection, maintains a living nature document
- **Knowledge base** — persistent markdown knowledge with semantic search via embeddings (auto-selects OpenRouter for fast cloud embeddings, Ollama as local fallback)
- **Memory** — remembers past tasks across sessions, learns from experience
- **Scheduling** — cron-based recurring tasks with natural language schedules
- **File operations** — read, write, list, delete, move files and directories
- **Shell commands** — execute any command with safety blacklists and approval controls
- **Telegram bot** — full conversational interface from your phone with approval flow, notifications, and slash commands
- **Discord bot** — slash commands, DM/mention support, reaction-based approvals (untested)
- **Slack bot** — app mentions, DM support, thread-based responses (untested)
- **Encrypted vault** — secure credential storage with PBKDF2 key derivation

## Architecture

```
┌─────────────────────────────────────────────────┐
│  CLI │ Telegram │ Discord │ Slack │ Web (planned)│  Channel Adapters
├─────────────────────────────────────────────────┤
│         WebSocket Gateway (ws://:18789)          │  Control Plane
├─────────────────────────────────────────────────┤
│         Session Manager (per-user isolation)     │  Session Layer
├─────────────────────────────────────────────────┤
│            Permission System                     │  Safety & Control
├─────────────────────────────────────────────────┤
│        Self-Development Pipeline                 │  Evolution Engine
├─────────────────────────────────────────────────┤
│   Tool System (95+ built-in + MCP + plugins)      │  Capabilities
├─────────────────────────────────────────────────┤
│   Agent Core Loop (plan → execute → reflect)     │  Brain
├─────────────────────────────────────────────────┤
│ Memory│Knowledge│Skills│Identity│Email│Payments│  Foundation
├─────────────────────────────────────────────────┤
│              EloPhantoHub Registry               │  Skill Marketplace
└─────────────────────────────────────────────────┘
```

### Gateway Architecture

All channels connect through a WebSocket gateway, providing:

- **Session isolation** — each user/channel gets independent conversation history
- **Unified approval routing** — approve from any connected channel
- **Event broadcasting** — task completions, errors, and notifications pushed to all channels
- **Backward compatible** — direct mode (no gateway) still works for CLI and Telegram

```
CLI Adapter ──────┐
Telegram Adapter ──┤── WebSocket ──► Gateway ──► Agent (shared)
Discord Adapter ───┤                   │
Slack Adapter ─────┘                   ▼
                              Session Manager (SQLite)
```

## Built-in Tools

| Category | Tools | Count |
|----------|-------|-------|
| System | shell_execute, file_read, file_write, file_list, file_delete, file_move | 6 |
| Browser | navigate, click, type, screenshot, extract, scroll, tabs, console, network, storage, cookies, drag, hover, wait, eval, audit + more | 47 |
| Knowledge | knowledge_search, knowledge_write, knowledge_index, skill_read, skill_list | 5 |
| Hub | hub_search, hub_install | 2 |
| Self-Dev | self_create_plugin, self_modify_source, self_rollback, self_read_source, self_run_tests, self_list_capabilities | 6 |
| Data | llm_call, vault_lookup, vault_set | 3 |
| Documents | document_analyze, document_query, document_collections | 3 |
| Goals | goal_create, goal_status, goal_manage | 3 |
| Identity | identity_status, identity_update, identity_reflect | 3 |
| Email | email_create_inbox, email_send, email_list, email_read, email_reply, email_search | 6 |
| Payments | wallet_status, payment_balance, payment_validate, payment_preview, crypto_transfer, crypto_swap, payment_history | 7 |
| MCP | mcp_manage (list, add, remove, test, install MCP servers) | 1 |
| Scheduling | schedule_task, schedule_list | 2 |

## Skills System

Skills are best-practice guides (`SKILL.md` files) that the agent reads before starting specific task types. 28 skills ship bundled, covering:

| Category | Skills |
|----------|--------|
| Core | python, typescript-nodejs, browser-automation, file-management, research |
| Development | nextjs, supabase, prisma, shadcn, react-best-practices, composition-patterns, mcp-builder, webapp-testing |
| UI/Design | frontend-design, interface-design, interaction-design, baseline-ui, design-lab, ui-ux-pro-max, wcag-audit-patterns, canvas-design, 12-principles-of-animation, and more |

### Install External Skills

```bash
# From a GitHub repo
elophanto skills install https://github.com/user/repo

# List installed skills
elophanto skills list

# Read a skill's content
elophanto skills read browser-automation
```

Compatible with skill directories like [ui-skills.com](https://www.ui-skills.com/), [anthropics/skills](https://github.com/anthropics/skills), [supabase/agent-skills](https://github.com/supabase/agent-skills), and any repo using the `SKILL.md` convention.

### EloPhantoHub — Skill Registry

Search, install, and update skills from the public EloPhantoHub registry:

```bash
# Search for skills
elophanto skills hub search "gmail automation"

# Install from the registry
elophanto skills hub install gmail-automation

# Update all hub-installed skills
elophanto skills hub update

# List hub-installed skills
elophanto skills hub list
```

The agent can also auto-discover and install hub skills when it encounters tasks without relevant local skills.

All hub skills pass through a 7-layer security pipeline: publisher verification, automated CI scanning, human review, SHA-256 integrity checksums, content security policy, runtime protection, and incident response. See [docs/19-SKILL-SECURITY.md](docs/19-SKILL-SECURITY.md) for the full spec.

## Permission Modes

| Mode | Behavior |
|------|----------|
| `ask_always` | Every tool requires your approval |
| `smart_auto` | Safe tools (read, search, list) auto-approve; risky ones ask |
| `full_auto` | Everything runs autonomously with logging |

Per-tool overrides configurable in `permissions.yaml`. Dangerous commands (`rm -rf /`, `mkfs`, `DROP DATABASE`) are always blocked regardless of mode.

## Multi-Channel Support

### Gateway Mode (recommended)

Start all enabled channels simultaneously:

```bash
elophanto gateway            # Gateway + CLI + all enabled channels
elophanto gateway --no-cli   # Headless mode (Telegram/Discord/Slack only)
```

Each channel connects to the gateway via WebSocket. Sessions are isolated per user per channel.

### Direct Mode

For single-channel use without the gateway:

```bash
elophanto chat               # CLI only (direct)
elophanto chat --direct      # Force direct mode even if gateway enabled
elophanto telegram           # Telegram only (direct)
```

### Channel Setup

**Telegram**: Create a bot via [@BotFather](https://t.me/BotFather), store the token in the vault (`elophanto vault set telegram_bot_token YOUR_TOKEN`), add your Telegram user ID to `config.yaml`.

**Discord**: Create a Discord application and bot, store the token in the vault (`elophanto vault set discord_bot_token YOUR_TOKEN`), add guild IDs to `config.yaml`.

**Slack**: Create a Slack app with Socket Mode, store both tokens in the vault (`elophanto vault set slack_bot_token` and `slack_app_token`), add channel IDs to `config.yaml`.

## Configuration

Configuration lives in `config.yaml`. Key settings:

```yaml
agent:
  permission_mode: full_auto

llm:
  provider_priority: [zai, ollama, openrouter]
  budget:
    daily_limit_usd: 10.00

browser:
  enabled: true
  mode: profile        # Uses your real Chrome sessions

scheduler:
  enabled: true

gateway:
  enabled: true
  host: "127.0.0.1"
  port: 18789

knowledge:
  embedding_provider: auto    # auto | openrouter | ollama

hub:
  enabled: true
  auto_suggest: true

identity:
  enabled: true
  auto_evolve: true
  reflection_frequency: 10

email:
  enabled: true
  provider: agentmail          # "agentmail" (cloud API) or "smtp" (your own server)
  api_key_ref: agentmail_api_key
  domain: agentmail.to
  smtp:                        # Used when provider: smtp
    host: ''
    port: 587
    use_tls: true
    username_ref: smtp_username
    password_ref: smtp_password
    from_address: ''
    from_name: EloPhanto Agent
  imap:
    host: ''
    port: 993
    use_tls: true
    username_ref: imap_username
    password_ref: imap_password
    mailbox: INBOX

payments:
  enabled: false
  crypto:
    enabled: false
    default_chain: base
    provider: local           # "local" (self-custody) or "agentkit" (Coinbase CDP)

mcp:
  enabled: false
  servers: {}                # See docs/23-MCP.md for server config examples

self_learning:
  enabled: false             # Opt-in only — disabled by default. Collects anonymized
                             # task interactions for model training. Does NOT affect
                             # identity evolution, task memory, or any other agent feature.
  batch_size: 10
  min_turns: 3
  success_only: false

documents:
  enabled: true
  ocr_enabled: true

telegram:
  enabled: false
  bot_token_ref: telegram_bot_token
  allowed_users: []

discord:
  enabled: false
  bot_token_ref: discord_bot_token
  allowed_guilds: []

slack:
  enabled: false
  bot_token_ref: slack_bot_token
  app_token_ref: slack_app_token
  allowed_channels: []
```

## CLI Commands

```bash
./start.sh                     # Chat (default)
./start.sh init                # Setup wizard
./start.sh chat --debug        # With debug logging
./start.sh gateway             # Start gateway + all enabled channels
./start.sh gateway --no-cli    # Headless gateway mode
./start.sh vault set KEY VAL   # Store a credential
./start.sh vault list          # List stored credentials
./start.sh schedule list       # List scheduled tasks
./start.sh skills list         # List available skills
./start.sh skills install SRC  # Install skills from git repo
./start.sh skills hub search Q # Search EloPhantoHub
./start.sh skills hub install N # Install from EloPhantoHub
./start.sh mcp list            # List MCP servers
./start.sh mcp add NAME       # Add an MCP server
./start.sh mcp test            # Test MCP connections
./start.sh rollback            # Revert a self-modification
./start.sh telegram            # Start Telegram bot (direct mode)
```

Or with manual venv activation: `source .venv/bin/activate && elophanto <command>`

## Development

```bash
./setup.sh                         # Full setup (deps + browser bridge)
source .venv/bin/activate          # Activate venv
uv sync --all-extras               # Install with dev dependencies
pytest tests/ -v                   # Run tests
ruff check .                       # Lint
mypy core/ tools/ cli/             # Type check
```

## Project Structure

```
elophanto/
├── core/                # Agent brain + foundation
│   ├── agent.py         # Main loop (plan/execute/reflect)
│   ├── planner.py       # XML-structured system prompt builder
│   ├── router.py        # Multi-provider LLM routing
│   ├── executor.py      # Tool execution + permissions
│   ├── gateway.py       # WebSocket gateway control plane
│   ├── session.py       # Session management + persistence
│   ├── protocol.py      # Gateway message types + serialization
│   ├── hub.py           # EloPhantoHub registry client
│   ├── skills.py        # Skills discovery and trigger matching
│   ├── telegram.py      # Telegram bot adapter (legacy direct mode)
│   ├── browser_manager.py # Chrome control via Node.js bridge
│   ├── mcp_client.py    # MCP client manager + server connections
│   ├── vault.py         # Encrypted credential vault
│   ├── identity.py      # Evolving agent identity manager
│   ├── payments/        # Crypto payments (manager, limits, audit)
│   ├── goal_manager.py  # Autonomous goal loop
│   ├── protected.py     # Protected files system
│   ├── approval_queue.py # Persistent approval tracking
│   └── ...
├── channels/            # Channel adapters (gateway clients)
│   ├── base.py          # ChannelAdapter ABC
│   ├── cli_adapter.py   # CLI adapter (Rich terminal)
│   ├── telegram_adapter.py # Telegram adapter (aiogram)
│   ├── discord_adapter.py  # Discord adapter (discord.py)
│   └── slack_adapter.py    # Slack adapter (slack-bolt)
├── tools/               # 95+ built-in tools
│   ├── system/          # Shell, filesystem
│   ├── browser/         # 47 browser tools
│   ├── knowledge/       # Search, write, index, skills, hub
│   ├── documents/       # Document analysis, query, collections
│   ├── goals/           # Goal loop tools
│   ├── email/           # Agent email (AgentMail + SMTP/IMAP, send, receive, search)
│   ├── identity/        # Identity status, update, reflection
│   ├── payments/        # Crypto wallet, transfers, swaps, audit
│   ├── self_dev/        # Plugin creation, modification, rollback
│   ├── scheduling/      # Cron-based task scheduling
│   ├── data/            # LLM calls
│   └── mcp_manage.py    # MCP server management
├── skills/              # Best-practice guides (27 SKILL.md files)
├── plugins/             # Agent-created tools
├── bridge/browser/      # Node.js browser bridge (Playwright)
├── knowledge/           # Markdown knowledge base
├── cli/                 # CLI commands
├── tests/               # Test suite
├── setup.sh             # One-command install
├── start.sh             # Quick launcher (activates venv)
├── config.yaml          # Configuration
├── permissions.yaml     # Per-tool permission overrides
└── docs/                # Full specification (20 docs)
```

## Implementation Status

| Phase | Feature | Status |
|-------|---------|--------|
| 0 | Foundation (agent loop, tools, CLI) | Done |
| 1 | Knowledge & Memory (SQLite, embeddings, RAG) | Done |
| 2 | Permission System (three-tier, protected files) | Done |
| 3 | Browser Bridge (47 tools, Chrome profile mode) | Done |
| 4 | Self-Development Pipeline (full QA, git integration) | Done |
| 5 | Core Self-Modification (impact analysis, rollback) | Done |
| 6 | Security Hardening (vault, log redaction, protected files) | Done |
| 7 | Scheduling & Automation (APScheduler, cron, natural language) | Done |
| 7.5 | Telegram Bot Interface (aiogram, commands, notifications) | Done |
| 7.6 | Skills System (27 skills, install from git, trigger matching) | Done |
| 7.7 | Gateway Architecture (WebSocket control plane, sessions) | Done |
| 7.8 | Channel Adapters (CLI, Telegram via gateway) | Done |
| 7.8b | Channel Adapters (Discord, Slack via gateway) | Untested |
| 7.9 | EloPhantoHub (skill registry, search, install, update) | Done |
| 8 | Web UI (FastAPI + React) | Planned |
| 9 | Polish & Open Source Release | Done |
| 10 | Self-Learning Model (HF Jobs + Unsloth, HuggingFace, Ollama) | Dataset Builder Done |
| 11 | Agent Payments (crypto wallet, spending limits, audit trail) | Done |
| 12 | Document & Media Analysis (images, PDFs, OCR, RAG research) | Done |
| 13 | Autonomous Goal Loop (decompose, checkpoints, context, self-eval) | Done |
| 14 | Evolving Identity (first awakening, reflection, nature document, credential tracking) | Done |
| 15 | Agent Email (dual provider: AgentMail cloud + SMTP/IMAP, send/receive/search, identity integration, skill, audit) | Done |
| 16 | EloPhantoHub Supply Chain Security (7-layer defense, publisher tiers, CI scanning, checksums, content policy) | P0 Done |
| 17 | Hosted Platform & Desktop App (Tauri desktop, Fly.io cloud instances, web dashboard, Stripe billing) | Spec |
| 18 | Agent Census (anonymous startup heartbeat, machine fingerprint, ecosystem stats) | Done |
| 19 | MCP Integration (MCP client, auto-install, mcp_manage tool, CLI, init wizard, agent self-management) | Done |

See [docs/10-ROADMAP.md](docs/10-ROADMAP.md) for full details.

## Credits

EloPhanto was built by **[Petr Royce](https://github.com/0xroyce)** as part of research into self-learning agents.

- Browser engine built on [FellouAI/eko](https://github.com/FellouAI/eko)
- UI skills from [ui-skills.com](https://www.ui-skills.com/) by Interface Office
- Skills from [anthropics/skills](https://github.com/anthropics/skills) by Anthropic
- React/Next.js skills from [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) by Vercel
- Supabase skills from [supabase/agent-skills](https://github.com/supabase/agent-skills) by Supabase
- Next.js/Prisma/shadcn skills from [gocallum/nextjs16-agent-skills](https://github.com/gocallum/nextjs16-agent-skills)
- Agent email powered by [AgentMail](https://agentmail.to) — API-native email for AI agents (cloud provider)
- SMTP/IMAP email via Python stdlib — zero-dependency self-hosted provider
- Local wallet powered by [eth-account](https://github.com/ethereum/eth-account) by the Ethereum Foundation
- Managed wallet provider by [Coinbase AgentKit](https://github.com/coinbase/agentkit) by Coinbase

## Changelog

| Date | Change |
|------|--------|
| 2026-02-22 | **Response speed fix** — Eliminated 25-40 second delay on every response caused by post-task housekeeping (identity reflection, task memory, dataset collection) blocking the reply. All post-task work now runs as fire-and-forget background tasks via `asyncio.create_task()`. Embedding detection moved to non-blocking startup. Response time dropped from 30+ seconds to ~4 seconds |
| 2026-02-22 | **Self-learning dataset builder** — Opt-in only (`self_learning.enabled: false` by default). Agent-side data collection pipeline for training. Captures task interactions, sanitizes locally (14 secret patterns, PII, browser data), enriches with training signals (user sentiment, denial/error detection, turn count), buffers in local SQLite, uploads in batches to elophanto.com collection API. Auto-registration via census fingerprint, key recovery on conflict. Server-side: collect endpoint, daily cron pushes to HuggingFace Datasets as JSONL. Collects both successes and failures for DPO/RLHF training. Only collects interactions with tool use (no greetings/chat). 42 tests |
| 2026-02-22 | **MCP integration** — Native MCP client support: connect to any MCP server and its tools appear alongside built-in tools. Dual transport (stdio + Streamable HTTP), vault-referenced secrets, per-server permissions. Agent self-management via `mcp_manage` tool (install SDK, add/remove/test servers through conversation). `elophanto mcp` CLI commands (list, add, remove, test). Init wizard step 8 with presets (filesystem, GitHub, Brave Search). Auto-install SDK on startup. System prompt integration. Welcome panel shows `mcp (N)` with connected server count |
| 2026-02-21 | **Agent Census** — Anonymous startup heartbeat for ecosystem statistics. SHA-256 machine fingerprint (survives reinstall), fire-and-forget with 3s timeout, zero PII. Payload: agent_id + version + platform + python version. `core/census.py` module, integrated in `Agent.initialize()`, 15 tests |
| 2026-02-21 | **Hosted platform spec** — Hybrid distribution: Tauri desktop app (free, local-first) + Fly.io cloud instances (pro, always-on) at elophanto.com. Per-user container isolation, Supabase auth, Stripe billing, shared web dashboard, wake-on-request for hibernated instances, data portability between local and cloud |
| 2026-02-21 | **EloPhantoHub security P0 implemented** — Content security policy with 16 blocked patterns + 5 warning patterns enforced at skill load time (`core/skills.py`), SHA-256 checksum verification on hub install (`core/hub.py`), skill revocation detection + quarantine to `_revoked/`, runtime safety guidance in system prompt (`core/planner.py`), skill origin tagging (source/tier/warnings in XML), enhanced `installed.json` with backward compat, 24 security tests |
| 2026-02-20 | **EloPhantoHub supply chain security spec** — 7-layer defense-in-depth design for skill marketplace security: publisher verification with tier system (New → Verified → Trusted → Official), automated CI scanning (malicious patterns, prompt injection, obfuscation), human review for new publishers, SHA-256 integrity checksums, content security policy (blocked/warning patterns enforced at load time), runtime protection (permission system, skill origin tagging), incident response with revocation broadcast |
| 2026-02-20 | **Agent email** — Own email inbox with dual provider support: AgentMail (cloud API, zero config) or SMTP/IMAP (your own server — Gmail, Outlook, etc.). 6 tools (email_create_inbox, email_send, email_list, email_read, email_reply, email_search), email-agent skill with verification flow patterns, identity integration (inbox stored in beliefs), audit logging via email_log table. Chat-based setup — agent asks for provider choice and credentials |
| 2026-02-19 | **Crypto payments** — Agent's own wallet on Base with dual provider support: local self-custody wallet (default, zero config, eth-account) and Coinbase AgentKit (optional, managed custody, gasless, DEX swaps). 7 payment tools (wallet_status, payment_balance, payment_validate, payment_preview, crypto_transfer, crypto_swap, payment_history), spending limits ($100/txn, $500/day, $5K/month), full audit trail, preview-before-execute protocol, chat-based setup |
| 2026-02-19 | **Evolving identity** — IdentityManager discovers identity on first run via LLM, evolves personality/values/capabilities through task reflection, maintains a living `knowledge/self/nature.md` document, tracks credential accounts in beliefs. 3 new tools (identity_status, identity_update, identity_reflect), 45 new tests. Per-session timestamped log files |
| 2026-02-19 | **Autonomous goal loop** — GoalManager decomposes complex goals into ordered checkpoints, persists progress across sessions, summarizes context to stay within token limits, self-evaluates and revises plans. 3 new tools (goal_create, goal_status, goal_manage), goals skill, 61 new tests |
| 2026-02-19 | **Document & media analysis** — PDF, DOCX, XLSX, PPTX, EPUB, image extraction with OCR (rapidocr), RAG collections for large documents, 3 new tools (document_analyze, document_query, document_collections), Telegram file/photo intake, structured `data/` storage manager |
| 2026-02-19 | Fix `/stats`, `/clear`, `/help` commands in gateway CLI mode |
| 2026-02-19 | Add EloPhanto logo assets |
| 2026-02-19 | Agent payments spec (idea phase), Telegram resilience fix (circuit-breaker + force-exit) |
| 2026-02-18 | Self-learning model pipeline spec (idea phase) |
| 2026-02-18 | Initial commit — EloPhanto v0.1.0 (foundation, knowledge, permissions, browser, self-dev, vault, scheduling, Telegram, skills, gateway, channels, EloPhantoHub) |

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
