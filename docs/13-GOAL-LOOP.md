# Phase 13 — Autonomous Goal Loop

## Overview

The Goal Loop allows EloPhanto to pursue multi-phase goals that span sessions, require progress tracking, and may need mid-run replanning. Any task that spans distinct phases — research, execution, verification — across minutes, hours, or days gets decomposed into ordered checkpoints with persistent state.

## Founder doctrine: stage, kill criterion, validate-first gate

(Added 2026-06-18.) Every goal and checkpoint carries a **founder-loop stage** — one of `scan | validate | build | launch | acquire | operate | scale` (default `unknown` for legacy rows) — and every goal carries a measurable **`kill_criterion`** (the abandon-threshold, decided before work starts: a number + a date/volume). Both are columns on `goals` (`stage`, `kill_criterion`) / `goal_checkpoints` (`stage`), populated by the decompose prompt or the `goal_create` tool.

**The validate-first gate** is the load-bearing rule: if a goal involves building, selling, launching, or growing something and there is no evidence yet that a paying party wants it, the decomposer makes the **first checkpoint a `validate`-stage checkpoint** whose success criterion is a real revenue-intent signal (paid pre-order, signed LOI, advertiser/sponsor/affiliate commitment) — never generic research, never a `build` step first. Research that doesn't end in a paying-party signal is treated as procrastination. Pure-research / internal-tooling goals legitimately have no `validate` stage.

Enforced two ways: (1) the `_DECOMPOSE_SYSTEM` prompt orders checkpoints accordingly, and (2) **`GoalManager.validate_gate_reason` + the goal runner** block execution of a `build`/`launch`/`acquire`/`scale` checkpoint while the goal still has an unfinished `validate` checkpoint. On gate fire the runner will: evaluate `kill_criterion` (cancel if met), `revise_plan` once if validate **failed**, or **reorder** pending validate ahead of build when the issue is only ordering — then pause only if those recoveries cannot proceed. The autonomous mind's prompts (`_MIND_PROMPT` rule 3, `_ARBITER_PROMPT`) are stage-anchored: validate beats everything pre-revenue; build means "a stranger can pay end-to-end"; acquire means one proven channel; operate means retention.

