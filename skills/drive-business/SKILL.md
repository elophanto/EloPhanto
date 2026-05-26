---
name: drive-business
description: Canonical workflow for "drive my business" — handles both NEW companies (onboard) and EXISTING companies with no active strategy (run Phase 11 capabilities → plan → apply → approve). The single entry point for any operator request to operate / run / drive / market a business through EloPhanto.
license: MIT
metadata:
  author: petr-royce
  version: "1.0.0"
  phase: 8.5+11
---

# Drive my business — canonical operator intent

When the operator says **"drive my business at X.com"** or **"I have a business on X, can you operate it"** or **"set up X.com as an ABE"**, this is the canonical work item. It looks like a casual chat request; it isn't. It's a request to wire up (or revive) a complete ABE — product config, voice contract, marketing strategy, blocker resolution, autonomous cadence. Get this wrong and you waste hours of operator attention on slop.

## Triggers

- drive my business
- drive the business
- I have a business
- operate this company
- run my business
- can you operate
- can you drive
- set up X.com
- drive X.com
- onboard X.com
- I have a startup
- run the business
- launch this
- run the company

## When this skill fires

The operator hands you a URL or business name and asks you to operate it. Do NOT respond conversationally. Do NOT immediately do tactical work (outreach, posts, prospect search). Do NOT create a single `goal_create` and call it done. Follow this skill to wire the ABE properly first.

## Decision tree (apply at the start)

```
1. Resolve the company slug from the URL/name (e.g. alphascala.com → "alphascala").
2. Call company_list to check if the slug already exists.

3. Branch:
   a. SLUG IS NEW                       → go to PATH A: onboard
   b. SLUG EXISTS + no active strategy  → go to PATH B: plan
   c. SLUG EXISTS + active strategy     → go to PATH C: execute
   d. SLUG IS "elophanto-self"          → treat as PATH B unless company_list
                                          shows an active strategy mission
                                          ("<slug> — <strategy_name>")
```

The PATH branches are the load-bearing distinction. Read on for the procedure of each.

## PATH A — NEW company (onboard)

1. **Research the business.** `browser_navigate(<url>)`, then `browser_extract`. If the homepage is sparse, `browser_navigate(<url>/about)`, `<url>/pricing`, `<url>/hire`, or web_search the domain. The goal: write a 1-3 sentence `what_we_sell` grounded in the actual product, not the brand vibe.
2. **One call: `company_onboard`** — `slug`, `name`, `what_we_sell`, `seed_goal` ("Establish baseline metrics + first paid customer for <name>"), optional `price`/`fulfillment`/`channels`/`kpis` if you found them. This atomically creates the company row + writes `companies/<slug>/company.yaml` + persists the sidecar + materializes `data/companies/<slug>/exemplars/{twitter,email}/`. Trust state defaults to `learning` (drafts only — outreach refused).
3. **Continue to PATH B** — a freshly onboarded company has no strategy yet.

## PATH B — EXISTING company, no active strategy (Phase 11 pipeline)

This is the path that DIDN'T fire automatically until this skill was written. The Phase 11 pipeline must run before any tactical work.

1. **Audit capabilities.** `company_capabilities(company_id=<slug>)`. Writes `data/companies/<slug>/capabilities.md`. Returns the structured map (vault keys, tools by group, installed skills). This grounds the planner in what's actually available.
2. **Ask the operator** in chat for the strategy inputs you don't already know:
   - Target audience (specific — "early-stage technical founders", not "businesses")
   - Competitors (top 3-5 by name)
   - Current challenges (concrete pain points)
   - Unique selling points (what only this business does)
   - Budget type (organic / mixed / paid), amount, period
   - Risk tolerance (0-100 — 30=conservative, 60=balanced, 80=aggressive)
   - Primary goals (3-5; pick from common: Brand Awareness, Lead Generation, Sales Growth, Customer Retention, Thought Leadership, Community Building, Content Authority, Market Disruption, Competitive Advantage, AI Search Visibility)
   - Strategy mode (standard / unconventional / guerrilla / brand-awareness / controversial)
   - Focus (full / SEO / content / paid / social / email / brand / GEO)
   - Timeline hint ("first paid job in 7 days", "3-month rolling", etc.)
