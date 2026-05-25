# 78 — ABE Operator Guide

**Status**: Active · **Owner**: Petr Royce + Claude · **First written**: 2026-05-25

How to use the Autonomous Business Entity framework shipped in
[`docs/76-ABE-FRAMEWORK.md`](76-ABE-FRAMEWORK.md). That doc is the
**design contract** (load-bearing decisions, what's deferred and
why); this doc is the **operator playbook** (commands you run,
files you edit, what to watch).

---

## What an ABE is

An ABE is a small focused company-of-roles EloPhanto runs on your
behalf. One operator (you), one runtime, one or more companies.
Each ABE has:

- A **slug** (`elophanto-self`, `acme-inc`, ...) that scopes every
  database row and ledger event
- A **product** declared in `companies/<slug>/company.yaml`
- A **ledger** (`resource_ledger` table) that captures revenue,
  spend, LLM tokens, email touches, pipeline advances — every
  meaningful action writes a typed event
- **Role personas** (CEO / sales / support / ops / marketing) the
  agent can switch into per cycle, with tool subsets enforced by
  the executor

EloPhanto plays the CEO by default. The CEO is not a separate
identity — it's EloPhanto with no overlay and full tool access.
Other roles are masks worn per cycle.

---

## First-run: bootstrap your default ABE

If you're new, the default company `elophanto-self` already exists.
See what's there:

```bash
elophanto company report
```

You'll see headline numbers (revenue, spend, tokens, email
touches, pipeline advances), the active product, the data
directory, last 10 ledger events, and (when prospects exist) a
"Pipeline by stage" table.

If the report shows historical zeros, run the one-shot backfill —
this imports your existing `llm_usage` / `payment_audit` /
`email_log` rows into the ledger (idempotent, safe to re-run):

```bash
elophanto company backfill
```

Edit your product config to anchor the dream phase:

```
companies/elophanto-self/company.yaml
```

The starter file ships with a placeholder. The only required
field is `what_we_sell` — it must be **non-empty** and must name
a real external consumer + concrete deliverable. Empty values
make the loader return `None` (navel-gazing guard); the dream
phase then has no business to anchor against and will drift back
into self-referential goals.

---

## Creating a second ABE

```bash
elophanto company create acme-inc "Acme Inc"
elophanto company use acme-inc       # scope this CLI session to acme-inc
```

The `use` selection persists at `~/.elophanto/current_company`
across CLI invocations. The contextvar default is
`elophanto-self`, so any code path that hasn't been wired to set
it gets safe behavior.

Now write the product file. There are two paths:

**Path A — operator hand-writes** (the recommended path, gives
you full control):

```bash
# Create companies/acme-inc/company.yaml by hand. Use
# companies/elophanto-self/company.yaml as a template.
```

**Path B — agent proposes** (the Phase 7 self-bootstrap path):

The arbiter will surface a `from_unproductized_companies`
candidate for any company without a `company.yaml`. When the
agent runs and that candidate wins, the LLM calls
`company_set_product(slug, what_we_sell, ...)`. The tool is
MODERATE permission — you approve every write. The same banlist
that filtered the dream lens rewrite is applied: agent-proposed
`what_we_sell` containing "framework for documenting agent
identity" etc. is rejected with a legible reason.

---

## Roles — defaults and customization

Five roles ship as YAML files under `roles/`:

| Role | Allowlist size | What it does |
|---|---|---|
| `ceo` | (no constraint) | Default — EloPhanto's own voice, full tools |
| `sales` | 11 tools | Prospect search/eval/outreach + email + research |
| `support` | 9 tools | Inbound triage + email + knowledge + file read |
| `ops` | 10 tools | Scheduler + knowledge + shell + file |
| `marketing` | 9 tools | X posts + browser + content + research |

Inspect them:

```bash
elophanto role list             # all roles + active marker
elophanto role show sales       # full overlay + allowlist + KPI
```

Manually scope a CLI session to a role:

```bash
elophanto role use sales        # persisted to ~/.elophanto/current_role
elophanto role clear            # back to CEO default
```

When a role is active, the executor denies tools outside the
role's allowlist BEFORE the generic permission check —
role-deny short-circuits even auto-approve modes. The denial
message names both the role and the rejected tool.