This pairs with the metabolism signal (the `[COMPANY]` state line shows net including the agent's own cognition cost) and the ABE finance rail ([80-ABE-FINANCE-RAIL.md](80-ABE-FINANCE-RAIL.md)).

## Autonomy hardening (closed loop)

(Added 2026-08.) Once a goal exists, the happy path is validate → build → launch **without babysitting**, pausing only for irreversible/CRITICAL acts or explicit trust promotion.

| Mechanism | Behavior |
| --- | --- |
| **Approval pause-not-deny** | Timeout → re-ping once → goal/checkpoint `awaiting_approval`. Never silent deny, never soft-auto-approve. Operator yes resumes the same checkpoint. See `core/approval_wait.py`. |
| **Kill criterion evaluation** | After checkpoint success/fail and on validate failure, numeric evidence (tool/SoR counts + age) can cancel the goal. Short `[kill_grace]` window allows undo. |
| **Tool-grounded receipts** | `verify_checkpoint_receipt` must pass before `mark_checkpoint_complete`. Quantitative claims with empty tool trail fail closed. **Percentages are proportions, not counts** — see below. |
| **No-progress guard** | Three consecutive evaluations calling for revision pauses the goal. Only a *goal-level* evaluation finding the goal on track resets the counter. |
| **CRITICAL always-ask** | Under `full_auto` / per-tool `auto`, `PermissionLevel.CRITICAL` still asks. Use `permission_mode: nuclear` to skip CRITICAL prompts too (only `tool_overrides: ask` still forces a prompt). |
| **GoalRunner context isolation** | `start_goal` clears inherited `in_agent_loop` so background goal work cannot skip `AGENT_LOOP` and run concurrent with Mind (2026-08-08 hang). |
| **AGENT_LOOP hold ceiling** | `agent.max_agent_loop_seconds` (default 7200) cancels a wedged holder so REL always fires; chat cannot block forever behind a hung cycle. |
| **revise_plan reactivates** | If a goal was marked `completed` and revise adds pending checkpoints, status returns to `active`. |
| **`budget_paused`** | Cost/time/LLM budget hits snapshot limits into context; resume only when a limit is **explicitly raised**. |
| **Instinct extract** | After a receipt-gated complete, optional few-shot instinct candidates (never force-applied). |

Tests: `tests/test_core/test_autonomy_hardening.py`.

### Two ways a goal used to loop forever, silently

Both were found by reading a 7-hour log on 2026-08-11, because neither
surfaced anywhere else.

**A percentage is not a count.** The receipt gate pulled every number out of
the success criteria and demanded each appear literally in the tool
evidence. `"A manifest covers 100% of discovered files"` yielded `100`, but
a run that genuinely covered all 37 files wrote *"37"* into the trail —
never `100`. Any criterion whose only number was a percentage was therefore
unsatisfiable, and the checkpoint could never pass however well the work was
done. One goal spent three hours failing the same receipt and escaped only
by rewriting the criterion to drop the "100%" wording — routing around the
gate rather than satisfying it. Percentages are now separated from counts:
a proportion requires the evidence to contain *some* count (you cannot
claim a fraction of a set you never enumerated), while counts still need a
word-boundary match. The count rule stays deliberately lenient — one
grounded count is enough — because it is a smell test for soft-completion,
and a stricter rule refuses honest work over phrasing, which is the failure
that caused the loop in the first place.

**The no-progress guard was dead code.** `revisions_without_progress` reset
on every *completed checkpoint*, but evaluation only runs after two
checkpoints complete — so each evaluation was preceded by two resets and the
counter read `1/3` forever. `_MAX_REVISIONS_WITHOUT_PROGRESS = 3` was
unreachable and the pause branch had never once executed. One goal revised
13 times across 2 hours and 55 completed checkpoints, every log line saying
`1/3`, and stopped only when the wall-clock budget cap tripped. The two
senses of "progress" disagree, and checkpoint-level was the wrong one: a
goal can tick off checkpoints indefinitely while going nowhere.

Tests: `tests/test_core/test_checkpoint_receipt_percent.py`,
`tests/test_core/test_goal_stall_guard.py`,
`tests/test_core/test_goal_failure_events.py`.

## How Goal Creation is Triggered

Goal creation is **LLM-driven, not rule-based**. There is no keyword matcher or heuristic that auto-creates goals. Instead, the system prompt includes a `<goals>` section that teaches the agent *when* to call `goal_create` vs working directly. Two mechanisms guide this decision:

1. **System prompt guidance** (`<when_to_create_goals>` in `core/planner.py`) — The LLM sees criteria for when a task warrants a goal: requires 10+ tool calls across distinct phases, spans research AND execution AND verification, may need to continue across conversations.

2. **Skill auto-loading** (`skills/goals/SKILL.md`) — When the user's message contains trigger words like "goal", "plan", "project", "achieve", "milestone", the goals skill is loaded into context, giving the LLM additional decomposition guidance and anti-patterns.

The LLM then decides: call `goal_create` for complex multi-phase work, or just work directly for simple tasks.

### Examples — When Goals ARE Created

| User says | Why it triggers a goal |
|-----------|----------------------|
| "Get a job at company X" | Research + resume + applications + follow-up across days |
| "Build me a portfolio website" | Design + implement + deploy + iterate — distinct phases |
| "Migrate our database from Postgres to MySQL" | Audit schema + write migration + test + cutover + verify |
| "Research competitors and write a market analysis report" | Gather data from multiple sources + synthesize + write + review |
| "Set up CI/CD for this project" | Evaluate options + configure + write pipeline + test + document |
| "Learn Python basics and build a small project" | Study topics + practice + plan project + implement + review |
| "Audit this codebase for security vulnerabilities" | Scan dependencies + review auth + check injections + report |
| "Plan and execute a social media campaign" | Research audience + create content + schedule posts + track metrics |
| "Refactor the monolith into microservices" | Map dependencies + define boundaries + extract services + test + deploy |

### Examples — When Goals Are NOT Created

| User says | Why it's handled directly |
|-----------|-------------------------|
| "List files in this directory" | Single tool call |
| "Search the web for Python tutorials" | One search, one response |
| "What's the weather in Tokyo?" | Simple lookup |
| "Fix the typo on line 42" | Single edit |
| "Summarize this PDF" | One document analysis call |
| "Run the test suite" | Single shell command |

### Edge Cases

The LLM uses judgment for tasks that sit between simple and complex:
- "Write a Python script that scrapes job listings" — Likely direct (single focused coding task)
- "Build a job scraping pipeline with scheduling, alerts, and a dashboard" — Goal (multiple distinct phases)
- "Research the best React state management library" — Likely direct (focused research)
- "Evaluate React state management libraries, prototype with the top 3, and recommend one with benchmarks" — Goal (research + prototyping + analysis)

## Architecture

```
User: "Build me a portfolio website"
         │
         ▼
   ┌─────────────┐     LLM decides this needs a goal
   │   Agent LLM  │────► Calls goal_create tool
   └──────┬──────┘
          │
          ▼
   ┌─────────────┐     LLM call (task_type="simple")
   │ goal_create  │────► Decompose into checkpoints
   │   tool       │◄──── [{order:1, title:"Research design trends", ...}, ...]
   └──────┬──────┘
          │ persist to goals + goal_checkpoints tables
          ▼
   ┌─────────────┐
   │ GoalManager  │     For each checkpoint:
   │  .execute()  │────► 1. Inject <active_goal> into system prompt
   └──────┬──────┘      2. Run agent loop (existing _run_with_history)
          │              3. Summarize + persist checkpoint result
          │              4. Self-evaluate: progress? revise plan?
          ▼
   ┌─────────────┐
   │  Checkpoint  │     On session boundary / max steps:
   │  persistence │────► Save state → resume next session
   └─────────────┘
```

## Components

### GoalManager (`core/goal_manager.py`)

Core orchestrator with methods for:

- **Lifecycle**: `create_goal()`, `get_goal()`, `get_active_goal()`, `list_goals()`, `cancel_goal()`, `pause_goal()`, `resume_goal()`
- **Decomposition**: `decompose()` — LLM decomposes goal into 3-20 ordered checkpoints
- **Revision**: `revise_plan()` — regenerates remaining checkpoints based on new information
- **Checkpoint tracking**: `get_checkpoints()`, `get_next_checkpoint()`, `mark_checkpoint_active()`, `mark_checkpoint_complete()`, `mark_checkpoint_failed()`
- **Context management**: `summarize_context()` — LLM compresses conversation into rolling summary; `build_goal_context()` — generates XML for system prompt injection
- **Self-evaluation**: `evaluate_progress()` — LLM assesses if plan needs revision
- **Budget enforcement**: `check_budget()` — caps LLM calls per goal

### GoalRunner (`core/goal_runner.py`)

Autonomous background executor. Runs goal checkpoints as `asyncio.create_task()` without waiting for user messages.

- **`start_goal(goal_id)`** — Launch background execution. One goal at a time.
- **`pause()`** / **`cancel()`** — Stop after current checkpoint or immediately.
- **`resume(goal_id)`** — Resume a paused goal's background execution.
- **`notify_user_interaction()`** — Called when user sends a message; sets `_stop_requested` flag so the loop pauses after the current checkpoint finishes.
- **`resume_on_startup()`** — Auto-resumes active goals when the agent restarts (if `auto_continue: true`).

**Execution loop** (`_run_goal_loop`):
1. Broadcast `GOAL_STARTED` event
2. Loop: get next pending checkpoint → execute via `agent.run(prompt)` → mark complete/failed → broadcast progress
3. Self-evaluate every 2 checkpoints (LLM checks if on track, revision needed)
4. Check safety limits (LLM calls, time, cost) before each checkpoint
5. Check `_stop_requested` flag between checkpoints (set by user interaction or pause)
6. When all checkpoints done → broadcast `GOAL_COMPLETED`

**Conversation isolation**: Each checkpoint starts fresh. Before `agent.run()`, the runner saves and clears `_conversation_history`, then restores it after. Goal context comes from the system prompt (via `build_goal_context()`).

**Approval routing**: Background checkpoint execution overrides the executor's approval callback to broadcast approval requests to all connected gateway clients. Any client on any channel can approve.

### Database Tables

**`goals`** — tracks goal lifecycle, status, context summary, budget counters.

**`goal_checkpoints`** — ordered steps within a goal with status tracking and result summaries.

### Tools

| Tool | Permission | Purpose |
|------|-----------|---------|
| `goal_create` | moderate | Start a new goal + trigger decomposition |
| `goal_status` | safe | List goals or show detailed checkpoint status |
| `goal_manage` | moderate | Pause, resume, cancel, or revise a goal |

### System Prompt Integration

Two XML sections are added to the system prompt via `build_system_prompt()`:

1. **`<goals>`** — static section (when `goals_enabled=True`) describing available tools, when to create goals, checkpoint execution rules, and self-evaluation guidance.

2. **`<active_goal>`** — dynamic section (when a goal is active) with goal ID, progress, current checkpoint details, context summary, and completed/remaining checkpoint lists.

### Protocol Events

Eight `EventType` values for gateway event propagation:

- `GOAL_STARTED`, `GOAL_CHECKPOINT_COMPLETE`, `GOAL_CHECKPOINT_FAILED`, `GOAL_REVISED`, `GOAL_COMPLETED`, `GOAL_FAILED`, `GOAL_PAUSED`, `GOAL_RESUMED`

Only successes used to be broadcast. Receipt-gate refusals, checkpoint
timeouts and plan revisions were `logger.warning` only, so from any channel
a goal failing the same checkpoint for the fifth time looked exactly like a
goal thinking — the operator's only way to find out was to read the log
file. `GOAL_CHECKPOINT_FAILED` carries `reason` and `attempts` (one failure
is work; the third in a row is a loop), and `GOAL_REVISED` carries
`revision`/`max_revisions` so a plan going in circles is visible while it
happens rather than afterwards.

### Skill

`skills/goals/SKILL.md` teaches the agent best practices for goal decomposition: concrete over abstract, 3-10 checkpoints, research before action, front-load unknowns, objective success criteria.

## Configuration

```yaml
goals:
  enabled: true
  max_checkpoints: 20
  max_checkpoint_attempts: 3
  max_goal_attempts: 3
  max_llm_calls_per_goal: 200
  max_time_per_checkpoint_seconds: 600    # base per checkpoint (attempt 1)
  context_summary_max_tokens: 1500
  auto_continue: true                     # auto-resume active goals on startup
  max_total_time_per_goal_seconds: 7200   # 2 hours total per goal
  cost_budget_per_goal_usd: 5.0           # max cost before auto-pause
  pause_between_checkpoints_seconds: 2    # brief pause between checkpoints
```

**Timeout escalation.** `max_time_per_checkpoint_seconds` is the budget for
*attempt 1*; attempt N gets N× the base, capped at 4×. A retry that got the
same budget as the attempt that just timed out would die the same death —
observed 2026-08-15, when a four-brand analysis batch needing ~25 minutes
burned all its attempts redoing the same first 10 minutes. On a timeout the
failure message names the budget spent and the next attempt's budget, and the
retry prompt tells the executor that work finished by earlier attempts is
real: verify what already has receipts from this run and do only the
remainder. The cap keeps the other half of the bargain — a checkpoint that
cannot finish in 4× base still exhausts `max_checkpoint_attempts` and pauses
the goal instead of holding it forever.

**Preemption is a yield, not a result.** Goal checkpoints run at the lowest
priority; operator chat and heartbeats preempt them at safe points, and the
response comes back marked `preempted`. The runner resets that checkpoint to
pending with the attempt refunded and re-picks it once the foreground drains
— it never verifies receipts on a preempted response's partial tool trail
(three checkpoints once shipped as "complete" with the summary "Task
stopped: preempted…"), and an operator asking "is it working?" can never
burn a checkpoint's attempts. Checkpoints left stranded `active` by a dead
run (hard cancellation, process kill) are reset to pending at loop start —
the runner is the only executor, so an active checkpoint it isn't running
is by definition abandoned, and skipping it silently is how one batch of
brands vanished from a plan until the reviser re-added it.

## Goal Lifecycle

```
planning ──► active ──► completed
               │
               ├──► paused ──► active (resume)
               │
               └──► failed

Any state ──► cancelled
```

## CLI surface

Goals are CREATED by the agent (via the `goal_create` LLM tool) — say
"set a goal to ..." in chat. From the CLI you can inspect and prune
the queue:

```bash
elophanto goals list                       # newest 20
elophanto goals list --status active       # filter by status
elophanto goals show <id>                  # detail + checkpoints + cost
elophanto goals cancel <id>                # mark cancelled (runner skips it)
elophanto goals pause <id>                 # active → paused
elophanto goals resume <id>                # paused → active
elophanto goals delete <id>                # hard-delete + checkpoints (confirms)
elophanto goals delete-all                 # wipe everything (confirms)
```

All read ops (`list` / `show`) bypass the LLM router and run offline.
A quick alias: `elophanto help goals` prints the same recipes.

## Context Management

At each checkpoint boundary, `summarize_context()` compresses the conversation into a rolling summary via a cheap LLM call. This summary replaces raw message history so the next checkpoint starts fresh with only the compressed context. The summary is stored in `goals.context_summary` and persists across sessions.

## Self-Evaluation

After every 2-3 checkpoints, the agent can call `evaluate_progress()` which asks the LLM: "Given what we've learned, should the plan be revised?" If revision is needed, `revise_plan()` regenerates the remaining (uncompleted) checkpoints while preserving completed ones.

## Budget Enforcement

Each LLM call increments `goal.llm_calls_used`. Before every call, `check_budget()` verifies the goal hasn't exceeded `max_llm_calls_per_goal`. Exceeding the budget pauses the goal.

## Files

| File | Description |
|------|-------------|
| `core/goal_manager.py` | GoalManager orchestrator |
| `core/goal_runner.py` | GoalRunner — autonomous background execution |
| `tools/goals/create_tool.py` | goal_create tool (triggers GoalRunner) |
| `tools/goals/status_tool.py` | goal_status tool |
| `tools/goals/manage_tool.py` | goal_manage tool (wires pause/resume/cancel to GoalRunner) |
| `skills/goals/SKILL.md` | Goal decomposition skill |
| `core/planner.py` | Extended with `<goals>`, `<autonomous_execution>`, and `<active_goal>` XML |
| `core/agent.py` | GoalManager/GoalRunner initialization, user-interrupt hook, context injection |
| `core/registry.py` | Goal tool registration |
| `core/database.py` | goals + goal_checkpoints DDL |
| `core/config.py` | GoalsConfig dataclass (includes background execution safety limits) |
| `core/protocol.py` | Goal event types (8 events) |
| `cli/gateway_cmd.py` | GoalRunner gateway wiring + startup resume |
| `cli/goals_cmd.py` | `elophanto goals` CLI (list / show / cancel / pause / delete) |
| `tests/test_core/test_goal_runner.py` | GoalRunner tests (12 tests) |

## Coordination with Autonomous Mind

When the autonomous mind is enabled (`autonomous_mind.enabled: true`), it coordinates with the goal loop:

- **Goal resumption**: The mind's priority stack places active goals at the top. On wakeup, if a goal has a pending checkpoint, the mind resumes it instead of starting independent work.
- **Pause/resume symmetry**: Both the goal runner and the mind pause on user interaction (`notify_user_interaction()`) and resume on task completion (`notify_task_complete()`). They share the same lifecycle pattern.
- **Event feedback**: Goal lifecycle events (checkpoint complete *and failed*, plan revised, goal complete, goal failed) are broadcast through the gateway. The mind sees these as pending events on its next wakeup cycle.
- **History isolation**: Both systems isolate their conversation history from user chat — saving, clearing, and restoring `_conversation_history` around each execution cycle.

See `26-AUTONOMOUS-MIND.md` for the full autonomous mind design.
