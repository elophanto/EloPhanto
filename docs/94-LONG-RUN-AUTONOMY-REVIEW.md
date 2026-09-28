# 94 — Long-Run Autonomy Review

**Status**: Review + proposed plan · **Date**: 2026-09-28 · **Scope**: agent loop,
autonomous mind, goal runner, memory/learning, model routing

This review asks one question: *what stops EloPhanto from running unattended for
days, making sound decisions, and actually thinking?* Everything below was read
from source, the live `data/elophanto.db`, and the retained `logs/`. Line
references are to the tree at `f9992ab1`.

Per the verify-before-phase rule, this is a diagnosis and a plan, not a
contract: each phase in §6 gets its own verified expansion (exact SQL, exact
edits, test approach) and an explicit go-ahead before any code.

**Implementation status (2026-09-28):** all six phases are built, each
verified against the code and live DB first (§8–§13). The suite grew from
3,808 to 3,885 passing tests. The soak run (`tests/test_core/test_soak_long_goal.py`)
drives a ten-checkpoint goal through operator-chat preemptions and a
mid-checkpoint kill-and-restart in about 15 seconds: every checkpoint completes
at one attempt, nothing is redone, every interruption leaves a handoff, and
the goal is verified as a whole before it completes. What it cannot show is a
72-hour live run on real providers — that part of the definition of done
still needs one.

---

## 1. Verdict

EloPhanto has more autonomy *machinery* than it has autonomy. The engine is
there: a scored arbiter, missions, goals with stage gates, receipts, kill
criteria, preemption, a kill switch, judge panels. But long loops need three
things that it has only in weak form:

1. **State that survives *inside* a unit of work, and initiative that
   survives without the operator.** State *between* units is good: goal and
   checkpoint rows, files in the workspace, and each session's last 20
   messages all survive a restart, and the agent checks them before
   answering. After a restart, "continue" reliably resumes at the right
   checkpoint (§2). What is lost is the inside of a unit: an interrupted
   checkpoint reruns from its start, and what earlier attempts tried and why
   they failed is barely recorded. The restart itself also depends on the
   operator: about 60 chat messages ask the agent to continue, finish or
   resume, several after a goal had stalled.
2. **A verifier that is not the actor.** "Done" means the model stopped
   calling tools. The receipt gate accepts the model's own summary as
   evidence. Progress evaluation reads the model's own summaries. The one
   genuinely independent verifier in the codebase (`core/panel.py`) is an
   optional tool that no loop calls.
3. **A thinking step separate from the acting step.** The prompts tell the
   agent to keep plans to "one or two sentences" and the mind to make "no prose
   preamble". The preferred planning provider receives no reasoning parameter,
   and no reasoning is carried from one turn to the next.

The one mode that does have all three is **AutoLoop** (docs/47): state in an
experiment journal, an objective metric as verifier, one hypothesis per
iteration. That is why it is the only loop designed to run overnight. The plan
in §6 generalises the AutoLoop shape to goals and the mind.

The history confirms the diagnosis. More than 20 commits since May each fix one
specific way an unattended run stalled: the percentage receipt, the dead
no-progress guard, stuck checkpoints, the AGENT_LOOP wedge, mind starvation,
dream convergence, the role-pin leak, preempted-as-result, retries dying the
same death. Nearly all were found by a person reading a multi-hour log. The
fixes are right, but the method does not scale: every new capability adds new
ways to stall, and there is no harness that finds them before production does.

---

## 2. How a long run works today

Three loops share **one** `AGENT_LOOP` slot (capacity 1), arbitrated by strict
priority: USER 0 → SCHEDULED 1 → MIND 2 → HEARTBEAT 3 → CADENCE 4 → GOAL 5.

| Loop | Unit of work | What crosses to the next unit |
|---|---|---|
| Agent loop (`_run_with_history`, `core/agent.py:3903`) | up to 500 steps, stops when the model returns text | Compressed message list inside the run; afterwards a `memory` row (the goal text + the final reply, or `"Max steps reached"`) |
| Goal runner (`core/goal_runner.py`) | one checkpoint = one agent run at GOAL priority | Checkpoint status + `result_summary`, any files the checkpoint wrote to the workspace, and `goals.context_summary`: an LLM digest of the **first 500 chars** of the final answer (`goal_manager.py:1201-1205`). The tool trail is used by the receipt gate, then discarded |
| Autonomous mind (`core/autonomous_mind.py`) | one wakeup = one agent run, ≤ `max_rounds_per_wakeup` | `data/scratchpad.md` (model-written, tail 3,000 chars shown), `_last_action` = tool names only (`"browser_navigate + update_scratchpad"`), 10 `[RECENT]` memory rows |

Across a restart, the durable state is: goal and checkpoint rows (status,
`result_summary`, `context_summary`); the files the agent writes to the
workspace; each session's last 20 messages (user text and final replies, no
tool calls), saved to SQLite (`core/session.py:22, 290-311`); the scratchpad;
and the `memory` table. The agent reads these and checks live runtime state
before answering, so continuation works at **checkpoint granularity**. A real
example from 2026-09-12: after an overnight stop, "hello" got *"Research goal
paused at 22 of 24, exactly where we left it … verified interim state on disk
in `workspace/…`; runner is off"*, and "ok continue" resumed checkpoint 22
with nothing lost.

What does *not* survive is anything that was never written to one of those
places: tool results, intermediate findings a checkpoint had not yet saved
to disk, and the reasoning behind approaches that failed. That example worked
because the stop fell between checkpoints (the operator had asked it to
finalise). A stop in the middle of a checkpoint loses that checkpoint's
in-progress work.

