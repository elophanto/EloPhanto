---
name: strategy-pipeline
description: Phase 11 procedure — capabilities → set_strategy_inputs → plan → apply → approve, plus 3-path blocker resolution (ask / build / defer). Covers WHOLE business surface via injected OPERATIONAL CONTEXT, not just what_we_sell.
license: MIT
metadata:
  author: petr-royce
  version: "1.1.0"
  phase: 11
---

# Strategy pipeline (Phase 11)

Called by [[drive-business]] PATH B, or directly when the operator asks to plan an existing productized company.

## Triggers

- company_plan
- company_capabilities
- company_plan_apply
- set up strategy
- capability audit
- 30 day plan
- marketing plan
- blockers
- strategy inputs

## Pipeline (5 tools, in order)

### 1. `company_capabilities(<slug>)`
Audit vault + tools + skills. Writes `capabilities.md`. Returns structured map.

### 2. Gather strategy inputs from operator in chat
Then `company_set_strategy_inputs(slug, …)` — MODERATE. Fields:
- `target_audience` (specific, not "businesses")
- `competitors` (3-5 by name)
- `current_challenges` / `unique_selling_points`
- `budget_type` (organic / mixed / paid) + `budget_amount` + `budget_period`
- `risk_tolerance` (0-100)
- `primary_goals` (3-5 from: Brand Awareness, Lead Gen, Sales Growth, Retention, Thought Leadership, Community, Content Authority, Market Disruption, Competitive Advantage, AI Search Visibility)
- `strategy_mode` (standard / unconventional / guerrilla / brand-awareness / controversial)
- `focus` (full / seo / geo / content / paid / social / email / brand)
- `timeline_hint`

### 3. `company_plan(<slug>, override_strategy_mode=…, override_focus=…)`
Deterministically prepends OPERATIONAL CONTEXT (active schedules + last-7d ledger + prospect funnel + missions) so the strategy covers EVERY surface, not just `what_we_sell`. Writes `strategy/proposed/<timestamp>.yaml`.

### 4. `company_plan_apply(<slug>)` — MODERATE
Atomically:
- Detects blockers (5 types — see below)
- Mission + N goals (tactic_meta packed in plan_json) + schedules (from `timeline.month1/2/3` via `execution_priority`)
- Writes `voice_proposed.yaml` from `creativeDirections.hookTemplates`
- Writes `blockers.yaml`
- Promotes proposed → active, archives prior

### 5. `company_plan_approve(<slug>, note="…")` — MODERATE
Operator finalize. Touches the strategy mission so arbiter ranks high.

## Blocker resolution (3 paths)

Each blocker in `blockers.yaml` has `resolution_proposal`:

- **`ask`**: operator must act (credentials, business decisions). Surface in chat with `build_hint`.
- **`build`**: `from_buildable_blockers` arbiter candidate invokes `self_create_plugin` (`build_method`) or `skill_promote`. CRITICAL permission gates each build. In chat mode, only attempt if operator explicitly OKs.
- **`defer`**: operator marked tactic out of scope. Note and move on.

## Surface coverage (CRITICAL)

The OPERATIONAL CONTEXT block lists every active surface (X growth, Pump.fun, email, prospect funnel, etc.). The resulting strategy MUST address each — not just `what_we_sell`. A single-surface strategy for a multi-surface business is a quality failure.

## Hard rules

- ❌ Don't skip `company_capabilities` — no operational context = narrow strategy.
- ❌ Don't skip operator approval of `strategy_inputs` — those calls aren't yours.
- ❌ Don't promote proposal to active via file_write — use `company_plan_apply`.
- ❌ Don't call `apply` + `approve` back-to-back without surfacing blockers between.
- ❌ Don't invoke `self_create_plugin` on a build blocker without explicit chat OK.
- ❌ Don't re-plan a company with an active strategy unless operator asks.

## Verify

- [ ] 5 steps ran in order
- [ ] `strategy/active/strategy.yaml` exists
- [ ] `blockers.yaml` surfaced to operator
- [ ] Voice seeded if hookTemplates populated
- [ ] Tactics span all surfaces from operational context
