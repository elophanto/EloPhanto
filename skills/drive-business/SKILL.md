---
name: drive-business
description: Canonical workflow for "drive my business" / "operate this company". Single entry point — branches internally to onboard (new), Phase 11 plan (existing without strategy), or execute (existing with strategy).
license: MIT
metadata:
  author: petr-royce
  version: "1.1.0"
  phase: 8.5+11
---

# Drive my business

The operator handed you a URL or business name and asks you to operate it. Do NOT respond conversationally. Do NOT jump straight to outreach. Do NOT just `goal_create` and call it done. Follow this decision tree.

## Triggers

- drive my business
- drive X.com
- I have a business at
- operate this company
- run my business
- set up X.com as ABE
- onboard X.com
- launch this business

## Decision tree

1. Resolve the slug from the URL/name (`alphascala.com` → `alphascala`).
2. `company_list` — does the slug exist?
3. If exists, check `data/companies/<slug>/strategy/active/strategy.yaml` — does an active strategy exist?

```
NEW slug                            → PATH A: onboard
EXISTING + no active strategy       → PATH B: Phase 11 pipeline
EXISTING + active strategy          → PATH C: execute (don't re-plan)
```

## PATH A — onboard a new company

Do NOT write `what_we_sell` blind and call onboard. Research first, propose the onboard params to the operator as a table, let them approve/modify, THEN call onboard. Same pattern as PATH B step 2.

1. **Research the business** (parallel where possible):
   - `browser_navigate(<url>)` + `browser_extract` on homepage
   - `browser_navigate(<url>/about)` + `/pricing` + `/hire` + `/faq` if they exist
   - `web_search('<domain> <industry>')` for industry context
   - `web_search('<domain> competitors')` for the competitive frame
2. **Propose onboard params** in chat as a table:

   | Field | Recommended | Rationale |
   |---|---|---|
   | `slug` | `<derived from domain>` | URL stem, lowercase, hyphenated |
   | `name` | `<from homepage title / brand>` | as the business presents itself |
   | `what_we_sell` | `<1-3 sentence value prop>` | from homepage + pricing page |
   | `seed_goal` | `"Establish baseline metrics + first paid customer"` (or stage-appropriate) | from product stage |
   | `price` | `<{amount, currency, model}>` | from /pricing if found, else `null` |
   | `fulfillment` | `<delivery model>` | from /hire or how the product is delivered |
   | `channels` | `<["channel1", "channel2"]>` | from contact methods / social links on the site |
   | `kpis` | `<[{type: pipeline_advance, target_weekly: N}]>` | from stated growth metrics or stage-appropriate defaults |

   Add: *"Approve all, or tell me which to change. Slug becomes the ABE id and shouldn't change after onboard."*
3. **After operator confirms**: ONE call to `company_onboard(slug, name, what_we_sell, seed_goal, price?, fulfillment?, channels?, kpis?)`. Atomically creates the row, writes `company.yaml`, persists the sidecar, materializes `exemplars/{twitter,email}/`. Trust state defaults to `learning`.
4. **Continue to PATH B** — newly onboarded means no strategy yet.

## PATH B — Phase 11 pipeline

See [[strategy-pipeline]] for the exact procedure. Briefly:

1. **Research, THEN propose strategy_inputs.** Do NOT ask the operator blank questions. Ground every field in research first, then present recommendations with one-line rationale. Operator approves all / modifies specific items / overrides:
   - **Research moves to run first** (parallel where possible): `browser_navigate(<url>)` + `browser_extract` + revisit `/about`, `/pricing`, `/hire` if they exist; `web_search('<domain> competitors')` or `web_search('<industry> top tools 2026')`; `company_report(<slug>)` for ledger/pipeline state; `file_read companies/<slug>/company.yaml` for declared channels/KPIs.
   - **Then propose** each field with rationale. Most CAN be derived from research:
     - `target_audience` ← from homepage + /hire positioning
     - `competitors` ← web_search + industry knowledge
     - `current_challenges` ← from company_report ledger gaps + product page friction
     - `unique_selling_points` ← from homepage value props + features
     - `primary_goals` ← from product type (hire page → Sales Growth + Lead Gen; content site → Thought Leadership)
     - `strategy_mode` ← from brand tone (corporate B2B → standard; punk brand → unconventional; small budget + viral potential → guerrilla)
     - `focus` ← from declared channels + recent ledger activity
   - **Operator-decided fields** (suggest defaults but flag for confirmation):
     - `budget_type` / `budget_amount` / `budget_period` — default to `organic` / `0` / `monthly` if no signal
     - `risk_tolerance` (0-100) — suggest 50 (balanced) unless brand tone is aggressive
     - `timeline_hint` — suggest "first paid customer in 30 days, repeatable cadence in 90" or similar based on stage
   - **Present as a table** in chat. Example format: `field | recommended value | rationale (≤15 words)`. Add: *"Approve all, or tell me which to change."*
2. **Bundle the rest in one call.** After operator confirms: `company_plan_full(slug, …strategy_inputs…)` — ONE MODERATE. Internally runs capabilities audit + writes strategy_inputs to `company.yaml` + generates the proposal + applies it (mission + goals + schedules + `voice_proposed.yaml` + `blockers.yaml`). Saves 2 of the previously chained MODERATE gates.
3. **Approve.** `company_plan_approve(<slug>)` — MODERATE finalize. Trust act for `voice_proposed.yaml` — kept separate by design so operator sees the voice draft before promoting.
4. **Surface blockers** to operator. Stop — autonomous mind picks up tactics on next wakeup.

**Fallback (legacy 4-call chain):** if `company_plan_full` is unavailable, fall back to `company_capabilities` → `company_set_strategy_inputs` → `company_plan` → `company_plan_apply` → `company_plan_approve`. Same result, 3 extra MODERATE gates.

## PATH C — execute existing strategy

The work is already planned. Don't re-plan unless operator asks.

1. `elophanto strategy show <slug>` (or `file_read strategy/active/strategy.yaml`).
2. `company_report <slug>` for current ledger/pipeline.
3. Unresolved blockers in `blockers.yaml` → surface to operator.
4. Don't create new goals yourself — arbiter is supposed to pick from strategy's tactics. Let it work.

## Hard rules

- ❌ Never `goal_create` directly for "drive my business" — bypasses planning.
- ❌ Never skip `company_capabilities` — it grounds the planner in available surfaces.
- ❌ Never promote `voice_proposed` or trust state yourself — operator only.
- ❌ Never draft outreach during this skill — drafts are downstream of plan + voice approval.

## Verify

- [ ] `companies/<slug>/company.yaml` has non-empty `what_we_sell`
- [ ] PATH B: `data/companies/<slug>/strategy/active/strategy.yaml` exists
- [ ] PATH B: blockers surfaced to operator with action hints
- [ ] Sidecar `~/.elophanto/current_company` points at the right slug