**Add or edit a role**: write a YAML file under `roles/<name>.yaml`
(use any existing role as a template), then:

```bash
elophanto role sync             # re-read roles/*.yaml into DB
```

`sync_from_disk` is idempotent; safe to re-run after every edit.

---

## What to watch in `elophanto company report`

The report is your honest dashboard for one company. Read it
top-to-bottom:

```
<slug> — <name> (active)
Product: <first 200 chars of what_we_sell>
Data dir: <abs path>

  Revenue (in)              $X.XX
  Spend (out)               $X.XX
  Net                       $X.XX
  LLM tokens (out)          N
  Email touches (out)       N
  Pipeline advances (in)    N

Pipeline by stage (when prospects exist):
  new           N
  evaluated     N
  outreach_sent N
  replied       N
  converted     N
  rejected      N
  expired       N

Last 10 ledger events:
  <newest first>
```

**Signals to look for**:

- **`Product: (not defined — write companies/<slug>/company.yaml...)`** in
  yellow — the company has no product. The dream phase will skip
  the PRODUCT block and goal proposals will drift. **Fix
  immediately**: write the yaml.

- **Net = $0.00** for an extended period — the company is
  spending but not earning. Two cases:
  1. You haven't logged any inbound payments yet (real, just
     missing data — call `payment_audit.log` with
     `payment_type='inbound'` next time money lands)
  2. The company is genuinely not making money — time to revise
     `what_we_sell` or pause via `elophanto company pause <slug>`

- **Pipeline advances flat at 0 for >1 week** in a sales-active
  company — the agent isn't getting prospect movement. Check
  whether the sales role is actually being activated (run with
  `elophanto role use sales` for a session and observe).

- **Heavy LLM tokens, zero email touches** — agent is thinking
  loudly but not shipping. Either the role isn't right or the
  product is too abstract for the agent to act on.

---

## How the arbiter steers (and when to tune)

Per-cycle, the arbiter sees a menu of candidates from these
sources:

- `from_workable_checkpoints` — advance an active goal
- `from_mission_momentum` — touch a stale mission
- `from_role_neglect` — switch into a role that hasn't run lately,
  weighted by `kpi_gap` (how far the role's actual ledger sums
  are from its declared targets)
- `from_unproductized_companies` — propose a product for a
  company that has none (Phase 7)
- `from_dream` — generate new goal candidates via the dream tool
- `from_reflexes` — capability review, mission rebalance
- `from_external_signals` — stub (Phase 3.5)

The score combiner is **linear and inspectable**. Defaults:

| Weight | Default | Effect |
|---|---|---|
| `value` | 1.0 | core quality term |
| `lens_bonus` | 0.6 | today's value-lens match |
| `staleness_bonus` | 0.4 | per-source neglect signal |
| `affect_bias` | 1.0 | felt-state nudge |
| `cost` | 0.3 | penalty per cost unit |
| `mission_weight` | 0.5 | per-priority-weight bonus |
| `kpi_gap_weight` | 0.4 | per-unit KPI gap (max-gap role: +4 raw) |

Tune in `config.yaml` under `autonomous_mind.arbiter.weights`.
Operators rarely need to touch this — the defaults were chosen
so a typical candidate scores 4-5 and a max-leverage candidate
scores 7-9. Bump a weight only when you've seen the arbiter
consistently choose wrong across many cycles.

---

## When the agent proposes a product (Phase 7)

If the agent calls `company_set_product`, you'll see an approval
prompt naming the slug + a preview of the proposed
`what_we_sell`. Three things to check before approving:

1. **Does the consumer actually exist?** "We sell automations to
   indie operators" requires that *real indie operators* are
   reachable; "We sell a framework for documenting agent
   identity boundaries" is the navel-gazing trap and should be
   auto-rejected by the banlist (but check anyway).

2. **Is the deliverable concrete?** A real deliverable is a URL,
   a PR, a service running somewhere, an email landing in
   someone's inbox. A taxonomy or rubric is not a deliverable.

3. **Can the agent actually fulfil it?** The current toolset
   should cover the work. If not, the proposal is aspirational
   and you should either reject or add a note that fulfilment
   needs operator hands.

Approve → file lands at `companies/<slug>/company.yaml`. Next
cycle, the dream phase will inject the PRODUCT block and the
arbiter's `from_unproductized_companies` candidate disappears.

