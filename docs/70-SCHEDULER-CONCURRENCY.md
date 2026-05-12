# 70 — Scheduler concurrency: resource-typed semaphores + real queue

**Status:** v1 implementation (2026-05-07); refined by [74-CONCURRENCY-MIGRATION.md](74-CONCURRENCY-MIGRATION.md) (2026-05-12) — agent-loop scheduled tasks now serialize on `TaskResource.AGENT_LOOP` (capacity 1) because they share singleton state (browser, executor callbacks, working memory). Direct-tool scheduled tasks still parallelize as designed. The "two agent-loop scheduled tasks run truly in parallel" framing below applies only to direct-tool tasks; agent-loop tasks serialize on AGENT_LOOP.
**Author:** EloPhanto + Claude (Opus 4.7).
**Related:** [core/scheduler.py](../core/scheduler.py), [core/task_resources.py](../core/task_resources.py).

---

## What this replaces

The scheduler used to gate concurrent task execution on a single boolean (`_is_executing`) with two consequences:

1. **`max_concurrent_tasks=1` forced pure serial execution.** A Polymarket scan via API blocked an X reply via browser even though they share zero resources.
2. **Cron firings while a task was running were DROPPED, not queued.** Four every-30-min schedules fighting for one slot lost three out of four fires per cycle. A 30-min task that ran 35 min was still blocking when the next cycle fired — both got skipped.

The rewrite (2026-05-07) replaces the boolean with a **resource-typed semaphore manager** plus a real **bounded queue with per-task dedup**.

## Design

```
┌──────────────────────────────────────────────────────────────┐
│  APScheduler cron trigger fires                              │
│         ↓                                                    │
│  _enqueue_for_execution(schedule_id)                         │
│    ├─ paused?                       → log + skip             │
│    ├─ already running?              → dedup, log + skip      │
│    ├─ already queued?               → dedup, log + skip      │
│    ├─ queue full (queue_depth_cap)? → log + drop loud        │
│    └─ otherwise                     → enqueue                │
│         ↓                                                    │
│  _worker_loop pops from queue                                │
│         ↓                                                    │
│  _run_one(schedule_id)                                       │
│    ├─ infer_resources(task_goal) → list[TaskResource]        │
│    └─ async with manager.acquire(resources):                 │
│           ├─ wait until all declared resources are free      │
│           ├─ run the task body                               │
│           └─ release on context exit                         │
└──────────────────────────────────────────────────────────────┘
```

## Resources

`core/task_resources.py` defines five resource types — only those where genuine contention exists:

| Resource | Capacity (default) | Why |
|---|---|---|
| `BROWSER` | 1 | One Chrome profile, one CDP. Two tasks driving the browser corrupt each other's cookie / tab / network state. Hard contention. |
| `DESKTOP` | 1 | One screen, one cursor. Hard contention. |
| `VAULT_WRITE` | 1 | Vault writes serialize on a single password-derived key. Reads don't contend; writes do. |
| `LLM_BURST` | 4 | Soft cap on concurrent LLM-heavy tasks — protects against provider rate limits. Configurable via `scheduler.llm_burst_capacity`. |
| `DEFAULT` | 3 | Fallback for tasks whose resources can't be inferred. Capacity = `scheduler.max_concurrent_tasks`. |

Filesystem reads, web_search via API, knowledge writes (sqlite WAL handles concurrent writes), outbound HTTP calls — none of these have entries here. They're parallel-safe.

### Acquisition semantics

Resources are acquired in **canonical order** (sorted by enum value) regardless of the order the task declared them. Two tasks declaring `[BROWSER, DESKTOP]` and `[DESKTOP, BROWSER]` both acquire BROWSER first, then DESKTOP — `asyncio.Semaphore` is FIFO so they serialize cleanly without deadlock.

The `acquire()` method is an async context manager:

```python
async with manager.acquire([TaskResource.BROWSER, TaskResource.LLM_BURST]):
    await run_task()  # blocks until both are acquired
# Released on context exit, including exception paths.
```

## Inference heuristic

`infer_resources(task_goal: str) → list[TaskResource]` does keyword pattern matching against the task goal text. **No LLM call** — pure regex.

### What's matched as `BROWSER`

- Specific tool references: `twitter_post`, `tiktok_post`, `youtube_post`, `pump.fun`, `agent.commune`
- Verb keywords: `navigate to`, `scrape`
- Action+platform combinations: `post on X` / `twitter`, `X reply` / `X engagement` / `X comments`, `tweet on twitter`
- Bare `\btwitter\b`, `\btweet\b` (specific enough to be reliable)

### What's deliberately NOT matched (lessons from production tightening)

- **Bare `\bbrowser\b`** — operator goal text often says *"Browser screenshots are NOT authoritative — rely on CLOB API"*, where the word appears in a negation context. Word-level regex can't read that. Tightened away 2026-05-07.
- **Bare `\breply\b`, `\blike\b`, `\bx\b`** — match too generically: "reply to emails", "I like this approach", "10x return". Use combined phrases instead (`X reply`, `twitter reply`).
- **Bare `\bpolymarket\b`** — Polymarket flows are API-driven via `py-clob-client`. Tagging them as browser-needing held back 3 schedules from parallelism for no reason.
- **Bare `\bclick\b`, `\bvisit\b`** — too generic; both appear in analyst speak ("click rate", "visit count").

