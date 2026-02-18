# EloPhanto — Project Structure & Tech Stack

## Tech Stack

| Component | Technology | Why |
|---|---|---|
| Agent Core | Python 3.12+ | Richest AI/ML ecosystem, litellm support, mature tooling |
| Package Manager | uv | Fast, modern Python package management |
| LLM Routing | litellm + custom Z.ai adapter | litellm for OpenRouter + Ollama, custom adapter for Z.ai/GLM |
| Database | SQLite | Zero-config, single-file, embedded, battle-tested |
| Vector Search | sqlite-vec | SQLite extension for vector similarity search |
| Knowledge | Markdown files | Human-readable, LLM-native, version-controllable |
| Gateway | websockets | Lightweight async WebSocket server for control plane |
| Browser Bridge | TypeScript (Node.js subprocess) | JSON-RPC bridge to AwareBrowserAgent engine |
| Browser Engine | playwright + playwright-extra + stealth | Anti-detection browser automation (runs in Node.js) |
| Task Scheduling | APScheduler | Cron-like scheduling within the Python process |
| Skill Registry | EloPhantoHub (GitHub-based) | Public skill registry with index.json + per-skill metadata |
| Testing | pytest + ruff | Industry-standard Python testing and linting |
| Secret Management | cryptography (Fernet) | Proven encryption, standard library-adjacent |
| CLI | click or typer | Clean CLI framework for Python |
| Web UI (Phase 2) | FastAPI + React | Fast API framework + flexible frontend |
| Version Control | git (programmatic) | GitPython for commit/rollback from agent code |
| Optional Sync | Supabase (user's own) | Encrypted cloud backup, user-controlled |

### Channel Adapters

| Channel | Library | Connection |
|---|---|---|
| CLI | Rich | WebSocket to gateway |
| Telegram | aiogram | WebSocket to gateway + Telegram Bot API polling |
| Discord | discord.py | WebSocket to gateway + Discord WebSocket |
| Slack | slack-bolt | WebSocket to gateway + Slack Socket Mode |

## Directory Structure

```
elophanto/
│
├── README.md                           # Project overview, quickstart
├── LICENSE                             # MIT
├── pyproject.toml                      # Python project config (uv/pip)
├── config.yaml                         # Non-secret configuration
├── permissions.yaml                    # Permission rules (Smart Auto-Approve)
├── vault.enc                           # Encrypted secrets (generated at init)
├── vault.salt                          # Salt for vault key derivation
├── .gitignore
│
├── core/                               # Agent brain — the main loop and systems
│   ├── __init__.py
│   ├── agent.py                        # Main agent class and loop (plan/execute/reflect/remember)
│   ├── planner.py                      # Goal decomposition and step planning
│   ├── executor.py                     # Tool execution orchestration (per-call approval routing)
│   ├── reflector.py                    # Post-action reflection and evaluation
│   ├── memory.py                       # Working memory + long-term memory management
│   ├── router.py                       # Multi-model LLM routing logic
│   ├── zai_adapter.py                  # Z.ai/GLM API adapter (message formatting, headers)
│   ├── registry.py                     # Tool/plugin registration and discovery
│   ├── gateway.py                      # WebSocket gateway control plane (ws://:18789)
│   ├── session.py                      # Session management + SQLite persistence
│   ├── protocol.py                     # Gateway message types + serialization
│   ├── hub.py                          # EloPhantoHub registry client (search, install, update)
│   ├── scheduler.py                    # Task scheduling (APScheduler wrapper)
│   ├── telegram.py                     # Telegram bot adapter (legacy direct mode)
│   ├── telegram_fmt.py                 # Telegram MarkdownV2 formatting
│   ├── skills.py                       # Skills discovery, loading, trigger matching, hub integration
│   ├── protected.py                    # Protected files system
│   ├── approval_queue.py              # Database-backed approval queue
│   ├── node_bridge.py                  # Generic async JSON-RPC client for Node.js subprocesses
│   ├── browser_manager.py             # Browser bridge client (thin wrapper over Node.js bridge)
│   ├── vault.py                        # Encrypted credential vault (Fernet + PBKDF2)
│   │
│   └── protected/                      # IMMUTABLE — agent cannot modify these
│       ├── permissions.py              # Permission engine (ask/auto/full-auto logic)
│       ├── safety.py                   # Destructive action blacklists
│       ├── vault.py                    # Secret encryption/decryption
│       └── rollback.py                 # Emergency recovery operations
│
├── channels/                           # Channel adapters (gateway WebSocket clients)
│   ├── __init__.py
│   ├── base.py                         # ChannelAdapter ABC (shared gateway connection logic)
│   ├── cli_adapter.py                  # CLI adapter — Rich terminal REPL over gateway
│   ├── telegram_adapter.py             # Telegram adapter — aiogram bot over gateway
│   ├── discord_adapter.py              # Discord adapter — discord.py bot over gateway
│   └── slack_adapter.py               # Slack adapter — slack-bolt Socket Mode over gateway
│
├── tools/                              # Built-in tools
│   ├── __init__.py
│   ├── base.py                         # Tool interface, base class, schema validation
│   ├── manifest.json                   # Tool registry (built-in + plugins)
│   │
│   ├── system/                         # System interaction tools
│   │   ├── shell.py                    # Shell command execution
│   │   ├── filesystem.py               # File read/write/list/delete/move
│   │   └── process.py                  # Process management (list, kill)
│   │
│   ├── browser/                        # Browser control tools (via Node.js bridge)
│   │   ├── tools.py                    # 44 browser tool classes (thin wrappers)
│   │   └── utils.py                    # Content sanitization utilities
│   │
│   ├── knowledge/                      # Knowledge management tools
│   │   ├── search.py                   # Semantic search across markdown files
│   │   ├── writer.py                   # Create/update knowledge files
│   │   ├── skill_tool.py              # Skill read/list tools
│   │   ├── hub_tool.py                # EloPhantoHub search/install tools (agent-accessible)
│   │   └── indexer.py                  # Chunking, embedding, indexing pipeline
│   │
│   ├── data/                           # Data tools
│   │   ├── database.py                 # SQLite read/write
│   │   └── llm.py                      # LLM call tool (through router)
│   │
│   ├── self_dev/                       # Self-development tools
│   │   ├── reader.py                   # Read own source code
│   │   ├── modifier.py                 # Modify own source code (with QA pipeline)
│   │   ├── creator.py                  # Create new plugins (full pipeline)
│   │   ├── capabilities.py             # List/introspect capabilities
│   │   ├── tester.py                   # Run tests
│   │   └── pipeline.py                 # Orchestrates the full dev pipeline
│   │
│   └── scheduling/                     # Task scheduling tools
│       └── scheduler.py                # Create/list/manage scheduled tasks
│
├── setup.sh                            # One-command install script
├── start.sh                            # Quick launcher (activates venv + runs elophanto)
│
├── skills/                             # Best-practice guides (SKILL.md files)
│   ├── _template/                     # Template for creating new skills
│   │   └── SKILL.md                   # SKILL.md format reference
│   ├── browser-automation/            # Bundled: browser best practices
│   │   └── SKILL.md
│   ├── code-quality/                  # Bundled: coding standards
│   │   └── SKILL.md
│   ├── research/                      # Bundled: information gathering
│   │   └── SKILL.md
│   └── file-management/              # Bundled: file operations
│       └── SKILL.md
│
├── plugins/                            # Agent-created tools (grows over time)
│   ├── _template/                      # Template for new plugins
│   │   ├── plugin.py                   # Implementation template
│   │   ├── test_plugin.py              # Test template
│   │   ├── schema.json                 # Schema template
│   │   └── README.md                   # Documentation template
│   └── .gitkeep
│
├── knowledge/                          # Markdown knowledge base
│   ├── system/                         # Agent's self-documentation
│   │   ├── identity.md                 # Who EloPhanto is
│   │   ├── architecture.md             # How it's built (auto-maintained)
│   │   ├── capabilities.md             # What it can do (auto-maintained)
│   │   ├── conventions.md              # Coding standards and patterns
│   │   ├── changelog.md                # History of all changes
│   │   ├── known-limitations.md        # What it can't do yet
│   │   ├── designs/                    # Design docs for self-developed features
│   │   └── decisions/                  # Architecture Decision Records
│   │
│   ├── user/                           # User-provided knowledge
│   │   └── .gitkeep
│   │
│   ├── learned/                        # Agent-discovered knowledge
│   │   ├── tasks/                      # Completed task summaries
│   │   ├── patterns/                   # Observed patterns
│   │   ├── failures/                   # Documented failures and lessons
│   │   └── services/                   # External service documentation
│   │
│   └── plugins/                        # Plugin documentation (auto-generated)
│       └── .gitkeep
│
├── bridge/                             # Node.js bridge plugins (one per subdirectory)
│   └── browser/                        # Browser bridge (AwareBrowserAgent)
│       ├── package.json                # Dependencies (playwright, stealth, sharp)
│       ├── tsconfig.json               # TypeScript config
│       ├── tsup.config.ts              # Build config → dist/server.js
│       ├── src/
│       │   ├── browser-agent.ts        # AwareBrowserAgent engine (from aware-agent)
│       │   └── server.ts               # JSON-RPC server wrapping the browser agent
│       └── dist/                       # Built output (gitignored)
│           └── server.js               # Bundled bridge server
│
├── web/                                # Web UI (Phase 2)
│   ├── api/                            # FastAPI backend
│   │   ├── main.py                     # FastAPI app
│   │   ├── routes/                     # API routes
│   │   └── websocket.py                # Real-time updates to frontend
│   └── frontend/                       # React frontend
│       └── ...
│
├── cli/                                # Command-line interface
│   ├── __init__.py
│   ├── main.py                         # CLI entry point (click group)
│   ├── init_cmd.py                     # `elophanto init` — setup wizard
│   ├── chat_cmd.py                     # `elophanto chat` — interactive conversation (direct or gateway)
│   ├── gateway_cmd.py                  # `elophanto gateway` — start gateway + channel adapters
│   ├── skills_cmd.py                   # `elophanto skills` — manage skills + EloPhantoHub
│   ├── vault_cmd.py                    # `elophanto vault` — credential management
│   ├── schedule_cmd.py                 # `elophanto schedule` — manage scheduled tasks
│   ├── rollback_cmd.py                 # `elophanto rollback` — emergency recovery
│   └── telegram_cmd.py                 # `elophanto telegram` — Telegram bot (direct mode)
│
├── tests/                              # Test suite
│   ├── conftest.py                     # Shared fixtures
│   ├── test_core/                      # Core loop tests
│   ├── test_tools/                     # Built-in tool tests
│   ├── test_knowledge/                 # Knowledge system tests
│   ├── test_security/                  # Security-specific tests
│   ├── test_browser/                   # Browser manager and tool tests
│   └── scenarios/                      # End-to-end behavioral test scenarios
│
├── scripts/                            # Utility scripts
│   ├── setup_extension.py              # Build and package Chrome extension
│   └── seed_knowledge.py              # Populate initial knowledge files
│
└── db/                                 # Database
    ├── schema.sql                      # SQLite schema (memory, tasks, vectors, sessions, etc.)
    └── migrations/                     # Schema migration files
```

## Database Schema (High Level)

```sql
-- Long-term memory
CREATE TABLE memory (
    id INTEGER PRIMARY KEY,
    task_id TEXT,
    summary TEXT,
    outcome TEXT,
    created_at DATETIME,
    embedding BLOB  -- via sqlite-vec
);

-- Task history
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    goal TEXT,
    status TEXT,  -- pending, running, completed, failed
    plan TEXT,    -- JSON of planned steps
    result TEXT,
    started_at DATETIME,
    completed_at DATETIME,
    tokens_used INTEGER,
    cost_usd REAL
);

-- Plugin registry (mirrors manifest.json but queryable)
CREATE TABLE plugins (
    name TEXT PRIMARY KEY,
    description TEXT,
    path TEXT,
    permission_level TEXT,
    status TEXT,  -- active, disabled, failed
    created_at DATETIME,
    last_used_at DATETIME,
    use_count INTEGER DEFAULT 0
);

-- Knowledge index
CREATE TABLE knowledge_chunks (
    id INTEGER PRIMARY KEY,
    file_path TEXT,
    heading_path TEXT,  -- e.g., "Architecture > Layer 2 > Tool System"
    content TEXT,
    embedding BLOB,
    tags TEXT,  -- JSON array
    updated_at DATETIME
);

-- Scheduled tasks
CREATE TABLE scheduled_tasks (
    id TEXT PRIMARY KEY,
    name TEXT,
    description TEXT,
    schedule TEXT,  -- cron expression
    task_goal TEXT, -- natural language goal
    enabled BOOLEAN DEFAULT 1,
    last_run DATETIME,
    next_run DATETIME,
    created_at DATETIME
);

-- Approval queue
CREATE TABLE approval_queue (
    id TEXT PRIMARY KEY,
    tool_name TEXT,
    params TEXT,  -- JSON
    context TEXT,  -- why the agent wants to do this
    status TEXT,  -- pending, approved, denied, expired
    created_at DATETIME,
    resolved_at DATETIME
);

-- Cost tracking
CREATE TABLE llm_usage (
    id INTEGER PRIMARY KEY,
    task_id TEXT,
    model TEXT,
    provider TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    task_type TEXT,
    created_at DATETIME
);

-- Gateway sessions
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    user_id TEXT NOT NULL,
    conversation_json TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    last_active TEXT NOT NULL,
    metadata_json TEXT DEFAULT '{}',
    UNIQUE(channel, user_id)
);
```

## Python Dependencies (Core)

```
# Core
litellm              # Unified LLM API (OpenRouter + Ollama)
httpx                # Async HTTP client (Z.ai/GLM adapter, EloPhantoHub)
sqlite-vec           # Vector search in SQLite
apscheduler          # Task scheduling
aiogram              # Telegram bot framework (async)
cryptography         # Secret vault encryption
gitpython            # Programmatic git operations
click                # CLI framework (or typer)
websockets           # Async WebSocket server/client (gateway)

# Development / QA
pytest               # Testing framework
ruff                 # Linting + formatting
mypy                 # Type checking

# Knowledge
tiktoken             # Token counting for chunking

# Optional channel adapters
discord.py           # Discord bot (optional)
slack-bolt           # Slack bot with Socket Mode (optional)

# Web UI (Phase 2)
fastapi              # API server
uvicorn              # ASGI server
```

## Build and Distribution

### For Users

```bash
# Install via pip (from PyPI eventually, from git initially)
pip install elophanto

# Or clone and install
git clone https://github.com/elophanto/elophanto.git
cd elophanto
uv sync

# First-time setup
elophanto init

# Start the agent
elophanto chat          # Direct mode (CLI only)
elophanto gateway       # Gateway mode (all channels)
```

### Node.js Bridge

The browser bridge requires Node.js and is built separately:

```bash
cd bridge/browser && npm install && npx tsup && cd ../..
```

This produces `bridge/browser/dist/server.js` which is spawned automatically by the Python agent
when browser tools are first used. The `bridge/*/node_modules/` and `bridge/*/dist/` directories
are gitignored.

### Docker (Optional)

A Dockerfile for users who want containerized deployment. Requires Node.js in the container
for the browser bridge.
