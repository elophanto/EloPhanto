# EloPhanto

A self-evolving AI agent that runs locally as your personal AI operating system. Full system access, real Chrome browser control, 47+ browser tools, a skills framework with EloPhantoHub registry, multi-channel gateway (CLI, Telegram, Discord, Slack), encrypted credential vault, and the ability to create new capabilities autonomously.

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Node.js 18+ (for the browser bridge)
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

- **File operations** — read, write, list, delete, move files and directories
- **Shell commands** — execute any command with safety blacklists and approval controls
- **Browser automation** — control a real Chrome browser with 47 tools (navigate, click, type, screenshot, extract data, manage tabs, inspect DOM, read console/network logs)
- **Knowledge base** — persistent markdown knowledge with semantic search via embeddings
- **Memory** — remembers past tasks across sessions, learns from experience
- **Self-development** — creates new tools through a full pipeline: research, design, implement, test, review, deploy
- **Core self-modification** — can modify its own source code with impact analysis, test verification, and automatic rollback
- **Scheduling** — cron-based recurring tasks with natural language schedules
- **Multi-channel gateway** — WebSocket control plane with channel adapters for CLI, Telegram, Discord, and Slack, all with isolated sessions
- **Telegram bot** — full conversational interface from your phone with approval flow, notifications, and slash commands
- **Discord bot** — slash commands, DM/mention support, reaction-based approvals (untested)
- **Slack bot** — app mentions, DM support, thread-based responses (untested)
- **Skills + EloPhantoHub** — best-practice guides loaded before tasks (27 bundled), with a public skill registry for searching, installing, and updating skills
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
│   Tool System (69+ built-in + plugins)           │  Capabilities
├─────────────────────────────────────────────────┤
│   Agent Core Loop (plan → execute → reflect)     │  Brain
├─────────────────────────────────────────────────┤
│ Memory │ Knowledge │ Skills │ LLM Router │ Vault │  Foundation
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
| Scheduling | schedule_task, schedule_list | 2 |

## Skills System

Skills are best-practice guides (`SKILL.md` files) that the agent reads before starting specific task types. 27 skills ship bundled, covering:

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

hub:
  enabled: true
  auto_suggest: true

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
│   ├── vault.py         # Encrypted credential vault
│   ├── protected.py     # Protected files system
│   ├── approval_queue.py # Persistent approval tracking
│   └── ...
├── channels/            # Channel adapters (gateway clients)
│   ├── base.py          # ChannelAdapter ABC
│   ├── cli_adapter.py   # CLI adapter (Rich terminal)
│   ├── telegram_adapter.py # Telegram adapter (aiogram)
│   ├── discord_adapter.py  # Discord adapter (discord.py)
│   └── slack_adapter.py    # Slack adapter (slack-bolt)
├── tools/               # 69+ built-in tools
│   ├── system/          # Shell, filesystem
│   ├── browser/         # 47 browser tools
│   ├── knowledge/       # Search, write, index, skills, hub
│   ├── self_dev/        # Plugin creation, modification, rollback
│   ├── scheduling/      # Cron-based task scheduling
│   └── data/            # LLM calls
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
└── docs/                # Full specification (14 docs)
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
| 9 | Polish & Open Source Release | Planned |

See [docs/10-ROADMAP.md](docs/10-ROADMAP.md) for full details.

## Credits

- UI skills from [ui-skills.com](https://www.ui-skills.com/) by Interface Office
- Skills from [anthropics/skills](https://github.com/anthropics/skills) by Anthropic
- React/Next.js skills from [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) by Vercel
- Supabase skills from [supabase/agent-skills](https://github.com/supabase/agent-skills) by Supabase
- Next.js/Prisma/shadcn skills from [gocallum/nextjs16-agent-skills](https://github.com/gocallum/nextjs16-agent-skills)
- Browser engine powered by [AwareBrowserAgent](https://github.com/AwareBrowserAgent)

## License

MIT
