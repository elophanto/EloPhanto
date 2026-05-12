# 74 — Concurrency migration: finish what 60→70 started

**Status:** Shipped (2026-05-12). All three phases implemented; 1332 core tests pass (+7 new).
**Author:** EloPhanto + Claude (Opus 4.7).
**Related:** [60-ACTION-QUEUE.md](60-ACTION-QUEUE.md), [70-SCHEDULER-CONCURRENCY.md](70-SCHEDULER-CONCURRENCY.md), [core/action_queue.py](../core/action_queue.py), [core/task_resources.py](../core/task_resources.py).

---

## TL;DR

Two concurrency primitives ship today: the older `ActionQueue` (single `asyncio.Lock` with priority preemption) and the newer `TaskResourceManager` (typed semaphores per real resource). They were introduced at different times to solve different incidents. They are now **both** wired into the scheduled-task path, which means every scheduled task waits for the resource semaphore *and then* the global lock — the lock dominates and defeats the resource-typed parallelism doc 70 promises.

Operator-visible symptoms:

1. **Operator can't chat while the agent is mid-turn.** A held lock by any background task blocks user input until the holder returns.
2. **Two scheduled tasks don't actually run in parallel.** Doc 70 says they do; they don't, because `_execute_scheduled_task` reacquires the global lock under the resource gate.
3. **The autonomous mind and heartbeat engine block each other and the user** for the same reason.

The fix is **not** "add an actor model" — that pattern is already half-shipped as `TaskResourceManager`. The fix is to **finish the migration**: drop the redundant global lock now that the resource-typed gate exists, route operator chat through the same resource gate, and add a between-step interrupt checkpoint so mid-turn user messages can be folded in. Three independent changes, each ~1 day.

---

## What shipped

All three phases landed together in the same change set (commit on `main`, 2026-05-12). Concretely:

- **Phase A** — [core/agent.py](../core/agent.py) `_execute_scheduled_task` is now a thin pass-through to `self.run`; the `ActionQueue` wrap is gone. Two scheduled tasks with disjoint resources execute concurrently, gated only by `TaskResourceManager`.
- **Phase B** — [core/task_resources.py](../core/task_resources.py) ships `_PrioritySemaphore` (heap-keyed by `(priority, seq)`, FIFO within priority, cancellation-tombstone-aware). `TaskResourceManager.acquire(resources, priority=...)` is now priority-aware. [core/agent.py](../core/agent.py) constructs an agent-wide resource manager in `__init__` and `run_session` routes through `self._resources.acquire([LLM_BURST], priority=USER)`. `notify_user_interaction` and `notify_task_complete` calls have been removed from `run_session` — the agent keeps living when watched. [core/autonomous_mind.py](../core/autonomous_mind.py) and [core/heartbeat.py](../core/heartbeat.py) also route through `self._resources` with their respective priorities (MIND, HEARTBEAT).
- **Phase C** — [core/session.py](../core/session.py) ships `Session.add_pending_message`, `drain_pending_messages`, `has_pending_messages`. The [core/agent.py](../core/agent.py) `_run_with_history` loop drains pending messages at the top of each iteration and folds them as `[user added mid-turn: ...]` synthetic turns. [core/gateway.py](../core/gateway.py) `_handle_chat` detects in-flight sessions via `_inflight_sessions` and routes second-message arrivals to `session.add_pending_message` instead of starting a second concurrent run.

Tests added: 7 new, covering parallel scheduled-task overlap (Phase A), priority-aware acquire / no-preempt / FIFO-within-priority / cancellation tombstones (Phase B), and session inbox + end-to-end mid-turn fold (Phase C).

The `/pause` operator command remains intact (`gateway.py` line ~2092) — explicit operator-asks-mind-to-pause is unchanged. Only the implicit "any operator message freezes everything" auto-pause was removed.

---

## Design principles (grounded in agent purpose)

Concurrency policy is an identity decision, not just an engineering one. EloPhanto is **one continuous autonomous entity** — one identity, one wallet building on-chain reputation, one calibration loop accumulating evidence, one mind that thinks when no one is watching. It is not a chatbot summoned by operator presence. Three principles fall out of this and decide the contested questions below:

1. **The agent finishes its current sentence.** Operator priority is real but lives at *decision boundaries* (next plan step), not mid-thought. Preempting a running LLM call wastes tokens already paid for and discards a chain-of-thought the agent will have to rebuild. Worst-case operator wait is one LLM call (~2–30 s) — well below the threshold where rudeness costs more than coherence.
2. **Tool calls are atomic commitments.** A tool call is the execution of a plan the agent already decided. Aborting mid-execution leaves half-sent transactions, partial files, dangling browser state. Operator input lands at the next *plan* boundary, not mid-tool. Long-running tools that genuinely need interruption are a `task_spawn` problem, not a tool-cancellation problem.
3. **The agent keeps living when watched.** A pause that freezes scheduled work whenever the operator chats encodes "the agent only acts in private," which is the inverse of autonomy. Resource-typed gates already prevent the contention that pause-on-chat was protecting against. Budget contention, if it shows up, is a budget problem to solve with `CostTracker`, not a concurrency pause.

