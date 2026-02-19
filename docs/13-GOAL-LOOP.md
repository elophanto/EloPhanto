# Phase 13 — Autonomous Goal Loop

## Overview

The Goal Loop allows EloPhanto to pursue multi-phase goals that span sessions, require progress tracking, and may need mid-run replanning. A user saying "get a job at X" triggers: research the company, tailor resume, find openings, apply, follow up — spread across hours/days with persistent state.

## Architecture

```
User: "get a job at X"
         │
         ▼
   ┌─────────────┐     LLM call (task_type="simple")
   │ goal_create  │────► Decompose into checkpoints
   │   tool       │◄──── [{order:1, title:"Research X", ...}, ...]
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

Five new `EventType` values for gateway event propagation:

- `GOAL_STARTED`, `GOAL_CHECKPOINT_COMPLETE`, `GOAL_COMPLETED`, `GOAL_FAILED`, `GOAL_PAUSED`

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
  max_time_per_checkpoint_seconds: 600
  context_summary_max_tokens: 1500
  auto_continue: true
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
| `tools/goals/create_tool.py` | goal_create tool |
| `tools/goals/status_tool.py` | goal_status tool |
| `tools/goals/manage_tool.py` | goal_manage tool |
| `skills/goals/SKILL.md` | Goal decomposition skill |
| `core/planner.py` | Extended with `<goals>` and `<active_goal>` XML |
| `core/agent.py` | GoalManager initialization and context injection |
| `core/registry.py` | Goal tool registration |
| `core/database.py` | goals + goal_checkpoints DDL |
| `core/config.py` | GoalsConfig dataclass |
| `core/protocol.py` | Goal event types |
