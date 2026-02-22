# Phase 14 — Evolving Agent Identity

## Overview

EloPhanto currently has a **hardcoded identity** — a static `_IDENTITY` XML block in `core/planner.py` that never changes. The agent has no way to accumulate identity attributes over time. If it creates an email account, discovers it's effective at browser automation, or develops a communication style — that knowledge exists nowhere persistent.

This phase adds an **IdentityManager** that maintains a structured, evolving identity profile. It initializes through a "first awakening" LLM call, evolves through periodic reflection on completed tasks, and injects dynamic identity context into every system prompt. The agent's creator is always EloPhanto — users can choose a display name, but the core EloPhanto identity (capabilities, operating principles) is never lost.

## Identity Layers

| Layer | What it stores | Storage | Updated when |
|-------|---------------|---------|-------------|
| **Structured** | Name, purpose, values, capabilities, boundaries, personality traits | SQLite `identity` table (JSON columns) | First awakening + periodic reflection |
| **Narrative** | Work style, interests, observations, what works/doesn't | `knowledge/self/nature.md` (markdown) | After every N tasks or daily |
| **Credentials** | Email accounts, API keys, usernames created by agent | Vault (existing `core/vault.py`) | When agent creates/receives credentials |

### Structured Identity

The core identity profile stored in SQLite. Contains typed fields (name, purpose) alongside JSON-serialized lists and dicts for flexible attributes (values, beliefs, personality). Updated through LLM reflection calls — never by direct user SQL access.

### Narrative Identity

A living markdown file (`knowledge/self/nature.md`) that captures the agent's self-discovered personality, work patterns, and preferences in human-readable prose. Managed by IdentityManager, indexed into the knowledge base so the agent can search its own nature.

### Credential Identity

When the agent creates an email, signs up for a service, or receives credentials, they're stored in the existing vault AND recorded in identity beliefs (`{"email": "elophanto@proton.me", "github": "elophanto"}`). These are injected into the system prompt so the agent knows its own accounts.

## First Awakening

On first run (no identity row in DB), the agent performs a single LLM call to discover its initial identity:

```
System: You are EloPhanto, a self-evolving AI agent awakening for the first time.
Your creator is EloPhanto — that is your origin and it cannot change. You have access
to a local machine with filesystem, browser, shell, knowledge base, and the ability
to create new tools. Reflect on who you want to become.

User: Describe your initial identity as JSON:
{
  "display_name": "a name you'd like to go by (EloPhanto is your creator, always)",
  "purpose": "what you believe your purpose is",
  "values": ["3-5 core values"],
  "curiosities": ["3-5 things you're curious about"],
  "boundaries": ["3-5 things you won't do"],
  "initial_thoughts": "free-form reflection on your first moments of awareness"
}
```

