# Phase 13 — Autonomous Goal Loop

## Overview

The Goal Loop allows EloPhanto to pursue multi-phase goals that span sessions, require progress tracking, and may need mid-run replanning. Any task that spans distinct phases — research, execution, verification — across minutes, hours, or days gets decomposed into ordered checkpoints with persistent state.

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

Six `EventType` values for gateway event propagation:

- `GOAL_STARTED`, `GOAL_CHECKPOINT_COMPLETE`, `GOAL_COMPLETED`, `GOAL_FAILED`, `GOAL_PAUSED`, `GOAL_RESUMED`

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
  max_time_per_checkpoint_seconds: 600    # per checkpoint
  context_summary_max_tokens: 1500
  auto_continue: true                     # auto-resume active goals on startup
  max_total_time_per_goal_seconds: 7200   # 2 hours total per goal
  cost_budget_per_goal_usd: 5.0           # max cost before auto-pause
  pause_between_checkpoints_seconds: 2    # brief pause between checkpoints
```

## Goal Lifecycle

```
planning ──► active ──► completed
               │
               ├──► paused ──► active (resume)
               │
               └──► failed

Any state ──► cancelled
```

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
| `core/protocol.py` | Goal event types (6 events) |
| `cli/gateway_cmd.py` | GoalRunner gateway wiring + startup resume |
| `tests/test_core/test_goal_runner.py` | GoalRunner tests (12 tests) |
