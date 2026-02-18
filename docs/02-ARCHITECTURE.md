# EloPhanto — Architecture

## System Layers

EloPhanto is organized into seven layers. Each layer has a clear responsibility and communicates with adjacent layers through defined interfaces.

```
┌─────────────────────────────────────────────────┐
│  CLI │ Telegram │ Discord │ Slack │ Web (planned)│  Layer 7: Channel Adapters
├─────────────────────────────────────────────────┤
│       WebSocket Gateway (ws://:18789)            │  Layer 6: Control Plane
├─────────────────────────────────────────────────┤
│              Permission System                   │  Layer 5: Safety & Control
├─────────────────────────────────────────────────┤
│          Self-Development Pipeline               │  Layer 4: Evolution Engine
├─────────────────────────────────────────────────┤
│         Tool System (built-in + plugins)         │  Layer 3: Capabilities
├─────────────────────────────────────────────────┤
│              Agent Core Loop                     │  Layer 2: Brain
│     (plan → execute → reflect → remember)        │
├─────────────────────────────────────────────────┤
│ Memory │ Knowledge │ Skills │ LLM Router │ Vault │  Layer 1: Foundation
├─────────────────────────────────────────────────┤
│            EloPhantoHub Registry                 │  Skill Marketplace
└─────────────────────────────────────────────────┘
```

## Layer 1: Foundation

### Memory System

**Working memory**: Current task context, conversation history, intermediate results. Held in memory during execution, persisted to database on task completion or session end.

**Long-term memory**: Stored in SQLite. Every completed task is summarized (what was asked, what was done, what the outcome was). Searchable via semantic similarity (embeddings) and keyword match. The agent automatically recalls relevant past tasks at the start of each new task — so when you ask "remember that website you built?", it finds the task memory from the previous session and knows exactly what it did and where the files are.

**Identity memory**: The `/knowledge/system/` markdown files. This is the agent's understanding of itself — its architecture, capabilities, history of changes, known limitations. Read on every startup. Updated by the self-development pipeline.

### Knowledge System

All knowledge is stored as markdown files, organized into directories. See `05-KNOWLEDGE-SYSTEM.md` for details.

Retrieval uses a local RAG pipeline: markdown files are chunked, embedded using a local model (via Ollama), and stored as vectors in SQLite using the `sqlite-vec` extension. The agent's `search_knowledge` tool performs semantic search across all knowledge.

### Skills System

Skills are best-practice guides (`SKILL.md` files) that teach the agent how to handle specific types of tasks well. They are discovered on startup, listed in the system prompt, and loaded on-demand before the agent starts work. Skills can be bundled, installed from external repos, installed from EloPhantoHub, or created by the user/agent. See `13-SKILLS.md` for the full specification.

### LLM Router

A unified interface to multiple LLM providers via `litellm`. See `06-LLM-ROUTING.md` for the routing strategy.

### Secret Vault

An encrypted local file storing all credentials (API keys, OAuth tokens, service passwords). See `07-SECURITY.md` for the full security architecture.

### EloPhantoHub Registry

A GitHub-based skill registry that the agent can search and install from. The agent auto-discovers relevant skills when no local match is found. See `13-SKILLS.md` for details.

## Layer 2: Agent Core Loop

The agent operates in a continuous cycle for every task.

**Plan**: Given a goal (from the user or from a scheduled task), the agent breaks it into steps. It considers which tools it has available, what knowledge is relevant, and what approach is most likely to succeed. If it determines it lacks a necessary capability, it flags this and can enter self-development mode.

**Execute**: The agent calls tools one at a time, observing the result of each step before deciding the next action. Tool calls go through the permission system before execution.

**Reflect**: After each step (and after task completion), the agent evaluates what happened. Did the tool return what was expected? Is the task progressing? Should the approach change? This is an explicit LLM call, not just implicit in the next planning step.

**Remember**: Completed tasks are summarized and stored in long-term memory. Failures are documented with what went wrong and why. This memory is searchable and influences future planning.

The loop supports nesting — if a tool call triggers a sub-task (e.g., self-development), that sub-task runs its own plan/execute/reflect cycle within the parent task.

### Session-Scoped Execution

The Agent supports two execution modes:

- **`run(goal)`** — Legacy direct mode. Uses the agent's internal conversation history. For single-channel CLI or Telegram usage.
- **`run_session(goal, session)`** — Gateway mode. Uses the session's isolated conversation history. Approval callbacks are routed through the gateway to the correct channel.

Both modes share the same core loop via `_run_with_history()`, keeping tool initialization, router, and registry shared while isolating user state.

## Layer 3: Tool System

Every capability EloPhanto has is expressed as a tool. Built-in tools ship with the project. Plugins are tools the agent creates for itself.

All tools share a common interface:

- **Name**: unique identifier (e.g., `shell_execute`, `gmail_send`)
- **Description**: natural language explanation of what the tool does, used by the LLM to decide when to use it
- **Input schema**: JSON schema defining required and optional parameters
- **Execute function**: the actual implementation
- **Permission level**: what approval tier this tool requires (see Layer 5)
- **Test suite**: every tool must have associated tests

Tools are registered in a manifest file (`tools/manifest.json`) that the agent reads on startup. When the agent creates a new plugin, it adds an entry to this manifest.

### Built-in Tools (ship with v1)

See `03-TOOLS.md` for the complete tool reference.

### Hub Tools

The agent has tools for interacting with EloPhantoHub:

- **`hub_search`** — Search the registry for skills matching a query (SAFE permission)
- **`hub_install`** — Install a skill from the registry (MODERATE permission)

These allow the agent to auto-discover and install skills when it encounters tasks without relevant local skills.

### Plugin Directory

Agent-created plugins live in `/plugins/`. Each plugin is a self-contained directory:

```
plugins/
  gmail_reader/
    plugin.py          # implementation
    test_plugin.py     # tests
    README.md          # documentation (agent-written)
    schema.json        # input/output schema
```

## Layer 4: Self-Development Pipeline

This is the engine that allows EloPhanto to grow. It is described in full in `04-SELF-DEVELOPMENT.md`.

The key point architecturally: self-development is itself a tool (`self_develop`). The agent core doesn't have special-cased logic for self-improvement. It simply recognizes "I need a capability I don't have" and calls the self-development tool, which orchestrates the full pipeline.

## Layer 5: Permission System

Three operating modes, selectable in the UI/config:

**Ask Always**: Every tool execution requires user approval. The agent presents what it wants to do and waits.

**Smart Auto-Approve**: A rules engine classifies actions as safe or potentially destructive. Safe actions execute automatically. Destructive actions require approval. The classification rules are defined in `permissions.yaml`, which supports per-tool overrides (force a tool to always ask, or always auto-approve).

Default safe actions: read files, search knowledge, query database (read-only), make LLM calls.
Default approval-required actions: write/delete files, shell commands, send emails, browser actions that submit forms, any self-development action, database writes.

**Full Auto**: Everything executes with logging only. For advanced users who trust the agent. A hard blacklist of catastrophically destructive patterns still requires approval even in this mode (e.g., `rm -rf /`, `DROP DATABASE`, formatting disks).

Per-tool overrides in `permissions.yaml` allow fine-grained control beyond these three modes — for example, forcing `shell_execute` to always require approval even in full-auto mode.

### Approval Routing

In gateway mode, approval requests are routed to the correct channel via WebSocket. The executor accepts a per-call `approval_callback` parameter so that each session's approvals go to the right adapter. In direct mode, the approval callback is set once on the executor instance.

### Immutable Core

Certain files are protected and cannot be modified by the agent under any circumstances, even if it modifies its own core logic:

- `core/protected/permissions.py` — the permission engine itself
- `core/protected/safety.py` — destructive action blacklists
- `core/protected/vault.py` — secret encryption/decryption
- `core/protected/rollback.py` — emergency recovery

These files are placed in a directory with filesystem-level read-only permissions for the agent's process. The agent is aware these files exist and are immutable — this is documented in its self-knowledge.

## Layer 6: Gateway Control Plane

The gateway is a WebSocket server (`ws://127.0.0.1:18789`) that acts as the central control plane. All channel adapters connect to it as clients.

### Session Management

Each user/channel pair gets an isolated `Session` with:

- Unique `session_id` (UUID)
- Channel identifier (`cli`, `telegram`, `discord`, `slack`)
- User identifier (channel-specific)
- Independent `conversation_history` (max 20 messages, auto-trimmed)
- Persistence to SQLite (survives restarts)

### Gateway Protocol

JSON messages over WebSocket:

| Type | Direction | Purpose |
|------|-----------|---------|
| `chat` | client → gateway | User message |
| `response` | gateway → client | Agent response (supports streaming via `done` flag) |
| `approval_request` | gateway → client | Tool needs approval |
| `approval_response` | client → gateway | User approves/denies |
| `event` | gateway → client(s) | Broadcast (task_complete, error, notification) |
| `status` | both | Connection status, heartbeat |
| `command` | client → gateway | Slash commands (/status, /tasks, /budget) |
| `error` | gateway → client | Error messages |

### Message Flow

```
1. CLI types "Summarize my Gmail"
2. CLI Adapter sends chat message via WebSocket
3. Gateway creates/retrieves Session for (cli, user)
4. Gateway calls agent.run_session(goal, session)
5. Agent plans and executes using session's history
6. If approval needed: gateway sends approval_request to CLI
7. CLI shows prompt, user approves
8. CLI sends approval_response back
9. Agent completes, gateway sends response to CLI
10. Gateway broadcasts task_complete event to all connected adapters
```

### Backward Compatibility

If `gateway.enabled: false` in config, CLI and Telegram work exactly as before — calling `agent.run()` directly with no gateway. The gateway is opt-in.

## Layer 7: Channel Adapters

Channel adapters are thin WebSocket clients that translate between their platform's API and the gateway protocol. All adapters extend `ChannelAdapter` (ABC).

### Available Adapters

| Adapter | Platform | Features |
|---------|----------|----------|
| `CLIAdapter` | Terminal | Rich terminal REPL, inline approval prompts |
| `TelegramChannelAdapter` | Telegram | Bot commands, inline keyboards, file sharing |
| `DiscordAdapter` | Discord | Slash commands, DM/mention, reaction approvals |
| `SlackAdapter` | Slack | App mentions, DM, thread-based responses |

### Adapter Responsibilities

Each adapter handles:
- Platform-specific message receiving (polling, WebSocket, events)
- Formatting responses for the platform's constraints
- Displaying approval requests in the platform's UI idiom
- Forwarding events/notifications to users

### Startup Flow (Gateway Mode)

```
elophanto gateway
    ↓
1. Load config.yaml
2. Create Agent + initialize (tools, browser, vault, hub, etc.)
3. Start Gateway on ws://127.0.0.1:18789
4. Launch enabled channel adapters as async tasks:
   - CLIAdapter → connects to gateway
   - TelegramAdapter → connects to gateway + starts polling
   - DiscordAdapter → connects to gateway + starts bot
   - SlackAdapter → connects to gateway + starts Socket Mode
5. All adapters send messages through gateway
6. Gateway routes to agent.run_session() with isolated sessions
7. Responses routed back to originating adapter
```

## Data Flow: Example Task

Here is how a typical task flows through the architecture:

```
User: "Summarize my unread Gmail messages"

1. Agent Core receives the goal
2. Plan: "I need to read Gmail. Do I have a gmail tool?"
   → Checks tool manifest → No gmail tool exists
3. Plan: "I need to build a Gmail tool first"
   → Calls self_develop tool with goal: "Create a Gmail reader"

   [Self-development sub-loop begins]
   3a. Research: searches knowledge for Gmail API docs
   3b. Design: writes design doc for gmail_reader plugin
   3c. Implement: writes plugin.py following tool interface
   3d. Test: writes and runs test_plugin.py
   3e. Review: self-reviews code with a different model
   3f. Deploy: registers plugin in manifest
   3g. Document: updates capabilities.md
   [Sub-loop ends]

4. Plan: "Now I have gmail_reader. Use it."
   → Permission system: gmail_read requires approval → asks user
   → User approves
5. Execute: calls gmail_reader tool → gets unread messages
6. Execute: calls llm_call tool → summarizes messages
7. Reflect: task complete, result looks good
8. Remember: stores task summary in long-term memory
9. Return: presents summary to user
```
