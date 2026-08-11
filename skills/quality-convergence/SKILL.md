---
description: Produce work that survives independent review — spawn focused judges, revise against their objections, and don't stop until it clears the bar
triggers:
  - don't stop until
  - dont stop until
  - make sure it's really good
  - compare with the actual
  - benchmark against
  - review this properly
  - is this actually good
  - until you're happy with the quality
  - not good enough yet
requires_tools: [panel_refine]
---

## Description

Produce work that survives independent review — spawn focused judges, revise against their objections, and don't stop until it clears the bar.

## Triggers

- "don't stop until it's genuinely good / until each reviewer is satisfied"
- "compare it with the actual X" / "benchmark it against Y"
- "review this properly" / "is this actually good?"
- Any deliverable that has to stand next to a competitor's or a spec

## Instructions

The default failure of agent work is shipping the first draft. It reads well,
it is plausible, and nothing checked it. You are the worst possible judge of
your own output — you wrote it, so it matches your model of what was wanted by
construction.

### Reach for `panel_refine` when

- The work will be **compared against something specific** — a competitor's
  output, a spec, an existing implementation, a reference document.
- Being wrong is **expensive**: client deliverables, anything published, code
  touching money, auth, or deletion.
- The operator signals a quality bar rather than a task ("don't stop until…",
  "make it genuinely good").

### Don't reach for it when

- The task is a lookup, a single tool call, or a quick answer. Each round is
  several full agent runs — it is the most expensive tool you have.
- There is no reference and no clear standard. Judges asked to rate vibes
  return vibes.

### How to use it well

**Always supply `reference` when one exists.** It is the difference between
"is this good?" (unanswerable) and "does this match or beat that?"
(answerable). If the operator named something to compare against, pass it.

**Pick lenses that disagree.** Five judges asked "is this good" give you one
opinion five times. The built-in packs (`code`, `writing`, `analysis`) are
already distinct; add custom lenses when the work has a specific risk:

```
lenses: [{"name": "licensing", "brief": "GPL code copied into a
          PolyForm-licensed repo; attribution stripped"}]
```

**Keep `max_rounds` at 2–3.** If three rounds of specific critique have not
fixed it, the goal is underspecified — go back to the operator rather than
burning a fourth.

**Use `panel_review` alone** when the work already exists and you only need
the verdict — reviewing a PR, checking a draft before sending.

### Reading the result

`converged: true` means independent lenses accepted it. Say so plainly.

`converged: false` means **it did not pass**. The artifact is the best
attempt, not a result. Report the outstanding findings and say what is still
wrong — do not present it as finished and do not quietly drop the caveat.
The tool refuses to claim success it did not earn; you must not launder that
on its behalf.

A rejection that cites no specific defect is discarded by design. If the run
stops with "withheld approval without citing a defect", the panel had nothing
real to say — treat the work as unvalidated rather than as failed.

### The honest version of "don't stop until"

The operator asking for that wants the work to be good, not the loop to run
forever. Converging in one round is a success, not a shortcut. Spending three
rounds and still failing is worth reporting immediately — it usually means
the task was ambiguous, and another round will not fix ambiguity.

## Verify

- A `reference` was passed whenever the operator named something to match
- Lenses were genuinely distinct, not rewordings of "be good"
- `converged` was reported honestly, including when false
- Outstanding findings were surfaced rather than dropped
- The tool was not used for work that did not warrant the cost
