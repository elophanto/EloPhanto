---
name: plan-review-design
description: Use when reviewing the UX/UI portion of a plan before implementation — rate each design dimension 0-10, explain what would make it a 10, and patch the plan to get there.
---

## Triggers

- design plan review
- review ux plan
- check design decisions
- design critique
- review the design
- plan design review
- review ui plan
- visual design review (planning, not live audit)

# Plan Review — Design mode

## Overview

This review runs *between* CEO review and engineering review. By
this point the scope is set; this pass shapes the *user experience*
before architecture is locked. For live-site visual audits of
already-shipped UI, use a different skill — this one operates on
the plan, not on rendered pixels.

**Don't re-litigate scope.** If a design problem reveals a scope
issue, escalate it back to CEO review rather than silently shrinking
or growing the plan.

## Six dimensions to score (0–10)

For each, one sentence on what makes it a 10, then the score.

1. **First five seconds** — when a brand-new user lands, do they
   immediately understand what this is and what to do? "Hero says
   X" / "primary CTA is Y" / "what they see first is Z."
2. **Information hierarchy** — does the page/screen order things
   from most important to least? Can a user accomplish the primary
   goal without scrolling, hovering, or hunting?
3. **Native interaction patterns** — does the design lean on
   patterns the user already knows (web/iOS/Android conventions),
   or invent novel patterns that need explaining?
4. **State coverage** — every interactive surface needs explicit
   loading, empty, error, partial-success, and success states. A
   plan that only describes the happy path is a 0 here regardless
   of how pretty the happy path is.
5. **Accessibility floor** — keyboard navigation, focus states,
   colour contrast (WCAG AA minimum), screen-reader labels,
   captions for video, alt text for image. Not optional.
6. **Brand fit** — does this look and read like the same product
   it claims to belong to? Match the existing styleguide
   (`knowledge/system/styleguide.md`), don't invent a new vibe per
   feature.

Below 7 on any dimension ➜ patch the plan before approval.

## What you must add to the plan

If the plan is missing any of these, write them in directly:

- **Wireframe sketch** — ASCII or component-level breakdown of the
  primary screens. Doesn't need to be pretty; needs to be specific
  enough that an eng reviewer can map it to components.
- **Copy block** — exact text for hero, primary CTA, error states,
  empty state. "TBD copy" is not acceptable; if you genuinely don't
  know, write your best guess and mark it `[needs-copy-review]`.
- **State table** — for each interactive surface, list states
  (default / loading / empty / error / success) with what the user
  sees in each.
- **Responsive breakpoints** — what happens below 640 px wide?
  Below 380 px? Cite specifics, not "responsive."
- **Style references** — link to the existing components or
  patterns in the codebase or styleguide that this should mirror,
  so the eng review knows what already exists.

## How to use

1. Read the plan (path / text / active goal).
2. Pull `knowledge_search(scope="system")` for `styleguide.md`,
   `identity.md`, and any brand context.
3. Walk the six dimensions.
4. Patch the plan in place OR return a structured diff with
   escalations.

When called from `plan_autoplan`, return the JSON schema the tool
expects. When called interactively, narrative + revised plan is
fine.

## Hard rules

- Don't accept "we'll figure out copy later" — write it now or
  flag it.
- Don't accept loading/empty/error states marked TODO — design
  them or punt with a placeholder spec.
- Don't introduce new visual primitives without naming the
  existing ones we considered and rejected.
- Don't move ahead with accessibility scores below 7 — they
  compound into legal and reputation risk.

## What this skill does NOT do

- Pick architecture (eng review's job).
- Re-open scope (CEO review's job — escalate).
- Audit a live, deployed site (different skill).
- Write code or generate visual assets.

## Verify

- The deliverable for this phase exists as a concrete artifact (doc, ticket, board, repo) and its location is shared, not described
- Each commitment has an owner name, a due date, and a definition-of-done that someone other than the author could check
- Risks are listed with likelihood/impact and a named mitigation, not as a generic 'risks: TBD' bullet
- Dependencies on other teams/vendors/agents are explicit; an ack from each dependency is recorded or marked 'pending'
- Success criteria for the next phase are numeric or otherwise objectively testable
- A rollback / kill-switch / 'we will stop if X' criterion is written down before work starts
