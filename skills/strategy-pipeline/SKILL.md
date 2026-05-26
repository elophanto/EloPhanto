---
name: strategy-pipeline
description: The exact procedure for company_capabilities → company_set_strategy_inputs → company_plan → company_plan_apply → company_plan_approve plus the 3-path blocker resolution loop (ask / build / defer). Auto-loads on planning verbs. Operates the WHOLE business surface, not just what_we_sell.
license: MIT
metadata:
  author: petr-royce
  version: "1.0.0"
  phase: 11
---

# Strategy pipeline — the Phase 11 procedure

This skill documents the exact steps for the Phase 11 strategic-planning pipeline. The [[drive-business]] skill calls this one as PATH B; you can also be triggered directly when the operator says "set up a strategy" / "plan the next 30 days" / "audit capabilities" for an existing productized company.

## Triggers

- strategy
- plan the
- planning
- set up strategy
- company_plan
- company_capabilities
- company_plan_apply
- company_plan_approve
- capability audit
- audit capabilities
- 30 day plan
- marketing plan
- launch plan
- blockers
- strategy inputs
- elophanto strategy
- pipeline strategy
- tactics
- run capabilities audit

## When this skill fires

- [[drive-business]] PATH B → reuse this skill for the procedure
- Operator says "let's plan", "set up the strategy for X", "what should we work on"
- A `from_unplanned_companies` arbiter candidate wins (autonomous mode)
- A `from_blocked_strategy_days` candidate wins (review stalled strategy)
- A `from_buildable_blockers` candidate wins (build a missing tool via self_create_plugin)

## The pipeline (5 tools, in order)

### 1. `company_capabilities(company_id=<slug>)`

Read-only audit. Writes `data/companies/<slug>/capabilities.md`. Returns:
- `vault_keys_count` — credentials available
- `vault_locked` — true means the audit couldn't read credentials
- `tool_groups` — `{email: [...], social: [...], prospecting: [...], ...}`
- `tool_count`, `skill_count`
- `capability_map` (structured)

This GROUNDS the planner in what's actually available. Always call FIRST.

### 2. Gather strategy inputs from the operator

If `companies/<slug>/company.yaml` already has a `strategy_inputs:` section, you can skip directly to step 3. Otherwise, ask the operator in chat for:

| Field | Example |
|---|---|
| `target_audience` | "early-stage technical founders shipping AI products, 1-10 person teams" |
| `competitors` | "Manus, browser-use, Firecrawl, Clay, Upwork freelancers" |
| `current_challenges` | "revenue is zero, prospects exist but no conversations, purchase friction from $ELO token requirement" |
| `unique_selling_points` | "agent runs the work locally with browser + email + filesystem access; signed paid-job envelope flow; public proof at /hire" |
| `budget_type` | `organic`, `mixed`, or `paid` |
| `budget_amount` + `budget_period` | `0` `monthly`, or `5000` `monthly` |
| `risk_tolerance` | 0-100. 30=conservative, 50=balanced, 70=aggressive, 90=very aggressive |
| `primary_goals` | 3-5 from: Brand Awareness, Lead Generation, Sales Growth, Customer Retention, Thought Leadership, Community Building, Content Authority, Market Disruption, Competitive Advantage, AI Search Visibility |
| `strategy_mode` | `standard` / `unconventional` / `guerrilla` / `brand-awareness` / `controversial` |
| `focus` | `full` / `seo` / `geo` / `content` / `paid` / `social` / `email` / `brand` |
| `timeline_hint` | "First 7 days: first paid job. First 30 days: 3 paid jobs and a weekly cadence." |

Then call `company_set_strategy_inputs(slug=<slug>, …)` — MODERATE permission, operator approves the captured inputs before they shape the strategy.

### 3. `company_plan(company_id=<slug>, override_strategy_mode=…, override_focus=…)`

Generates the strategy via LLM call. The tool deterministically prepends an OPERATIONAL CONTEXT block (active schedules + last-7d ledger sums + prospect funnel + active missions) so the LLM addresses EVERY surface this company operates, not just `what_we_sell`.

Output: `data/companies/<slug>/strategy/proposed/<ISO_timestamp>.yaml` — the LLM's proposed strategy, schema mirrors `tmp/strategy.js` 1:1 plus EloPhanto extensions (`vault_requirements`, `tool_requirements`, `voice_seed`, `agent_role_assignments`, `execution_priority`).

Returns:
- `proposal_path`
- `strategy_name`, `tactic_count`
- `vault_requirement_count`, `tool_requirement_count`
- `execution_priority`

The proposal sits in `/proposed/` until apply.

