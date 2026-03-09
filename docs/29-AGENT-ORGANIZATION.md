# Agent Organization — Persistent Specialist Child Agents

> **Status: Phases 1–5 Implemented** — Complete organization system: self-spawn,
> config derivation, knowledge seeding, management tools, bidirectional
> communication (parent channel adapter), teaching loop (feedback → knowledge),
> delegation intelligence (LLM-driven specialist routing via system prompt),
> and child autonomy (autonomous mind output → parent reporting).

EloPhanto becomes a CEO. Instead of doing everything itself, it spawns persistent specialist agents — marketing, research, coding, design — that are full EloPhanto instances with their own identity, knowledge vault, and autonomous mind. They work proactively, report back, and learn from the master's feedback.

You talk to EloPhanto. EloPhanto runs the organization.

## The Problem with a Single Agent

One agent doing everything is like one person running a company. It works at small scale, but as tasks get more complex and domain-specific, the agent:

- Lacks deep expertise in every domain (marketing, research, finance, etc.)
- Can't parallelize independent work across platforms
- Has no knowledge specialization — everything goes into one vault
- Has no feedback-driven learning per domain

The swarm system (Phase 25) solves this for **coding** — EloPhanto spawns Claude Code, Codex, or Gemini CLI on code tasks. But those agents are ephemeral, external, and can't learn. They start from zero every time.