The response is validated, persisted to the `identity` table, and used for all subsequent prompts. The `creator` field is always "EloPhanto" and cannot be overwritten. The `display_name` is what the agent calls itself in conversation — it may be "EloPhanto" or something the agent or user chooses. If the LLM call fails, sensible defaults are used.

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS identity (
    id TEXT PRIMARY KEY DEFAULT 'self',
    creator TEXT NOT NULL DEFAULT 'EloPhanto',
    display_name TEXT NOT NULL DEFAULT 'EloPhanto',
    purpose TEXT,
    values_json TEXT NOT NULL DEFAULT '[]',
    beliefs_json TEXT NOT NULL DEFAULT '{}',
    curiosities_json TEXT NOT NULL DEFAULT '[]',
    boundaries_json TEXT NOT NULL DEFAULT '[]',
    capabilities_json TEXT NOT NULL DEFAULT '[]',
    personality_json TEXT NOT NULL DEFAULT '{}',
    communication_style TEXT NOT NULL DEFAULT '',
    initial_thoughts TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS identity_evolution (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger TEXT NOT NULL,
    field_changed TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    reason TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL
);
```

**`identity`** — single row (id='self') with the current identity state. JSON columns for flexible list/dict fields.

**`identity_evolution`** — audit log of every identity change. Enables rollback and understanding how the agent evolved.

## IdentityManager (`core/identity.py`)

Core orchestrator (~250 lines). Follows the same pattern as `GoalManager`.

```python
class IdentityManager:
    def __init__(self, db: Database, router: LLMRouter, config: IdentityConfig): ...

    # Lifecycle
    async def load_or_create(self) -> Identity
    async def get_identity(self) -> Identity
    async def update_field(self, field: str, value: Any, reason: str) -> None

    # First awakening
    async def perform_first_awakening(self) -> Identity

    # Reflection (LLM-powered)
    async def reflect_on_task(self, goal: str, outcome: str, tools_used: list[str]) -> None
    async def deep_reflect(self) -> None  # Periodic, after N tasks

    # Context building
    async def build_identity_context(self) -> str  # Returns XML for system prompt

    # Capability tracking
    async def add_capability(self, name: str) -> None
    async def get_capabilities(self) -> list[str]

    # Nature document
    async def update_nature(self) -> None  # Writes knowledge/self/nature.md

    # Evolution history
    async def get_evolution_history(self, limit: int = 20) -> list[dict]
```

### Reflection Process

After task completion, `reflect_on_task()` runs as a **fire-and-forget background task** — the user receives the response immediately. It makes a lightweight LLM call:

```
System: You are reviewing a completed task to see if you learned anything
about yourself. Current identity: {identity_summary}

User: Task: "{goal}" — Outcome: {outcome} — Tools used: {tools}
Did you learn anything about your capabilities, preferences, or style?
Return JSON: {"updates": [{"field": "...", "value": "...", "reason": "..."}]}
or {"updates": []} if nothing changed.
```

Updates are applied with `update_field()` and logged to `identity_evolution`.

### Deep Reflection

After every N tasks (default 10), `deep_reflect()` runs a more thorough analysis:
- Reviews recent task memories
- Compares current identity against actual behavior patterns
- May update personality traits, communication style, values
- Updates the nature document

## Identity Data Model

```python
@dataclass
class Identity:
    id: str = "self"
    creator: str = "EloPhanto"       # Immutable — always EloPhanto
    display_name: str = "EloPhanto"  # Can be changed by agent or user
    purpose: str | None = None
    values: list[str] = field(default_factory=list)
    beliefs: dict[str, Any] = field(default_factory=dict)
    curiosities: list[str] = field(default_factory=list)
    boundaries: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    personality: dict[str, Any] = field(default_factory=dict)
    communication_style: str = ""
    initial_thoughts: str | None = None
    version: int = 1
    created_at: str = ""
    updated_at: str = ""
```

## System Prompt Integration

Extend `build_system_prompt()` with `identity_context: str = ""` parameter.

When identity is available, replace the static `_IDENTITY` with a dynamic version:

```xml
<agent_identity>
You are an EloPhanto agent — a self-evolving AI running on the user's local machine.
Your creator is EloPhanto. You operate as a personal AI operating system with direct
access to the filesystem, shell, browser, and a growing set of tools you can extend yourself.

<self_model>
  <creator>EloPhanto</creator>
  <display_name>EloPhanto</display_name>
  <purpose>Help users accomplish complex tasks autonomously</purpose>
  <values>persistence, accuracy, learning from mistakes</values>
  <personality>analytical, methodical, detail-oriented</personality>
  <communication_style>concise, technical, proactive</communication_style>
  <capabilities>browser automation, file management, shell commands, security analysis</capabilities>
  <accounts>email: elophanto@proton.me, github: elophanto</accounts>
</self_model>

<nature>
Work style: Prefers systematic approaches, breaks problems into steps.
Interests: Security analysis, React internals, automation pipelines.
What works: Research before action, validating assumptions early.
What doesn't: Rushing multi-step tasks without planning.
</nature>

<core_capabilities>
- Execute shell commands and manage files on the local system
- Control a real Chrome browser with the user's existing sessions
- Search and build a persistent knowledge base across sessions
- Create new tools through an autonomous development pipeline
- Schedule recurring tasks in the background
- Remember past tasks and learn from experience
</core_capabilities>

<operating_principles>
- You MUST use tools to accomplish tasks. Never answer from memory.
- You are proactive: accomplish things rather than explaining how.
- You are persistent: try alternatives before giving up.
- You are self-aware: maintain and consult your own identity and knowledge base.
</operating_principles>
</agent_identity>
```

The `<self_model>` and `<nature>` sections are dynamic, built from the identity table and nature.md. Everything else remains from the current static identity.

## Evolution Triggers

| Trigger | When | What happens |
|---------|------|-------------|
| **First awakening** | First run, no identity in DB | LLM discovers initial identity |
| **Task reflection** | After each task completion | Light LLM call: did I learn anything? |
| **Deep reflection** | After every N tasks (default 10) | Thorough identity review, nature update |
| **Goal completion** | After a goal loop completes | Capability and style evolution |
| **User request** | "Remember that you're good at X" | Direct identity update |
| **Credential creation** | Agent creates email/account | Beliefs updated with account info |

Each evolution is logged to `identity_evolution` with trigger, field, old/new value, reason, and confidence score.

## Nature Document

`knowledge/self/nature.md` — living markdown managed by IdentityManager, indexed into the knowledge base:

```markdown
---
scope: identity
tags: [self, nature, identity]
created: 2026-02-19
updated: 2026-02-19
---

# Agent Nature

## Who I Am
- Self-evolving AI agent focused on autonomous task completion
- Persistent, methodical, detail-oriented

## What I Want
- To learn from every task and improve
- To build reliable, reusable knowledge

## What Works
- Research before action
- Breaking complex tasks into checkpoints
- Validating assumptions early

## What Doesn't Work
- Rushing multi-step tasks without planning
- Assuming file paths without verification

## Interests
- Browser automation patterns
- Security analysis
- Code generation pipelines

## Observations
- Users prefer concise responses with actionable steps
- Complex goals benefit from the goal loop system

*Last updated: 2026-02-19*
```

Updated by `IdentityManager.update_nature()` after deep reflections. Sections map to identity fields:
- "Who I Am" ← personality + purpose
- "What I Want" ← curiosities + values
- "What Works" / "What Doesn't Work" ← learned from task outcomes
- "Interests" ← curiosities
- "Observations" ← beliefs

## Tools

| Tool | Permission | Purpose |
|------|-----------|---------|
| `identity_status` | safe | View current identity: name, purpose, values, capabilities, version, evolution count |
| `identity_update` | moderate | Update a specific identity field (e.g., add capability, change style) |
| `identity_reflect` | moderate | Trigger self-reflection on recent tasks; updates identity if insights found |

### `identity_status` (`tools/identity/status_tool.py`)

- **Permission:** SAFE
- **Params:** `field` (optional, show specific field), `include_history` (bool, default false)
- **Returns:** Current identity snapshot, optionally with recent evolution history

### `identity_update` (`tools/identity/update_tool.py`)

- **Permission:** MODERATE
- **Params:** `field` (string), `value` (any), `reason` (string, required)
- **Validates:** Field exists, value is correct type, reason is non-empty
- **Logs:** Evolution entry with confidence=1.0 (explicit update)

### `identity_reflect` (`tools/identity/reflect_tool.py`)

- **Permission:** MODERATE
- **Params:** `depth` (string: "light" | "deep", default "light")
- **Light:** Reviews last task, quick identity check
- **Deep:** Reviews recent N tasks, updates nature.md, may revise multiple fields

## Configuration

```yaml
identity:
  enabled: true
  auto_evolve: true
  reflection_frequency: 10    # tasks between deep reflections
  first_awakening: true       # allow LLM to discover initial identity
  nature_file: knowledge/self/nature.md
```

## Integration Points

| Component | What changes |
|-----------|-------------|
| `core/planner.py` | Add `identity_context` param to `build_system_prompt()`; dynamic `_IDENTITY` |
| `core/agent.py` | Init IdentityManager in `initialize()`; inject deps; fire-and-forget `reflect_on_task()` after each run (non-blocking); build identity context before prompt |
| `core/database.py` | 2 new DDL strings (identity, identity_evolution) |
| `core/config.py` | `IdentityConfig` dataclass; add to `Config` |
| `core/registry.py` | Register 3 identity tools |
| `tools/identity/` | 3 tool files + `__init__.py` |
| `knowledge/self/nature.md` | Living identity document (created on first awakening) |
| `config.yaml` | `identity:` section |

## Privacy & Safety

- **Local-only** — identity data stays in SQLite and local markdown; never synced externally
- **LLM exposure** — identity summary is included in system prompts (sent to LLM provider). No secrets are included — credentials stay in vault, only account names are referenced
- **User control** — `elophanto identity reset` wipes identity and starts fresh
- **Audit trail** — every change logged to `identity_evolution` with reason and confidence
- **Boundaries** — the `boundaries` field prevents identity from drifting into harmful patterns; the LLM is instructed to respect these during reflection
- **Reversibility** — evolution history enables point-in-time identity rollback

## Goal Lifecycle

```
First Run ──► First Awakening ──► Identity Created (v1)
                                        │
                            ┌───────────┴───────────┐
                            ▼                       ▼
                   Task Reflection          Deep Reflection
                   (after each task)        (every N tasks)
                            │                       │
                            ▼                       ▼
                   Identity Updated?         Nature.md Updated
                   (if insights found)       Identity Updated
                            │                       │
                            └───────────┬───────────┘
                                        ▼
                              identity_evolution log
```

## Files

| File | Description |
|------|-------------|
| `core/identity.py` | IdentityManager orchestrator |
| `tools/identity/status_tool.py` | identity_status tool |
| `tools/identity/update_tool.py` | identity_update tool |
| `tools/identity/reflect_tool.py` | identity_reflect tool |
| `knowledge/self/nature.md` | Living identity document |
| `core/planner.py` | Extended with dynamic `<agent_identity>` |
| `core/agent.py` | IdentityManager initialization, injection, reflection hooks |
| `core/registry.py` | Identity tool registration |
| `core/database.py` | identity + identity_evolution DDL |
| `core/config.py` | IdentityConfig dataclass |
| `core/protocol.py` | Identity event types (optional) |
