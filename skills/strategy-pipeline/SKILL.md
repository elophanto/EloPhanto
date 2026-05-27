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

### 2. Research, propose recommendations, then capture inputs
Do NOT ask the operator blank questions. The agent has the research tools to ground every field. Operator's job is approve / modify / override, not fill blanks.

**Research first** (parallel where possible):
- `browser_navigate(<url>)` + `browser_extract` (homepage, /about, /pricing, /hire, /faq)
- `web_search('<domain> competitors')` and `web_search('<industry> alternatives 2026')`
- `company_report(<slug>)` — ledger gaps, pipeline state
- `file_read companies/<slug>/company.yaml` — declared channels, KPIs

**Propose each field with one-line rationale** in chat as a table:

| Field | Recommended | Rationale |
|---|---|---|
| `target_audience` | <derived from homepage + /hire positioning> | <evidence> |
| `competitors` | <3-5 from web_search> | <industry/category> |
| `current_challenges` | <from ledger gaps + funnel friction> | <evidence> |
| `unique_selling_points` | <from homepage value props> | <what only this does> |
| `primary_goals` | <3-5 from list below> | <inferred from product type> |
| `strategy_mode` | <one of: standard / unconventional / guerrilla / brand-awareness / controversial> | <from brand tone> |
| `focus` | <full / seo / geo / content / paid / social / email / brand> | <from active channels> |
| `budget_type` + `_amount` + `_period` | suggest `organic / 0 / monthly` if no signal | operator-decided |
| `risk_tolerance` | suggest 50 (balanced) unless brand tone suggests higher | operator-decided |
| `timeline_hint` | suggest based on stage (e.g. "first paid customer in 30d") | operator-decided |

Valid `primary_goals`: Brand Awareness, Lead Gen, Sales Growth, Retention, Thought Leadership, Community Building, Content Authority, Market Disruption, Competitive Advantage, AI Search Visibility.

Add: *"Approve all, or tell me which to change."*

**After operator confirms/modifies**: `company_set_strategy_inputs(slug, …)` — MODERATE. Uses the operator-approved values.

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
