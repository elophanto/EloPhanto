# EloPhanto — Implementation Roadmap

## Phase 0: Foundation (Week 1-2)

**Goal**: A working skeleton — the agent can receive a goal, plan, and execute basic tools.

### Deliverables

- Project scaffolding (directory structure, pyproject.toml, git init)
- Tool base class and interface definition
- Tool manifest system (register, discover, load tools)
- Basic agent loop: plan → execute → reflect (single-pass, no recursion yet)
- LLM router with litellm (OpenRouter + Ollama)
- Config system (config.yaml parsing)
- Basic CLI: `elophanto init`, `elophanto chat`

### Built-in Tools

- `shell_execute` (with safety blacklist)
- `file_read`, `file_write`, `file_list`
- `llm_call`

### Tests

- Tool interface compliance tests
- Agent loop basic flow test
- Router model selection test

### Exit Criteria

You can run `elophanto chat`, give it a task like "list all Python files in my home directory", and it plans the shell command, executes it (with approval), and returns the result.

---

## Phase 1: Knowledge & Memory (Week 2-3)

**Goal**: The agent has persistent memory and can search a markdown knowledge base.

### Deliverables

- SQLite database with schema (memory, tasks, knowledge_chunks, llm_usage)
- sqlite-vec integration for vector search
- Knowledge indexer: markdown chunking + embedding via Ollama
- Knowledge search tool (semantic + keyword hybrid)
- Knowledge write tool
- Working memory (in-session context management)
- Long-term memory (task summaries persisted to DB, searchable)
- Initial `/knowledge/system/` files: identity.md, capabilities.md, conventions.md, changelog.md

### Tests

- Chunking correctness (respects heading hierarchy)
- Embedding + retrieval accuracy (known document, known query, expected result)
- Memory persistence across agent restarts

### Exit Criteria

The agent can answer questions using its knowledge base ("What tools do you have?") and remember tasks from previous sessions ("What did I ask you to do yesterday?").

---

## Phase 2: Permission System (Week 3-4)

**Goal**: Three-tier permission system is fully operational.

### Deliverables

- Permission engine in `core/protected/permissions.py`
- Three modes: Ask Always, Smart Auto-Approve, Full Auto
- `permissions.yaml` with default rules
- Approval queue (database-backed, with CLI display)
- Safety blacklists in `core/protected/safety.py`
- Filesystem-level protection for `core/protected/`
- Integration with tool executor (every tool call goes through permission check)
- CLI approval flow: agent asks, user approves/denies in terminal

### Tests

- Each permission mode behaves correctly
- Blacklisted commands are always blocked
- Approval queue persists across restarts
- Protected files cannot be modified by the agent process

### Exit Criteria

In Smart Auto mode, `file_read` executes immediately, `shell_execute rm something` asks for approval, and `rm -rf /` is always blocked.

---

## Phase 3: Browser Bridge (Week 4-6)

**Goal**: The agent can control a real Chrome browser via a Node.js bridge.

### Deliverables

- Node.js bridge (`bridge/browser/`) wrapping the AwareBrowserAgent TypeScript engine
- JSON-RPC protocol over stdin/stdout (Python ↔ Node.js)
- Generic `NodeBridge` async client (`core/node_bridge.py`)
- `BrowserManager` as thin bridge client (`core/browser_manager.py`)
- Connection modes: fresh, CDP port, CDP WebSocket, profile (with session copy)
- 11 browser tools: navigate, read_page, interact, elements, screenshot, eval, cookies, storage, console, network, tabs
- Content sanitization (script stripping, password redaction)
- Anti-detection via playwright-extra + stealth plugin
- Element stamping system for reliable interaction targeting

### Tests

- Bridge spawn and JSON-RPC communication
- Command/response cycle for each action type
- Content sanitization (password fields redacted, scripts stripped)
- Profile copy and session preservation
- Console and network log capture

### Exit Criteria

The agent can navigate to Gmail in the user's browser (profile mode), read unread email subjects, and report them back — using the user's actual logged-in Gmail session.

---

## Phase 4: Self-Development Pipeline (Week 6-8)

**Goal**: EloPhanto can create new plugins through the full QA pipeline.

### Deliverables