Live-data picture (all counts from this machine):

- `memory`: 2,747 rows. **All 242 incomplete rows store the literal string
  `"Max steps reached"`.** The actual reason (stagnation, preemption, STOP,
  budget) is computed at `agent.py:5257` and then thrown away.
- Goal checkpoints: 481 completed, **138 incomplete (22%)**, each recorded
  with no trace of what it did.
- **360 mind-cycle memories begin with the identical prompt boilerplate**
  (`"You are EloPhanto in autonomous mode. The arbiter has scored…"`), because
  the stored "goal" is the whole prompt. The `[RECENT]` block shows `goal[:120]`,
  so the mind sees ten near-identical lines. The embedding covers the first
  1,000 chars (`memory.py:127`), which are mostly template, so semantic
  recall over mind history is close to noise.
- The loop was held by GOAL work for 12.1 h across 73 runs (≈10 min each).
  GOAL waited a median of 13 s for the slot, p90 100 s, **max 1,297 s** —
  against a 1,800 s checkpoint budget that includes that wait.
- 38 preemption yields; 34 checkpoints reset to pending after preemption, one
  of them at step 120.
- Every call carries ~96K chars of system prompt plus ~150K chars of tool
  schemas (135–291 tools), roughly 60–80K tokens, with no prompt caching.

---

## 3. P0 — defects that break long unattended runs today

Each is small and independent. **[V]** = verified first-hand in code or data;
**[R]** = reproduced by running the code path.

| # | Defect | Evidence | Effect on a long run |
|---|---|---|---|
| F1 | **Goal cost cap is dead.** `goal.cost_usd` is persisted but never incremented anywhere. | [V] no assignment in `core/`, `tools/`, `cli/`; upsert at `goal_manager.py:1375` writes the untouched value | `cost_budget_per_goal_usd` can never trip. The LLM-call cap counts only goal-manager calls (decompose/summarize/evaluate/revise), not the agent-loop calls that do the work. |
| F2 | **Checkpoint timeout includes queue time.** `asyncio.wait_for(submit_task(GOAL, …), timeout_s)` starts before the slot is acquired, at the lowest priority. | [V] `goal_runner.py:572`, failure path `698-722`; max observed wait 1,297 s vs 1,800 s budget | A checkpoint can burn a non-refunded attempt without running. If it has been running, it is hard-cancelled mid-tool — the exact thing cooperative preemption was built to avoid. |
| F3 | **Wrong goal in context.** Every run injects `<active_goal>` for the *most recently updated* active goal, not the one being executed. | [V] `agent.py:3978-3988`, `goal_manager.py:511` (`ORDER BY updated_at DESC`) | With two active goals, goal A's checkpoint can run under goal B's plan. The same block also appears in operator chat and switches off the nudges (`agent.py:4567`). |
| F4 | **Shared state mutated outside the lock.** The mind and the goal runner clear `_conversation_history` and swap `_approval_callback` / `_on_tool_executed` *before* `submit_task` acquires `AGENT_LOOP`, and restore them afterwards. | [V] `autonomous_mind.py:1326-1377`, `goal_runner.py:523-568` | Interleaved waiters restore each other's stale callbacks. A goal's tool trail — the receipt gate's evidence — can collect another loop's tools or lose its own. |
| F5 | **The knowledge consolidator deletes what the agent learned.** A 500-chunk cap drops the oldest chunks regardless of scope, then `_clean_orphaned_files` unlinks every `knowledge/learned/*.md` without chunks. | [V] `knowledge_consolidator.py:18, 134-161, 163-203`; 4,768 chunks live; last run: `capped 1166, disk_cleaned 52` | Lessons, strategies and self-create failure notes are erased from disk each day the mind runs. `last_accessed_at` is never written, so "stale" just means "old". Vector rows are left behind. |
| F6 | **Failures leave no reason in memory.** Every non-success exit stores `"Max steps reached"` in `memory`; the learner skips non-success outcomes. The stop reason does reach the session's conversation (`"Task stopped: {reason}…"`), so it lasts 10 turns in chat, not in long-term memory. | [V] `agent.py:5257-5281, 5296`, `learner.py:156`; 242/242 rows | The agent cannot learn from the runs it most needs to learn from, and in memory preemptions look the same as failures. |
| F7 | **Mind memories are the prompt.** The stored goal for a mind cycle is the full template. | [V] 360 identical-prefix rows; `autonomous_mind.py:1914`, `memory.py:127` | The mind's view of its own recent past is ten copies of its instructions. |
| F8 | **The receipt gate grades the model's own words.** `sor_text=goal.context_summary`; one number from the criteria appearing anywhere is enough; any successful tool call satisfies the keyword check. | [V] `goal_runner.py:612`, `checkpoint_receipt.py:117, 161-163`; [R] a checkpoint with **zero tool calls** passed | The completion gate for autonomous work can be satisfied by prose. The checkpoint prompt promises a "no fetches" check (`goal_runner.py:54-58`) that does not exist. |
| F9 | **Preemption restarts from zero, forever.** A preempted checkpoint is reset, refunded, and rerun with no retry note. | [V] `goal_runner.py:594-604` | Under steady chat/heartbeat load a long checkpoint can be restarted indefinitely without ever pausing or reporting. |
| F10 | **Silent goal stalls.** Failed checkpoints are skipped on resume (`get_next_checkpoint` reads only `pending`), then the loop exits "all done" without completing the goal. Only one goal runs; a second `goal_create` stays `active` with no runner. `resume()` flips to `active` before `start_goal` can fail. | [V] `goal_runner.py:119-121, 179-189, 323-331`; `create_tool.py:161-162` | Goals sit `active` with nothing executing them — the failure mode docs/75 was written to stop. |
| F11 | **Compression is mis-sized and cannot fail loudly.** It assumes a 200K window for every model; its circuit breaker records success even when summarisation failed. | [V] `context_compressor.py:21-24, 323-325, 480-481` | 128K models overflow before compression; a failing summariser is retried every step. |
| F12 | **Dead provider treated as transient.** Z.ai `429 code 1113 "Insufficient balance"` is handled as a rate limit with a 60 s cooldown. | [V] 76 occurrences in the latest log; `router.py:337-343` | The primary planning provider is retried indefinitely instead of being failed over and reported. |

