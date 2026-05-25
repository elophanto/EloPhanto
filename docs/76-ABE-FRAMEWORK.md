# 76 — ABE Framework: EloPhanto as an Autonomous Business Entity

**Status**: Plan · **Owner**: Petr Royce + Claude + GPT-5.5 · **Started**: 2026-05-24

> **Concept attribution**: The Autonomous Business Entity (ABE) framing —
> EloPhanto playing one identity that wears role masks, with a general
> typed ledger as the honest progress signal, missions as role mandates,
> product YAML as the steering anchor, and verification-first phased
> rollout — was originated by **Petr Royce** in 2023. The
> implementation in this codebase (Phases 1-8) was built collaboratively
> in May 2026 with Claude and GPT-5.5 to Petr's design.

> **Re-reading this doc**: jump to **Current Status** at the bottom for what's
> done and what's next. The body is the design contract — re-read top to
> bottom before starting any new phase so the load-bearing constraints
> (single identity, general ledger, reuse-first) stay in front of you.

## Verification failure log

Recording the verification gaps that surfaced after a phase was
declared "done." Each entry is an institutional-memory artifact —
the corresponding rule below is the durable lesson.

| Date | Phase | Symptom | Root cause | Rule that would have caught it |
|---|---|---|---|---|
| 2026-05-25 | 1-7 | Operator-side CLI worked; chat-side agent had no ABE tools | Built CLI commands without matching agent tools; chat operator can't drive ABE | **Check operator surface AND agent surface before declaring a phase shipped** |
| 2026-05-25 | Awareness fix (post-Phase 8) | Agent kept reconstructing "companies" from memory after the awareness-block patch | `personality.items()` crashed `build_identity_context` on the live DB (personality was a string, not a dict); `try/except: pass` in `Agent._build_prompt` swallowed it; entire identity injection was empty for production | **Test the fix against the live data shape, not just synthetic fixtures** + **silent excepts around prompt assembly hide production bugs** |
| 2026-05-25 | 2/7/8 | `company_list` returned "not initialized" even after awareness fix; ABE init silently never ran in the agent process | `self._project_root` referenced in Agent init but Agent only sets `self._config.project_root` — AttributeError swallowed by a try/except at the goal-init outer boundary; role_manager, company_manager, and every ABE tool's deps stayed None | **Integration test that exercises `Agent.initialize()` end-to-end** + **silent try/except around init code is the same anti-pattern as around prompt assembly — convert ALL such swallows to logged warnings with exc_info=True** |

**The unified pattern across all three**: silent partial-init or
silent injection failure looks identical to "feature didn't ship"
from the operator's seat. Synthetic-fixture unit tests pass; the
agent's actual init path is the one that breaks. The fix in every
case is logging + integration tests against `Agent.initialize()`,
NOT a smarter unit test of the new code in isolation.

## Process rule (non-negotiable)

**Before writing ANY code for a phase, do a detailed verification review
and expand that phase's section in this doc with the verified specifics.**

What this means concretely, for every phase:

0. **Grep for `try/except: pass` and `try/except Exception:` around any
   code path the phase touches.** Silent excepts hide load-bearing
   bugs that look exactly like "feature didn't ship" — see the
   Verification failure log above. Convert every such swallow to
   `logger.warning(..., exc_info=True)` BEFORE adding new logic
   inside or near it.
1. **Read the actual code** the phase touches — not what an audit said,
   not what feels right. Open `core/database.py`, `core/identity.py`,
   `core/mission_manager.py`, etc., and confirm constructor signatures,
   table columns, and migration patterns first-hand.
2. **Open the live SQLite DB** and verify table shapes / row counts /
   FK behavior. Audits can be optimistic; the DB is authoritative.
3. **Write the expanded phase section in this doc**: exact migration
   SQL with up/down, exact interface signatures (`CompanyContext.x()`,
   `IdentityManager.with_role(...)`), exact file edits with line refs,
   test approach, and explicit "things that turned out different from
   the original plan" callouts.
4. **Get explicit go-ahead** from Petr before starting implementation.
5. **Only then** write code.

If verification surfaces something that breaks the design contract
(decisions A–F), stop and update the contract section — do not silently
work around it.

The doc must always reflect what we will actually build, not what we
thought we'd build at design time. **A wrong contract is worse than no
contract.**

---

## Why this exists

EloPhanto today is a self-evolving AI agent that does tasks. The next step
is for it to act as an **Autonomous Business Entity (ABE)** — a small,
focused company-of-roles that:

- has a stated product/service
- tracks its own books (revenue in, cost out, runway)
- manages a customer pipeline
- assigns work to role personas (sales, support, ops, marketing)
- reports to the operator as a board, not as raw logs
- runs **multiple isolated companies** on one runtime

This is the realistic version of the ABE concept — **not** the marketing
version ("zero employees, infinite scale, 70% margins, unicorn exits").
The infinite-scale framing produces Evidence Gardens. We are building one
operator running a small focused company-of-agents that does one bounded
thing and tracks its own books. If the work starts drifting toward
"AI replaces all employees" — stop and re-read this paragraph.

## Load-bearing design decisions

These are the constraints. Every later choice must respect them.

### A. EloPhanto IS the CEO. Single evolving identity, roles as overlays.

There is **one identity** — EloPhanto's. It evolves over time as it does
today. The CEO is not a separate persona; **EloPhanto plays the CEO** by
default. Other roles (sales, support, ops, marketing, finance, legal) are
**system-prompt overlays + tool subsets** the mind switches into per cycle.

- ❌ Do not create N identities
- ❌ Do not create N agents
- ✅ One identity, current_role attribute, prompt overlay layered at runtime
- ✅ Role context is ephemeral; identity evolution is permanent

### B. The ledger is general, not "books".

Money is one resource flow. LLM tokens are another. Time spent in role-X
is another. Customer touches are another. Build **one typed ledger** that
all of these write to. This is also the **honest progress signal** that
fixes the "bounded reconciliation" loop documented in
[`docs/75-AUTONOMOUS-MIND-V2.md`](75-AUTONOMOUS-MIND-V2.md) — if no
ledger event fires in a cycle, the goal didn't make progress, regardless
of what the LLM narrates.

- ❌ Do not build a separate "books" / accounting module
- ❌ Do not build a separate cost-tracking module
- ✅ `resource_ledger` table; `type` discriminates (`usd`, `tokens`, `email_sent`, `pipeline_advance`, ...)
- ✅ Every meaningful action writes a ledger event; goal progress = ledger delta

### C. `company_id` is the single isolation key.

One column threaded through everything. Default company `elophanto-self`
owns all existing rows via a one-shot migration so old code keeps working.

- ✅ Add `company_id` column (DEFAULT `'elophanto-self'`) on: `sessions`, `missions`, `goals`, `scheduled_tasks`, `llm_usage`, `payment_audit`, `payment_requests`, `email_log`, `prospects`, `outreach_log`
- ✅ Integrity enforced in app code, not SQLite (verified 2026-05-25: `PRAGMA foreign_keys=0` in live DB; codebase convention is "FK is informational" — see `core/database.py:800-802`). No `REFERENCES` clause needed.
- ❌ Do not invent a separate tenancy / workspace / org abstraction

### D. Mission IS the mandate.

`missions` already exists with priority weight + momentum decay. Add
`owner_role` and you have role-scoped mandates. CEO (= EloPhanto) creates a
mission `owner_role='sales'` ("grow qualified pipeline to 50/wk"); the
sales role's cycles operate against it.

- ❌ Do not invent a `mandates` table
- ✅ `missions.owner_role` column, nullable (null = CEO/EloPhanto)

### E. Roles are NOT plugins.

Plugins are heavy (dir + schema.json + python). Roles need a ~20-line YAML
each. They are config, not code.

- ✅ `roles/<name>.yaml` files + a `roles` table seeded from them
- ❌ Do not put roles in `plugins/`

### F. Product config = YAML file, not table.

Mirrors how `skills/` and `plugins/` already work. One file per company:
`companies/<slug>/company.yaml`. Read on demand. If `what_we_sell` is
empty, the company refuses to activate — empty product = navel-gazing
risk reborn.

- ✅ `companies/<slug>/company.yaml` (the only per-company config surface)
- ❌ Do not build a `company_config` key-value table

---

## What the audit found (the reuse map)

A full codebase audit on 2026-05-25 confirmed: **11 of 16 areas extend
in-place; 5 need new schema/UI**. No architectural rewrites needed.

| Area | Verdict | Action |
|---|---|---|
| Identity & evolution (`core/identity.py`) | EXTEND | add `role_persona` column |
| Missions (`core/mission_manager.py`) | EXTEND | add `owner_role` column |
| Goals (`core/goal_manager.py`) | EXTEND | add `assigned_to_role` column |
| Skills (`core/skills.py`) | REUSE | roles compose skill tags |
| Tool registry + per-call permission (`core/executor.py`) | EXTEND | pass `current_role` to `approval_callback` |
| Sessions (`core/session.py`) | EXTEND | add `company_id` FK |
| Channels (`channels/*`, `core/gateway.py`) | EXTEND | route by `company_id` on `ClientConnection` |
| Scheduler (`core/scheduler.py`) | EXTEND | add `owner_role` column |
| LLM cost tracking (`llm_usage`) | EXTEND | add `company_id`; mirror to ledger |
| Email (`tools/email/*`, `email_log`) | EXTEND | add `company_id` |
| Payments (`tools/payments/*`, `payment_audit`, `payment_requests`) | EXTEND | add `company_id` |
| CRM (`prospects`, `outreach_log` — already exist!) | EXTEND | add `company_id` + stage enum |
| Dream / arbiter (`core/mind_arbiter.py`) | EXTEND | add `from_role_neglect` candidate source |
| Config (`core/config.py`) | REUSE | per-company config = YAML file, not table |
| Plugins (`core/plugin_loader.py`) | REUSE | unchanged |
| Dashboard (`cli/dashboard/app.py`) | EXTEND | add `CompanyBoardPanel` + company selector |
| **`companies` table** | NEW | `(id, slug, name, status, product_yaml_path, created_at)` |
| **`roles` table** | NEW | `(role_name, prompt_overlay, skill_tags, kpi_json, scope)` |
| **`resource_ledger` table** | NEW | `(company_id, ts, direction, type, amount, unit, source_table, source_id)` |

**Total new tables: 3. New columns on existing tables: 4 + 10 FK additions.**

## Things we explicitly DO NOT build