- Plugin template (`/plugins/_template/`)
- Self-development pipeline: research → design → implement → test → review → deploy → document → monitor
- `self_create_plugin` tool (orchestrates the pipeline)
- `self_read_source` tool
- `self_run_tests` tool
- Automated test execution in subprocess with timeout
- Self-review stage (different model reviews the code)
- Git integration: every plugin creation is a commit
- Automatic documentation updates (capabilities.md, changelog.md)
- Budget limits and retry caps
- Failure documentation in `/knowledge/learned/failures/`

### Tests

- End-to-end plugin creation (agent builds a simple tool, tests pass, tool works)
- Failed plugin creation (intentionally flawed, verify agent detects and handles failure)
- Budget limit enforcement
- Manifest updated correctly after plugin creation
- Documentation updated correctly

### Exit Criteria

You can say "I need you to be able to read PDF files" and the agent researches PDF libraries, designs a plugin, implements it with tests, reviews its own code, deploys the plugin, and then uses it — all without manual intervention (with approval at key stages if permission mode requires it).

---

## Phase 5: Core Self-Modification (Week 8-10)

**Goal**: EloPhanto can modify its own core behavior safely.

### Deliverables

- `self_modify_source` tool with stricter QA pipeline
- Impact analysis stage (what else is affected by this change)
- Full regression test requirement for core changes
- Diff presentation in CLI for user review
- Git tagging for core modifications
- Rollback mechanism (`elophanto rollback` CLI command)
- Agent-accessible rollback tool (restricted to known-good states)
- Behavioral test scenarios (before/after comparison)

### Tests

- Core modification applies correctly
- Full test suite passes after modification
- Rollback restores previous state
- Protected files remain unmodifiable
- Agent cannot modify the permission system

### Exit Criteria

The agent can modify its own planning logic (e.g., add a new strategy for multi-step tasks), test the change, and deploy it — with automatic rollback if the change breaks anything.

---

## Phase 6: Security Hardening (Week 10-11)

**Goal**: Production-grade security for an agent with full system access.

### Deliverables

- Encrypted vault (Fernet) with master password flow
- PBKDF2 key derivation with high iteration count
- Credential isolation (secrets never in LLM prompts)
- Log redaction for sensitive values
- Dependency auditing for self-installed packages
- Subprocess sandboxing for plugin tests
- Prompt injection defenses for browser content
- Security-focused test suite

### Tests

- Vault encryption/decryption roundtrip
- Secrets not present in agent logs
- Secrets not present in LLM call inputs
- Prompt injection attempts detected and neutralized
- Blacklisted dependencies flagged

### Exit Criteria

A security review finds no credential leakage paths, and prompt injection test cases are handled correctly.

---

## Phase 7: Scheduling & Automation (Week 11-12)

**Goal**: EloPhanto can run tasks on a schedule without user initiation.

### Deliverables

- APScheduler integration
- `schedule_task` tool (cron expressions + natural language)
- `schedule_list` tool
- Scheduled task execution within the agent loop
- Task result logging and notification
- Error handling for scheduled tasks (retry, notify on failure)
- Persistent schedules (survive agent restarts)

### Tests

- Schedule creation and execution
- Cron expression parsing
- Persistence across restarts
- Error handling and retry behavior

### Exit Criteria

You can say "Check my email every morning at 9am and send me a Slack summary" and the agent sets up the schedule, builds the necessary plugins if missing, and runs autonomously.

---

## Phase 7.5: Telegram Interface (Week 12-13)

**Goal**: EloPhanto is accessible from the user's phone via Telegram.

### Deliverables

- Telegram bot adapter using `aiogram` (async)
- Bot registration flow in `elophanto init`
- User ID whitelist security (silent ignore of unauthorized users)
- Full chat interface (natural language tasks via Telegram)
- Slash commands: `/status`, `/tasks`, `/approve`, `/deny`, `/plugins`, `/mode`, `/budget`, `/help`
- Inline keyboard buttons for approval requests (one-tap approve/deny)
- Notification system: task completion, errors, approval needed, scheduled results
- File and screenshot sending
- Message formatting adapter (agent markdown → Telegram MarkdownV2)
- Message splitting for long responses
- Conversation context tracking (multi-turn via Telegram)
- Polling mode (default) with optional webhook support
- Optional daily summary notification

### Tests

- User ID verification (authorized vs unauthorized)
- Command handling for all slash commands
- Approval flow (request → notify → approve/deny → confirm)
- Message formatting and splitting
- Notification delivery for each event type
- Context persistence across multi-turn conversation

