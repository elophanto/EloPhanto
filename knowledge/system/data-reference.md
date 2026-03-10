---
title: EloPhanto Domain Model Reference
created: 2026-03-10
updated: 2026-03-10
tags: architecture, domain-model, data, relationships
scope: system
covers: [core/agent.py, core/gateway.py, core/session.py, core/skills.py, core/autonomous_mind.py, core/identity.py]
---

# Domain Model Reference

> Explains how EloPhanto's core concepts relate to each other — the semantic
> connections that aren't obvious from reading individual files.
> Inspired by [Arvid Kahl](https://x.com/arvidkahl/status/2031457304328229184).

---

## The Communication Stack

```
Channel Adapter (CLI, Web, Telegram, Discord, Slack, VS Code)
    │
    ▼
Gateway (WebSocket server, ws://127.0.0.1:18789)
    │
    ├── ClientConnection (one per connected client)
    │       ├── client_id (unique per connection)
    │       ├── channel (e.g. "telegram", "discord", "vscode")
    │       ├── user_id (e.g. Telegram user ID, Discord user ID)
    │       └── session_id → Session
    │
    ▼
Session (per-user/channel isolation)
    ├── LLM context (conversation turns, system prompt)
    ├── conversation_id → Conversation (display grouping)
    └── approval queue (pending tool approvals routed back to correct client)
```

**Key relationships:**
- One **gateway** serves all channels simultaneously
- Each **client connection** maps to one **session** (identified by channel + user_id)
- Sessions are isolated — Telegram user A and Discord user B have separate LLM contexts
- **Conversations** are display-layer groupings within a session (like ChatGPT's sidebar)
- **Chat messages** belong to a conversation (persisted in `chat_messages` table)
- **Session messages** are the per-message log for cross-session search (FTS5 indexed)
- Approval requests are routed back to the **specific client** that triggered them

---

## The Intelligence Stack

```
Skills (147 SKILL.md files)
    │  "How to do X well"
    │  Loaded into system prompt before tasks
    │  Matched by trigger keywords, auto-loaded for top match
    │
Knowledge Chunks (indexed markdown → SQLite + embeddings)
    │  "What I know and have learned"
    │  Semantic search surfaces relevant chunks
    │  Drift detection flags stale docs via covers: field
    │
Tools (140+ registered tool instances)
    │  "What I can do"
    │  Grouped into profiles (minimal, coding, browsing, full, etc.)
    │  Filtered per-request based on task type
    │
Working Memory (assembled before each LLM call)
    "What's relevant right now"
    = system prompt + runtime state + matched skills
      + knowledge chunks + task memory + scratchpad
```

**Key relationships:**
- **Skills** teach the agent *best practices* — they're read-only instruction sets
- **Knowledge** is the agent's *accumulated understanding* — writable, searchable, evolving
- **Tools** are the agent's *actions* — each has a permission level and group
- **Working memory** is the *assembled context* for each LLM call — ephemeral
- Skills can reference tools ("use `browser_navigate` to...") but don't execute them
- Knowledge chunks have `scope` (system/user/learned) determining visibility and priority
- User-scoped knowledge (owner directives) overrides all other context

---

## The Agency Stack

```
Identity (who I am)
    ├── display_name, purpose, values, personality
    ├── beliefs (email, github, username — accumulated facts)
    ├── capabilities (learned abilities)
    ├── communication_style
    └── evolution history (identity_evolution table)
         │
         ▼
Autonomous Mind (what I do when idle)
    ├── Think cycle: sleep → evaluate state → execute → update scratchpad → sleep
    ├── State snapshot: goals + schedules + recent activity + knowledge drift + directives
    ├── Budget: % of daily LLM cost allocated to background thinking
    ├── Scratchpad: persistent working notes (data/scratchpad.md)
    └── Events: MIND_WAKEUP, MIND_ACTION, MIND_SLEEP, broadcast to all channels
         │
         ▼
Goals (what I'm working toward)
    ├── goal_create → goal with checkpoints
    ├── Checkpoints: ordered milestones within a goal
    ├── Status: planning → active → paused → completed / failed
    └── Goal runner: executes checkpoints, marks progress
         │
         ▼
Task Memory (what I've done)
    ├── Stored after each completed task
    ├── Recalled before each new task (dedup, context)
    └── Includes: goal, summary, tools_used, outcome, timestamp
```

**Key relationships:**
- **Identity** shapes how the agent communicates and what it prioritizes
- **Autonomous mind** drives proactive behavior between user interactions
- **Goals** are the agent's long-term objectives — survive across sessions
- **Task memory** prevents repetition and provides historical context
- Identity evolves through triggers (reflection, capability learning, user correction)
- The mind sees goals, schedules, directives, and drift — all in one state snapshot
- Mind pauses during user interaction (cooperative multitasking)

---

## The Trust Stack

```
Vault (encrypted credential storage)
    ├── PBKDF2 key derivation from master password
    ├── Fernet symmetric encryption per value
    └── Stores: API keys, tokens, wallet keys, secrets
         │
         ▼
Payments Manager (financial operations)
    ├── Chain routing: Solana → SolanaWallet, EVM → BaseWallet/AgentKit
    ├── Spending limits: per-txn, daily, monthly, per-recipient, rate
    ├── Audit trail: all transactions logged with hash, timestamp, approval
    └── Preview before execute: payment_preview shows fees/rates without sending
         │
         ▼
Approval System (permission control)
    ├── Tool risk levels: safe, moderate, destructive, critical
    ├── Permission modes: ask_always, smart_auto, auto_approve
    ├── Approval queue: persists across restarts (database-backed)
    └── Multi-channel routing: approval request → correct client → response
         │
         ▼
Protected Files (immutable safety boundary)
    └── core/protected/* — cannot be modified by agent, even via self_modify_source
```

**Key relationships:**
- **Vault** is the root of all credential access — tools call `vault.get(ref)`
- **Payments** depend on vault for wallet keys and API keys
- **Approvals** gate tool execution — critical tools always require owner confirmation
- **Protected files** are the hard boundary the agent cannot cross
- Permission mode affects approval flow but never overrides critical tool requirements
- Authority tiers (owner/trusted/public) determine what a channel user can do
- Organization children inherit vault refs but not vault contents (derived config)

---

## The Delegation Stack

```
Organization (persistent specialist agents)
    ├── OrganizationManager: spawn, delegate, review, teach
    ├── Children: full EloPhanto clones in ~/.elophanto-children/{id}/
    │   ├── Own identity, knowledge, database, autonomous mind
    │   ├── ParentChannelAdapter connects child → parent gateway
    │   └── Trust score: approved_count - rejected_count
    └── Teaching: corrections written as knowledge in child's knowledge/learned/corrections/
         │
         ▼
Swarm (temporary coding agents)
    ├── SwarmManager: spawn, redirect, stop, status
    ├── Agents: Claude Code, Codex, Gemini in isolated tmux sessions
    │   ├── Git worktrees (self-dev) or cloned repos (external)
    │   ├── Headless mode with prompt injection via CLI args
    │   └── Done criteria: pr_created, ci_passed, tmux_exit
    └── Security: diff scanning, env sanitization, kill switch
```

**Key relationships:**
- **Organization** = long-lived domain specialists (marketing agent, research agent)
- **Swarm** = short-lived coding tasks (build feature X, fix bug Y)
- Organization children persist across sessions — swarm agents are ephemeral
- Both use isolated workspaces — children get full repo clones, swarm gets worktrees
- Organization uses trust scoring and teaching — swarm uses security scanning
- Master agent decides which to use based on task type

---

## Database Tables (SQLite — data/elophanto.db)

| Table | Purpose | Key relationships |
|-------|---------|-------------------|
| `identity` | Agent identity fields | Single row, evolves over time |
| `identity_evolution` | Change history | Each identity update logged |
| `memory` | Task memory | Per-session task summaries |
| `goals` | Long-term goals | Has child `goal_checkpoints` |
| `goal_checkpoints` | Milestones within goals | Ordered, statusable |
| `conversations` | Chat conversation groups | Display-layer grouping |
| `chat_messages` | Per-message chat log | Belongs to conversation |
| `session_messages` | FTS5-indexed messages | Cross-session search |
| `sessions` | Gateway sessions | Per user/channel |
| `scheduled_tasks` | Cron/one-time tasks | APScheduler backing |
| `knowledge_chunks` | Indexed knowledge | Semantic + keyword search |
| `document_chunks` | Analyzed documents | With embeddings for RAG |
| `document_files` | Uploaded documents | Parent of document_chunks |
| `document_collections` | Document groupings | Organize by topic |
| `plugins` | Installed plugins | Self-created tools |
| `llm_usage` | LLM call tracking | Cost, tokens, provider, latency |
| `approval_queue` | Pending approvals | Persists across restarts |
| `organization_children` | Spawned specialists | Trust scores, status |
| `organization_feedback` | Approval/rejection log | Teaching history |
| `swarm_activity_log` | Swarm agent events | Spawn, complete, fail |
| `swarm_agents` | Active swarm agents | Status, PR, worktree |
| `email_log` | Sent/received emails | Audit trail |
| `payment_audit` | Financial transactions | Amount, hash, approval |
| `schedule_runs` | Task execution history | Last run, next run |
| `collect_examples` | Training data staging | For HuggingFace push |
