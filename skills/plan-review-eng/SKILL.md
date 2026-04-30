---
name: plan-review-eng
description: Use when reviewing the implementation plan for architecture, data flow, edge cases, and test coverage before any code is written.
---

## Triggers

- eng plan review
- review the architecture
- review architecture
- engineering review
- lock in the plan
- tech review
- technical review
- plan engineering review
- arch review
- review implementation plan

# Plan Review — Engineering mode

## Overview

The plan has been through CEO and design review. Scope is locked,
shape is locked. This review's job: catch the architecture issues
that would make the plan painful to build, scary to ship, or
expensive to maintain.

This is the *third* review in the autoplan pipeline (CEO → design
→ eng). Run it after scope and shape are settled, not before — eng
review of a plan that's about to be re-scoped is wasted.

**Do not re-litigate scope.** If you find a fundamental scope
problem at this stage, escalate it to the user as a blocker rather
than silently rewriting it.

## Six dimensions to score (0–10)

For each, one-sentence "what would make it a 10," then the score.

1. **Architecture clarity** — does the plan name every component
   and the boundary between them? Could a stranger draw the diagram
   from the plan alone?
2. **Data flow** — for each user-facing action, is the path
   traced through every layer (request → auth → business logic →
   storage → response)? Are state transitions explicit?
3. **Edge cases** — what happens on partial failure, network
   timeout, duplicate request, expired auth, race condition,
   empty input, oversized input? At least 5 named edge cases per
   non-trivial component.
4. **Test coverage** — are there testable acceptance criteria for
   each shipped behaviour? What's the smallest reproduction for
   the bug that would convince us it's broken?
5. **Reversibility** — can changes be rolled back without data
   loss? Is the schema backwards-compatible? Are deploys staged?
6. **Operability** — what would the on-call person need to
   diagnose this at 3am? Logs, metrics, runbook, structured
   errors with codes?

Below 7 on any dimension ➜ patch the plan before approval.

## What you must add to the plan

If missing, fill these in directly (don't just flag them):

- **Module map** — list of files / new packages and what each
  owns. Reference existing files in the repo by path so callers
  can be located.
- **Schema diff** — table-level changes, indexes, constraints,
  migration order, backfill plan.
- **Failure modes** — bullet list of named failures + the agent's
  intended response (retry / fail-loud / silent-skip / escalate).
- **Acceptance criteria** — testable statements that match the
  CEO/design layer's "demand reality." Not "the function returns,"
  but "the user sees X within Y seconds."
- **Rollback** — exact steps to revert. If "we'd just push another
  commit," say so explicitly.

## How to use

1. Read the plan (path, text, or `goal_status` of the active goal).
2. Pull `knowledge_search(scope="system")` for the project's
   architecture/conventions docs and any previously-learned
   `scope="learned"` lessons (we don't want to repeat known
   mistakes).
3. Walk the six dimensions.
4. Either (a) patch the plan in place, or (b) return a structured
   diff + list of escalations.

When called from `plan_autoplan`, return JSON matching the schema
the tool expects. When called interactively, narrative is fine.

## Hard rules

- Don't add a new dependency without naming the alternative we
  considered and rejected.
- Don't change a public API without a deprecation path.
- Don't propose a schema change without a backfill / rollback
  plan.
- Don't paper over a known scope issue with engineering rigor —
  escalate to the user.

## What this skill does NOT do

- Re-litigate scope (CEO review's job — escalate instead).
- Critique UI/UX (design review's job).
- Write code or implement.
