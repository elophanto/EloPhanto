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
  (`router.py:1002-1015, 1080-1093`), so the preferred planning provider never
  gets it. Codex does, but runs with `store: False, include: []`, so reasoning
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