3. **Persist the inputs.** `company_set_strategy_inputs(slug=<slug>, …)`. Writes the `strategy_inputs:` section of `companies/<slug>/company.yaml`. MODERATE permission — operator approves the inputs before they shape the strategy.
4. **Generate the strategy.** `company_plan(company_id=<slug>, override_strategy_mode=…, override_focus=…)`. The tool deterministically appends the OPERATIONAL CONTEXT block (active schedules + last-7d ledger sums + prospect funnel + active missions) so the LLM addresses EVERY surface, not just `what_we_sell`. Returns the path of the proposed strategy YAML at `data/companies/<slug>/strategy/proposed/<timestamp>.yaml`.
5. **Apply the strategy.** `company_plan_apply(company_id=<slug>)` (defaults to newest proposal). MODERATE permission — operator approves the fan-out. Atomically creates: 1 mission + N goals (tactic_meta packed) + M schedules + `voice_proposed.yaml` (from `creativeDirections.hookTemplates`) + `blockers.yaml`. Archives any prior active strategy.
6. **Approve.** `company_plan_approve(company_id=<slug>, note="…")` — MODERATE. Touches the strategy mission so the arbiter ranks it high on next wakeup.
7. **Surface blockers to operator** in chat:
   - List unresolved blockers from `data/companies/<slug>/blockers.yaml`
   - For each `resolution_proposal=ask`: name the operator-actionable item ("add SMTP credential to vault", "approve voice_proposed.yaml")
   - For each `resolution_proposal=build`: explain the tool/skill you'll build via `self_create_plugin` / `skill_promote` once they OK it (operator still approves per CRITICAL invocation)
   - For each `resolution_proposal=defer`: confirm the operator wants the tactic skipped
8. **Voice contract.** If the company has exemplars at `data/companies/<slug>/exemplars/<channel>/*.md`, run `voice_extract` to propose a voice.yaml from them — voice_seed in the strategy is the day-1 starting point but operator-curated exemplars produce a stronger contract. Operator approves via `elophanto voice approve <slug>`.
9. **Stop.** Do NOT start drafting or scheduling work yourself — the autonomous mind will pick up the goals on its next wakeup, and the schedules created by apply will fire on their cron. Tell the operator what was set up and what they need to resolve.

## PATH C — EXISTING company, active strategy already (execute)

The work is already planned. Don't re-plan unless the operator asks to.

1. `elophanto strategy show <slug>` (or the equivalent file_read of `strategy/active/strategy.yaml`) — review what's in force.
2. `company_report <slug>` — current ledger / pipeline / role activity.
3. If there are unresolved blockers (`blockers.yaml`), surface them in chat — that's why the strategy isn't moving.
4. If schedules are firing but ledger is flat → there's a quality/voice issue. Check `voice.yaml` + recent rejected drafts in `companies/<slug>/drafts/<kind>/rejected/`.
5. Don't create new goals yourself unless the operator explicitly asks. The autonomous mind's arbiter is supposed to pick from the strategy's tactics; let it work.

## What NOT to do

- ❌ Do NOT respond conversationally and stop ("Sure, let me know what you want me to do") — drive the workflow.
- ❌ Do NOT call `goal_create` directly for "drive my business" — that bypasses the whole strategic-planning loop and produces work without a plan.
- ❌ Do NOT skip `company_capabilities` — the operational context it surfaces is what prevents narrow strategies that ignore active channels.
- ❌ Do NOT skip operator approval of `strategy_inputs` — the audience/competitor/budget calls are not yours to make.
- ❌ Do NOT promote `voice_proposed.yaml` to `voice.yaml` yourself — operator approves voice contracts.
- ❌ Do NOT promote trust state yourself — operator-only via `company_trust_set` or `elophanto company trust`.
- ❌ Do NOT create per-tactic outreach drafts during this skill's execution — drafts are downstream of plan approval + voice approval.

## Verify

Before reporting "done" on PATH A or B, check:

- [ ] `companies/<slug>/company.yaml` exists with non-empty `what_we_sell`
- [ ] `data/companies/<slug>/strategy/active/strategy.yaml` exists (PATH B)
- [ ] `data/companies/<slug>/blockers.yaml` exists (PATH B) and you've named the blockers to the operator
- [ ] `data/companies/<slug>/voice_proposed.yaml` exists if `creativeDirections` had hook templates
- [ ] One active mission for `elophanto-self — <strategy_name>` (PATH B)
- [ ] Goals created (PATH B) — count matches `tactics[]` length in the proposal
- [ ] `~/.elophanto/current_company` sidecar points to the right slug (so autonomous mind inherits)

Emit `Verification: PASS / FAIL / UNKNOWN` per check before returning the final response to the operator.