If you find yourself doing one of these, stop and re-read the design
decisions above. Each was rejected for a specific reason.

- ❌ A CRM module — extend existing `prospects` + `outreach_log`
- ❌ A books / accounting module — `resource_ledger` is general
- ❌ A per-tenant config DB table — `companies/<slug>/company.yaml`
- ❌ Separate role agents / identities — one identity, role overlay
- ❌ A new arbiter — extend `mind_arbiter.py` with `from_role_neglect`
- ❌ A new dashboard — add panels to existing one
- ❌ A new scheduler — extend `scheduled_tasks` with `owner_role`
- ❌ A new permission system — pass `current_role` through `approval_callback`
- ❌ An external "company API" / orchestration layer — operator interacts via existing channels

## Schema delta (minimal)

```sql
-- NEW
CREATE TABLE companies (
  id           TEXT PRIMARY KEY,    -- slug; default 'elophanto-self'
  name         TEXT NOT NULL,
  status       TEXT NOT NULL,       -- 'active' | 'paused' | 'archived'
  product_yaml TEXT,                -- relative path to companies/<slug>/company.yaml
  created_at   INTEGER NOT NULL
);

CREATE TABLE roles (
  role_name        TEXT PRIMARY KEY,
  prompt_overlay   TEXT NOT NULL,
  skill_tags       TEXT NOT NULL,   -- JSON array
  kpi_json         TEXT,            -- JSON object
  scope            TEXT NOT NULL    -- 'global' | 'company'
);

CREATE TABLE resource_ledger (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id   TEXT NOT NULL REFERENCES companies(id),
  ts           INTEGER NOT NULL,
  direction    TEXT NOT NULL,        -- 'in' | 'out'
  type         TEXT NOT NULL,        -- 'usd' | 'tokens' | 'email_sent' | 'pipeline_advance' | ...
  amount       REAL NOT NULL,
  unit         TEXT NOT NULL,        -- 'usd' | 'tok' | 'count' | 'min'
  source_table TEXT,                 -- e.g. 'llm_usage'
  source_id    INTEGER,              -- pointer back to origin row
  role_name    TEXT,                 -- which role booked this, if any
  note         TEXT
);
CREATE INDEX idx_ledger_company_ts ON resource_ledger(company_id, ts);
CREATE INDEX idx_ledger_company_type ON resource_ledger(company_id, type);

-- EXTEND (new columns on existing tables)
ALTER TABLE identity         ADD COLUMN role_persona TEXT;          -- nullable, current role
ALTER TABLE missions         ADD COLUMN owner_role TEXT;            -- nullable, null = CEO/EloPhanto
ALTER TABLE goals            ADD COLUMN assigned_to_role TEXT;      -- nullable
ALTER TABLE scheduled_tasks  ADD COLUMN owner_role TEXT;            -- nullable
-- NOTE: `prospects.status` already exists (DEFAULT 'new'). Reuse it
-- for stage with the enum: new | qualified | opportunity | customer | lost.
-- Do NOT add a parallel `stage` column. (Verified 2026-05-25.)

-- EXTEND (company_id FK on 10 tables; one migration adds all)
-- Each gets: ALTER TABLE <t> ADD COLUMN company_id TEXT
--            REFERENCES companies(id) DEFAULT 'elophanto-self';
-- Tables: sessions, missions, goals, scheduled_tasks, llm_usage,
--         payment_audit, payment_requests, email_log, prospects, outreach_log
```

---

## Phased rollout (in leverage order)

Each phase is an independent merge. Do not start a phase before the
previous one is in.

### Phase 1 — Company scope + ledger (the foundation) — VERIFIED 2026-05-25

Without this everything else is fiction.

#### Verification findings (deltas from the original plan)

The verification pass on 2026-05-25 read `core/database.py`,
`core/identity.py`, `core/mission_manager.py`, `core/goal_manager.py`,
`core/session.py`, `core/scheduler.py`, `core/executor.py`,
`core/router.py`, `core/payments/audit.py`, `tools/email/*`, and the
live SQLite DB. Confirmed facts (so we don't re-verify these):

1. **FK enforcement is OFF.** Live DB has `PRAGMA foreign_keys = 0`; the
   ON pragma is set per-connection inside [`_init_sync`](../core/database.py)
   but the convention is "FK is informational — SQLite enforces only
   when foreign_keys pragma is on; we don't depend on cascade" (comment
   at `core/database.py:800-802`). **Consequence**: new `company_id`
   columns are plain `ADD COLUMN … NOT NULL DEFAULT 'elophanto-self'`.
   No `REFERENCES` clause needed; integrity enforced in app code.
2. **Migration pattern is two Python lists** in `core/database.py`:
   `_SCHEMA` (CREATE TABLE IF NOT EXISTS, runs first) and `_MIGRATIONS`
   (idempotent ALTER TABLEs, "duplicate column name" silently swallowed
   at lines 849-854). Extending both lists IS the migration. No
   versioned migrations directory, no schema_version table.
3. **`goals.mission_id` already exists** (added at `core/database.py:803`
   for mind v2). So Phase 1 only adds `assigned_to_role` to goals.
4. **`prospects.status` already exists** with `DEFAULT 'new'`. **The
   original plan called for a new `stage` column — DROP that.** Reuse
   the existing `status` column with the enum
   `new | qualified | opportunity | customer | lost`. Phase 3 will
   formalise the enum; Phase 1 just adds `prospects.company_id`.
5. **`approval_callback` is positional**: `(tool_name, description, params) -> bool`,
   set via `Executor.set_approval_callback` (`core/executor.py:123-130`),
   called at `core/executor.py:462-464`. **Adding a positional `role`
   would break every existing caller.** Use a `contextvars.ContextVar`
   for current_role + company_id instead — the executor reads from
   context, callback signature unchanged.
6. **`sessions` table has `UNIQUE(channel, user_id)`** (`core/database.py:125`).
   SQLite cannot drop a UNIQUE constraint via ALTER. **For Phase 1 we
   leave the constraint alone** and scope by `company_id` in app code
   (3 sessions live; collision risk negligible). A proper table-rebuild
   migration is **deferred to Phase 6** (multi-company hardening).
7. **`MissionManager.create`** signature is
   `(title, description, priority_weight, *, mission_id)` — keyword-only
   tail. Adding `owner_role: str | None = None` as another kw-only is
   non-breaking (Phase 2).
8. **`GoalManager.create_goal`** signature is
   `(goal, session_id, *, mission_id)` — same pattern. Adding
   `assigned_to_role: str | None = None` is non-breaking (Phase 2).
9. **`IdentityManager.__init__`** = `(db, router, config, agent_name="EloPhanto")`
   (`core/identity.py:193-217`). Singleton row at `id='self'`. Phase 1
   does NOT touch identity (role_persona lands in Phase 2).
10. **Live row counts**: `llm_usage` = 12,968; `payment_audit` = 30;
    `email_log` = 187; `scheduled_tasks` = 45; `sessions` = 3;
    `prospects` / `outreach_log` / `goals` / `missions` / `payment_requests` = 0.
    All non-zero tables backfill via a single `UPDATE … SET company_id
    = 'elophanto-self' WHERE company_id IS NULL`. The `DEFAULT` on
    the column makes the backfill effectively free for new rows.

#### Schema delta (Phase 1 only)

Add to `_SCHEMA` in `core/database.py` (place near related tables):

```sql
-- After the `missions` block:
CREATE TABLE IF NOT EXISTS companies (
    id TEXT PRIMARY KEY,                      -- slug; e.g. 'elophanto-self'
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','paused','archived')),
    product_yaml TEXT,                        -- rel path to companies/<slug>/company.yaml
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resource_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id TEXT NOT NULL,
    ts TEXT NOT NULL,                          -- ISO8601 UTC
    direction TEXT NOT NULL CHECK (direction IN ('in','out')),
    type TEXT NOT NULL,                        -- 'usd' | 'tokens' | 'email_sent' | 'pipeline_advance' | 'decision' | ...
    amount REAL NOT NULL,
    unit TEXT NOT NULL,                        -- 'usd' | 'tok' | 'count' | 'min'
    source_table TEXT,                         -- e.g. 'llm_usage', 'payment_audit', 'email_log'
    source_id INTEGER,                         -- rowid in source_table
    role_name TEXT,                            -- which role booked it (Phase 2 fills this)
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_ledger_company_ts ON resource_ledger(company_id, ts);
CREATE INDEX IF NOT EXISTS idx_ledger_company_type ON resource_ledger(company_id, type);
```

Append to `_MIGRATIONS` in `core/database.py` (each line is independent;
idempotent via existing try/except):

```python
# ABE Phase 1 — company_id on every multi-tenant table.
# DEFAULT 'elophanto-self' so existing 12,968 llm_usage rows etc.
# attribute correctly without a separate backfill UPDATE.
"ALTER TABLE sessions         ADD COLUMN company_id TEXT NOT NULL DEFAULT 'elophanto-self'",
"ALTER TABLE missions         ADD COLUMN company_id TEXT NOT NULL DEFAULT 'elophanto-self'",
"ALTER TABLE goals            ADD COLUMN company_id TEXT NOT NULL DEFAULT 'elophanto-self'",
"ALTER TABLE scheduled_tasks  ADD COLUMN company_id TEXT NOT NULL DEFAULT 'elophanto-self'",
"ALTER TABLE llm_usage        ADD COLUMN company_id TEXT NOT NULL DEFAULT 'elophanto-self'",
"ALTER TABLE payment_audit    ADD COLUMN company_id TEXT NOT NULL DEFAULT 'elophanto-self'",
"ALTER TABLE payment_requests ADD COLUMN company_id TEXT NOT NULL DEFAULT 'elophanto-self'",
"ALTER TABLE email_log        ADD COLUMN company_id TEXT NOT NULL DEFAULT 'elophanto-self'",
"ALTER TABLE prospects        ADD COLUMN company_id TEXT NOT NULL DEFAULT 'elophanto-self'",
"ALTER TABLE outreach_log     ADD COLUMN company_id TEXT NOT NULL DEFAULT 'elophanto-self'",
```

Seed `elophanto-self` in `Database._init_sync` after the migrations run:

```python
# Seed default company; idempotent.
self._conn.execute(
    "INSERT OR IGNORE INTO companies (id, name, status, created_at, updated_at) "
    "VALUES ('elophanto-self', 'EloPhanto (self)', 'active', ?, ?)",
    (now_iso, now_iso),
)
self._conn.commit()
```

