---
name: strategy-foundations
description: Marketing-strategy foundations distilled from the Phase 11 strategy generator. Use BEFORE drafting a strategy or proposing tactics so output reflects the PESO / RACE / STDC / JTBD frameworks and avoids generic agency clichés. Pairs with the `company_plan` tool — this skill is the meta-grounding; the tool runs the full LLM strategy generation.
license: MIT
metadata:
  author: petr-royce
  version: "1.0.0"
  phase: 11
---

# Strategy foundations — what makes a marketing plan real

A strategy is not a tactic list. A strategy is the **insight that
makes a specific set of tactics correct for a specific business at
a specific moment**. If the insight is missing, the tactic list is
indistinguishable from a generic agency deck.

## Triggers

- company_plan
- company_set_strategy_inputs
- marketing strategy
- positioning
- tactics
- campaign
- launch plan
- 30-day strategy

## The five agency principles (load-bearing)

1. **STRATEGY BEFORE TACTICS** — every tactic must ladder to a stated objective. If you can't name the objective in one sentence, the tactic is decoration.
2. **DISTINCTIVE > DIFFERENT** — create memory structures (recognizable hooks, repeated assets), not just differentiation. Sameness is invisible; memory is durable.
3. **COMPOUND EFFECTS** — prioritize tactics that build on each other over time (an editorial calendar that becomes a SEO moat) over one-shot stunts.
4. **MEASURE WHAT MATTERS** — vanity metrics (impressions, follower counts) are a distraction. Pick a North Star that corresponds to revenue or activation.
5. **SPEED TO LEARN** — launch fast, iterate faster. The perfect strategy that ships in week 4 loses to the rough strategy that runs experiments in week 1.

## Four strategic frameworks (apply at least one)

- **PESO** — Paid / Earned / Shared / Owned media. Maps every tactic to its distribution category so you know your channel mix.
- **RACE** — Reach / Act / Convert / Engage. Maps every tactic to its funnel stage. Most strategies over-index on Reach; balanced strategies have all four.
- **See-Think-Do-Care** — intent-based marketing. What is the audience trying to do at this moment? Tactics that don't match intent fail.
- **Jobs-to-be-Done** — focus on the customer outcome, not your features. "Hired for what job?" beats "what does it do?".

## Reference campaigns to learn from (real numbers)

- **Slack** — "So Yeah, We Tried Slack" — 8,000 companies in 24hrs from authenticity-led B2B viral.
- **HubSpot** — Inbound Marketing flywheel — $1B+ company built on free tools and content.
- **Spotify Wrapped** — UGC engine — 60M shares annually, zero ad spend.
- **Dollar Shave Club** — $4,500 video → $1B acquisition. Hook + ruthless brevity.
- **Notion** — Template Gallery — 30M users via community-led growth.

When proposing a tactic, name which reference campaign or framework it inherits from. "Editorial calendar" with no provenance is decoration; "HubSpot-style flywheel content" with three named pillars is a tactic.

## The four dead shapes (do NOT use)

1. **Tactic-first strategy** — listing tactics with no objective ("we'll do SEO + email + social"). Always start with the insight.
2. **Generic positioning** — "We help businesses leverage AI". Replace every "leverage" with a specific verb.
3. **Vanity-metric north star** — measuring impressions or followers. Pick a metric that connects to a dollar.
4. **One-channel monoculture** — putting all weight on one platform is fragile. PESO forces channel diversity.

## When you're inside `company_plan`

1. Read `company.yaml` (product) + `strategy_inputs` (business context) + the capability map from `company_capabilities`.
2. Pick the **strategy mode** from inputs (standard / unconventional / guerrilla / brand-awareness / controversial). Don't default — different brands need different tones.
3. Pick the **focus** (full / SEO / content / paid / social / email / brand / GEO). Match to the company's channels list, not your preference.
4. Output the full JSON schema (16+ fields) including the EloPhanto extensions: `vault_requirements`, `tool_requirements`, `voice_seed`, `agent_role_assignments`, `execution_priority`.
5. **Be exhaustive on requirements.** Every credential the strategy assumes (SMTP, social tokens) becomes a `vault_requirements` entry. Every tool/connector the strategy mentions (LinkedIn poster, podcast scheduler) becomes a `tool_requirements` entry. Missing entries become operator blockers later.
6. **Seed the voice contract.** Pull 3-6 hookTemplates from `creativeDirections`, list 3-8 banned phrases that would contradict the desired voice, name 2-4 tone descriptors, write one cta_style sentence. This pre-seeds Phase 10's voice gate so drafts are lint-able on day one.

## What this skill does NOT do

- It does NOT generate the strategy itself — that's `company_plan`'s job (it ships a full LLM-tuned prompt with these principles embedded).
- It does NOT pick tactics for any specific business — tactics depend on product + audience + budget + risk.
- It does NOT replace per-company `voice.yaml` — voice is downstream of strategy; the voice_seed in the strategy proposal feeds the Phase 10 contract.
