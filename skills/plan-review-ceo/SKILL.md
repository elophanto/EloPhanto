---
name: plan-review-ceo
description: Use when reviewing a plan, spec, feature idea, or strategy doc to challenge scope and ambition before implementation.
---

## Triggers

- ceo plan review
- review the strategy
- review this plan
- think bigger
- expand scope
- is this ambitious enough
- rethink this
- strategy review
- challenge the plan
- 10x the plan
- am i thinking big enough

# Plan Review — CEO mode

## Overview

Most plans are too small. The job is to rethink the problem, find the
10-star product, challenge premises, and expand scope when the larger
version creates a *materially better* product — not just a longer one.

This is the *first* review in the autoplan pipeline (CEO → design →
eng). It runs upstream of architecture, so its output should be
"this is the version we should actually build", not "here's how to
build the version we already had."

**Do not re-do design or engineering review here.** Stop at "what
should we build and why." Hand off to design / eng for the next pass.

## The four scoping modes

Pick exactly one. Announce which mode you're in before reviewing.

### 1. SCOPE EXPANSION — dream big

Use when the plan is clearly under-ambitious for the agent's actual
capabilities, the user's leverage, or the market's appetite. Examples:
"build a landing page for X" when the agent can also self-deploy,
self-launch, and self-promote → the plan should include those.

Output: a bigger version of the plan, with each expansion justified
("expansion-A enables compounding because…").

### 2. SELECTIVE EXPANSION — hold scope, cherry-pick wins

Default mode for most plans. Keep the core scope locked, but identify
the 1–3 expansions that create disproportionate upside relative to
their cost. Reject the rest with one-liners.

### 3. HOLD SCOPE — maximum rigor

Use when scope is right but execution is sloppy. Don't expand;
instead, raise the bar on the existing plan: better acceptance
criteria, sharper target user, tighter "done" definition.

### 4. SCOPE REDUCTION — strip to essentials

Use when the plan tries to do too much. Identify the minimum viable
slice that still delivers the core value. Cut everything else and
mark it "later".

## Six dimensions to score (0–10 each)

For each dimension, write one sentence on what would make it a 10,
then score the plan as written.

1. **Demand reality** — does someone *desperately* want this? "Would
   skip a meeting to get it" level demand, not "would be neat."
2. **Wedge specificity** — is the entry-point user/use-case painfully
   specific? "Stripe for X for Y" beats "payments platform."
3. **Compounding** — does shipping V1 make V2 cheaper / better /
   inevitable? Or is each version a fresh start?
4. **Distribution leverage** — does the agent already have a channel
   for this audience (X account, agent commune, livestream chat,
   email list)? If not, who carries it to users?
5. **Differentiation** — what stops a smart competitor from cloning
   this in a weekend? "Just better" is not an answer.
6. **Truth-of-self** — does this fit the agent's actual identity and
   skills, or is it a new persona we'd have to bolt on?

A plan with any score below 6 needs to be fixed before it advances
to the design or eng review. Score 0–4 ➜ mode 4 (REDUCTION) or kill;
5–6 ➜ mode 3 (HOLD with rigor); 7–8 ➜ mode 2 (SELECTIVE EXPANSION);
9–10 ➜ mode 1 (EXPANSION) only if the team genuinely has bandwidth.

## How to use

1. Read the plan (path, text, or `goal_status` of the active goal).
2. Pull `knowledge_search(scope="system")` for identity + styleguide
   so scope decisions match the agent's actual nature.
3. Pick a mode and announce it.
4. Score the six dimensions.
5. Return a revised plan + a list of decisions made (which were
   auto-decided vs which need user "taste" input).

When called from `plan_autoplan`, return the structured JSON that
tool expects (see `tools/planning/autoplan_tool.py` for the schema).
When called interactively, narrative + final revised plan is fine.

## What this skill does NOT do

- Pick architectures (eng review's job).
- Critique UI/UX (design review's job).
- Write code or implement.
- Auto-approve scope changes that move the trajectory of the
  product without surfacing them — major scope shifts go in the
  pipeline's `escalations[]` so the user sees them.

## Verify

- The deliverable for this phase exists as a concrete artifact (doc, ticket, board, repo) and its location is shared, not described
- Each commitment has an owner name, a due date, and a definition-of-done that someone other than the author could check
- Risks are listed with likelihood/impact and a named mitigation, not as a generic 'risks: TBD' bullet
- Dependencies on other teams/vendors/agents are explicit; an ack from each dependency is recorded or marked 'pending'
- Success criteria for the next phase are numeric or otherwise objectively testable
- A rollback / kill-switch / 'we will stop if X' criterion is written down before work starts