#### New code files (Phase 1)

**`core/company.py`** — context + manager (target ~150 LOC):

```python
import contextvars
from dataclasses import dataclass

# Module-level context var. Defaults to elophanto-self so any code
# path that forgets to set it gets safe behavior, not a crash.
_current_company: contextvars.ContextVar[str] = contextvars.ContextVar(
    "elophanto_company_id", default="elophanto-self"
)

def current_company_id() -> str:
    return _current_company.get()

def set_current_company(company_id: str) -> contextvars.Token:
    return _current_company.set(company_id)

@dataclass
class Company:
    id: str
    name: str
    status: str           # 'active' | 'paused' | 'archived'
    product_yaml: str | None
    created_at: str
    updated_at: str

class CompanyManager:
    def __init__(self, db): self._db = db
    async def list(self) -> list[Company]: ...
    async def get(self, company_id: str) -> Company | None: ...
    async def create(self, slug: str, name: str, product_yaml: str | None = None) -> Company: ...
    async def use(self, company_id: str) -> None:
        """Sets the process-wide context var. CLI helper; the mind loop
        sets this per-cycle from the company it's serving."""
```

**`core/ledger.py`** — single writer (target ~100 LOC):

```python
from dataclasses import dataclass
from datetime import datetime, UTC

@dataclass
class LedgerEntry:
    company_id: str
    direction: str       # 'in' | 'out'
    type: str            # 'usd' | 'tokens' | 'email_sent' | 'pipeline_advance' | 'decision'
    amount: float
    unit: str            # 'usd' | 'tok' | 'count' | 'min'
    source_table: str | None = None
    source_id: int | None = None
    role_name: str | None = None
    note: str | None = None

class ResourceLedger:
    def __init__(self, db): self._db = db
    async def write(self, entry: LedgerEntry) -> int: ...        # returns row id
    async def sum(self, company_id: str, *, type: str | None = None,
                  direction: str | None = None,
                  since: str | None = None) -> float: ...
    async def recent(self, company_id: str, limit: int = 50) -> list[dict]: ...
```

**`cli/company_cmd.py`** — CLI surface (target ~80 LOC):

```bash
elophanto company list                       # all companies + status
elophanto company create <slug> [--name X]   # creates row; doesn't activate
elophanto company use <slug>                 # writes ~/.elophanto/current_company
elophanto company current                    # prints active company
```

The "current company" persists across CLI invocations via a file at
`~/.elophanto/current_company` (single line: the slug). Process-wide
contextvar reads it on startup.

#### Existing-file edits (Phase 1)

1. **`core/database.py`**
   - Insert `companies` and `resource_ledger` CREATE TABLE blocks into
     `_SCHEMA` (around line 217, after the `missions` block).
   - Append 10 `ALTER TABLE … ADD COLUMN company_id` lines to `_MIGRATIONS`
     (after line 803).
   - In `_init_sync`, after migrations loop (line ~855), add the
     `INSERT OR IGNORE` seed for `elophanto-self`.

2. **`core/router.py:112-125`** — `CostTracker.flush()` INSERT into
   `llm_usage`. Change to also append two `resource_ledger` rows per
   call: one `(direction='out', type='tokens', unit='tok')`, one
   `(direction='out', type='usd', unit='usd')`. Use the current company
   from `core.company.current_company_id()`. Set
   `source_table='llm_usage'`, `source_id=<new llm_usage rowid>`.

3. **`core/payments/audit.py:39-63`** — `PaymentAudit.log()`. After the
   INSERT, append a `resource_ledger` row with `direction='out'`
   (`payment_type='outbound'` cases) or `direction='in'`
   (`payment_type='inbound'` cases), `type='usd'`, `unit='usd'`,
   `source_table='payment_audit'`. **Do not block on ledger write
   errors** — log a warning, swallow; payment_audit is the source of
   truth.

4. **`tools/email/send_tool.py:257-287`**,
   **`tools/email/reply_tool.py:305`**,
   **`tools/email/create_inbox_tool.py:305`** — after each email_log
   INSERT, append `resource_ledger` row `(direction='out', type='email_sent', unit='count', amount=1, source_table='email_log')`.
   Three call sites; factor out into a helper in `tools/email/_log.py`
   to avoid drift.

5. **No changes** in Phase 1 to: identity, mission_manager, goal_manager,
   scheduler, executor, agent, sessions. Those land in Phases 2-6.

#### Tests (Phase 1)

Create `tests/test_core/test_company.py` and `tests/test_core/test_ledger.py`:

1. `test_default_company_seeded_on_init` — fresh DB has exactly one
   `companies` row with `id='elophanto-self'`.
2. `test_existing_rows_attribute_to_self` — migration preserves
   `llm_usage` row count and stamps all rows with
   `company_id='elophanto-self'`.
3. `test_company_create_and_list` — `CompanyManager.create('test-co', 'Test Co')`
   round-trips through `list()` and `get()`.
4. `test_ledger_write_and_sum` — write 3 entries (one in, two out),
   `sum(direction='in')` returns 1st amount, `sum(type='usd')` returns
   all matching by type.
5. `test_llm_usage_mirrors_to_ledger` — flushing CostTracker creates
   paired ledger rows; sum matches `llm_usage.cost_usd`.
6. `test_email_send_mirrors_to_ledger` — mock email tool; assert
   `type='email_sent'` row appears with `source_id` = email_log row id.
7. `test_current_company_contextvar_default` — `current_company_id()`
   returns `'elophanto-self'` without explicit `set_current_company`.
8. `test_migration_idempotent` — running `_init_sync` twice doesn't
   raise; column count unchanged.

#### Phase 1 acceptance criteria

- All Phase 1 tests pass
- `uv run ruff check` clean, `uv run mypy core/ cli/` clean
- One PR, one migration commit, ~700 LOC including tests
- After merge, running `elophanto company list` shows `elophanto-self`
  with all 12,968 llm_usage rows attributed to it
- `ResourceLedger.sum('elophanto-self', type='usd', direction='out')`
  returns sum of `llm_usage.cost_usd + payment_audit.amount` for
  outbound payments (new rows only — backfilling historical
  `llm_usage` into ledger is deferred to Phase 5 if needed for board)

#### What Phase 1 does NOT include

- ❌ Roles, role_persona, owner_role, assigned_to_role (Phase 2)
- ❌ Backfilling 12,968 historical `llm_usage` rows into the ledger
  (Phase 5 if board view needs it; until then, ledger is forward-only)
- ❌ Sessions UNIQUE constraint rebuild (Phase 6)
- ❌ Per-company data directories (Phase 6)
- ❌ Channel routing by company_id (Phase 6)
- ❌ `companies/<slug>/company.yaml` schema (Phase 4)

---

### Phase 2 — Roles as overlays — VERIFIED 2026-05-25

The architectural lift. EloPhanto plays N roles via system-prompt
overlays + tool subsets; identity stays single and evolving.

#### Verification findings (deltas from the original sketch)

The Phase 2 verification pass read `core/identity.py`, `core/skills.py`,
`core/executor.py`, `core/registry.py`, `core/mission_manager.py`,
`core/goal_manager.py`, `core/planner.py`, `core/mind_candidates.py`,
and `plugins/_template/`. Confirmed facts:

1. **Identity dataclass has no role concept today** — `core/identity.py:71-97`,
   15 fields, all single-self. Adding `role_persona: str | None = None`
   is a clean addition (no existing field to repurpose).
2. **System prompt injection is via `IdentityManager.build_identity_context()`**
   at `core/identity.py:534`, which returns an XML `<self_model>` block
   that `core/planner.py:1894-1895` concatenates into the rendered
   identity section. Role overlay slots in at that build site — we
   add `<role>` to the XML block when `role_persona` is set, plus a
   role-specific prompt overlay loaded from `roles/<name>.yaml`.
3. **Skills have no `tags` or `category` field** (`core/skills.py:156-173`).
   So roles can't reference "skills tagged X" — roles must list
   skills by name. The seed YAML names skills explicitly; if the named
   skill is missing the role loader logs a warning, doesn't crash.
4. **Tool objects have no `tags` either** (`core/registry.py`). Existing
   filter mechanism is `task_groups` on `get_tools_for_context`. The
   minimal Phase 2 design adds `allowed_tools: [list of tool names]`
   AND `allowed_tool_groups: [list of group strings]` to the role,
   so an operator can express either "exact tool list" or "everything
   in these groups." Empty role = no filter (full registry).
5. **`Executor._check_permission()` is the gate point** at
   `core/executor.py:427-466`, called at `core/executor.py:186-187`.
   The role-gate inserts **before** the existing permission logic so
   a role-denied tool short-circuits even if permission_mode would
   auto-approve it. Signature of `approval_callback` stays unchanged
   (positional `(tool_name, description, params) -> bool`); role is
   read from the contextvar Phase 1 established the pattern for.
6. **`MissionManager.create()` is kw-only-tail** at
   `core/mission_manager.py:103-134` — `(title, description, priority_weight, *, mission_id=None)`.
   Adding `owner_role: str | None = None` as another kw-only is
   non-breaking. The INSERT at `core/mission_manager.py:117-122` needs
   one extra column.
7. **`GoalManager.create_goal()` is kw-only-tail** at
   `core/goal_manager.py:177-202` — `(goal, session_id=None, *, mission_id=None)`.
   Same pattern: add `assigned_to_role: str | None = None` kw-only.
   The Goal dataclass at `core/goal_manager.py:44-66` needs one new
   field. INSERT updated accordingly.
8. **Plugins are heavyweight** — `plugins/_template/` has 4 files
   (`plugin.py` BaseTool subclass + `schema.json` + `test_plugin.py`
   + `README.md`). Confirms the "roles are NOT plugins" decision:
   roles are config files, plugins are code. **`roles/` directory does
   not exist yet** — create it in Phase 2.
9. **`from_mission_momentum`** exists at `core/mind_candidates.py:182-226`
   with signature `async def from_mission_momentum(ctx: CandidateContext) -> list[Candidate]`.
   Mirror this exactly for `from_role_neglect`: read roles ordered by
   staleness (last cycle a role was active), yield candidates that
   propose "switch into role X for this cycle." `CandidateContext` at
   `core/mind_candidates.py:38-57` carries optional managers; add an
   optional `role_manager` to it.