The bias is intentional: **over-acquire is safe** (a task waits slightly longer in the queue), but **under-acquire causes browser-state corruption** (two tasks corrupting each other). When in doubt, the current heuristic prefers to declare LLM_BURST only and skip BROWSER. Override per-schedule if needed (see below).

### Always-declared resources

Every scheduled task gets `LLM_BURST` declared automatically — every task triggers the agent loop, which uses the LLM. The LLM_BURST semaphore is the *global throttle on parallel LLM work*, not per-task.

## Configuration

In `config.yaml`:

```yaml
scheduler:
  enabled: true
  max_concurrent_tasks: 3       # global parallelism cap (was 1)
  llm_burst_capacity: 4         # cap on concurrent LLM-heavy tasks
  queue_depth_cap: 50           # bounded wait queue
  task_timeout_seconds: 600
  default_max_retries: 3
```

The defaults assume a single-operator workstation with one browser profile. Bump `max_concurrent_tasks` and `llm_burst_capacity` if your workload supports more parallelism (the right number is "just below the LLM provider's rate-limit pain threshold").

## Dedup semantics

Per-schedule_id dedup is enforced at three points:

1. **At enqueue time** — if `schedule_id` is already in `_queued_ids`, skip with log.
2. **At enqueue time** — if `schedule_id` is already in `_running_tasks`, skip with log.
3. **At queue-overflow** — bounded by `queue_depth_cap`, drop with a loud warning.

This protects against the spiral case: a 30-min task that takes 35 min running on a 30-min cron. Without dedup, every cycle would queue another fire on top of the already-running one, creating an unbounded backlog. With dedup, the second fire is skipped while the first is still running; one fire runs per cycle even when the previous one ran long.

## Observability

```bash
elophanto schedule status
```

Static report (no running daemon required) — reads the SQLite scheduled-tasks table and prints:

- Concurrency config (max_concurrent_tasks, llm_burst_capacity, queue_depth_cap)
- Enabled schedules grouped by **inferred resource fingerprint** (sorted by group size)
- Oversubscription warnings — *"5 schedules need the browser (capacity 1). They will serialize."*

Live queue depth (in-memory) is logged at INFO level on every enqueue:

```
[INFO] Scheduler: enqueued <id> (queue depth N)
[DEBUG] Schedule <id> requesting resources: ['browser', 'llm_burst']
```

So `tail -f logs/latest.log | grep Scheduler` is the simplest live-state view.

## Backpressure modes

| Mode | Behavior |
|---|---|
| Healthy | Queue depth ≤ 1, browser+desktop occasional waits, llm_burst rarely saturated. |
| Browser-bound | Multiple browser-needing schedules; one runs, others wait. Look for `<elophanto schedule status>` showing `N schedules need the browser` ≥ 2. Mitigate: stagger cron fire times, or remove unneeded browser flagging via heuristic refinement. |
| LLM-bound | More than `llm_burst_capacity` schedules trying to run concurrently. Mitigate: bump capacity (modern providers handle 6-8 fine on a paid plan), or stagger cron times. |
| Queue-bound | `queue_depth_cap` reached → drops logged. This means the entire pipeline is jammed; a task is taking longer than its cadence consistently. Audit which task. |

## What this is not

- **Not a browser pool.** Browser capacity is 1 because there's one Chrome profile. Multiple browser-needing schedules will serialize through that single semaphore. If that's the bottleneck for you, see [docs/proposals/REMOTE-BROWSER.md](proposals/REMOTE-BROWSER.md) for the proposed multi-instance fix.
- **Not pre-emptive.** A running task isn't interrupted when a higher-priority schedule fires; the new fire queues and waits. There's no priority field on schedules — they're FIFO.
- **Not budget-aware.** The LLM_BURST semaphore caps concurrency, not spend. Daily/per-task budget is enforced by `core/router.py` via `CostTracker`. The two are independent.

## Tests

`tests/test_core/test_task_resources.py` (17 tests) covers:

- **Heuristic** — empty / twitter / polymarket / web_search / desktop / vault_set / canonical-order
- **Manager** — acquire/release, unknown-resource raises, browser serializes two browser tasks, disjoint resources parallelize, status reflects in_use+waiters, canonical-order prevents deadlock
- **Scheduler queue** — cron-while-running enqueues (no drops), duplicate-fire dedup, queue_status shape

`tests/test_core/test_scheduler.py` (26 tests) — pre-existing, unchanged behavior plus updated names where the private symbol moved (`_execute_schedule` → `_run_one`).

## Future work

Tracked in the original concurrency review (chat thread 2026-05-07):

- **Phase 3 — browser pool.** Multiple browser sessions in a pool, bumping BROWSER capacity > 1. Tied to [docs/proposals/REMOTE-BROWSER.md](proposals/REMOTE-BROWSER.md). Skip until usage data shows browser-queue depth as the actual bottleneck.
- **Auto-staggering.** When the operator adds a cron schedule whose minute aligns with an existing one, scheduler nudges by N minutes. Cheap, prevents collision pile-ups, doesn't add real concurrency. ~20 LOC.
- **Per-schedule resource override.** Add a `resources: list[str]` field on `scheduled_tasks` so the operator can override `infer_resources` when the heuristic gets it wrong. Most useful for "this Polymarket task is genuinely API-only, don't touch the browser" cases.
- **Dashboard widget.** Live queue depth + resource utilisation in the web dashboard. The CLI status command + log INFO lines cover the static and trace views; live UI is a nice-to-have.