### 4. `company_plan_apply(company_id=<slug>)` — MODERATE

Reads the newest proposal (or a specific `proposal_path`). Atomically:
- Detects blockers (5 types — see below)
- Creates one mission ("`<slug> — <strategy_name>`")
- Creates one goal per tactic, packing `priority / channel / budget / expectedImpact / riskLevel / dependencies / successMetrics / inspiredBy` into `plan_json.tactic_meta`. Assigns roles from `agent_role_assignments` (advisory hint — arbiter still rotates).
- Creates schedules from `timeline.month1/month2/month3` (cron derived from `execution_priority`: `immediate` = daily 9am; `staged` = month1 daily, month2 every-3-days, month3 weekly; `experimental` = weekly review)
- Writes `voice_proposed.yaml` from `creativeDirections.hookTemplates` (skipped if `voice.yaml` already active)
- Writes `blockers.yaml` + `blockers.md`
- Promotes proposed → `strategy/active/strategy.yaml`; archives any prior active to `strategy/archive/<timestamp>.yaml`

### 5. `company_plan_approve(company_id=<slug>, note="…")` — MODERATE

Operator finalize. Verifies active strategy exists, touches the strategy mission (so arbiter ranks it high next wakeup), surfaces unresolved blocker count.

## Blocker resolution loop (3 paths)

After apply, `data/companies/<slug>/blockers.yaml` lists detected gaps. Each blocker has `resolution_proposal: ask | build | defer`.

### `ask` blockers
The operator must act. Surface them in chat with the `build_hint` (which says WHAT the operator needs to do). Common case: missing vault credentials (SMTP, social tokens, deploy keys). Never try to build credentials yourself.

### `build` blockers
The autonomous mind's `from_buildable_blockers` candidate can win arbitration and invoke the build tool:
- `build_method: self_create_plugin` → invokes the tool with `goal=<build_hint>`, CRITICAL permission gates the actual build, LLM-generates Python + tests + git-commits + registers the new tool
- `build_method: skill_promote` → identifies 2-30 lesson files matching the gap + invokes `skill_promote`, MODERATE permission

In chat mode, only attempt a build if the operator explicitly approves: "build the LinkedIn poster". Otherwise surface it and let the autonomous arbiter pick it up.

### `defer` blockers
The operator marked the tactic out of scope. Note it in your response; don't fight it.

## Surface coverage (CRITICAL)

The `OPERATIONAL CONTEXT` block prepended to the planner's input lists active schedules, ledger sums, prospect funnel, and missions. The resulting strategy MUST address every distinct surface listed there — not just the company's primary `what_we_sell`.

Example: if the operational context shows X growth schedules + Pump.fun livestream + Polymarket monitor + email inbox, the strategy can't just produce 7 tactics about the `/hire` page. It needs tactics that distribute across all five surfaces with explicit allocation in `budgetAllocation` / `resourceAllocation`.

If the LLM produced a single-surface strategy anyway, that's a quality failure — re-plan with explicit operator guidance like "the strategy must include tactics for X / Pump.fun / Polymarket as well as the hire page".

## What NOT to do

- ❌ Do NOT skip `company_capabilities` — without it the planner has no signal about active surfaces.
- ❌ Do NOT skip operator approval of `strategy_inputs` — those calls (audience, budget, risk) aren't yours to make.
- ❌ Do NOT promote a proposal to active manually via `file_write` or `shutil.move` — use `company_plan_apply`.
- ❌ Do NOT call `company_plan_apply` and `company_plan_approve` back-to-back without surfacing blockers to the operator in between — the approve step assumes operator review of blockers.
- ❌ Do NOT invoke `self_create_plugin` on a `build` blocker without explicit operator OK in chat mode (autonomous mode goes through the arbiter + CRITICAL approval).
- ❌ Do NOT re-plan a company that has an active strategy unless the operator asks; check via `company_report` or `data/companies/<slug>/strategy/active/strategy.yaml` first.

## Verify

- [ ] Steps 1-5 ran in order; nothing skipped.
- [ ] `data/companies/<slug>/strategy/active/strategy.yaml` exists.
- [ ] `data/companies/<slug>/blockers.yaml` exists; unresolved blockers surfaced to operator in chat.
- [ ] If voice was empty + `creativeDirections.hookTemplates` populated: `voice_proposed.yaml` exists for operator approval.
- [ ] Strategy addresses every surface from the operational context, not just `what_we_sell`.
- [ ] At least one tactic per non-empty channel in `companies/<slug>/company.yaml`.

Emit `Verification: PASS / FAIL / UNKNOWN` per check.
