# 60 — Action Queue

> Serialized task execution with priority preemption. Prevents concurrent
> browser/tool access between scheduled tasks, manual messages, and
> background operations.

**Status:** Superseded by [74-CONCURRENCY-MIGRATION.md](74-CONCURRENCY-MIGRATION.md) (2026-05-12). The global `ActionQueue` lock described below no longer wraps `run_session` or `_execute_scheduled_task`; serialization moved to `TaskResource.AGENT_LOOP` (capacity 1) with priority-aware ordering. The `TaskPriority` enum from this doc is retained as the priority vocabulary. Doc kept for historical context.
**Priority:** P0 — Critical concurrency fix

---

## Problem

Scheduled tasks and manual user messages share the same browser and tools
with zero coordination. When a cron job is mid-execution (e.g., reply grind
using the browser) and the user sends a message, both compete for the
browser simultaneously — corrupting JSON-RPC streams, creating race
conditions on page state, and producing unpredictable behavior.

The autonomous mind, heartbeat engine, and goal runner had pause/resume
mechanisms, but the scheduler did not. And none of them serialized actual
task execution — they only paused their *sleep loops*, not their *agent.run()
calls*.

---

## Solution

### Action Queue (`core/action_queue.py`)

A central `asyncio.Lock`-based queue that serializes all task execution.
Only one task runs at a time, with priority preemption for user messages.

**Priority Levels:**

| Priority | Value | Source |
|----------|-------|--------|
| USER | 0 (highest) | Manual chat messages via gateway |
| HEARTBEAT | 1 | Heartbeat standing orders |
| SCHEDULED | 2 | Cron-scheduled tasks |
| MIND | 3 | Autonomous mind think cycles |
| GOAL | 4 (lowest) | Goal runner background execution |

**Preemption:** When a higher-priority task arrives while a lower-priority
task holds the lock, the queue sets a `preempted` event on the current
holder. The holder can check `slot.preempted.is_set()` between steps to
yield gracefully.

### Scheduler Pause/Resume

Added `notify_user_interaction()` and `notify_task_complete()` to
`TaskScheduler`, matching the pattern already used by `AutonomousMind`
and `HeartbeatEngine`. When a user message arrives:

1. `run_session()` calls `scheduler.notify_user_interaction()`
2. Scheduler sets `_paused = True`
3. Any pending scheduled executions are skipped while paused
4. After user task completes, `scheduler.notify_task_complete()` resumes

---

## Integration Points

### `agent.run_session()` (manual user messages)
```python
async with self._action_queue.acquire(TaskPriority.USER):
    response = await self._run_with_history(...)
```

### `agent._execute_scheduled_task()` (cron tasks)
```python
async with self._action_queue.acquire(TaskPriority.SCHEDULED):
    return await self.run(goal)
```

### `autonomous_mind._think()` and `_run_autoloop_cycle()`
```python
async with self._agent._action_queue.acquire(TaskPriority.MIND):
    response = await self._agent.run(prompt, ...)
```

---

## Behavior

| Scenario | Before | After |
|----------|--------|-------|
| Scheduled task running, user sends message | Both fight for browser | Scheduler pauses, user task runs, scheduler resumes |
| Mind thinking, user sends message | Mind already paused, but agent.run() still racing | Mind's run() blocked by queue, user gets exclusive access |
| Two scheduled tasks overlap | Both run simultaneously | Second waits for first to complete |
| User sends message during heartbeat | Heartbeat paused but run() races | Heartbeat's run() blocked, user goes first |

---

## Files

| File | Change |
|------|--------|
| `core/action_queue.py` | New — `ActionQueue`, `TaskPriority`, `_Slot` |
| `core/agent.py` | Wrap `run_session()` and `_execute_scheduled_task()` with queue |
| `core/scheduler.py` | Add `notify_user_interaction()` / `notify_task_complete()` |
| `core/autonomous_mind.py` | Wrap both `agent.run()` calls with queue |
