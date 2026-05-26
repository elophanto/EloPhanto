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

1. Research: `browser_navigate(url)` + `browser_extract`. If sparse, visit `/about`, `/pricing`, `/hire`. Write 1-3 sentence `what_we_sell` grounded in actual product.
2. ONE tool call: `company_onboard(slug, name, what_we_sell, seed_goal="Establish baseline metrics + first paid customer")`. Atomically creates the row, writes `company.yaml`, persists the sidecar, materializes `exemplars/{twitter,email}/`. Trust state defaults to `learning`.
3. Continue to PATH B — newly onboarded means no strategy yet.

## PATH B — Phase 11 pipeline

See [[strategy-pipeline]] for the exact procedure. Briefly:

1. `company_capabilities(<slug>)` — audit vault + tools + skills, writes `capabilities.md`.
2. Ask operator in chat for strategy inputs (audience, competitors, budget, risk, goals, mode, focus, timeline). Then `company_set_strategy_inputs(slug, …)` — MODERATE.
3. `company_plan(<slug>, override_strategy_mode=…, override_focus=…)` — LLM strategy generation.
4. `company_plan_apply(<slug>)` — MODERATE. Creates mission + goals + schedules + `voice_proposed.yaml` + `blockers.yaml`.
5. `company_plan_approve(<slug>)` — MODERATE finalize.
6. Surface unresolved blockers to operator. Stop — autonomous mind picks up tactics on next wakeup.

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
