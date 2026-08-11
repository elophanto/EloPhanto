# 86 — Judge Panels

*Independent review, and the refine-until-good loop.*

Status: shipped 2026-08-10.

## Why

EloPhanto had four ways to spawn work — `delegate`, `swarm_*`, `org_*`,
`kid_*` — and they all shared one shape: dispatch, collect, continue. That is
fan-out, and it is the easy half.

None of them **converge**. Nothing kept working until the result was actually
good, judged by something other than the model that produced it. That gap
shows up as the most common failure of agent work: the first draft is
returned as the answer. It is coherent, it is plausible, and nobody checked
it against anything.

Asking the same model "is this good?" does not help. It wrote the thing, so
the output matches its own model of what was wanted by construction. It will
say yes.

This tier is the missing primitive:

```
produce → N independent judges, each with a distinct lens
        → accept, or feed the specific defects back and revise
        → repeat until the bar is met or the budget is spent
```

## The five rules

Each is enforced in `core/panel.py` rather than asked for in a prompt,
because each one is a specific way the loop otherwise degrades into theatre.

**1. Judges are independent.** Each sees the artifact, the reference, and its
own lens — never another judge's verdict. Show them each other's scores and
they converge on the first opinion voiced, which is one reviewer wearing five
hats and costing five times as much.

**2. A rejection must cite a specific defect.** A judge that fails something
without naming what is wrong has its rejection discarded. Without this the
loop never terminates: there is always a vaguer dimension on which something
"could be stronger". `Verdict.counts_as_rejection` is where the rule lives.

**3. A blocking finding fails regardless of score.** 4.6/5 with a security
hole is not a pass. Averaging is precisely the operation that hides the
defects that matter.

**4. The producer never judges its own work.** Self-assessment is what the
panel exists to replace.

**5. It terminates, and says so honestly.** Hitting the round cap returns
`converged: false` with the outstanding findings — never a success claim. A
loop that cannot fail is not a quality gate, it is a delay.

## Lenses

Distinct lenses are the entire point. Five judges asked "is this good?"
produce one opinion five times; five judges asked about correctness,
coverage, fidelity to the reference, failure modes, and what is missing
produce five different objections.

Three packs ship (`code`, `writing`, `analysis`), each with a `fidelity`
lens that compares directly against the supplied reference. Custom lenses
combine with a pack:

```json
{"lens_pack": "code",
 "lenses": [{"name": "licensing",
             "brief": "GPL code copied into a PolyForm repo; attribution stripped",
             "blocking": true}]}
```

A `blocking: false` lens (concision, simplicity) contributes to the score but
cannot veto. That distinction matters: style should inform, not gate.

## The tools

| Tool | Permission | Does |
|---|---|---|
| `panel_review` | SAFE | Judge an existing artifact, return per-lens scores and defects |
| `panel_refine` | MODERATE | Produce → judge → revise, until it clears the bar |

`panel_refine` is MODERATE because a single call is several full agent runs —
one producer plus one judge per lens, per round. It is the most expensive tool
in the registry and should be reserved for work that has to stand comparison
with something.

**Judges run with a read-only registry view.** A reviewer that can edit the
thing it is reviewing is not a reviewer, and one that can spawn reviewers is a
fork bomb with opinions. The exclusion list covers writes, shell, HTTP,
browser, payments, and every spawn tier including `panel_*` itself.

## Reading the result

`converged: true` — independent lenses accepted it.

`converged: false` — **it did not pass**. The artifact is the best attempt,
not a result. The tool attaches an explicit `warning` telling the caller to
report the outstanding findings rather than presenting the work as finished.
The `quality-convergence` skill reinforces the same thing on the model side:
the tool refuses to claim success it did not earn, and the agent must not
launder that on its behalf.

There is a third outcome worth distinguishing: *rejected, but nobody could say
why*. The loop stops immediately rather than spinning, and reports that the
panel withheld approval without citing a defect. That is a signal the work is
unvalidated, not that it is bad.

## Also in this change: `delegate` is actually parallel

`delegate`'s own docstring said "Sequential in v1" while its description
promised "fan out N **parallel** sub-tasks". It now runs its subagents
concurrently, four at a time.

Concurrent subagents serialize inside `run_isolated` (see below); the cap
here is about queue fairness — the shared
`LLM_BURST` / `BROWSER` semaphores already bound real resource use, so this
only stops one ten-way delegation from starving everything else in the
process. Results are gathered with `return_exceptions=True` and re-sorted by
index, so one crashing subagent cannot cancel its siblings and callers still
get results in the order they asked for them.

**`run_isolated` serializes.** It swaps shared instance attributes —
conversation history, working memory, activated tools, the *filtered
registry* — and restores them in a `finally`. That is only correct one call
at a time: concurrently, the second caller saves the first's swapped-in state
instead of the parent's, both read whichever landed last, and the parent is
left holding a subagent's history. The registry swap makes it a safety bug
rather than merely a correctness one, since that filter is what hides payment
and spawn tools from subagents.

A lock inside `run_isolated` is the honest fix for the current design: callers
that `gather()` queue rather than corrupt each other. Genuine parallel
subagents need this state moved off the instance — contextvars or a per-call
context object — which is a larger change than this tier warranted. Subagents
also now get their own `LoopDetector`, so a sibling's reset cannot wipe the
parent's counters and four siblings legitimately reading the same file no
longer look like one agent repeating itself.

## Files

| Path | Role |
|---|---|
| `core/panel.py` | Lenses, verdicts, `assess`, `run_panel`, `converge` |
| `tools/panel/panel_tool.py` | `panel_review`, `panel_refine`, exclusion lists |
| `skills/quality-convergence/SKILL.md` | When to reach for it, and how to read the result |
| `tools/delegate/delegate_tool.py` | Now concurrent |

Tests: `tests/test_core/test_panel.py` — 42 covering finding quality, the
assess rule, verdict parsing, judge independence, and every convergence exit.

The engine is transport-agnostic: `converge()` takes `produce` and `judge`
callables, so the same logic drives real subagents in production and plain
functions in tests. None of the 42 tests needs an LLM.