### Exit Criteria

The user can open Telegram on their phone, send "What's my agent doing?", and receive a real-time status update. They can give tasks, approve pending actions with one tap, and receive notifications when scheduled tasks complete.

---

## Phase 7.6: Skills System (Week 13)

**Goal**: EloPhanto has a skills framework for best-practice guides that improve task quality.

### Deliverables

- `skills/` directory with bundled skills (browser-automation, code-quality, research, file-management)
- `SKILL.md` convention: triggers, instructions, examples per skill
- `SkillManager` in `core/skills.py`: discovery, trigger matching, loading
- `skill_read` and `skill_list` tools for agent use
- Skills listed in system prompt under `<available_skills>` XML block
- `elophanto skills` CLI: install, list, read, remove
- Git-based skill installation from external repos (compatible with ui-skills.com, OpenClaw skills)
- Agent can create new skills via self-development
- Template skill in `skills/_template/`

### Tests

- Skill discovery finds all valid skills in directory
- Trigger matching returns relevant skills for queries
- Install from local directory and git repo
- Remove skill cleans up files and registry
- System prompt includes available skills section

### Exit Criteria

The user can run `elophanto skills install https://github.com/ibelick/ui-skills` to install external skills, and the agent automatically reads relevant skills before starting matching tasks.

---

## Phase 7.7: Gateway Architecture (Week 13-14)

**Goal**: A WebSocket control plane that all channels connect through, with session isolation.

### Deliverables

- Gateway protocol with typed JSON messages (`core/protocol.py`)
- Session manager with SQLite persistence (`core/session.py`)
- WebSocket gateway server on `ws://127.0.0.1:18789` (`core/gateway.py`)
- Agent refactored with `run_session()` for session-scoped execution
- Per-call approval callback routing in executor
- Sessions table in database schema
- Gateway configuration section in `config.yaml`

### Exit Criteria

Start the gateway, connect with a WebSocket client, send a chat message, and get a response back. Connect two clients and verify they get independent sessions.

---

## Phase 7.8: Channel Adapters (Week 14-15)

**Goal**: All communication channels connect through the gateway as thin adapters.

### Deliverables

- `ChannelAdapter` ABC in `channels/base.py`
- CLI adapter — Rich terminal REPL over gateway
- Telegram adapter — aiogram bot over gateway
- Discord adapter — discord.py bot with slash commands, reaction approvals
- Slack adapter — slack-bolt Socket Mode with thread-based responses
- `elophanto gateway` CLI command for multi-channel startup
- `elophanto chat` auto-detects gateway mode with `--direct` fallback

### Exit Criteria

`elophanto gateway` launches the gateway plus all enabled channel adapters. Chat from CLI and Telegram simultaneously with independent sessions. Approvals route to the correct channel.

---

## Phase 7.9: EloPhantoHub — Skill Registry (Week 15)

**Goal**: A public skill registry that the agent can search, install from, and auto-discover skills.

### Deliverables

- `HubClient` in `core/hub.py` — GitHub-based registry client with caching
- `hub_search` and `hub_install` agent tools in `tools/knowledge/hub_tool.py`
- EloPhantoHub integration in `SkillManager` (search_hub, install_from_hub)
- CLI commands: `elophanto skills hub search/install/update/list`
- Agent auto-suggests hub skills during planning when no local match found
- Hub configuration section in `config.yaml`

### Exit Criteria

`elophanto skills hub search "react"` returns results. `elophanto skills hub install react-best-practices` downloads and installs. Agent auto-suggests hub skills when encountering unfamiliar task types.

---

## Phase 8: Web UI (Week 15-17)

**Goal**: A browser-based interface for configuration and monitoring.

### Deliverables

- FastAPI backend with routes for all CLI functionality
- WebSocket endpoint for real-time updates
- React frontend with pages for:
  - Dashboard (current status, recent activity, running tasks)
  - Chat interface (conversation with the agent)
  - Plugin manager (list, enable/disable, view source, trigger)
  - Knowledge browser (view/edit markdown files)
  - Configuration (LLM routing, permissions, integrations)
  - Approval queue (pending actions, approve/deny)
  - Logs and history
  - Cost tracking and usage stats
- Authentication (local only, simple password or token)