Smaller items worth folding in: the loop detector's "block" is advisory (it
records *after* execution, `agent.py:4909`); the reflector is a log line with no
effect on control flow (`reflector.py:28-59`); `<autonomous_execution>` in
`planner.py` still says goals pause when the user messages (no longer true);
the mind's rule 6 says to mark checkpoints complete with `goal_status`, which is
read-only; the mind's "recover" candidate tells it to resume paused goals while
its prompt forbids exactly that; approval timeouts are 150 s + 150 s while the
comment says 5 min each (`approval_wait.py:26-28`); the kill-criterion regex
reads numbers from the criterion's own text ("fewer than 5", "in 14").

---

## 4. P1 — structural limits on long loops and thinking

### S1. Working state is checkpoint-grained, and resuming needs the operator

The durable layer that works (goal rows, workspace files, session history)
records *outcomes*. It does not record the working state *inside* a
checkpoint: an interrupted checkpoint reruns from its start, with the
400-char retry note (`goal_runner.py:468-519`) as the only memory of earlier
attempts, and no note at all after preemption. The goal runner already
collects a `tool_trace` with outputs (`goal_runner.py:543-566`) and then
throws it away. The mind already knows the candidate it picked
(`_last_arbiter_top`) and then records tool names.

The second gap is initiative. On startup the runner auto-resumes one active
goal and skips `budget_paused` and `awaiting_approval` goals (F10); a goal that
stalls stays stalled until someone says "continue". In the chat log the
operator does exactly that repeatedly, including after a goal sat stalled at
59 of 69 checkpoints (2026-08-11). The fix is to extend the layer that already
works: record what happens inside a checkpoint as it happens (§5.1) and let the
runner resume on its own from that record (§5.3).

### S2. Acting is favoured over thinking, everywhere

- `<reasoning>` in `_BEHAVIOR`: *"State your plan briefly before executing —
  one or two sentences, not a detailed breakdown"*; `<operating_principles>`:
  *"action-first … DO IT immediately"*. Right for chat; wrong as the only mode
  for a multi-day goal.
- The arbiter prompt: *"Begin by making the first tool call … No prose
  preamble."* The mind's choice between candidates is made with no written
  reasoning.
- Planning runs on Z.ai `GLM-5.3-Flash` with `reasoning_effort: medium` in
  config, but `_call_zai` / `_call_kimi` take no effort parameter
  (`router.py:1002-1015, 1080-1093`), so the setting never reaches the
  provider. *Correction (verified against Z.ai's API reference during
  Phase 2):* that does not mean GLM does not think — `thinking` defaults to
  enabled and `reasoning_effort` to `max`, so every call ran at maximum
  effort regardless of the config, and its `reasoning_content` was discarded
  every turn. Codex does, but runs with `store: False, include: []`, so reasoning
  is never replayed across tool turns. `LLMResponse` has no reasoning field.
- Temperature is fixed at 0.2 for planning.
- Decomposition is a single `task_type="simple"` JSON call that sees only the
  goal text: no memory, no lessons, no tool catalogue, no workspace
  (`goal_manager.py:680-702`). There is no draft → critique → revise pass, and
  `revise_plan` receives only `evaluation.reason` — `suggested_changes` is
  dropped.
- `evaluate_progress` runs only after two *successful* checkpoints, so a goal
  that keeps failing is never evaluated; a JSON parse failure reads as "on
  track" and resets the no-progress counter.

### S3. Every verifier is self-assessment

The model decides it is done; the receipt gate reads its summary; evaluation
reads its summaries; the browser verifier is the same model family on the same
goal. `core/panel.py` already implements the right primitive — independent
judges, rejections must cite a defect, blocking findings fail regardless of
score, honest non-convergence — but it is reachable only as a tool the model
may choose to call.

### S4. One slot, lowest priority, and yielding is expensive

Strict priority without aging (docs/76 — still unimplemented,
`task_resources.py:172, 204`) plus "preempt = restart" makes long goal work the
first casualty of a busy day. Cheap, resumable yields would make the priority
scheme harmless; today it throws away up to 120 steps per yield.

### S5. Guards instead of a harness

The core loop carries five overlapping stop mechanisms (same-tool window,
consecutive errors, response-hash dedup, loop detector, browser stagnation) and
the goal runner several more. None of the 249 test files runs a goal for
simulated hours. Each new stall is found in production, fixed locally, and
guarded with a unit test for that one shape.

### S6. Learning does not close

Lessons come only from successes. 9,599 instincts (75 MB) are written; the only
reader is the ambient-signal ranker; the evolver and pruner have no callers.
The "capture what you learned" nudge is switched off whenever any goal is
active or paused — exactly the long runs. And F5 deletes the lessons that do get
written.