10. **`mission_id` was already a kw-only on `create_goal`** (verified
    by reading the function, not just the audit). Goal dataclass has
    `mission_id`. So our column-addition pattern is proven safe.

#### Schema delta (Phase 2 only)

Append to `_SCHEMA` (new table — placed after the `companies`/`resource_ledger`
block from Phase 1):

```sql
-- ABE Phase 2 (docs/76-ABE-FRAMEWORK.md) — role personas. A role is
-- a system-prompt overlay + tool subset that EloPhanto switches into
-- per cycle. NOT a separate identity. Loaded from roles/<name>.yaml
-- files on boot, mirrored into this table for query efficiency.
CREATE TABLE IF NOT EXISTS roles (
    role_name TEXT PRIMARY KEY,           -- e.g. 'ceo', 'sales', 'support'
    description TEXT NOT NULL DEFAULT '',
    prompt_overlay TEXT NOT NULL DEFAULT '',
    allowed_tools TEXT NOT NULL DEFAULT '[]',       -- JSON array of tool names
    allowed_tool_groups TEXT NOT NULL DEFAULT '[]', -- JSON array of group strings
    kpi_json TEXT NOT NULL DEFAULT '{}',  -- JSON object: {ledger_type: target_amount}
    scope TEXT NOT NULL DEFAULT 'global'
        CHECK (scope IN ('global','company')),
    last_active_at TEXT,                  -- for role-neglect ranking
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_roles_last_active ON roles(last_active_at);
```

Append to `_MIGRATIONS`:

```python
# ABE Phase 2 — role overlay on identity, owner_role on missions,
# assigned_to_role on goals. All nullable; null = "CEO" / EloPhanto-as-self.
"ALTER TABLE identity ADD COLUMN role_persona TEXT",
"ALTER TABLE missions ADD COLUMN owner_role TEXT",
"ALTER TABLE goals    ADD COLUMN assigned_to_role TEXT",
```

#### New code files (Phase 2)

**`core/role.py`** — Role dataclass + RoleManager (target ~200 LOC):

```python
@dataclass(slots=True)
class Role:
    name: str                          # 'ceo', 'sales', 'support'
    description: str
    prompt_overlay: str                # appended to identity context
    allowed_tools: list[str]           # exact tool names; empty = no constraint
    allowed_tool_groups: list[str]     # group strings; empty = no constraint
    kpi: dict[str, float]              # ledger_type → target_amount
    scope: str                         # 'global' | 'company'
    last_active_at: str | None
    created_at: str
    updated_at: str

class RoleManager:
    def __init__(self, db, roles_dir: Path | None = None): ...
    async def list(self) -> list[Role]: ...
    async def get(self, name: str) -> Role | None: ...
    async def upsert_from_yaml(self, path: Path) -> Role: ...
    async def sync_from_disk(self) -> int:
        """Walk roles/*.yaml and upsert each. Idempotent. Returns count."""
    async def touch(self, name: str) -> None:
        """Mark a role as active right now (sets last_active_at)."""
    async def list_by_neglect(self, limit: int = 5) -> list[Role]: ...
    def is_tool_allowed(self, role: Role, tool_name: str, tool_group: str | None) -> bool:
        """Empty allowed_tools AND empty allowed_tool_groups → allow.
        Otherwise tool name OR group must match."""
```

