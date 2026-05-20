# 76 — Mind starvation under sustained pressure (future work)

**Status**: Future consideration. Not scheduled. · **Surfaced**: 2026-05-20

## Observation

The `[agent_loop]` lifecycle logs added on 2026-05-20 made AGENT_LOOP
contention empirically observable. On a busy day, MIND can wait
indefinitely behind sustained USER + SCHEDULED arrivals.

Real trace from a development boot (annotated):

```
11:46:16  ACQ   src=USER       waited=0.00s
11:50:07  REL   src=USER       held=230.99s          ← chat #1 done (3:51)
11:50:16  ACQ   src=USER       waited=0.00s          ← chat #2 starts
11:50:17  WAIT  src=MIND       in_use=1 waiters=0    ← mind wakeup queued
11:55:00  SCHED dispatch       (email check)         waiters=1
11:55:00  WAIT  src=SCHEDULED  waiters=1
11:56:36  REL   src=USER       held=379.99s          ← chat #2 done (6:20)
11:56:36  ACQ   src=SCHEDULED  waited=96.55s         ← email took it; mind skipped
11:57:14  WAIT  src=USER       waiters=1             ← chat #3 typed
11:57:34  REL   src=SCHEDULED  held=58.19s
11:57:34  ACQ   src=USER       waited=20.29s         ← user jumped ahead of mind
12:00:00  SCHED dispatch       (X hourly post)       waiters=1
12:00:00  SCHED dispatch       (xStock 12h)          waiters=2
12:00:00  SCHED dispatch       (unnamed)             waiters=3
```

By 12:00:31, MIND had been waiting since 11:50:17 — **10 minutes**, four
ACQ events into other priorities, still no slot. Three more SCHEDULED
tasks queued ahead of it. Under steady chat + schedule load, MIND can
starve indefinitely.

## Why this happens

Priorities are correct:

```
USER              = 0  (highest)
SCHEDULED         = 1
MIND              = 2
HEARTBEAT         = 3
SCHEDULED_CADENCE = 4
GOAL              = 5
```

`_PrioritySemaphore` correctly transfers the slot to the highest-
priority live waiter on each release. With USER + SCHEDULED constantly
arriving, MIND (priority 2) is never the highest-priority waiter at
release time. The semaphore behaves exactly as designed; the policy
is what produces starvation.

## Why this is **not** a bug

- The gating is provably correct — `grep '\[agent_loop\]' logs/latest.log`
  shows every ACQ has a matching REL; no overlap.
- Priority ordering is correct — every release went to the highest-
  priority live waiter at that moment.
- Starvation is the natural consequence of strict priority on a busy
  system. Same trade-off every OS scheduler faces.

## Why not fix it now

- Most operator workloads have idle windows between USER chats and
  cron schedules; MIND runs fine then.
- The dream/reflex tier exists to fill idle space — pre-empting it
  during busy windows is acceptable.
- The fix has a real failure mode: aging USER chat to "background"
  effectively, or aging MIND past USER, would invert operator intent.
  Get the policy wrong and the agent talks back slowly while it does
  internal reflection.
- No operator has reported "the mind isn't running" as a complaint
  yet. The complaint that triggered this observability work was the
  opposite — "the scheduler is running while I'm using browser",
  which turned out to be a false positive driven by misleading logs.

## When to revisit

Reconsider when ANY of these is true:

- An operator reports that MIND visibly stops running for hours under
  normal use.
- A dream candidate or reflex would have caught a problem but didn't
  fire because MIND was starved.
- A mission's `last_touched_at` falls so far behind that the
  arbiter's neglect bonus is no longer enough to compete with
  cheaper SCHEDULED arrivals.
- We add a second mind-tier source (e.g. external-signal handler)
  whose neglect would matter to operators.

## Proposed fix when revisited — priority aging

Standard OS-scheduler trick. Wait time increases effective priority.

```python
# Conceptual — actual integration goes in _PrioritySemaphore.acquire's
# heappop step, not here.
def effective_priority(waiter) -> int:
    raw = waiter.priority
    waited_seconds = time.monotonic() - waiter.queued_at
    age_bonus = waited_seconds / AGE_SECONDS_PER_PRIORITY_BUMP
    return raw - int(age_bonus)
```

With `AGE_SECONDS_PER_PRIORITY_BUMP = 60` and the trace above:

- MIND queued at 11:50:17 with raw priority 2.
- At 11:56:36 (waited 6:19), effective priority is `2 - 6 = -4`.
- That beats USER's 0 and SCHEDULED's 1. MIND gets the next slot.

Adjustable knob, ~20-30 LOC, doesn't change any existing semantics
for the common case (USER chat with no contention still runs
immediately because no aging has accrued).

Key implementation considerations when we do this:

- **Cap the bonus.** Without a cap, a long-waiting MIND would
  permanently outrank fresh USER chats — wrong. Cap at e.g. `-1` so
  MIND can age into SCHEDULED territory but never USER.
- **Don't age inside `_holders`.** Aging applies only to `_waiters`.
  Holders are running; aging them is meaningless.
- **Re-sort lazily.** Don't re-heapify on every tick; compute
  effective priority at heappop time and re-push the loser if a
  later waiter has lower effective priority.
- **Telemetry.** Add the aged-priority value to the `[agent_loop]
  ACQ` log so operators can see "MIND aged from 2 to -1 over 6:19
  wait".

## Alternatives considered (do not pick these)

- **Hard reservation** — block out hours where only MIND can fire
  (e.g. 03:00–05:00 local). Replaces a scheduler problem with an
  operator-policy problem. Different installations have different
  idle windows; not portable.
- **Multi-level queues** — separate per-priority sub-queues with
  configurable proportions. Overkill for current scale; the priority
  semaphore would need a near-rewrite.
- **Bump MIND to priority 1 globally** — same as SCHEDULED. Defeats
  the entire reason cadence schedules sit *below* MIND (see
  `docs/74-CONCURRENCY-MIGRATION.md`).

## Cross-references

- `docs/74-CONCURRENCY-MIGRATION.md` — resource-typed concurrency
  design, why priorities are ordered the way they are.
- `docs/75-AUTONOMOUS-MIND-V2.md` — what MIND does and why missing
  cycles matters for arbiter behavior.
- `core/task_resources.py:_PrioritySemaphore` — implementation site
  for any future aging logic.
- `core/agent.py` — `[agent_loop]` lifecycle logging that makes
  starvation visible; revisit telemetry when aging lands.