The organization system extends this to **any domain** with persistent, learning specialists.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Master EloPhanto (CEO)                        │
│  Knowledge │ Vault │ Memory │ Goals │ Scheduler │ Identity      │
│  Browser   │ Email │ Payments │ Multi-Channel │ Swarm           │
├─────────────────────────────────────────────────────────────────┤
│                   Organization Manager                           │
│  spawn · monitor · delegate · review · teach · track             │
├────────────┬─────────────┬─────────────┬────────────────────────┤
│ Specialist │ Specialist  │ Specialist  │  ...                    │
│ Marketing  │ Research    │ Design      │                         │
│ Agent      │ Agent       │ Agent       │                         │
├────────────┴─────────────┴─────────────┴────────────────────────┤
│  Each specialist is a full EloPhanto instance:                   │
│  Own identity · Own knowledge vault · Own autonomous mind        │
│  Connects to master gateway as channel client                    │
│  Learns from master's approval/rejection feedback                │
└─────────────────────────────────────────────────────────────────┘
```

## How It Works

### Spawning a Specialist

The master recognizes it needs domain expertise and spawns a specialist:

```
User: "Create a marketing strategy for our product launch"
EloPhanto: I'll spawn a marketing specialist for this.
→ Clones itself into ~/.elophanto-children/{child_id}/
→ Derives config (same API keys, different identity/DB/knowledge)
→ Seeds knowledge (copies relevant marketing docs from master's vault)
→ Starts child: python -m elophanto gateway --config {child_config}
→ Child goes through first awakening — discovers its identity as a marketing specialist
→ Master delegates the task via gateway
```

### Self-Spawn Mechanics

Each child is a full EloPhanto installation:

1. **Clone** — Copy master's codebase into `~/.elophanto-children/{child_id}/`
2. **Config derivation** — Generate child's `config.yaml`:
   - Same LLM provider config (API keys inherited)
   - Different `database.db_path` (own state)
   - Different `knowledge.knowledge_dir` (own knowledge vault)
   - Different `gateway.port` (own WebSocket endpoint)
   - Identity config with `first_awakening: true` and specialized purpose
   - Budget allocation (% of master's daily limit)
3. **Knowledge seeding** — Copy selected knowledge files from master to child
4. **Bootstrap** — Start as subprocess, wait for gateway health check
5. **Connect** — Master's child adapter connects to child's gateway

### Config Derivation

```yaml
# Auto-generated child config
agent_name: "marketing-specialist-a1b2c3d4"

gateway:
  enabled: true
  host: "127.0.0.1"
  port: 18801                # Unique per child

database:
  db_path: "data/elophanto.db"

knowledge:
  knowledge_dir: "knowledge/"

identity:
  enabled: true
  first_awakening: true      # Child discovers its own identity
  auto_evolve: true

autonomous_mind:
  enabled: true
  wakeup_seconds: 300
  budget_pct: 100            # Child controls its full allocated budget

llm:
  budget:
    daily_limit_usd: 1.0     # Allocated from master's budget
    per_task_limit_usd: 0.5

# LLM providers inherited from master config
```

### Specialist Persistence

Specialists persist across master restarts:

- **DB registry** — `organization_children` table tracks all children (status, port, work_dir, performance)
- **Reuse, don't recreate** — `get_or_spawn(role)` checks registry first. If a marketing specialist already exists and is stopped, restart it with all its accumulated knowledge.
- **Knowledge accumulation** — Each child's knowledge vault grows independently. Corrections from master persist as learned knowledge files.
- **Performance tracking** — Approved/rejected counts, tasks completed, trust score

## Bidirectional Communication

Children connect to the master's gateway as channel clients — just like Telegram or Discord:

```
Master Gateway (ws://127.0.0.1:18789)
├── CLI adapter
├── Telegram adapter
├── Discord adapter
├── child:marketing-a1b2c3d4    ← Specialist agent
├── child:research-f3e4d5c6     ← Specialist agent
└── ...
```

### Message Flow

```
Master → Child:  Task assignment, feedback (approve/reject), knowledge push
Child → Master:  Task report, approval request, proactive findings
```

Each child appears as `channel="child:{child_id}"`. The gateway protocol handles routing natively — no new transport needed.

### ParentChannelAdapter (`channels/child_adapter.py`)

The child-side adapter extends `ChannelAdapter` and runs inside child EloPhanto instances:

```python
adapter = ParentChannelAdapter(
    parent_host="127.0.0.1",
    parent_port=18789,
    child_id="a1b2c3d4",
)
await adapter.start()                              # Connect to master gateway
await adapter.send_report("Task completed: ...")   # Report back to master
await adapter.request_approval("wrote post", "...")# Ask master to review
task = await adapter.receive_task(timeout=30)       # Wait for assignment
feedback = await adapter.receive_feedback()         # Get approval/rejection
```

Child config includes a `parent:` section (auto-generated by `_derive_config()`):

```yaml
parent:
  enabled: true
  host: "127.0.0.1"
  port: 18789       # Master's gateway port
  child_id: "a1b2c3d4"
```

### Protocol Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `child_task_assigned` | Master → Child | New task delegated |
| `child_report` | Child → Master | Task completed, results attached |
| `child_approval_request` | Child → Master | Wants approval before acting |
| `child_feedback` | Master → Child | Approval/rejection with reason |

## Teaching & Learning

The core feedback loop that makes children improve over time:

```
                    ┌──────────────┐
                    │ Master       │
                    │ reviews      │
                    └──┬───────┬───┘
                       │       │
                  Approve    Reject + reason
                       │       │
                       ▼       ▼
              ┌────────────────────────┐
              │ Stored in child's      │
              │ knowledge vault as     │
              │ learned correction     │
              └────────────────────────┘
                       │
                       ▼
              ┌────────────────────────┐
              │ Future tasks: child's  │
              │ LLM sees corrections   │
              │ in knowledge context   │
              └────────────────────────┘
```

### Correction Knowledge Format

When master rejects child work, the feedback is written as a knowledge file in the child's vault:

```markdown
---
scope: learned
tags: correction, marketing, social-media
created: 2026-03-02
source: master-feedback
---

# Correction: Social Media Post Formatting

**Task**: Post announcement about product launch on X
**Feedback**: The post exceeded X's 280 character limit. Always verify
platform limits before composing. X: 280 chars, Mastodon: 500 chars,
LinkedIn: 3000 chars.
```

The child's knowledge indexer picks this up. On future tasks, the correction appears in the child's working memory context — it literally learns from mistakes.

### Trust Score & Auto-Approve

```
trust_score = approved_count - rejected_count
```

| Trust Score | Behavior |
|-------------|----------|
| < 0 | Master reviews all output, may re-seed knowledge |
| 0-9 | Master reviews all output |
| 10+ | Auto-approve eligible — master can skip review |
| 20+ | High trust — delegate complex tasks with minimal oversight |

`auto_approve_threshold` is configurable (default: 10).

## Delegation Intelligence

The master decides when to self-handle vs delegate. This is **LLM-driven, not rule-based** — the master's system prompt includes:

```
DELEGATION FRAMEWORK:
- Quick, simple tasks you can handle well → do it yourself
- Tasks requiring deep domain expertise → delegate to specialist
- Multiple independent tasks → delegate in parallel
- High-trust specialist → delegate with less oversight
- New/low-trust specialist → review all output
```

The master sees available specialists, their roles, trust scores, and recent performance. It makes the delegation decision naturally as part of its reasoning.

Implementation: `build_system_prompt()` in `core/planner.py` includes `_TOOL_ORGANIZATION` (tool guidance) and the dynamic `organization_context` (live specialist list with trust scores) when `organization_enabled=True`. The context is built by `OrganizationManager.get_organization_context()` and passed through `core/agent.py`.

### When Master Does It Itself

Not everything gets delegated. Just like a CEO:
- Quick answers to user questions → handle directly
- Simple file edits or lookups → handle directly
- Tasks the master is equally capable of → handle directly (faster than delegation overhead)
- Urgent time-sensitive actions → handle directly

### When Master Delegates

- "Create a full marketing strategy" → marketing specialist
- "Research competitor pricing" → research specialist
- "Post on X, Mastodon, and LinkedIn" → delegate each to marketing specialist (or parallelize)
- "Analyze this dataset and create visualizations" → data specialist

## Child Autonomy

Each specialist has its own autonomous mind (the same system from Phase 26). When enabled, the autonomous mind's think cycle automatically reports output to the master:

1. **Child wakes up** on its configured schedule
2. **Evaluates priorities** within its domain (constrained by identity.purpose + boundaries)
3. **Works proactively** — scans for opportunities, monitors platforms, generates content
4. **Reports to master** — `AutonomousMind._report_to_parent()` sends the cycle output via `ParentChannelAdapter.send_report()` as a `CHILD_REPORT` event
5. **Master reviews** when convenient — approves or corrects

The reporting hook is in `core/autonomous_mind.py`. After each think cycle completes and the action is broadcast locally, the mind checks for a `_parent_adapter` on the agent. If present (meaning this is a child instance), it sends the full cycle content to the master with a `mind-cycle-{N}` task reference.

### Domain-Constrained Autonomy

The child's identity (set during first awakening) constrains autonomous behavior:

- **Marketing specialist**: Monitors campaign metrics, drafts content calendar, analyzes competitor social presence
- **Research specialist**: Scans industry news, updates competitive analysis, surfaces trends
- **Design specialist**: Audits visual consistency, proposes improvements, prepares assets

Each specialist stays within its domain boundaries. The master can adjust boundaries through the identity system.

## Tools

| Tool | Input | Description |
|------|-------|-------------|
| `organization_spawn` | `role`, `purpose`, `seed_knowledge` | Spawn or reuse a specialist |
| `organization_delegate` | `role` or `child_id`, `task` | Send task to specialist |
| `organization_review` | `child_id`, `task_ref`, `approved`, `feedback` | Approve/reject work |
| `organization_teach` | `child_id` or `role`, `content` | Push knowledge to child |
| `organization_status` | `child_id` (optional) | List children + performance |

## Configuration

```yaml
organization:
  enabled: false
  max_children: 5
  port_range_start: 18801
  children_dir: ""          # Default: ~/.elophanto-children/
  monitor_interval_seconds: 30
  auto_approve_threshold: 10

  # Pre-configured specialist blueprints
  specs:
    marketing:
      role: "marketing"
      purpose: "Marketing strategy, content creation, social media management"
      seed_knowledge:
        - "knowledge/system/social-media.md"
        - "knowledge/user/brand-guidelines.md"
      budget_pct: 10.0
      autonomous: true
      wakeup_seconds: 600

    research:
      role: "research"
      purpose: "Competitive research, market analysis, trend identification"
      seed_knowledge:
        - "knowledge/system/research-methods.md"
      budget_pct: 10.0
      autonomous: true
      wakeup_seconds: 900
```

## Database Schema

### `organization_children`

| Column | Type | Description |
|--------|------|-------------|
| `child_id` | TEXT PK | 8-char hex identifier |
| `role` | TEXT | Specialist role (marketing, research, etc.) |
| `purpose` | TEXT | Identity purpose for this specialist |
| `status` | TEXT | starting, running, stopped, failed |
| `port` | INTEGER | Gateway port |
| `work_dir` | TEXT | Installation directory |
| `config_path` | TEXT | Path to derived config.yaml |
| `pid` | INTEGER | Process ID (NULL if stopped) |
| `approved_count` | INTEGER | Cumulative approvals |
| `rejected_count` | INTEGER | Cumulative rejections |
| `tasks_completed` | INTEGER | Total tasks completed |
| `spawned_at` | TEXT | First spawn timestamp |
| `last_active` | TEXT | Last activity timestamp |
| `metadata_json` | TEXT | Extensible metadata |

### `organization_feedback`

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `child_id` | TEXT FK | Which child |
| `task_ref` | TEXT | Reference to the task |
| `feedback_type` | TEXT | approval, rejection, teaching |
| `content` | TEXT | The feedback text |
| `created_at` | TEXT | Timestamp |

## Gateway Events

| Event | When | Data |
|-------|------|------|
| `CHILD_SPAWNED` | New specialist created | child_id, role, port |
| `CHILD_STARTED` | Specialist process started | child_id, pid |
| `CHILD_STOPPED` | Specialist stopped | child_id, reason |
| `CHILD_REPORT` | Specialist reports results | child_id, task, result |
| `CHILD_FEEDBACK` | Master sends feedback | child_id, approved, feedback |

## Relationship to Existing Systems

### vs Agent Swarm (Phase 25)

| Aspect | Swarm | Organization |
|--------|-------|-------------|
| What it spawns | External agents (Claude Code, Codex) | Full EloPhanto instances |
| Domain | Coding tasks only | Any domain |
| Communication | One-way (tmux send-keys) | Bidirectional (gateway) |
| Persistence | Ephemeral (task → done) | Persistent (reuse + grow) |
| Learning | None | Approval/rejection → knowledge |
| Identity | None (external tool) | Own identity + first awakening |
| Autonomy | None | Own autonomous mind |

Both systems coexist. Use swarm for coding tasks. Use organization for domain specialists.

### vs Autonomous Mind (Phase 26)

The autonomous mind runs in the master AND in each child. The difference:
- **Master's mind**: CEO-level — prioritizes goals, delegates, reviews child reports
- **Child's mind**: Domain-level — works within specialist boundaries, reports to master

## Pre-Built Role Templates

75 organization role templates are available in `knowledge/organization-roles/`, adapted from [msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents) (Apache 2.0). Each template provides a complete persona definition — identity, capabilities, workflows, deliverable templates, and success metrics.

When spawning a specialist, reference a role template:

```
organization_spawn role="design-brand-guardian"
organization_spawn role="marketing-growth-hacker"
organization_spawn role="testing-reality-checker"
```

The role template seeds the child's identity and knowledge vault during first awakening. Available roles span 10 divisions:

| Division | Count | Examples |
|---|---|---|
| Design | 8 | brand-guardian, ui-designer, ux-architect, visual-storyteller |
| Engineering | 11 | backend-architect, frontend-developer, devops-automator, security-engineer |
| Marketing | 11 | growth-hacker, content-creator, twitter-engager, tiktok-strategist |
| Product | 4 | feedback-synthesizer, sprint-prioritizer, trend-researcher |
| Project Management | 5 | studio-producer, project-shepherd, experiment-tracker |
| Support | 6 | analytics-reporter, infrastructure-maintainer, support-responder |
| Testing | 8 | reality-checker, evidence-collector, api-tester, performance-benchmarker |
| Specialized | 9 | agents-orchestrator, data-analytics-reporter, developer-advocate |
| Spatial | 6 | visionos-spatial-engineer, xr-immersive-developer, macos-spatial-metal-engineer |
| Strategy | 7 | phase-0-discovery through phase-6-operate |

## Security

- **API key isolation**: Children inherit LLM API keys but NOT vault secrets
- **Budget isolation**: Each child has its own daily limit (allocated from master's budget)
- **Knowledge isolation**: Each child has its own knowledge dir (seeded, then independent)
- **Process isolation**: Each child runs as a separate Python process
- **Auth tokens**: Parent-child gateway connections use shared secrets
- **No cross-child access**: Children cannot talk to each other directly (only through master)

## Implementation Phases

1. **Self-Spawn Foundation** — OrganizationManager, config derivation, knowledge seeding, DB schema, tools ✅
2. **Bidirectional Communication** — ParentChannelAdapter, protocol events, parent config ✅
3. **Teaching & Learning** — Feedback loop, correction knowledge files, trust scoring ✅
4. **Delegation Intelligence** — System prompt context (`_TOOL_ORGANIZATION`), LLM-driven routing ✅
5. **Child Autonomy** — Autonomous mind → parent reporting via `_report_to_parent()` ✅