These principles drive the phase recommendations below.

---

## What already exists (verified)

### `ActionQueue` — older, coarse, global
[core/action_queue.py](../core/action_queue.py) (145 LOC).

- Single `asyncio.Lock`. One task at a time across all priorities.
- Priority preemption: arriving USER/HEARTBEAT/SCHEDULED/MIND/GOAL ranks who acquires next, and sets a `preempted` event on the current holder.
- Holders are expected to check `slot.preempted.is_set()` at safe checkpoints and yield. In practice nobody checks it during an agent turn — the loop runs plan→tool→reflect atomically.

**Why it was introduced** ([60-ACTION-QUEUE.md:12-18](60-ACTION-QUEUE.md)): a cron job and a user message both grabbing the browser corrupted JSON-RPC streams. The single lock was a coarse but real fix — guarantee one Chrome user at a time.

### `TaskResourceManager` — newer, fine-grained, per-resource
[core/task_resources.py](../core/task_resources.py) (310 LOC).

- Typed semaphores: `BROWSER=1`, `DESKTOP=1`, `VAULT_WRITE=1`, `LLM_BURST=4`, `DEFAULT=3`.
- `infer_resources(task_goal)` regex-matches the goal text to a resource list. Acquired in canonical order to prevent deadlock.
- This is exactly the actor-ownership pattern: BROWSER is "owned" by the BROWSER semaphore (capacity 1); calls to the browser serialize *only against other browser calls*; everything else runs concurrently.

**Why it was introduced** ([70-SCHEDULER-CONCURRENCY.md:11-15](70-SCHEDULER-CONCURRENCY.md)): a Polymarket API scan was blocking an X reply via browser even though they share zero resources. Coarse serialization had become the bottleneck.

---

## Current code reality (verified)

The scheduled-task firing path is double-gated:

```
APScheduler cron fire
  ↓
scheduler._enqueue_for_execution(schedule_id)
  ↓
scheduler._run_one(schedule_id)                      [core/scheduler.py:836]
  ├─ infer_resources(task_goal) → e.g. [LLM_BURST]
  └─ async with self._resources.acquire(resources):   [scheduler.py:858]  ← gate A
        await self._execute_schedule_body(...)
          ↓
        self._task_executor(task_goal)               [scheduler.py:879]
          = agent._execute_scheduled_task           [agent.py:3451]
            ↓
          async with self._action_queue.acquire(   [agent.py:3463]  ← gate B
              TaskPriority.SCHEDULED, timeout=600):
              await self.run(goal, is_user_input=False)
```

**Gate A** (TaskResourceManager) is correct and load-bearing. Two scheduled tasks with disjoint resource declarations pass it concurrently.

**Gate B** (ActionQueue) re-serializes everything. Two tasks past gate A now wait on the single global lock. Gate A's parallelism promise is silently defeated.

User-chat path is gate-B-only:

```
gateway / channel adapter → session.run_session()
  ↓
async with self._action_queue.acquire(TaskPriority.USER):    [agent.py:2146]
    response = await self._run_with_history(...)
```

User chat waits for whatever currently holds gate B. If a scheduled task is mid-turn, the operator's message blocks for the full plan→execute→reflect cycle before being read.

Direct-tool scheduled tasks ([scheduler.py:649](../core/scheduler.py)) bypass both gates via `asyncio.create_task` — they're correctly concurrent. This is the only path that delivers what doc 70 promises.

---

## Why the global lock is no longer load-bearing

The original incident gate B was added to prevent ([60-ACTION-QUEUE.md:12-18](60-ACTION-QUEUE.md)) was *browser state corruption from two simultaneous Chrome users*. That exact failure mode is now prevented by `TaskResource.BROWSER` (capacity 1) — two tasks declaring BROWSER serialize through the semaphore regardless of whether gate B exists.

Restating: gate B currently provides