### Tests

- API endpoint tests
- WebSocket message delivery
- Frontend renders correctly

### Exit Criteria

A user who prefers GUIs can set up, configure, and interact with EloPhanto entirely through the web interface.

---

## Phase 9: Polish & Open Source Release (Week 15-17)

**Goal**: Ready for public use.

### Deliverables

- Comprehensive README with quickstart guide
- Contributing guide (CONTRIBUTING.md)
- Documentation site (GitHub Pages or similar)
- Node.js bridge build and setup instructions
- PyPI package publication
- Demo video / GIF showing capabilities
- GitHub Issues templates
- CI/CD pipeline (GitHub Actions): tests, linting, type checking
- Security policy (SECURITY.md)
- Example plugins (shipped but optional)
- First-run experience polish (smooth init wizard)

### Exit Criteria

A developer who has never seen EloPhanto can clone the repo, run `elophanto init`, and have a working self-evolving agent within 10 minutes.

---

## Implementation Status

| Phase | Status |
|---|---|
| Phase 0: Foundation | **Done** |
| Phase 1: Knowledge & Memory | **Done** — includes cross-session task memory recall |
| Phase 2: Permission System | **Done** — includes permissions.yaml, protected files, approval queue persistence |
| Phase 3: Browser Bridge | **Done** — 47 tools via Node.js Playwright bridge |
| Phase 4: Self-Development Pipeline | **Done** — includes git integration, auto-doc updates |
| Phase 5: Core Self-Modification | **Done** — includes rollback tool and CLI command |
| Phase 6: Security Hardening | **Done** — includes vault, log redaction, protected files |
| Phase 7: Scheduling & Automation | **Done** — includes one-time and recurring scheduling |
| Phase 7.5: Telegram Interface | **Done** — aiogram adapter with commands and notifications |
| Phase 7.6: Skills System | **Done** — 27 skills, CLI installer, trigger matching |
| Phase 7.7: Gateway Architecture | **Done** — WebSocket control plane, session isolation, protocol |
| Phase 7.8: Channel Adapters | **Done** — CLI, Telegram, Discord, Slack via gateway |
| Phase 7.9: EloPhantoHub | **Done** — Skill registry, search, install, update, agent auto-discovery |
| Phase 8: Web UI | Planned |
| Phase 9: Polish & Release | Planned |
| Phase 10: Self-Learning Model | Idea Phase |

## Phase 10: Self-Learning Model (Idea Phase)

**Goal**: Train a custom EloPhanto base model that improves over time from its own interaction data.

### Deliverables

- Automated dataset collector capturing planning traces, tool calls, conversations, and reflections
- Central dataset repository (GitHub/HuggingFace) with quality filtering and privacy sanitization
- Unsloth QLoRA fine-tuning pipeline on an open-source base model (7B-14B range)
- Model published to HuggingFace (`0xroyce/EloPhanto-Base-Model`) with versioning
- Ollama integration for local deployment with auto-pull of new versions
- Benchmark suite: tool accuracy, plan quality, code generation, reflection quality
- Continuous improvement loop: collect → train → publish → deploy → monitor → repeat
- Fallback strategy: auto-rollback to previous version if regression detected

### Exit Criteria

The fine-tuned EloPhanto model outperforms the base model on agent-specific benchmarks (tool selection, multi-step planning) and runs locally via Ollama as the default model for routine tasks.

See [14-SELF-LEARNING.md](14-SELF-LEARNING.md) for the full specification.

---

## Future Directions (Post-Launch)

These are not scoped but represent the natural evolution:

- **Voice interface**: Speak to EloPhanto, receive spoken responses
- **Visual understanding**: Agent can interpret screenshots and images (using vision models)
- **Multi-agent**: Multiple EloPhanto instances collaborating on tasks
- **Mobile companion**: A mobile app that connects to the home agent
- **Plugin marketplace**: Community-shared plugins (curated, security-reviewed)
- **Supabase sync**: Multi-device encrypted configuration sync
- **Adaptive routing**: Agent learns which models work best for which tasks
- **Firefox support**: Extend browser bridge to support Firefox via Playwright
- **Windows / macOS native**: Desktop app packaging
- **WhatsApp adapter**: WhatsApp Business API channel adapter
- **Web adapter**: Browser-based chat widget via gateway WebSocket