### S7. The prompt is heavy and uncacheable

~60–80K tokens per call, rebuilt per run with the current time near the top of
the system prompt, and the tool list rebuilt each step. For a 100-step
checkpoint that is several million uncached input tokens and a lot of
attention spent on 200+ tool schemas that the checkpoint will never use. The
mind cycle also carries the scratchpad twice (system prompt
`<autonomous_mind_state>` and the user message).

### S8. The mind and the goal runner do not coordinate

The mind has no reference to the runner. Its "advance goal" candidate does
checkpoint work itself, outside the receipt gate. Goals the mind decomposes
become active with no runner. The attractor detector (docs/75 §4.1) is not
implemented, and the capability-review reflex is a stub that is always due.

---

## 5. What to build

### 5.1 The run ledger — the spine of every long loop

One durable, structured record per goal (and per mind *thread*, keyed by the
arbiter's `dedup_key`). DB tables plus a rendered markdown file in
`agent.workspace` so the operator can read it.

| Section | Written by | Rule |
|---|---|---|
| Objective + success criteria | decomposer | immutable once validated |
| Plan + assumptions + how each step will be verified | deliberation step (5.2) | revised only through `revise_plan` |
| Artifacts (path / URL / ID, checkpoint, tool receipt) | **code**, from tool results | append-only; never model-summarised |
| Established facts (claim + source receipt) | model via a `ledger_note` tool | a fact without a receipt is shown as unverified |
| Decisions (what, why, alternatives rejected) | model | append-only |
| Attempts that failed (what, why, what changes next time) | code (reason) + model (diagnosis) | append-only; read before every retry |
| Open questions / blockers | model | closed explicitly |
| Handoff note | model at yield/timeout/limit; code fallback | the resume point (5.3) |

The ledger replaces the 500-char `context_summary` in `_CHECKPOINT_PROMPT`,
replaces the scratchpad for goal-scoped state (the scratchpad stays as the
mind's cross-goal notebook), and is the evidence source for the receipt gate
(5.4). The goal runner's existing `tool_trace` becomes the artifact feed rather
than being discarded.

### 5.2 Deliberate at the moments that matter

Not "think more everywhere" — think at the points where a wrong call costs
hours:

- **Checkpoint start**: read the ledger, write a plan with explicit assumptions
  and a verification method into it, then act.
- **After a failure or a retry**: diagnose before acting (what failed, why,
  what is different this time). This is where the no-progress loops in the
  history came from.
- **Before an irreversible or CRITICAL action**: state the expected outcome
  and how it will be checked.
- **Mind arbitration**: a short written comparison of the top candidates before
  the first tool call, stored with the cycle — which also gives docs/75 §4.6 its
  "why did the agent do X" record for free.
- **Decomposition**: give it context (lessons, recent failures, tool catalogue,
  workspace, related past goals) and a draft → critique → revise pass on the
  planning tier, not `simple`.

Mechanically: pass reasoning/thinking parameters to Z.ai and Kimi (check each
provider's API for the field), carry reasoning across tool turns where the
provider supports it, and save reasoning summaries into the ledger's Decisions
section. Split the `<reasoning>` rule: keep "brief" for chat; require a plan
block for goal and mind runs.

### 5.3 Make every stop resumable

Preemption, timeouts, step limits, budget pauses and crashes all end the same
way: persist a handoff (ledger + the last few tool results + the model's
one-paragraph "where I am, what's next"), then resume from it. Preemption
becomes nearly free, a checkpoint can span days, and F6/F9 go away. The memory
row for a stopped run stores the reason and the handoff instead of
`"Max steps reached"`.

### 5.4 Put an independent verifier on the stopping condition

- Receipt evidence = tool outputs only; never `context_summary`. At least one
  tool call.
- The decomposer writes a machine-checkable `verification_method` per
  checkpoint where one exists (file exists and parses, URL returns 200, ledger
  row present, count ≥ N from a query), and the runner executes it.
- For judgment checkpoints (research quality, copy, strategy), run `panel`
  with a round cap; non-convergence pauses with the outstanding findings.
- Goal completion = one final verifier pass against the original success
  criteria, not "no pending rows".

### 5.5 Schedule for long work

Priority aging per docs/76, extended to GOAL, capped below USER; the checkpoint
clock starts at ACQ; a goal queue (several active goals, one executing,
round-robin at checkpoint boundaries); per-day cost/time envelopes that refresh,
so a multi-day goal continues inside a limit instead of pausing forever; goal
cost attributed from `CostTracker` (F1). Move the callback/history swaps inside
the lock, or make them contextvars as `run_isolated` already does (F4).

### 5.6 Memory that informs the next run

Store a real title (checkpoint title; the mind's chosen `action_spec`), the
outcome, the stop reason, and the artifacts. Add failure post-mortems as
lessons. Retrieve by checkpoint text at start *and* at every retry. Fix the
consolidator: never delete `learned/` files, make the cap scope-aware and much
larger, write `last_accessed_at` on retrieval, delete vector rows with chunks.

### 5.7 A long-run harness and a health digest

- **Soak harness**: a stub router with scripted responses plus fake tools, and
  a simulated clock, running a multi-checkpoint goal alongside chat,
  heartbeat and mind load. Assert invariants: no attempt burned without work;
  no goal `active` without a runner; every stopped run has a reason and a
  handoff; receipts cite tool outputs only; no checkpoint passes with zero
  tools; the goal context matches the goal being executed.
- **Autonomy health digest** (daily, pushed to the operator): attempts lost to
  queue timeouts, preemptions per checkpoint, zero-tool passes, orphaned active
  goals, empty memory rows, provider balance errors. It turns "read a 7-hour
  log" into a morning glance.

### 5.8 Lighten the prompt

Stable content first, volatile content (time, runtime state) last; enable
provider prompt caching where available; let a checkpoint declare the tool
groups it needs so it does not carry 200+ schemas; drop the duplicated
scratchpad in mind cycles.

---

## 6. Proposed order

Each phase gets a verified expansion (code + live DB) and an explicit
go-ahead before code, per the standing rule for this repo.

| Phase | Contents | Why this order |
|---|---|---|
| **0 — Stop the bleeding** | F1–F12, the small items in §3, and a **consolidator kill-switch first** (F5 is actively deleting data) | Independent, low-risk fixes; several are silently corrupting today's runs |
| **1 — Spine** | Run ledger (5.1), resumable stops (5.3), informative memory rows (5.6 storage half), soak harness skeleton (5.7) | Everything else reads or writes the ledger; the harness guards the rest |
| **2 — Thinking** | Deliberation points, reasoning parameters for Z.ai/Kimi, context-rich decomposition with critique (5.2) | Needs the ledger to store plans and decisions |
| **3 — Verification** | Tool-only receipts, `verification_method`, panel on judgment checkpoints, final goal verification (5.4) | Needs plans that state how they will be verified |
| **4 — Scheduling** | Aging, ACQ-based clock, goal queue, daily envelopes, mind ↔ runner coordination (5.5, S8) | Cheap yields from Phase 1 make aggressive scheduling safe |
| **5 — Learning + weight** | Failure post-mortems, retrieval at retry, instinct read path or removal, health digest, prompt caching and tool scoping (5.6–5.8) | Compounds once runs produce good records |

**Definition of done for this plan**: a goal with ≥ 10 checkpoints runs for 72
hours under normal chat, heartbeat and mind load, survives at least one restart
and several preemptions without redoing receipted work, pauses only for
CRITICAL approval or a real budget envelope, and every checkpoint's completion
can be traced to tool outputs in its ledger. The soak harness reproduces the
same run in minutes.

---

## 7. What not to do

- **Don't add another stagnation guard to the core loop.** There are five.
  Make stops cheap and recorded instead of adding ways to stop.
- **Don't solve continuity with a longer summary.** Summaries of summaries
  drift; the artifacts and failed attempts must be recorded by code, not
  paraphrased.
- **Don't raise `max_steps` or timeouts to get longer runs.** Longer single
  runs mean more context compression and more lost work per preemption.
  Shorter, resumable units with a ledger go further.
- **Don't make thinking unconditional.** Deliberation at checkpoint start,
  after failure, and before irreversible acts buys most of the value; thinking
  on every tool step mostly buys cost.
- **Don't let the actor grade itself** on anything that gates autonomous
  progress.

---

## 8. Phase 0 — verified implementation spec

**Status: implemented 2026-09-28.** Verified against the tree at `f9992ab1`
and the live DB. Core suite baseline 2,842 passed; after the change 2,872
(30 new tests in `tests/test_core/test_long_run_phase0*.py`), plus 966 in the
other suites.

Found while verifying, beyond the table below: the consolidator's "duplicate
merge" grouped on file + heading only, and all 6 such groups in the live
index were *different* chunks of one long section — it now merges only
identical content. The mind's highest-scoring candidate ("Advance goal …
next checkpoint") had it doing checkpoint work outside the runner; with a
runner present it now proposes only starting an idle runner.

| Fix | Change | Different from §3 |
|---|---|---|
| F1 cost | Goal runner adds `CostTracker.task_total` from each checkpoint run to `goal.cost_usd` and persists it. `_budget_limits_raised` parses `inf` snapshots. | `llm_calls_used` keeps its current meaning (goal-manager calls only). Counting agent-loop calls against the default cap of 200 would pause every real goal after two checkpoints; per-day envelopes (Phase 4) replace it. |
| F2 timeout | New `time_budget_seconds` on `Agent.run()` / `submit_task()`. The clock starts **after** `AGENT_LOOP` is acquired and stops the loop cooperatively between steps (`stop_reason="time_limit"`). The hard hold ceiling becomes budget + 300 s grace. The goal runner drops its outer `asyncio.wait_for`. | A timeout is now a cooperative stop, not a mid-tool cancellation. The hard ceiling remains only for hung awaits. |
| F3 wrong goal | `ExecutionContext.goal_id`. The goal runner sets it; `_run_with_history` builds `<active_goal>` for that goal. Other runs keep the most-recent-goal fallback. | — |
| F4 shared state | New `core/run_hooks.py`: a contextvar holding approval / tool-executed / tool-result hooks, read by the executor ahead of its instance attributes. `run()`/`submit_task()` gain `isolated_history=True`, which runs on a fresh history list. Mind, AutoLoop, heartbeat and goal runner stop mutating agent-wide state. | Covers heartbeat and AutoLoop too; §3 named only mind and goal runner. |
| F5 consolidator | Never deletes files. Removes the age cap and the age-based stale prune (the index is rebuilt from disk at every startup, so they only caused churn and, via the orphan pass, data loss). Instead it removes index rows whose file no longer exists, and deletes `vec_chunks` rows alongside every chunk it drops. | The 52 files already deleted are unrecoverable: `knowledge/learned/` is gitignored. |
| F6 / F7 memory | `AgentResponse.stop_reason` on every exit. Incomplete runs store `Stopped (<reason>) after N steps` + the last tools + the last note, not `"Max steps reached"`. New `memory_label` on `run()`/`submit_task()`: mind cycles store the arbiter intent, checkpoints store `Goal … checkpoint i/n: title`, heartbeats `Heartbeat standing orders`. The label is also what gets embedded. | — |
| F8 receipts | The runner passes no `sor_text` (the model's summary is not a system of record). The gate requires ≥ 1 successful tool call. Counts must appear in tool **outputs**, not in call parameters — the rule the retry note already states. | Stricter only where the gate was accepting prose or request parameters. |
| F9 preemption | A preempted checkpoint stores a resume note (steps done, the tools already run this attempt) in `result_summary`, and the next attempt is shown it even at attempt 1. | Full handoffs and a preemption cap are Phase 1 and Phase 4. |
| F10 stalls | Resuming a goal resets its `failed` checkpoints to pending. When no pending checkpoint remains the runner either completes the goal, pauses it with the failed checkpoint named, or pauses it as "plan incomplete" — never exits silently. An unexpected exception pauses the goal. When a goal stops, the runner starts the next active goal that has pending work. `resume()` while busy queues the goal instead of stranding it. | The simple "next active goal" hand-off is a minimal queue; round-robin is Phase 4. |
| F11 compression | `agent.context_window_tokens` (default 200,000) is passed to `needs_compression`/`tiered_compress`. Tool-call arguments count toward the estimate. A failed Tier-2 summary records a breaker failure. | — |
| F12 provider | Billing errors (`insufficient balance`, code `1113`, `insufficient_quota`, `credit balance`, HTTP 402) put the provider in a 1 h cooldown and log an error, instead of the 60 s rate-limit cooldown. | — |
| Small | The loop detector really blocks: once a call is blocked, the same tool with the same arguments returns an error without running. `<autonomous_execution>` no longer says a chat message pauses the goal. Mind rule 6 no longer names the read-only `goal_status`. Operator pauses are tagged `by operator`; the recover candidate and the prompt distinguish them from auto-pauses. The kill-criterion count regex needs a word boundary and a `:`/`=`, never reads the criterion's own text, and does not kill on absent evidence. The approval-wait comment matches its 150 s + 150 s values. | Kill-on-absent-evidence was the effective intent of the old code, but it never fired, and enabling it now would cancel goals on phrasing. |

---

## 9. Phase 1 — verified implementation spec (the spine)

**Status: implemented 2026-09-28.** 3,857 tests pass (13 new: ledger, note
tool, handoff, and the soak run). The soak run completes a six-checkpoint
goal through two chat preemptions and a mid-checkpoint kill-and-restart
with every checkpoint at exactly one attempt, no failures, a handoff per
interruption and every artifact on the record. Found while building it:
memory retrieval used the entire checkpoint prompt as its search query, so
every background run searched for the same instructions; it now searches by
the run's title.

Verified 2026-09-28 against `e02d0e04`. Live DB: 7 goals, 69 checkpoints, no
ledger table. New tables go in `_SCHEMA` (`CREATE TABLE IF NOT EXISTS`, run at
every `Database.initialize()`), so existing installs pick them up on restart.
`PRAGMA foreign_keys=ON` is set, so the ledger deliberately has **no** FK to
`goals`; `delete_goal` / `delete_all_goals` delete ledger rows explicitly.

**Run ledger** — `run_ledger` table and `core/run_ledger.py`:

```sql
CREATE TABLE IF NOT EXISTS run_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL,          -- goal_id today; "mind:<key>" later
    checkpoint_order INTEGER,         -- NULL = goal-level entry
    attempt INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL,               -- artifact|fact|decision|failure|question|handoff|plan
    content TEXT NOT NULL,
    ref TEXT NOT NULL DEFAULT '',     -- path / URL / id for artifacts
    source TEXT NOT NULL DEFAULT 'model',   -- 'code' | 'model'
    status TEXT NOT NULL DEFAULT '',  -- question: open|closed
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_ledger_thread ON run_ledger(thread_id, kind, id);
```

Written by **code** (the goal runner): artifacts extracted from each
successful call in the checkpoint's `tool_trace` — any `path` / `file_path` /
`output_path` / `url` parameter of a write-type tool, and any `path` / `url` /
`id` key a tool returned; a `failure` row for every failed attempt (receipt,
timeout, error) with the reason and the attempt's last tools; a `handoff` row
for every stop that is not a completion. Written by the **model** through a new
CORE tool `goal_note(kind, content, ref)`, which takes the goal from
`ExecutionContext.goal_id` (refuses outside goal work unless `goal_id` is
given). Rendered by `RunLedger.render(thread_id, max_chars=4000)` into
`_CHECKPOINT_PROMPT` as a `RUN LEDGER` block (artifacts, facts, decisions,
failed attempts, open questions, latest handoff), into `goal_status detail`,
and to `<agent.workspace>/goals/<goal_id>/LEDGER.md` after each checkpoint.
`context_summary` stays, labelled as prose.

**Resumable stops** — `_run_with_history(handoff=True)`: on `time_limit`,
`max_steps`, `stagnation`, `loop` or `errors`, one `simple`-tier call (30 s cap)
writes "where I am / what's next" from the last 12 messages into
`AgentResponse.handoff`; on `preempted`, `stop_file` and `budget` it is
code-only (no LLM call while a higher-priority task waits). The runner stores
it as the ledger `handoff`; the next attempt's prompt shows the latest handoff.

**Soak harness** — `tests/soak/harness.py`: a scripted router, a fake work
tool, a real `Agent` + `GoalManager` + `GoalRunner` + DB, with injected
preemptions and a runner restart. `tests/test_core/test_soak_long_goal.py`
asserts: no attempt burned without work; no goal left `active` with nothing
running; every stopped run has a reason and a handoff; every completed
checkpoint's receipt cites a tool output; the ledger holds the artifacts.

Different from §5.1: mind-thread ledgers are deferred — the mind does not know
which candidate it will pick until after the call. Phase 2 records the pick.

---

## 10. Phase 2 — verified implementation spec (thinking)

**Status: implemented 2026-09-28.** 3,861 tests pass (13 new).

Verified before code: Z.ai's chat completion API (docs.z.ai, API reference)
accepts `thinking: {"type": "enabled" | "disabled"}` (GLM-4.5 and later,
including GLM-5.3), `reasoning_effort` (`max`, `xhigh`, `high`, `medium`,
`low`, `minimal`, `none`; default `max`, effective when thinking is on),
returns `reasoning_content`, and keeps earlier turns' reasoning with
`clear_thinking: false`. Kimi's parameters were not verified, so Kimi only
has its `reasoning_content` captured; nothing new is sent to it.

| Piece | What it does |
| --- | --- |
| Effort reaches Z.ai | `_call_zai` passes the task type's `reasoning_effort` as `thinking` + `reasoning_effort` ("none"/"off" disables thinking; empty keeps the API default). `LLMRouter.complete(reasoning_effort=…)` overrides it per call. |
| Reasoning is kept | `LLMResponse.reasoning` carries Z.ai/Kimi `reasoning_content` and Codex reasoning summaries. The agent loop stores it on the assistant turn under the private key `_reasoning` (stripped before any other provider sees it), counts it in the context estimate, and uses it in handoffs. `llm.preserve_reasoning: true` sends it back to Z.ai with `clear_thinking: false` (off by default: it grows input tokens). |
| Checkpoint plan | `goals.deliberate` (default on): before each attempt, one planning-tier call at `goals.deliberation_effort` (default `high`) returns approach, steps, assumptions, risks, how the criteria will be shown by tool outputs, what it reuses, and on a retry a diagnosis of the last failure. Recorded as a ledger `plan` (with the reasoning summary), charged to the goal, and put in the checkpoint prompt. A failed planning call is skipped, never blocking. |
| Mind decision | `autonomous_mind.deliberate` (default on): a separate call weighs the arbiter's top candidates and commits to one with why, the rejected alternative, expected outcome and done-when. The acting prompt carries the decision; the dashboard intent and the memory title follow the actual pick; the role pin follows it too. |
| Pre-action review | `agent.pre_action_review` (default on): in mind/goal/heartbeat/scheduled runs, a CRITICAL tool call (static or dynamic level) gets a short review first. A decline returns the objection to the model without running the call; the identical call repeated proceeds. An approved review records the expected outcome and check as a ledger decision. Chat is never reviewed — the operator is present. |
| Plan critique | `goals.plan_critique` (default on): decomposition runs on the planning tier with context from `Agent._goal_plan_context` (related past runs with their outcomes, tools by group), then a critique pass checks the draft against seven rules plus `_PLAN_RULES` and returns a corrected plan; the critique is recorded as a goal-level ledger decision. An unusable critique keeps the draft. |
| Prompt rule | `<reasoning>` keeps "one or two sentences" for chat and adds: autonomous work follows the plan made before it, records decisions when reality contradicts it, and diagnoses a failed step before retrying. |

Not done, and why: replaying Codex's encrypted reasoning items across tool
turns (`include: ["reasoning.encrypted_content"]`) changes the Responses-API
input format and cannot be verified without live calls on the operator's
subscription; it stays a follow-up.

---

## 11. Phase 3 — verified implementation spec (verification)

**Status: implemented 2026-09-28.** 3,870 tests pass (9 new; the soak run
now also asserts the goal was verified as a whole before completion).

Verified 2026-09-28 against `d5d34a86`. `goal_checkpoints` has no column for a
check (live columns: id, goal_id, checkpoint_order, title, description,
success_criteria, status, result_summary, attempts, started_at, completed_at,
stage); one is added through `_MIGRATIONS`
(`ALTER TABLE goal_checkpoints ADD COLUMN verification TEXT NOT NULL DEFAULT ''`),
so existing rows read as "no check". `mark_checkpoint_complete` has exactly
one caller (the goal runner), so completion can move behind a final check.
`core/panel.py` exposes `run_panel(artifact, lenses, judge)` and
`assess(verdicts, bar)`; judges are plain LLM calls here, not agent runs, so
verification never contends for `AGENT_LOOP`. `core/net_policy.classify_host`
blocks private and reserved addresses for URL checks.

| Piece | What it does |
| --- | --- |
| Checks | Each checkpoint may carry `verification`: one check or a list, all of which must pass. `tool_output` (a successful call this attempt — optionally of a named tool — returned text containing X), `file_exists` (path relative to the workspace; optional `contains`, `min_bytes`), `url_ok` (public http(s) only, status < 400, optional `contains`), `artifact` (the ledger holds an artifact whose ref contains X), `judgment` (an independent panel — `analysis`, `writing` or `code` lens pack — reviews the checkpoint's result against its criteria). Unknown types are ignored, not failed. |
| Where checks come from | The decompose and revise prompts ask for a `verification` per checkpoint (code-checkable where possible, `judgment` only where quality is the point); the critique pass checks for it. |
| Runner | Checks run after the receipt gate. A failed check fails the attempt with the reason (and a panel's specific findings) in the retry note and the ledger. |
| Final verification | When the last checkpoint completes, the goal is not marked complete yet: one planning-tier call compares the original goal (and kill criterion) with the checkpoint results and the ledger and answers met / not met with the missing pieces. Met → completed. Not met → the plan is revised to add the missing work (at most twice), then the goal pauses for the operator with the findings. An unavailable verifier completes the goal, noting it on the ledger. |
| Self-recovery | A checkpoint that exhausts its attempts no longer pauses the goal at once: the runner revises the plan once with the ledger's failure history (splitting or re-approaching the checkpoint), up to twice per goal, and pauses only when that fails too. |
| Evaluation | `evaluate_progress` reads the ledger (artifacts, facts, failures) as well as summaries, parses leniently, and marks an unparseable answer as such: it no longer counts as "on track" and no longer resets the no-progress guard. `revise_plan` receives the evaluation's `suggested_changes`, which were dropped. |

---

## 12. Phase 4 — implementation (scheduling)

**Status: implemented 2026-09-28.** 3,877 tests pass (7 new).

Verified before code: `_PrioritySemaphore` kept a heap keyed `(priority, seq)`
at insertion, so a waiter's standing never changed however long it waited;
the only external reader of its internals is `status_dict()["waiters"]`.
`max_total_time_per_goal_seconds` was measured from `time.monotonic()` at loop
start. The capability-review reflex returned "due" unconditionally.

| Piece | What it does |
| --- | --- |
| Priority aging | `effective_priority(raw, waited)`: one level better per full 60 s of waiting, never better than SCHEDULED — aged work overtakes schedules and the mind, never operator chat. `release()` hands the slot to the best effective priority (ties by arrival); the winner holds at its aged level so a peer arriving next cannot immediately preempt it back out. `[agent_loop] ACQ` logs `aged_pri=` when aging decided it. |
| Work time and envelopes | `goal_usage (goal_id, day, cost_usd, seconds)`. Each checkpoint run's cost and `AgentResponse.elapsed_seconds` (loop time, never queue time) are recorded. The total-time cap reads the sum across all runs and restarts. `goals.daily_cost_envelope_usd` / `daily_time_envelope_seconds` (0 = off) pause a goal as `budget_paused` with `envelope_day=`; the runner lifts envelope pauses from earlier days itself. |
| Round-robin | `goals.round_robin` (off by default — sequential finishes each goal sooner): after each completed checkpoint the goal yields to the next active goal with work. |
| Attractor detector | `demote_attractor`: the same pick (dedup key, else action text) in 3 of the mind's last 5 cycles is ranked last and the prompt says why — docs/75 §4.1, unbuilt until now. |
| Capability-review reflex | Due only 7 days after the mind last picked it (`metadata.mind_last_capability_review`). |
| Mind ↔ runner | (Phase 0) with a runner present the mind proposes only starting an idle runner, never doing a checkpoint itself. |

---

## 13. Phase 5 — implementation (learning and prompt weight)

**Status: implemented 2026-09-28.** 3,885 tests pass (8 new; the soak run
now covers ten checkpoints).

Verified before code: `LessonExtractor.extract_and_store` returned early for
every non-completed run. The live instinct store holds 9,599 instincts, 6,932
of them single observations at the 0.3 confidence floor; `prune_stale` was
never called and, as written (`confidence < 0.3`), would remove none. Z.ai
caches identical prompt prefixes implicitly, reports
`usage.prompt_tokens_details.cached_tokens`, and bills cached input at about
half (docs.z.ai, context caching). The system prompt put the identity state,
runtime state and the clock ahead of 59K characters of static text.

| Piece | What it does |
| --- | --- |
| Failures teach | A run that stopped for an instructive reason (loop, stagnation, errors, time, steps — not preemption, STOP or budget) gets one "Avoid:" lesson extracted into `knowledge/learned/lessons`. So do a checkpoint that failed every attempt and a goal that failed its final verification. |
| Lessons are recalled | `Agent.recall_lessons` searches learned knowledge and matches *confirmed* instincts (seen 3+ times, cached) for the checkpoint planner and for decomposition context. |
| Instincts | Read path over confirmed instincts only, cached for 10 min instead of re-reading every file. **Nothing is pruned automatically**: deleting 6,932 unconfirmed instincts is the operator's call. |
| Health digest | `core/autonomy_health.py`: goals by status, active goals with nothing to run, checkpoints failing repeatedly, failures by cause, interruptions by reason, recoveries, goals verified complete, unfinished runs by reason, today's goal spend. As a tool (`autonomy_health`), a command (`elophanto goals health [hours]`), and a daily broadcast at `goals.health_digest_hour_utc` (default 07 UTC) to every channel. |
| Cacheable prompt | Static sections first; identity and self-perception state, runtime state, user, matched skills, knowledge, goal and mind context after them; the clock and current task last. Background runs pin their title instead of their whole prompt as `CURRENT TASK` (it was sent twice every step). The mind's own cycles and goal checkpoints no longer carry the mind scratchpad in the system prompt. Z.ai cached tokens are read, logged (`cached=N/M`) and billed at half. |

Not done, and why: per-checkpoint tool scoping. The tool list is a stable
part of the cacheable prefix; scoping it per checkpoint would break the cache
between checkpoints and risk stranding a tool the plan did not foresee.