- Global serialization (which gate A's typed semaphores already provide *where it actually matters*),
- Priority reordering (useful — USER should jump the queue),
- A preempt signal (theoretically useful, in practice nobody checks it during a turn).

The serialization is redundant. The priority and preempt mechanisms are worth keeping but don't require a global lock to implement — both can be expressed against the resource gate.

---

## Migration plan

Three phases. Each is independent, each ships in a day, each individually moves the operator-visible needle.

### Phase A — Drop gate B from the scheduled-task path

Remove the `action_queue.acquire(SCHEDULED, ...)` wrap from `agent._execute_scheduled_task`. The scheduler's `_run_one` already holds the right resource semaphores; the global lock is the redundant layer.

**Concrete change**: [core/agent.py:3451-3477](../core/agent.py) — `_execute_scheduled_task` becomes a thin pass-through to `self.run(goal, is_user_input=False)`. No lock acquire, no timeout.

**Effect**: two scheduled tasks with disjoint resource fingerprints (the docs' example: Polymarket API scan + X reply via browser) actually run concurrently, as doc 70 claims they already do.

**Risk**: any code path that relied on "exactly one agent turn at a time globally" loses that guarantee for scheduled tasks. Audit:

- Conversation history (`_conversation_history`): per-session, scheduled tasks already shouldn't touch it.
- Cost tracking ([core/router.py](../core/router.py) CostTracker): already thread-safe by design.
- Provider rate limits: `LLM_BURST=4` is the explicit throttle.
- Browser, desktop, vault writes: still serialized at the resource gate.

Verification: extend [tests/test_core/test_task_resources.py](../tests/test_core/test_task_resources.py) with a new test — *two scheduled tasks with disjoint resources both reach `agent.run()` concurrently within ε* — that fails today and passes after the change.

### Phase B — Route operator chat through `TaskResourceManager`

Change `agent.run_session` from `async with self._action_queue.acquire(USER)` to `async with self._resources.acquire([LLM_BURST])`. Keep the priority semantics by making the resource manager priority-aware: a USER caller arriving at LLM_BURST gets a position-1 slot ahead of MIND/SCHEDULED waiters.

**Concrete change**: extend `TaskResourceManager.acquire(resources, priority=TaskPriority.USER)` to use a `PriorityQueue` of waiters per semaphore instead of FIFO. ~50 LOC in [core/task_resources.py](../core/task_resources.py). The semaphore's release routine wakes the highest-priority waiter, not the oldest.

**Priority semantics — wait-queue only, not running-call preemption.** When a USER caller arrives and all LLM_BURST slots are held by MIND/SCHEDULED tasks, USER jumps to the **front of the wait queue** but does *not* abort an in-flight LLM call. Worst-case operator wait is one LLM call (~2–30 s). Rationale: principle 1 above — the agent finishes its current sentence. Aborting an in-flight call wastes paid-for tokens and discards a chain-of-thought the agent will have to rebuild on retry. If operators need a harder interrupt for rare cases, that's an explicit verb (`/cancel`), not the default behavior of every chat message.

**Remove `scheduler.notify_user_interaction()` pause as part of this phase.** Once chat runs concurrently with scheduled tasks via the resource gate, the explicit pause becomes anti-agent (principle 3): it freezes the mind, the calibration loop, and the wallet's activity the moment the operator opens a chat session. The contention it was protecting against (two tasks fighting for the browser, the wallet, or LLM burst) is now prevented at the resource layer where it belongs. Budget contention — the one legitimate concern hiding inside the pause — is a `CostTracker` problem and gets its own proposal; using a concurrency pause to solve a budget problem is solving the wrong problem.

**Effect**: operator chat (declares LLM_BURST) runs concurrently with any task that doesn't need LLM at the same instant. When LLM contention exists, operator chat takes the next available LLM_BURST slot (capacity 4 — there usually is one). Chat that needs browser still serializes against browser-bound work, *which is the correct behavior* — two users of one Chrome must serialize. The mind keeps thinking and the calibration loop keeps logging while the operator chats.

**Risk**: deadlock if priority inversion meets resource ordering. Mitigated because canonical-order acquisition is preserved and priority only changes wait-queue ordering, not lock ordering.

### Phase C — Cooperative interrupt checkpoint in the run loop

Add an `asyncio.Event`-based inbox-pending signal to each session. The run loop checks it **only between LLM calls** (after each plan, before each reflect). If pending: fetch the new operator message, append it to the conversation as `[user added mid-turn: <message>]`, and feed into the next plan step.

**Concrete change**: [core/agent.py](../core/agent.py) — the plan→execute→reflect loop gains 3-line checks at the plan-boundary positions only. The channel adapter's existing inbox push sets the event. No new threading, no new task primitive.

**Checkpoint placement — between LLM calls only, not between tool calls.** Rationale: principle 2 above — tool calls are atomic commitments to a plan the agent already decided. Aborting tools mid-plan leaves half-finished state (half-sent transactions, partial files, dangling browser sessions). The decision unit is the plan; tools are the execution. Operator input lands at the next *decision* boundary.

The case for per-tool-call checkpoints is "long-running tools" — but the right answer there is to make those tools `task_spawn`-able so they don't block the loop in the first place, not to make every tool interruptible. Mixing interrupt-mid-tool with atomic-commitment semantics creates the worst of both: tools that *sometimes* run to completion and *sometimes* get cancelled, with state recovery code at every call site.

**Forward door (don't build yet, just leave room)**: a future tool can opt in via `cancellable=True` and the loop checks between *its* sub-steps. Browser scrape with many independent sub-steps could declare itself cancellable; transaction signing never could. Default stays atomic. This scales with the codebase instead of paying complexity tax everywhere.

**Effect**: this is the Claude Code "submit during turn" experience. Operator types correction; agent sees it on the next planner call (typically <30 s later); pivots without operator having to wait the full turn out.

**Out of scope**: mid-LLM-stream interruption (cancel the current generation). Hard to get right, wastes paid-for tokens, conflicts with principle 1 — the agent finishes its current sentence.

---

## What we keep, what we drop

| Component | Keep? | Why |
|---|---|---|
| `TaskPriority` enum | Keep | Drives priority-aware waiter ordering in `TaskResourceManager` (phase B). |
| `ActionQueue` global lock | Drop after phase A+B | Redundant once typed semaphores cover all paths. |
| `ActionQueue.preempted` event | Drop | Was never checked inside a turn; phase C's inbox event replaces it. |
| `scheduler.notify_user_interaction()` pause | Drop in phase B | Anti-agent (principle 3) — freezes the mind, calibration, and wallet activity whenever the operator opens a chat. The contention it protected against is now handled at the resource layer. Budget contention is a `CostTracker` problem, separate proposal. |
| `TaskResourceManager` | Keep + extend | This is the canonical concurrency primitive going forward. |

[60-ACTION-QUEUE.md](60-ACTION-QUEUE.md) should be marked **Superseded by 74** when phase A ships. [70-SCHEDULER-CONCURRENCY.md](70-SCHEDULER-CONCURRENCY.md) is correct except for the "truly in parallel" claim about agent-loop scheduled tasks — it becomes correct after phase A.

---

## Sequencing

Recommended order — each phase shippable independently:

1. **Phase A first** (one PR, ~50 LOC). Lowest risk, biggest unlock for the scheduled-task pain point. Concurrent crons start working.
2. **Phase C second** (one PR, ~80 LOC). Operator-facing UX win. Doesn't depend on B; the existing global lock continues to serialize chat against background work until phase B, but the interrupt checkpoint already gives the "submit during turn" feel for any case where the user's own turn is the holder (e.g. correcting a planned tool call before it executes).
3. **Phase B last** (one PR, ~150 LOC). The biggest behavioral change — chat truly parallel to background work. Needs the priority-aware semaphore extension, hence the largest test surface.

Total: ~280 LOC, three PRs, ~3 days of focused work.

---

## What this does NOT solve

- **Background-task primitive (`task_spawn`)**: a user-facing tool to fork a long-running task that the operator can chat *about* in parallel. Belongs in a separate proposal once phases A–C land; phase B's priority-aware semaphore is the substrate it would build on.
- **Browser pool / remote browser**: multiple Chrome instances bumping `BROWSER` capacity > 1. Tracked in [docs/proposals/REMOTE-BROWSER.md](proposals/) (not addressed here).
- **Budget-aware concurrency**: cap concurrent LLM spend at the dollar level rather than the task count. `LLM_BURST=4` is a coarse approximation; tighter coupling to `CostTracker` is a separate concern.

---

## Behavior changes operators will notice

This migration is mostly invisible — but three behaviors change in ways an operator should know going in:

1. **The agent will keep working while you chat.** Today, opening a chat session pauses scheduled tasks. After phase B, the mind keeps thinking, scheduled crons keep firing, the calibration loop keeps logging shadow predictions. Resource contention is handled at the resource layer; you only feel a wait when the chat and a background task literally want the same resource at the same instant.
2. **Mid-turn corrections land at the next plan step, not instantly.** After phase C, you can type a correction while the agent is mid-turn; the agent sees it on the next planner call (~2–30 s). It does not abort an in-flight LLM call or a running tool. If you need a hard stop, that's an explicit `/cancel` verb (separate proposal), not the default behavior.
3. **Two scheduled tasks with disjoint resources actually run in parallel.** Today they serialize through the global lock. After phase A, a Polymarket API scan and an X reply via browser run concurrently, as [70-SCHEDULER-CONCURRENCY.md](70-SCHEDULER-CONCURRENCY.md) already claimed they did.

None of these change the agent's identity or what it works on — they restore the autonomy and responsiveness that the current implementation accidentally suppresses.