**`core/role_context.py`** — contextvar (mirror Phase 1's company pattern):

```python
import contextvars
_current_role: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "elophanto_current_role", default=None
)
def current_role() -> str | None: ...
def set_current_role(name: str | None) -> contextvars.Token: ...
def reset_current_role(token) -> None: ...
```

**`roles/ceo.yaml`**, **`roles/sales.yaml`**, **`roles/support.yaml`**,
**`roles/ops.yaml`**, **`roles/marketing.yaml`** — five seed files,
~20 lines each. The CEO role is the default-when-nothing-set (no
overlay, no tool restriction); the others have explicit tool
allowlists. Example:

```yaml
# roles/sales.yaml
name: sales
description: |
  Lead generation, qualification, outreach, follow-up.
prompt_overlay: |
  You are operating in the SALES role for this cycle. Your job is to
  move qualified leads through the pipeline. Every cycle should end
  with either: (a) a new prospect added, (b) a prospect advanced one
  stage, or (c) an outbound touch sent. If none of these happened,
  the cycle made no progress.
allowed_tools:
  - prospect_search
  - prospect_evaluate
  - prospect_outreach
  - prospect_status
  - email_send
  - email_reply
  - email_search
  - knowledge_search
allowed_tool_groups: []
kpi:
  pipeline_advance: 5   # 5 stage-advances per week
  email_sent: 20        # 20 outbound touches per week
scope: global
```

**`cli/role_cmd.py`** — `elophanto role list / show <name> / sync /
use <name>` (sync re-reads roles/*.yaml into the DB; use sets the
role for the current shell, persisted to `~/.elophanto/current_role`).

#### Existing-file edits (Phase 2)

1. **`core/database.py`** — append new `roles` table to `_SCHEMA`
   (after the Phase 1 `resource_ledger` block); append the 3 ALTER
   statements to `_MIGRATIONS`.

2. **`core/identity.py:71-97`** — add `role_persona: str | None = None`
   to the `Identity` dataclass.
   **`core/identity.py:717-742`** — add `role_persona` to the
   `_persist_identity()` INSERT OR REPLACE column list + values tuple.
   **`core/identity.py:534-569`** — `build_identity_context()`: when
   the active role contextvar is set, append `<role>{name}</role>` and
   the role's `prompt_overlay` to the XML. Cache invalidation: clear
   the identity context cache on role change so a stale identity
   string can't outlive the role switch.

3. **`core/executor.py:186-190`** — before the existing permission
   check, gate on the active role:
   ```python
   role_name = current_role()
   if role_name and self._role_manager is not None:
       role = await self._role_manager.get(role_name)
       if role is not None and not self._role_manager.is_tool_allowed(
           role, tool.name, getattr(tool, "group", None)
       ):
           return ExecutionResult(
               denied=True,
               error=f"Tool {tool.name!r} not in role {role_name!r} allowlist",
           )
   ```
   The `_role_manager` field is set by `Agent.__init__` if Phase 2
   is enabled; None during the Phase 1-only window keeps the gate
   inert. **No change to `approval_callback` signature.**

4. **`core/mission_manager.py:103-134`** — add
   `owner_role: str | None = None` to `create()`; update INSERT at
   line 117-122 to include `owner_role`. Add `owner_role` to the
   `Mission` dataclass at line 46-56.

5. **`core/goal_manager.py:177-202`** — add
   `assigned_to_role: str | None = None` to `create_goal()`. Update
   `Goal` dataclass at line 44-66. Update `_persist_goal()` INSERT
   columns.

6. **`core/mind_candidates.py`** — add new generator
   `from_role_neglect(ctx)` mirroring `from_mission_momentum` (line
   182-226). Add optional `role_manager` to `CandidateContext`
   (line 38-57). Each role becomes one candidate with
   `staleness_bonus` scaled by hours since `last_active_at`.

7. **`core/autonomous_mind.py`** — wire `RoleManager` instantiation
   (same pattern as `MissionManager`); after the arbiter picks a
   candidate that carries `role_focus`, call `set_current_role(name)`
   for the duration of the cycle (in a try/finally so the contextvar
   resets on failure). Touch the role's `last_active_at` at cycle end.

8. **`cli/main.py`** — read `~/.elophanto/current_role` at startup
   into the contextvar (same pattern as Phase 1 company persistence).
   Register `role_cmd`.

#### Tests (Phase 2)

Create `tests/test_core/test_role_manager.py` and
`tests/test_core/test_role_overlay.py`:

1. `test_role_yaml_sync_creates_rows` — `RoleManager.sync_from_disk()`
   reads `roles/*.yaml` and inserts matching DB rows; re-running is a
   no-op (idempotent upsert).
2. `test_is_tool_allowed_empty_means_full` — a role with empty
   `allowed_tools` AND `allowed_tool_groups` accepts every tool.
3. `test_is_tool_allowed_name_match` — role with `allowed_tools=['email_send']`
   accepts `email_send`, denies `shell_execute`.
4. `test_is_tool_allowed_group_match` — role with
   `allowed_tool_groups=['email']` accepts every tool in the `email`
   group regardless of name.
5. `test_role_persona_persists_on_identity` — set
   `identity.role_persona = 'sales'`, persist, reload — value survives.
6. `test_identity_context_includes_role` — when current_role contextvar
   is set, `build_identity_context()` includes `<role>` and the
   role's prompt_overlay.
7. `test_identity_context_no_role_unchanged` — default contextvar
   value (None) produces identical XML to pre-Phase-2.
8. `test_executor_denies_tool_outside_role` — execute a tool with
   `current_role='sales'` against a role that doesn't include the
   tool — assert `denied=True`, error mentions the role.
9. `test_executor_allows_tool_in_role` — same as above but tool IS in
   the allowlist — assert it goes through to the normal permission
   check.
10. `test_mission_create_with_owner_role` — `mission.create(title='x', owner_role='sales')`
    persists and reloads with `owner_role='sales'`.
11. `test_goal_create_with_assigned_to_role` — same for goals.
12. `test_from_role_neglect_yields_candidate_per_role` — given 3
    seeded roles with varied `last_active_at`, the generator returns
    candidates ranked by neglect.
13. `test_role_context_var_default_none` — default value is `None`,
    not a string.

Plus regression sanity: full suite still 1962+ passing.

#### Phase 2 acceptance criteria

- All 13 new tests pass
- `uv run ruff check` + `uv run mypy core/ cli/` clean
- One PR, ~900 LOC including tests + 5 YAML files
- After merge: `elophanto role sync` populates the `roles` table from
  the 5 seed YAMLs; `elophanto role use sales` switches the active
  role; running any subsequent CLI command (chat, schedule, mind) has
  `current_role()` returning `'sales'`; the executor denies tools
  outside the sales allowlist with a legible error
- The dashboard's mascot / status panels can display the current role
  alongside the current company (Phase 5 will formalize this; for
  Phase 2 just exposing the contextvar is enough)

#### What Phase 2 does NOT include

- ❌ CRM stage normalization (Phase 3 — adds prospects.status enum)
- ❌ `companies/<slug>/company.yaml` product config (Phase 4)
- ❌ `from_role_neglect` weight tuning in arbiter (Phase 4 — for
  Phase 2, neglect_score is just an additive bonus, no weight knob)
- ❌ CompanyBoardPanel role widget (Phase 5)
- ❌ Per-company role scoping (Phase 6 — `roles.scope='company'`
  exists in the schema but is enforced only globally in Phase 2)

---

### Phase 3 — Pipeline (CRM) on existing tables — VERIFIED 2026-05-25

#### Verification findings (deltas from the original sketch)

Phase 3 verification read `tools/prospecting/*.py` and re-checked the
live DB. Confirmed facts:

1. **`prospect_outreach` ALREADY exists** (`tools/prospecting/outreach_tool.py`)
   and does everything Phase 3 was going to build a new tool for:
   logs to `outreach_log`, updates `prospects.status`, has a hard
   10/day email rate-limit. Its `new_status` enum is the established
   pipeline:
   `new | evaluated | outreach_sent | replied | converted | rejected | expired`.
   **The original Phase 3 sketch picked a different funnel (lead /
   qualified / opportunity / customer / lost) without checking what
   the codebase already used. Drop the new enum; use the existing
   one.** Sales SaaS terminology is not a contract — the existing
   states are what current code reads and writes.
2. **Phase 3 needs zero new tools.** The original sketch said "one
   new tool: `crm_advance_lead`" — but that would duplicate
   `prospect_outreach` with cleaner wording, giving operators two
   tools that overlap. Reuse-first: **extend `prospect_outreach` to
   mirror to the resource ledger when status advances**, instead of
   adding a sibling. Same pattern as Phase 1's `email_log` mirror.
3. **Phase 3 needs zero schema changes.** `prospects.status` exists
   (`DEFAULT 'new'`), `prospects.company_id` was added in Phase 1,
   `outreach_log.company_id` was added in Phase 1. The only schema
   work is `_MIGRATIONS` — none of which is needed.
4. **All 4 prospect tools currently write WITHOUT `company_id`** —
   relying on the column DEFAULT. Phase 3 wires `company_id`
   explicitly so non-default companies (Phase 2+) get correct
   attribution. Same surgical pattern as the Phase 1 LLM/email/payment
   tools.
5. **Live DB**: `prospects` = 0 rows, `outreach_log` = 0 rows. So no
   backfill needed — the wiring activates on the next write.
6. **Pipeline-advance ledger rule**: ANY transition to one of
   `{evaluated, outreach_sent, replied, converted}` writes one
   `resource_ledger` row with `direction='in', type='pipeline_advance',
   unit='count', amount=1`. Transitions to `rejected` / `expired`
   do NOT — those are negative outcomes (pipeline shrinks). The
   ledger sums "how many positive stage advances happened" without
   needing to know about CRM funnels specifically.
7. **Visibility (per the Phase-1 rule that visibility ships in the
   same phase as the data)**: `elophanto company report` gets a
   "Pipeline" section grouping prospects by `status` for the active
   company. No new CLI command — extending the existing report keeps
   the operator's surface area constant.

#### What Phase 3 actually does (verified-spec)

| Area | Change | File |
|---|---|---|
| Schema | None (everything in place from Phase 1) | — |
| `prospect_outreach.execute` | Pass `company_id` explicitly in both INSERT and UPDATE; write `resource_ledger` row when `new_status` is one of `{evaluated, outreach_sent, replied, converted}` | `tools/prospecting/outreach_tool.py` |
| `prospect_search.execute` | Pass `company_id` explicitly in INSERT INTO prospects | `tools/prospecting/search_tool.py` |
| `prospect_evaluate.execute` | Pass `company_id` explicitly in the UPDATE (so when Phase 2+ runs the agent under `acme-inc`, the evaluate stays attributed there even if the prospect row was created under `elophanto-self`) | `tools/prospecting/evaluate_tool.py` |
| `company report` CLI | New "Pipeline by stage" table — counts prospects grouped by status for the active company | `cli/company_cmd.py:_report` |

#### Tests (Phase 3)

Create `tests/test_tools/test_prospect_ledger_mirror.py`:

1. `test_outreach_email_sent_status_writes_ledger` — call
   `prospect_outreach(action='email_sent')` on a fresh prospect,
   assert one `resource_ledger` row with `type='pipeline_advance'`,
   `amount=1`, `direction='in'`, `source_table='outreach_log'`.
2. `test_outreach_reply_received_writes_ledger` — same for
   `action='reply_received'` (auto-sets status to `replied`).
3. `test_outreach_rejected_does_NOT_write_ledger` — explicit
   `new_status='rejected'` writes outreach_log but no
   pipeline_advance ledger row.
4. `test_outreach_attributes_to_active_company` — wrap call in
   `set_current_company('acme-inc')`; assert ledger row has
   `company_id='acme-inc'`, NOT `'elophanto-self'`.
5. `test_search_writes_with_active_company_id` — wrap in
   `set_current_company('acme-inc')`; assert new prospect row has
   `company_id='acme-inc'`.
6. `test_pipeline_advance_count_sums_correctly` — three positive
   transitions + one negative; `ResourceLedger.sum(type='pipeline_advance')`
   returns 3.0.

#### Phase 3 acceptance criteria

- All 6 new tests pass
- `uv run ruff check` + `uv run mypy` clean on touched files
- After implementation: `elophanto company report` shows a "Pipeline"
  section (empty for the operator's current DB since `prospects` is
  empty — but the section renders, and any new prospect will appear)
- Full regression still 1981+

#### What Phase 3 does NOT include

- ❌ Stage normalization migration (the existing enum is what the
  codebase already uses and tests would break for no operator gain)
- ❌ A `crm_advance_lead` tool (`prospect_outreach` is the existing
  mechanism; duplicating it adds noise)
- ❌ A separate `elophanto crm` CLI (the pipeline section in
  `company report` is the visibility surface)
- ❌ Per-role prospect filtering (Phase 4 once role-rotation lands
  in the arbiter)

---

### Phase 4 — Product config + arbiter role-rotation — VERIFIED 2026-05-25

#### Verification findings

1. **`companies/` dir does not exist yet.** Phase 4 creates it +
   seeds `companies/elophanto-self/company.yaml` as the starter
   template. `CompanyManager` already has a `product_yaml` column on
   the `companies` row (added in Phase 1) but it's `NULL` for the
   default seed — Phase 4 doesn't use that column; loader checks the
   path directly at `companies/<slug>/company.yaml`. Keep the column
   for a future operator-overridable path; don't depend on it.
2. **Arbiter score is linear** (`core/mind_arbiter.py:182-208`):
   `score = value*quality + lens_bonus*lens_match*quality +
   staleness_bonus*staleness + affect_bias*affect - cost*cost +
   mission_weight*mission_priority`. Adding a `kpi_gap` term follows
   the exact same shape — one new field on `Candidate`, one new
   weight knob on `ArbiterWeights`, one new line in `score_candidate`.
3. **`ArbiterWeights.from_config_dict`** ignores unknown keys (line
   163-164) — so adding `kpi_gap` to the dataclass is non-breaking
   for existing configs.
4. **`from_role_neglect` already passes through scoring** (Phase 2).
   Phase 4 just enriches each candidate with the role's KPI gap so
   the arbiter biases toward the role whose actual ledger sums are
   furthest below its declared targets.
5. **Dream-phase context injection point**: `tools/goals/dream_tool.py:692`
   right after `PURPOSE` block. New PRODUCT section slots in there.
   Empty/missing product = no section (no scolding, no crash).
6. **Empty product safeguard** (per design F: empty `what_we_sell`
   is the navel-gazing risk reborn): the loader returns `None` when
   `what_we_sell` is empty/missing. The dream-phase code only prepends
   PRODUCT if the loader returned a real product. The CLI `company
   report` shows `(product not defined)` line when missing. **We do
   NOT block `company use` on missing product** — the company is
   still a valid attribution scope; the product is what *steers*
   work, not what *gates* operation.
7. **`Role.kpi`** (Phase 2 field) maps `ledger_type → target_amount`.
   Currently `target_amount` was implicitly "per week" — Phase 4
   formalizes that by computing actual = `ResourceLedger.sum(type=X,
   since=7d_ago, direction='in')` and gap = `max(0, target-actual)/target`.

#### Schema delta (Phase 4)

**None.** Reuses:
- `companies.product_yaml` (Phase 1 column, unused until now — but Phase 4 *still* doesn't write it; loader reads `companies/<slug>/company.yaml` by convention)
- `roles.kpi_json` (Phase 2)
- `resource_ledger` (Phase 1) — KPI-gap is computed from ledger sums

#### New files (Phase 4)

**`core/product.py`** — Product loader (~120 LOC):
```python
@dataclass(slots=True)
class Product:
    name: str
    what_we_sell: str
    price: dict[str, Any] | None
    fulfillment: str
    channels: list[str]
    wallet: dict[str, str] | None
    kpis: list[dict[str, Any]]      # [{type, target_weekly}, ...]
    source_path: str                # where this was loaded from

def load_product(project_root: Path, company_id: str) -> Product | None:
    """Load companies/<slug>/company.yaml. Returns None if missing,
    empty what_we_sell, or YAML parse fails. Never raises."""
```

**`companies/elophanto-self/company.yaml`** — starter template:
```yaml
name: EloPhanto (self)
what_we_sell: |
  Open-source self-evolving AI agent (this codebase). Operator (Petr
  Royce) provides bespoke automations, agent-building, and consulting
  built on top of EloPhanto.
price:
  amount: 0
  currency: USD
  model: project-based
fulfillment: |
  Operator-mediated. The agent does research / drafting / outreach;
  the operator finalises, ships, and bills.
channels: [cli, telegram, x]
wallet:
  chain: solana
  address: ""        # operator sets via vault, not in product yaml
kpis:
  - type: pipeline_advance
    target_weekly: 5
  - type: email_sent
    target_weekly: 20
```

#### Existing-file edits (Phase 4)

1. **`core/mind_arbiter.py`** — extend `Candidate` (line 46) with
   `kpi_gap: float = 0.0` (range 0.0–1.0; 0 = at/above target, 1.0
   = no progress at all). Add `kpi_gap_weight: float = 0.4` to
   `ArbiterWeights` (line 117) + `from_config_dict` (line 160). Add
   `score += weights.kpi_gap_weight * c.kpi_gap * 10` to
   `score_candidate` (line 200) — multiplier of 10 puts a max-gap
   role at ~+4 points, comparable to a stale mission move.

2. **`core/mind_candidates.py:from_role_neglect`** — compute
   `kpi_gap` for each role candidate. For each KPI on the role,
   read `ResourceLedger.sum(company_id=current_company, type=KPI.type,
   direction='in', since=7d_ago)` and gap_per_kpi = `max(0,
   target - actual) / max(target, 1)`. Role's `kpi_gap` = mean of
   per-KPI gaps. Falls through to 0.0 if no KPIs declared or no
   ledger available.

3. **`tools/goals/dream_tool.py`** — at line 692 (after PURPOSE),
   inject PRODUCT block when `load_product(project_root,
   current_company_id())` returns non-None:
   ```
   PRODUCT (this company sells):
   <what_we_sell, capped at 600 chars>
   ```
   Lazy load; failures log at debug and skip the block.

4. **`cli/company_cmd.py:_report`** — add PRODUCT row to the
   headline. When product is None, show
   `(product not defined — write companies/<slug>/company.yaml)`.

#### Tests (Phase 4)

Create `tests/test_core/test_product_and_kpi_gap.py`:

1. `test_load_product_missing_file_returns_none` — fresh tmp_path,
   no YAML — `load_product` returns `None`, no exception.
2. `test_load_product_empty_what_we_sell_returns_none` — YAML present
   but `what_we_sell: ""` → returns `None` (navel-gazing guard).
3. `test_load_product_happy_path` — valid YAML round-trips through
   `Product` dataclass with all fields.
4. `test_load_product_invalid_yaml_returns_none` — malformed file
   doesn't crash; returns `None`; warning logged.
5. `test_arbiter_kpi_gap_term_adds_to_score` — score one candidate
   with `kpi_gap=0.0` and one with `kpi_gap=1.0`, all else equal —
   the latter scores `kpi_gap_weight * 10` higher.
6. `test_arbiter_kpi_gap_zero_when_no_gap_field` — legacy Candidate
   construction (no `kpi_gap`) defaults to 0 and doesn't break the
   score combiner.
7. `test_from_role_neglect_populates_kpi_gap_from_ledger` — seed a
   role with `kpi={pipeline_advance: 10}`, write 3 pipeline_advance
   ledger rows for the past 7d, call `from_role_neglect`, assert
   gap = (10-3)/10 = 0.7.
8. `test_from_role_neglect_no_kpis_has_zero_gap` — role with empty
   `kpi` dict → candidate `kpi_gap` is 0.0.
9. `test_dream_context_includes_product_when_available` — seed the
   product yaml, build context, assert "PRODUCT" appears.
10. `test_dream_context_omits_product_when_missing` — no yaml,
    context has no PRODUCT block, no error.

#### Phase 4 acceptance criteria

- 10 new tests pass
- `uv run ruff check` + `uv run mypy` clean on touched files
- After implementation: `companies/elophanto-self/company.yaml`
  exists with the operator-provided `what_we_sell`; `elophanto
  company report` shows the product summary; running the dream phase
  produces context that includes the product (verifiable via dream
  journal entries); creating a new role with KPIs and running for
  a few days, `from_role_neglect` favors the role with the largest
  ledger-target gap
- Full regression still 1989+

#### What Phase 4 does NOT include

- ❌ Auto-create `companies/<slug>/company.yaml` on `company create`
  (operator writes it by hand; auto-creation invites garbage)
- ❌ Per-company channel routing (Phase 6)
- ❌ Wallet binding (the YAML declares a wallet field but Phase 4
  doesn't wire it into payment_audit — that's a Phase 6 isolation
  concern)
- ❌ Hard-blocking `company use` on missing product (kept soft so
  Phase 1-3 attribution still works for any slug)
- ❌ KPI-gap-driven arbiter for non-role candidates (only
  `from_role_neglect` gets the bias; missions get their existing
  mission_weight only)

---

### Phase 5 — Board view

- `CompanyBoardPanel` in dashboard: revenue (sum `ledger where type='usd' direction='in'`), spend (sum `usd out`), runway (cash / 30-day burn), pipeline by stage (count `prospects group by stage`), last 5 role decisions (recent `resource_ledger` rows where `type='decision'`), blockers (goals where status='paused' or needs-input)
- Company selector at top of dashboard; existing panels filter on selection

### Phase 6 — Multi-company isolation hardening — VERIFIED 2026-05-25

#### Verification findings (deltas from the original sketch)

Verification surfaced that the original Phase 6 bullets mixed *load-bearing primitives* (one-line wiring) with *heavy structural lifts* (multi-week features). The honest split:

| Original bullet | Verdict | Phase 6 action |
|---|---|---|
| Channel routing by company_id | Lightweight primitive | **DO**: add `company_id` to `ClientConnection`, defaulted from contextvar; `Gateway.broadcast` accepts optional `company_id=` filter |
| Per-company scheduler queue | Lightweight primitive | **DO**: when scheduler dispatches a task, set `current_company(task.company_id)` for its execution scope — task's writes attribute correctly. No queue partitioning. |
| Per-company `data/<id>/` dir | Lightweight primitive | **DO**: create `data/companies/<slug>/` on `company create`; document as the per-company runtime-state location. Don't migrate existing flows. |
| Sessions `UNIQUE` rebuild | Heavy + low payoff | **DEFER**: requires SQLite table rebuild (rename / create / insert / drop / rename); 3 live sessions = trivial collision risk; bookkeeping deferred since Phase 1 with same reasoning. Document why. |
| `roles.scope='company'` enforced | Heavy + speculative | **DEFER**: needs a `company_id` column on `roles`, scope-aware queries throughout, role manager rework. No current role wants company-scoping. Document why. |

The pattern across Phases 3 and 4 — verification shrinking the scope by surfacing what's already in place — repeats here. Phase 6 ships as three small primitives + two documented deferrals, not five features.

1. **`ClientConnection`** at `core/gateway.py:43-75` is a dataclass — adding a field is one line. Routing logic (`Gateway.broadcast`) is the natural filter site; no existing per-conn metadata is queried, so the new field is additive.
2. **Scheduler dispatch**: scheduled_tasks already has `company_id` (Phase 1). The dispatch site needs `set_current_company(task.company_id)` wrapped in try/finally around the task callback. ~5 lines.
3. **`data/companies/<slug>/`**: creating a directory is `Path.mkdir(parents=True, exist_ok=True)`. Hook into `CompanyManager.create()`. Plus a one-time backfill for `elophanto-self` on next CLI invocation. Document the location in the company `report` output so operators discover it.
4. **Session UNIQUE deferral note**: The risk is "two operators on different companies share a channel+user_id and collide on session lookup." Current setup is one operator, mostly one company. The fix is a table rebuild — straightforward SQL but high-touch (cache invalidation, in-flight session handling). Worth doing only when there are multiple real companies sharing channels. **Trigger to revisit**: when `companies` row count > 1 AND any channel adapter is shared between them.
5. **`roles.scope='company'` deferral note**: Today every role is `scope='global'`. A company-scoped role would only matter if e.g. "acme-inc's sales overlay differs from elophanto-self's sales overlay." That's a real use case for multi-tenant ABE-as-a-service but not for one operator's two companies. **Trigger to revisit**: when an operator wants role overlays that differ per company.

#### Schema delta (Phase 6)

**None.** All necessary columns landed in Phases 1-2.

#### Existing-file edits (Phase 6)

1. **`core/gateway.py:43-75`** — add `company_id: str = "elophanto-self"` to `ClientConnection`. In `Gateway.broadcast(msg, *, session_id=None)`, add optional `company_id: str | None = None` kwarg; when set, only fan out to connections whose `company_id` matches.
2. **`core/scheduler.py`** — in the dispatch callback, wrap the task execution in `set_current_company(task.company_id) / reset_current_company(token)` (read company_id from the row; default `'elophanto-self'`). Means a scheduled task tagged for `acme-inc` writes its ledger events / outreach rows under `acme-inc` even when the operator's CLI is set to `elophanto-self`.
3. **`core/company.py:CompanyManager.create()`** — after the row insert, `(project_root / "data" / "companies" / slug).mkdir(parents=True, exist_ok=True)`. Need to thread `project_root` into `CompanyManager.__init__` (optional, defaults to CWD-based discovery).
4. **`cli/company_cmd.py:_dispatch`** — pass `project_root` to `CompanyManager(db, project_root=config.project_root)`. After existing init logic for `elophanto-self`, ensure its data dir exists too (one-shot idempotent).
5. **`cli/company_cmd.py:_report`** — add a `Data dir:` line showing the per-company directory location (or "(not created)" if missing).

#### Tests (Phase 6)

Create `tests/test_core/test_phase6_isolation.py`:

1. `test_client_connection_default_company` — `ClientConnection(client_id="x", websocket=mock)` has `company_id="elophanto-self"`.
2. `test_gateway_broadcast_filters_by_company` — two `ClientConnection` instances (one acme-inc, one elophanto-self); broadcast with `company_id="acme-inc"` only fans out to the matching one.
3. `test_gateway_broadcast_no_filter_fans_to_all` — broadcast with no `company_id=` reaches every connection regardless.
4. `test_company_create_makes_data_dir` — `CompanyManager.create("test-co")` results in `<root>/data/companies/test-co/` existing.
5. `test_company_create_data_dir_idempotent` — second `create` (which raises `ValueError`) didn't make the test's tmp_path data dir gain duplicate state; ensure_data_dir helper runs cleanly on existing dirs.
6. `test_scheduler_dispatch_sets_current_company` — fake scheduled task with `company_id="acme-inc"`; mock the dispatch callback to assert `current_company_id() == "acme-inc"` during execution, returns to previous value afterward.

#### Phase 6 acceptance criteria

- 6 new tests pass
- ruff + mypy clean on touched files
- After implementation: `elophanto company create acme-inc` creates `data/companies/acme-inc/`; `company report` shows the data dir line; full 2007+ regression green.

#### What Phase 6 does NOT include (deferrals recorded)

- ❌ Session `UNIQUE` constraint rebuild — see #4 above; trigger: >1 company sharing channels
- ❌ `roles.scope='company'` enforcement — see #5 above; trigger: operator wants per-company role overlays
- ❌ Per-company channel adapter binding (e.g. one Telegram bot per company) — heavyweight infrastructure, not needed until multiple companies actually want to publish through dedicated channels. Phase 7 territory.
- ❌ File-system isolation for scratchpad / workspace / knowledge — would touch the entire skill + indexer pipeline. Out of scope; tools can opt in to `data/companies/<slug>/` as they need it.

---

### Phase 8 — Chat-driven ABE management — VERIFIED 2026-05-25

**Verification failure recorded**: Phases 1-7 shipped CLI commands
(`elophanto company …`, `elophanto role …`) without corresponding
agent-callable tools. For an operator who lives in chat, that's
half a feature — the agent can't be told *"create a company
called acme-inc and switch to it"* because no tool exists.
Phase 8 closes this gap.

**Senior call recorded** (no operator question asked — pattern is
established, no real tradeoff): full set of 10 tools; session-only
contextvar by default with optional `persist: true` for the rare
case of changing the operator's CLI default.

#### Tools (10) — all in `tools/companies/` + `tools/roles/`

| Tool | Tier | Reuses | Purpose |
|---|---|---|---|
| `company_list` | SAFE | `CompanyManager.list()` | List all companies + status + product status |
| `company_report` | SAFE | `cli/company_cmd._report` logic | Structured headline + recent ledger events for one company |
| `company_create` | MODERATE | `CompanyManager.create()` | New company row + data dir |
| `company_use` | MODERATE | `core.company.set_current_company` | Session-only by default; `persist=true` writes sidecar |
| `company_pause` | MODERATE | `CompanyManager.set_status()` | status='paused' |
| `company_resume` | MODERATE | `CompanyManager.set_status()` | status='active' |
| `role_list` | SAFE | `RoleManager.list_roles()` | All roles + active marker + last_active_at |
| `role_show` | SAFE | `RoleManager.get()` | Full overlay + allowlist + KPI |
| `role_use` | MODERATE | `core.role_context.set_current_role` | Session-only by default; `persist=true` writes sidecar |
| `role_sync` | MODERATE | `RoleManager.sync_from_disk()` | Re-read roles/*.yaml into DB |

`company_set_product` (Phase 7) already exists; Phase 8 adds the 10
above. Total ABE-tool surface: 11.

#### Schema delta

**None.** All logic reuses Phases 1-7 managers.

#### Existing-file edits

1. `tools/companies/__init__.py` — re-export the 6 new company tools
2. `core/registry.py` — register the 10 new tools alongside `CompanySetProductTool`
3. `core/agent.py:_inject_company_deps()` — extend to inject `_db` + `_project_root` + `_company_manager` + `_role_manager` into all 11 tools (idempotent)

#### Tests

`tests/test_tools/test_abe_management_tools.py` — at least one round-trip per tool (create → list → report → use → pause → resume; sync → list_roles → show → use). ~15 tests.

#### Phase 8 acceptance criteria

- 15+ new tests pass; full regression green
- Live smoke via chat: ask the agent "list all companies" → it calls `company_list` and reports cleanly; "switch to demo-co" → it calls `company_use(slug='demo-co')`, operator approves, the tool returns "active for this session"

#### What Phase 8 does NOT include

- ❌ A "switch role for one tool call only" mechanic (use + clear is fine)
- ❌ A "company_delete" tool (operator territory; archive via pause)
- ❌ Auto-detection of company_use intent from chat (no, the LLM picks the tool — that's how every other tool works)

---

### Phase 7 — Agent self-bootstraps its ABE — VERIFIED 2026-05-25

EloPhanto edits its own ABE config (with operator approval). Closes
the read-only-write-only asymmetry of Phase 4 — today the agent
reads product/KPI config to decide; Phase 7 lets it propose changes
to that config based on what it learns from the ledger.

#### Verification findings (deltas from the original sketch)

1. **`PermissionLevel.RESTRICTED` does not exist.** The enum at
   `tools/base.py:22-25` is `SAFE | MODERATE | DESTRUCTIVE`.
   MODERATE is the operator-approval tier; DESTRUCTIVE is for
   irreversible actions (`rm -rf`). Product-YAML writes are
   reversible (just overwrite a file), so the right tier is
   **MODERATE** — operator approves but the action can be undone.
2. **`_is_consumerless()` + `_BANNED_TITLE_FRAGMENTS` already exist**
   at `tools/goals/dream_tool.py:158,207`. Phase 7 extracts these
   to a shared module (`core/consumer_filter.py`) so
   `company_set_product` validates `what_we_sell` with the same
   filter — single source of truth for what counts as
   navel-gazing.
3. **Mission tools pattern** at `tools/missions/tools.py:19+` is
   the template: a `_CompanyToolBase` parent that injects the
   project_root + db dependency; individual tools subclass it and
   set their own `permission_level`.
4. **`from_reflexes` pattern** at `core/mind_candidates.py:413` is
   the template: a top-level reflex function calls per-reflex
   `_X_due(ctx)` helpers that return staleness/None; KPI
   calibration adds another `_kpi_calibration_due(ctx)` alongside.
5. **MVP scope shrunk vs original**: the original sketch listed
   `role_update_kpi`, role-evolution, and a chat-based calibration
   proposal. Verification says **defer all of those** — the truly
   load-bearing piece is just the product-write loop (tool +
   candidate source). KPI calibration's value is bounded by Phase 4
   already firing `from_role_neglect` with KPI gaps; updating
   targets is operator territory. Role evolution is months away
   from being useful. **Phase 7 MVP**: 1 tool, 1 candidate source,
   1 shared filter module.

#### Schema delta (Phase 7)

**None.** Reuses Phase 1 `companies` row + Phase 4
`companies/<slug>/company.yaml` file location.

#### New / extracted files

**`core/consumer_filter.py`** — extract from `tools/goals/dream_tool.py`:

```python
# Moves _BANNED_TITLE_FRAGMENTS, _INTERNAL_ARTIFACT_HINTS, and
# _is_consumerless() to a new module. dream_tool.py keeps the same
# names as re-exports for backwards compat.
_BANNED_TITLE_FRAGMENTS: tuple[str, ...] = (...)  # unchanged
_INTERNAL_ARTIFACT_HINTS: tuple[str, ...] = (...)  # unchanged

def is_consumerless_text(
    title: str, body: str, *, consumer: str | None = None
) -> tuple[bool, str]:
    """Generalised filter used by dream_tool AND company_set_product.
    Returns (is_consumerless, reason)."""
```

**`tools/companies/__init__.py`** + **`tools/companies/set_product_tool.py`**:

```python
class CompanySetProductTool(BaseTool):
    name = "company_set_product"
    description = "Write or update a company's product.yaml."
    permission_level = PermissionLevel.MODERATE
    # Schema: slug (required), what_we_sell (required, non-empty),
    # price?, fulfillment?, channels?, wallet?, kpis?
    async def execute(self, params) -> ToolResult:
        # 1. Validate slug exists in `companies` table (refuse to
        #    write for unknown slugs — agent must use existing
        #    company management to create one first).
        # 2. Run is_consumerless_text on what_we_sell — refuse if
        #    the banlist matches.
        # 3. Render YAML, write to companies/<slug>/company.yaml,
        #    return the path + the parsed Product object.
```

**`from_unproductized_companies(ctx)` in `core/mind_candidates.py`**:

```python
async def from_unproductized_companies(ctx: CandidateContext) -> list[Candidate]:
    """One candidate per company whose product yaml is missing
    or has empty what_we_sell. The dream rotation will surface
    these so the agent proposes a product (via company_set_product)
    rather than drifting into unanchored work."""
    # Iterates `companies` table; for each, calls load_product();
    # those returning None yield a high-expected_value candidate
    # 'Draft a product for company <slug>: propose what_we_sell
    # then call company_set_product.'
```

#### Existing-file edits

1. **`tools/goals/dream_tool.py:158-228`** — remove
   `_BANNED_TITLE_FRAGMENTS`, `_INTERNAL_ARTIFACT_HINTS`, and
   `_is_consumerless`. Re-export them from `core.consumer_filter`
   so any external code referencing them still works.
2. **`core/mind_candidates.py:collect_all`** — add
   `from_unproductized_companies` to the generator tuple.
3. **`CandidateContext`** — already has `mission_manager` and
   `role_manager`; need access to the `companies` table (via the
   same `db` handle the role_manager carries). Add
   `company_manager: Any = None` to the context dataclass and have
   the generator fall through (return []) when it's None.
4. **`core/autonomous_mind.py`** — when building
   `CandidateContext`, pass `company_manager=self._agent._company_manager`.
   Requires `Agent` to construct a `CompanyManager` on init — quick
   check: does it already? **Verify before implementing.**

#### Tests (Phase 7)

Create `tests/test_core/test_consumer_filter.py` (extract tests
from existing dream_tool tests, plus new ones for the generalised
API) and `tests/test_tools/test_company_set_product.py`:

1. `test_banlist_rejects_navel_gazing_title` — `is_consumerless_text("Evidence Garden v2", "...", consumer="me")` returns True with banlist reason.
2. `test_consumer_other_passes` — title without banned fragments + consumer="newsletter readers" passes.
3. `test_company_set_product_writes_yaml` — fresh tmp_path, tool call, assert file exists with correct fields.
4. `test_company_set_product_rejects_empty_what_we_sell` — empty string → ToolResult.error mentions empty/required.
5. `test_company_set_product_rejects_navel_gazing` — what_we_sell containing banned fragment → ToolResult.error mentions banlist.
6. `test_company_set_product_refuses_unknown_slug` — slug not in `companies` table → error, no file written.
7. `test_company_set_product_overwrites_existing` — second call replaces the first.
8. `test_from_unproductized_companies_yields_candidate_per_missing` — 3 companies seeded, only 1 has a yaml — generator yields 2 candidates.
9. `test_from_unproductized_companies_empty_without_manager` — `CandidateContext()` with no company_manager → [].
10. `test_loader_reads_post_write` — write via tool, load via `load_product` — round trips fields.

#### Phase 7 acceptance criteria

- 10 new tests pass; full regression green
- `uv run ruff check` + `uv run mypy` clean on touched files
- Live smoke: simulate agent calling `company_set_product` on a
  test company; YAML lands at `companies/<slug>/company.yaml`;
  `elophanto company report <slug>` shows the product line

#### What Phase 7 does NOT include (deferrals)

- ❌ `role_update_kpi` tool (operator territory; Phase 4's KPI-gap signal already biases the arbiter)
- ❌ Weekly KPI calibration reflex (deferred — the dream + arbiter already nudge toward neglected roles via Phase 4; no evidence a separate reflex adds value)
- ❌ Role evolution from observed patterns (premature; the 5 seed roles cover the realistic surface)
- ❌ Auto-creating companies via tool (operator controls company creation — `elophanto company create`)
- ❌ Dream-prompt addendum about agent-proposed `what_we_sell` (the banlist enforces the rule deterministically at tool level; prompt-side language adds nothing the tool doesn't already enforce)

---

---

## Risks (where this can still go wrong)

1. **Role overlay quality.** A 20-line YAML doesn't make the LLM a real CFO. Mitigation: same discipline as the dream-lens rewrite — every role decision must write a typed `decision_record` ledger event. No event = no decision = no progress. (See [`docs/76-DREAM-CONSUMER-FILTER`](76-ABE-FRAMEWORK.md) section above re: consumer-grounding.)
2. **Empty products.** A company with no `what_we_sell` is a generator of identity goals. The product YAML loader **must refuse to activate** the company in that case. Enforce in code, not in comments.
3. **Migrations.** ~10 `company_id` FK additions touch a lot of code. Do them in a single migration with `DEFAULT 'elophanto-self'` so old code keeps working unchanged. Budget one focused afternoon.
4. **Scope creep into the marketing version.** If a future you starts adding "AI legal counsel auto-contracts" or "infinite-scale deployment", stop and re-read "Why this exists" above. The scope is one operator running a small focused company-of-roles.

## Relation to other docs

- [`docs/78-ABE-OPERATOR-GUIDE.md`](78-ABE-OPERATOR-GUIDE.md) — **operator playbook**: commands you run, files you edit, what to watch in `company report`, common failure modes
- [`docs/17-IDENTITY.md`](17-IDENTITY.md) — identity manager EloPhanto uses; we extend it with `role_persona`, do not replace
- [`docs/13-GOAL-LOOP.md`](13-GOAL-LOOP.md) — goals; we add `assigned_to_role`
- [`docs/75-AUTONOMOUS-MIND-V2.md`](75-AUTONOMOUS-MIND-V2.md) — missions/arbiter; we add `owner_role` to missions and `from_role_neglect` to arbiter
- [`docs/15-PAYMENTS.md`](15-PAYMENTS.md) — payments; we add `company_id` and mirror to ledger
- [`docs/18-EMAIL.md`](18-EMAIL.md) — email; we add `company_id`; outreach becomes CRM source

---

## Current Status

**Last updated**: 2026-05-25

| Phase | Verification | Implementation |
|---|---|---|
| 0 — Design captured in this doc | ✅ done | ✅ done |
| 1 — Company scope + ledger | ✅ done 2026-05-25 | ✅ done 2026-05-25 |
| 2 — Roles as overlays | ✅ done 2026-05-25 | ✅ done 2026-05-25 |
| 3 — CRM on existing tables | ✅ done 2026-05-25 | ✅ done 2026-05-25 |
| 4 — Product config + arbiter rotation | ✅ done 2026-05-25 | ✅ done 2026-05-25 |
| 5 — Board view | ⬜ not started | ⬜ blocked on verification |
| 6 — Multi-company isolation hardening | ✅ done 2026-05-25 | ✅ done 2026-05-25 |
| 7 — Agent self-bootstraps its ABE | ✅ done 2026-05-25 | ✅ done 2026-05-25 |
| 8 — Chat-driven ABE management | ✅ done 2026-05-25 | ✅ done 2026-05-25 |

**Phase 1 outcome (2026-05-25)**: shipped + visible. Live DB migrated
(12,968 llm_usage rows attributed to `elophanto-self`); `companies` and
`resource_ledger` tables created; `CompanyManager` / `ResourceLedger` /
context var live; `CostTracker.flush` mirrors LLM calls to ledger as
paired tokens+usd rows; `PaymentAuditor.log` mirrors payments; all
three email tools mirror outbound sends. CLI: `elophanto company
list / create / use / current / pause / resume / backfill / report`
working. 21 new tests pass; full 1962-test suite green; ruff + mypy
clean.

**Reversed from the original Phase 1 spec (2026-05-25)**: the original
plan said "backfilling historical llm_usage into the ledger is deferred
to Phase 5 if needed for board" — that was wrong. Without the backfill
the report shows `$0.00` for the entire pre-2026-05-25 history, which
makes the only company visible useless to a human. Backfill + report
landed in the same Phase 1 work. The rule learned: visibility comes
in the same phase as the data, not in a downstream phase. Acceptance
criteria for any future phase must include "the operator can SEE the
effect."

**Live numbers after backfill** (snapshot, 2026-05-25):

- Spend: **$10.92** total LLM cost
- LLM tokens out: **649,111,508**
- Email touches out: **178**
- Revenue: **$0.00** (no income tracked yet — confirms ledger is honest)
- 26,144 ledger rows after backfill (12,968 × 2 from llm_usage + 30 payments + 178 emails)

**Phase 2 outcome (2026-05-25)**: shipped. Schema delta landed (5
roles seeded from `roles/*.yaml`, 3 column ALTERs on `identity` /
`missions` / `goals`). `RoleManager` + `current_role` contextvar live
(`core/role.py`, `core/role_context.py`). `IdentityManager.build_identity_context()`
appends `<role>` + `<role_overlay>` to the system prompt when the
contextvar is set. `Executor` denies tools outside the active role's
allowlist BEFORE the generic permission check (so role-deny
short-circuits auto-approve modes). `MissionManager.create()` accepts
`owner_role`; `GoalManager.create_goal()` accepts `assigned_to_role`.
`from_role_neglect` candidate generator yields one entry per role
ranked by `last_active_at` staleness, surfaced in the arbiter menu
alongside `from_mission_momentum`. Autonomous mind touches the active
role at cycle end so neglect ranking advances. CLI: `elophanto role
list / show / sync / use / clear / current` working; selected role
persists across invocations via `~/.elophanto/current_role`. 14 new
tests pass; full 2K-test regression green; ruff + mypy clean.

**Phase 3 outcome (2026-05-25)**: shipped. Zero new schema, zero new
tools. Existing `prospect_outreach` extended to mirror positive
status transitions to `resource_ledger` as `pipeline_advance` events
attributed to the prospect's own company (its funnel) — not the
operator's currently-active company. `prospect_search` and
`prospect_evaluate` thread `company_id` explicitly so non-default
companies attribute correctly. `evaluate` ALSO writes a
`pipeline_advance` event when `decision='pursue'` (status →
'evaluated'). Verification found a latent bug — `Database` had no
`fetch_all` method but every prospect tool called it (matching the 0
prospect rows in production). Added a one-line `fetch_all` alias to
`Database` so the previously-dead prospect tools come to life as part
of Phase 3. `elophanto company report` now shows a "Pipeline advances
(in)" headline row plus a "Pipeline by stage" table grouped by the
existing status enum. 8 new tests pass; full 1989-test regression
green; ruff + mypy clean.

**Reversal recorded**: original Phase 3 sketch picked a new sales-SaaS
funnel (`lead | qualified | opportunity | customer | lost`). Drop
that — the codebase already uses
`new | evaluated | outreach_sent | replied | converted | rejected | expired`.
Reuse the existing enum. The original sketch also proposed a new
`crm_advance_lead` tool — drop that too; extending `prospect_outreach`
beats duplicating it.

**Phase 4 outcome (2026-05-25)**: shipped. Zero new schema. New
`core/product.py` with a single `load_product` function (file-based,
no DB); seed YAML at `companies/elophanto-self/company.yaml`
declaring what the default company sells, prices, fulfills, KPIs.
Arbiter `Candidate` extended with `kpi_gap: float`, `ArbiterWeights`
extended with `kpi_gap_weight=0.4` (configurable, default produces
+4 raw points for a max-gap role — comparable to a stale mission
move). `from_role_neglect` reads role KPIs vs ledger sums over the
past 7 days for the active company and populates each candidate's
`kpi_gap`. Dream-phase context (`tools/goals/dream_tool.py:692`)
gets a PRODUCT block right after PURPOSE; missing/empty product =
silent skip. `elophanto company report` shows the PRODUCT line in
the headline (yellow warning when undefined). 18 new tests pass;
ruff + mypy clean.

**Phase 6 outcome (2026-05-25)**: shipped as three small primitives,
two documented deferrals. `ClientConnection` gets `company_id`
(default `elophanto-self`); `Gateway.broadcast` accepts an optional
`company_id=` filter. Scheduler dispatch wraps every task in
`set_current_company(task.company_id) / reset_current_company`
(restoration enforced in `finally`, survives task failure).
`CompanyManager(db, project_root=...)` materializes
`data/companies/<slug>/` on `create()` and on demand via
`ensure_data_dir()`; the seed `elophanto-self` dir is backfilled on
first CLI invocation. `company report` shows the data dir line. 9 new
tests pass; full regression green; ruff + mypy clean. Deferrals:
session `UNIQUE` rebuild (trigger: >1 company on shared channels)
and `roles.scope='company'` enforcement (trigger: operator wants
per-company role overlays).

**Phase 7 outcome (2026-05-25)**: shipped tight. One new tool
(`company_set_product`, MODERATE permission), one new candidate
source (`from_unproductized_companies`), one shared module
(`core/consumer_filter.py` extracted from `tools/goals/dream_tool.py`).
Closes the read-only/write-only asymmetry of Phase 4 — the agent
can now propose a `company.yaml` for any company that doesn't have
one, subject to operator approval. The shared banlist (Phase 4's
navel-gazing guard) applies at the tool level so agent-proposed
`what_we_sell` can't drift back into "framework for documenting
agent identity" patterns. Refuses to write for slugs not in the
`companies` table (operator controls company creation). The mind's
arbiter now sees a high-`expected_value` candidate per unproductized
company, capped at 3 to avoid menu drowning. KPI calibration reflex,
role evolution, and a `role_update_kpi` tool were all in the
original sketch — verification deferred them with explicit reasoning
(Phase 4's KPI-gap signal already biases the arbiter; KPI updates
are operator territory; role evolution is months from value). 22
new tests pass; full regression green; ruff + mypy clean.

**Next action when resuming**: Phase 5 (board view) — the only
remaining planned phase. Dashboard panel (`CompanyBoardPanel`)
showing revenue/spend/runway/pipeline/role activity/blocked goals
with a company selector. Read `cli/dashboard/app.py` for the panel
pattern; the existing report logic in `cli/company_cmd.py:_report`
is the data layer to lift into the panel.

**When updating this doc**: bump the table above, add a one-line entry to
a "Changelog" section if changes are non-obvious, and keep the design
decisions section frozen unless we deliberately revise the contract.