---

## What the data directory is for

`data/companies/<slug>/` is materialized on `company create` (and
backfilled for `elophanto-self` on first run). It's the
**per-company runtime-state location** — tools that opt into
per-company file state write here. As of Phase 6 nothing does
this yet; the directory is a primitive for future tool work.

---

## Pause / resume a company

```bash
elophanto company pause acme-inc      # status='paused', no longer 'active'
elophanto company resume acme-inc     # back to 'active'
```

Paused companies are filtered out by `from_unproductized_companies`
so the arbiter won't propose products for them. Existing rows
under a paused company keep working — pause is a "stop adding
new things" signal, not a hard freeze.

---

## Useful queries

The ledger is the read model for almost everything. Direct SQL:

```sql
-- Spend by week, per company
SELECT company_id, strftime('%Y-W%W', ts) AS week, SUM(amount) AS usd
FROM resource_ledger WHERE type = 'usd' AND direction = 'out'
GROUP BY company_id, week ORDER BY week DESC;

-- Top-spending models this month
SELECT note, SUM(amount) AS usd
FROM resource_ledger
WHERE company_id = 'elophanto-self' AND type = 'usd' AND direction = 'out'
  AND ts >= strftime('%Y-%m-01', 'now')
GROUP BY note ORDER BY usd DESC LIMIT 10;

-- Pipeline advances per role over the past week
-- (role_name only set when the agent attributed the advance —
-- can be NULL for operator-mediated advances)
SELECT role_name, COUNT(*) AS advances
FROM resource_ledger
WHERE type = 'pipeline_advance' AND ts >= datetime('now', '-7 days')
GROUP BY role_name;
```

---

## Common failure modes (from real production logs)

These all happened in development; the framework has guards
against them now.

1. **Empty `what_we_sell` → dream drift**. Symptom: dream phase
   proposes "Identity Memory Index" / "Self-Perception Diff
   Report" / "Evidence Garden" goals. **Cause**: company has no
   product so dream has no anchor. **Fix**: write the yaml.
   Phase 7's `company_set_product` tool also enforces this at
   write time (empty value → loader returns None).

2. **Wrong-role tool calls**. Symptom: agent tries to call
   `shell_execute` while operating in the SALES role and gets
   "denied by role gate". **Cause**: working as intended — the
   role allowlist is enforced before the generic permission
   check. **Fix**: either switch to a role with the tool, or
   `elophanto role clear` to go back to CEO with full tools.

3. **Ledger sums don't match payment_audit**. Symptom: the
   report's revenue line disagrees with what you see in the
   `payment_audit` table. **Cause**: a ledger write failed
   silently (the mirror logs warnings but swallows errors —
   source tables are truth, ledger is denormalized). **Fix**:
   re-run `elophanto company backfill` (idempotent, fills in
   missing rows by source_id).

4. **Agent stuck on `elophanto-self` even after `company use`**.
   Symptom: `elophanto company current` shows `acme-inc` but new
   rows still attribute to `elophanto-self`. **Cause**: the
   process you're observing (e.g. daemon) was started before
   `company use` ran. **Fix**: restart the daemon — the
   contextvar is loaded from sidecar at startup.

---

## When to revisit the framework

The deferred items in [`docs/76-ABE-FRAMEWORK.md`](76-ABE-FRAMEWORK.md)
each have a stated trigger. The ones most likely to fire first:

- **Phase 5 (board view)** — when you genuinely feel the gap
  between `company report` (transactional) and "I want to watch
  the agent decide in real time" (continuous)
- **Sessions UNIQUE constraint rebuild** (Phase 6 deferral) —
  when you run >1 company that shares a channel (e.g. both
  publishing through the same Telegram bot)
- **`roles.scope='company'` enforcement** (Phase 6 deferral) —
  when you want a role to mean different things in different
  companies (acme-inc's sales has different rules than
  elophanto-self's sales)
- **KPI calibration reflex** (Phase 7 deferral) — when target
  numbers in role YAMLs are obviously wrong for weeks and you
  want the agent to propose adjustments

None of these are urgent today. The Phase 1-7 substrate covers
the realistic use cases for one operator running 1-3 companies.
