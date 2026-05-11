"""Task scheduler — APScheduler wrapper with database persistence.

Manages scheduled tasks using APScheduler's AsyncIOScheduler.
Schedules are persisted to SQLite and restored on restart.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from core.database import Database
from core.task_resources import TaskResource, TaskResourceManager, infer_resources

logger = logging.getLogger(__name__)


@dataclass
class ScheduleEntry:
    """A single scheduled task definition.

    Two execution paths:
    - **Agent-loop path** (default): ``task_goal`` is a natural-language
      goal; the scheduler hands it to the agent's ``run()`` for a full
      plan-execute-reflect cycle with LLM calls. Right for anything
      that needs judgment.
    - **Direct-tool path** (when ``direct_tool`` is set): the scheduler
      invokes that registry tool directly with ``direct_params`` as
      input. Bypasses the LLM and the action queue entirely. Right for
      mechanical cron jobs (polymarket_resolve_pending, solana_balance,
      etc.) where there's no decision to make.
    """

    id: str
    name: str
    description: str
    cron_expression: str
    task_goal: str
    enabled: bool = True
    last_run_at: str | None = None
    next_run_at: str | None = None
    last_status: str = "never_run"
    max_retries: int = 3
    created_at: str = ""
    updated_at: str = ""
    direct_tool: str | None = None
    direct_params: str | None = None  # JSON string


@dataclass
class ScheduleRunResult:
    """Result of a single schedule execution."""

    schedule_id: str
    status: str
    result: str
    error: str | None = None
    steps_taken: int = 0


class TaskScheduler:
    """Manages scheduled task execution using APScheduler.

    Concurrency model (2026-05-07 rewrite):
      * Cron firings are NEVER dropped — they enqueue.
      * Per-task dedup: if the same schedule_id is already running OR
        already queued, the new fire is skipped + logged. This is what
        prevents a 30-min task that takes 35 min from spiraling into
        a queue full of duplicate fires.
      * A single worker loop pops from the queue and dispatches via
        :class:`TaskResourceManager`. The manager owns the resource
        contention (browser/desktop/vault are 1, LLM-burst is N,
        default-bucket is the global parallelism cap).
      * Tasks that share no resources run truly in parallel. The
        Polymarket-via-API scan + the X reply via browser only
        serialize on the BROWSER semaphore — and only if both
        actually need the browser.

    See `core/task_resources.py` for the resource manager and
    `infer_resources()` heuristic that maps task goal text →
    resource set.
    """

    def __init__(
        self,
        db: Database,
        task_executor: Callable[[str], Coroutine[Any, Any, Any]],
        result_notifier: (
            Callable[[str, str, str], Coroutine[Any, Any, None]] | None
        ) = None,
        *,
        resource_manager: TaskResourceManager | None = None,
        queue_depth_cap: int = 50,
        registry: Any = None,
    ) -> None:
        self._db = db
        self._task_executor = task_executor
        self._result_notifier = result_notifier
        self._scheduler = AsyncIOScheduler()
        self._active_jobs: dict[str, str] = {}
        self._running_tasks: dict[str, asyncio.Task[Any]] = {}
        self._paused: bool = False
        # Resource-typed concurrency. Default capacities mirror what the
        # operator gets from config (browser/desktop/vault=1, llm_burst=4,
        # global=3) so tests and standalone use without config Just Work.
        self._resources = resource_manager or TaskResourceManager.from_defaults()
        # Queue: (schedule_id,) tuples. We keep the dedup set in sync.
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=queue_depth_cap)
        self._queued_ids: set[str] = set()
        self._queue_lock = asyncio.Lock()
        self._worker_task: asyncio.Task[Any] | None = None
        # Registry handle for the direct-tool fast path. Optional —
        # falls back to "agent-loop only" when not injected (back-compat
        # with tests + any caller that constructs scheduler without
        # registry). Agent injects it at startup.
        self._registry = registry
        # Direct-tool runs aren't queued (they bypass the action queue
        # entirely) but we still track them to support cancel-on-delete.
        self._direct_running: dict[str, asyncio.Task[Any]] = {}

    @property
    def is_running(self) -> bool:
        """True if the scheduler has started."""
        return self._scheduler.running

    @property
    def is_paused(self) -> bool:
        """True if paused due to user interaction."""
        return self._paused

    @property
    def resources(self) -> TaskResourceManager:
        """Read-only handle to the resource manager (for doctor/UI)."""
        return self._resources

    def queue_status(self) -> dict[str, Any]:
        """Snapshot for `elophanto doctor`. Returns queue depth, set
        of queued ids (small — bounded by queue_depth_cap), running
        count, and per-resource state."""
        return {
            "queue_depth": self._queue.qsize(),
            "queued_ids": sorted(self._queued_ids),
            "running": len(self._running_tasks),
            "paused": self._paused,
            "resources": self._resources.status_dict(),
        }

    def notify_user_interaction(self) -> None:
        """Pause scheduled execution — user task takes priority."""
        if self._resources.is_busy() and not self._paused:
            self._paused = True
            logger.info("User interaction — pausing scheduler")

    def notify_task_complete(self) -> None:
        """Resume scheduled execution after user task completes."""
        if self._paused:
            self._paused = False
            logger.info("User task complete — resuming scheduler")

    async def start(self) -> None:
        """Start the scheduler and restore persisted schedules."""
        schedules = await self._load_from_db()
        for schedule in schedules:
            if schedule.enabled:
                self._add_job(schedule)
        # Worker loop pops from the queue and dispatches via the
        # resource manager. Started before APScheduler so a fast first
        # cron fire can never beat it to the queue.
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker_loop())
        self._scheduler.start()
        logger.info(f"Scheduler started with {len(schedules)} schedule(s)")

    async def stop(self) -> None:
        """Gracefully stop the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        if self._worker_task is not None and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except (asyncio.CancelledError, Exception):
                pass
            self._worker_task = None

    async def create_schedule(
        self,
        name: str,
        task_goal: str,
        cron_expression: str,
        description: str = "",
        max_retries: int = 3,
        direct_tool: str | None = None,
        direct_params: dict[str, Any] | str | None = None,
    ) -> ScheduleEntry:
        """Create a new scheduled task and persist it.

        Pass ``direct_tool`` to bypass the agent loop on fire: the
        scheduler will invoke that registry tool directly with
        ``direct_params`` as input. ``direct_params`` accepts either a
        dict (preferred) or a pre-serialised JSON string. The tool
        must exist in the registry and be SAFE-permission — destructive
        cron jobs go through the agent loop where the planner can
        reason about them.
        """
        # Validate trigger expression (cron OR interval like "30s"/"5m")
        self._validate_trigger(cron_expression)

        # Validate direct-tool target if provided
        params_json: str | None = None
        if direct_tool is not None:
            params_json = self._validate_direct_tool(direct_tool, direct_params)
            # task_goal becomes a readable trace of what fires, used in
            # logs and the agent-loop notifier. Doesn't drive execution.
            if not task_goal:
                task_goal = f"[direct-tool] {direct_tool}({params_json or '{}'})"

        schedule_id = str(uuid.uuid4())[:8]
        now = datetime.now(UTC).isoformat()

        entry = ScheduleEntry(
            id=schedule_id,
            name=name,
            description=description,
            cron_expression=cron_expression,
            task_goal=task_goal,
            enabled=True,
            max_retries=max_retries,
            created_at=now,
            updated_at=now,
            direct_tool=direct_tool,
            direct_params=params_json,
        )

        await self._db.execute_insert(
            """INSERT INTO scheduled_tasks
               (id, name, description, cron_expression, task_goal, enabled,
                max_retries, created_at, updated_at, direct_tool, direct_params)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                entry.name,
                entry.description,
                entry.cron_expression,
                entry.task_goal,
                entry.max_retries,
                entry.created_at,
                entry.updated_at,
                entry.direct_tool,
                entry.direct_params,
            ),
        )

        self._add_job(entry)
        return entry

    @staticmethod
    def _validate_trigger(expr: str) -> None:
        """Validate either a 5-field cron OR an interval like '30s'/'5m'/'2h'."""
        expr = expr.strip()
        # Interval syntax: '30s', '5m', '2h', '1d' — sub-minute cadence
        # support. Used for direct-tool fast-path crons that need to
        # fire more often than 1/min.
        m = re.fullmatch(r"(\d+)\s*([smhd])", expr)
        if m:
            n = int(m.group(1))
            if n <= 0:
                raise ValueError(f"Interval must be positive, got '{expr}'")
            return
        # Standard 5-field cron
        try:
            CronTrigger.from_crontab(expr)
        except ValueError as e:
            raise ValueError(f"Invalid cron expression: {e}") from e

    def _validate_direct_tool(
        self, tool_name: str, params: dict[str, Any] | str | None
    ) -> str:
        """Validate the tool exists, is SAFE, and params are JSON-serialisable.

        Returns the params as a JSON string for DB storage.
        """
        if self._registry is None:
            raise ValueError(
                "direct_tool requires the scheduler to be constructed with "
                "a registry handle. Construct TaskScheduler(..., registry=registry)."
            )
        tool = self._registry.get(tool_name)
        if tool is None:
            raise ValueError(f"Unknown tool: {tool_name!r}")
        # Lazy-import to avoid a hard dep cycle
        from tools.base import PermissionLevel

        if tool.permission_level != PermissionLevel.SAFE:
            raise ValueError(
                f"direct_tool refuses non-SAFE tool {tool_name!r} "
                f"(permission={tool.permission_level.value}). "
                "Destructive cron jobs must go through the agent loop so "
                "the planner can reason about them. Use task_goal instead."
            )
        # Normalise params → JSON string
        if params is None:
            return "{}"
        if isinstance(params, str):
            # Validate parseable JSON
            try:
                import json as _json

                _json.loads(params)
                return params
            except _json.JSONDecodeError as e:
                raise ValueError(f"direct_params is not valid JSON: {e}") from e
        if isinstance(params, dict):
            import json as _json

            return _json.dumps(params)
        raise ValueError(
            f"direct_params must be a dict or JSON string, got {type(params).__name__}"
        )

    async def schedule_once(
        self,
        name: str,
        task_goal: str,
        run_at: datetime,
        description: str = "",
    ) -> ScheduleEntry:
        """Schedule a one-time task at a specific datetime."""
        schedule_id = str(uuid.uuid4())[:8]
        now = datetime.now(UTC).isoformat()

        entry = ScheduleEntry(
            id=schedule_id,
            name=name,
            description=description,
            cron_expression=f"once@{run_at.isoformat()}",
            task_goal=task_goal,
            enabled=True,
            max_retries=1,
            created_at=now,
            updated_at=now,
        )

        await self._db.execute_insert(
            """INSERT INTO scheduled_tasks
               (id, name, description, cron_expression, task_goal, enabled,
                max_retries, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
            (
                entry.id,
                entry.name,
                entry.description,
                entry.cron_expression,
                entry.task_goal,
                entry.max_retries,
                entry.created_at,
                entry.updated_at,
            ),
        )

        trigger = DateTrigger(run_date=run_at)
        job_id = f"schedule_{schedule_id}"
        self._scheduler.add_job(
            self._execute_once,
            trigger=trigger,
            args=[schedule_id],
            id=job_id,
            replace_existing=True,
        )
        self._active_jobs[schedule_id] = job_id
        return entry

    async def _execute_once(self, schedule_id: str) -> None:
        """Execute a one-time task and then clean it up.

        Goes through ``_run_one`` (which acquires resources) so a one-
        shot task is subject to the same concurrency rules as recurring
        ones — no special path that bypasses the browser semaphore.
        """
        await self._run_one(schedule_id)
        try:
            await self.delete_schedule(schedule_id)
        except Exception:
            pass

    async def delete_schedule(self, schedule_id: str) -> bool:
        """Delete a scheduled task. Cancels in-flight execution if running."""
        # Cancel in-flight agent-loop task if running
        running = self._running_tasks.pop(schedule_id, None)
        if running and not running.done():
            running.cancel()
            try:
                await running
            except (asyncio.CancelledError, Exception):
                pass
            logger.info("Cancelled running task for schedule %s", schedule_id)
        # Cancel in-flight direct-tool task if running
        direct = self._direct_running.pop(schedule_id, None)
        if direct and not direct.done():
            direct.cancel()
            try:
                await direct
            except (asyncio.CancelledError, Exception):
                pass
            logger.info(
                "Cancelled in-flight direct-tool task for schedule %s", schedule_id
            )

        job_id = self._active_jobs.pop(schedule_id, None)
        if job_id:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass

        # Delete child rows first to satisfy foreign key constraint
        await self._db.execute_insert(
            "DELETE FROM schedule_runs WHERE schedule_id = ?", (schedule_id,)
        )
        await self._db.execute_insert(
            "DELETE FROM scheduled_tasks WHERE id = ?", (schedule_id,)
        )
        return True

    async def update_schedule(
        self,
        schedule_id: str,
        name: str | None = None,
        task_goal: str | None = None,
        cron_expression: str | None = None,
        description: str | None = None,
        max_retries: int | None = None,
    ) -> ScheduleEntry | None:
        """Update fields on an existing schedule. Preserves id/history.

        Re-installs the APScheduler job when cron or enabled state changes.
        Cancels any in-flight run only if the cron expression itself changes
        (the agent fires this from the daily review and an in-flight task is
        likely the morning's not-yet-finished work — leave it alone otherwise).
        """
        existing = await self.get_schedule(schedule_id)
        if not existing:
            return None

        if cron_expression is not None:
            try:
                CronTrigger.from_crontab(cron_expression)
            except ValueError as e:
                raise ValueError(f"Invalid cron expression: {e}") from e

        fields: list[str] = []
        values: list[Any] = []
        if name is not None:
            fields.append("name = ?")
            values.append(name)
        if task_goal is not None:
            fields.append("task_goal = ?")
            values.append(task_goal)
        if cron_expression is not None:
            fields.append("cron_expression = ?")
            values.append(cron_expression)
        if description is not None:
            fields.append("description = ?")
            values.append(description)
        if max_retries is not None:
            fields.append("max_retries = ?")
            values.append(max_retries)

        if not fields:
            return existing

        now = datetime.now(UTC).isoformat()
        fields.append("updated_at = ?")
        values.append(now)
        values.append(schedule_id)

        await self._db.execute_insert(
            f"UPDATE scheduled_tasks SET {', '.join(fields)} WHERE id = ?",
            tuple(values),
        )

        if cron_expression is not None:
            old_job_id = self._active_jobs.pop(schedule_id, None)
            if old_job_id:
                try:
                    self._scheduler.remove_job(old_job_id)
                except Exception:
                    pass

        updated = await self.get_schedule(schedule_id)
        if updated and updated.enabled and cron_expression is not None:
            self._add_job(updated)
        return updated

    async def enable_schedule(self, schedule_id: str) -> None:
        """Enable a schedule."""
        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            "UPDATE scheduled_tasks SET enabled = 1, updated_at = ? WHERE id = ?",
            (now, schedule_id),
        )
        schedule = await self.get_schedule(schedule_id)
        if schedule:
            self._add_job(schedule)

    async def disable_schedule(self, schedule_id: str) -> None:
        """Disable a schedule. Cancels in-flight execution if running."""
        # Cancel in-flight task if running
        running = self._running_tasks.pop(schedule_id, None)
        if running and not running.done():
            running.cancel()
            try:
                await running
            except (asyncio.CancelledError, Exception):
                pass
            logger.info("Cancelled running task for schedule %s", schedule_id)

        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            "UPDATE scheduled_tasks SET enabled = 0, updated_at = ? WHERE id = ?",
            (now, schedule_id),
        )
        job_id = self._active_jobs.pop(schedule_id, None)
        if job_id:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass

    async def stop_running(self, schedule_id: str) -> bool:
        """Cancel an in-flight scheduled task without disabling/deleting it.

        Returns True if a task was cancelled, False if nothing was running.
        """
        running = self._running_tasks.pop(schedule_id, None)
        if running and not running.done():
            running.cancel()
            try:
                await running
            except (asyncio.CancelledError, Exception):
                pass
            logger.info("Stopped running task for schedule %s", schedule_id)
            return True
        return False

    async def stop_all_running(self) -> int:
        """Cancel ALL in-flight scheduled tasks. Returns count cancelled."""
        cancelled = 0
        for task in list(self._running_tasks.values()):
            if not task.done():
                task.cancel()
                cancelled += 1
        # Wait for cancellations to settle
        for task in list(self._running_tasks.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._running_tasks.clear()
        if cancelled:
            logger.info("Stopped %d running scheduled tasks", cancelled)
        return cancelled

    async def list_schedules(self) -> list[ScheduleEntry]:
        """List all schedules from the database."""
        return await self._load_from_db()

    async def get_schedule(self, schedule_id: str) -> ScheduleEntry | None:
        """Get a single schedule by ID."""
        rows = await self._db.execute(
            "SELECT * FROM scheduled_tasks WHERE id = ?", (schedule_id,)
        )
        if not rows:
            return None
        return self._row_to_entry(rows[0])

    async def get_run_history(
        self, schedule_id: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get execution history for a schedule."""
        rows = await self._db.execute(
            """SELECT * FROM schedule_runs
               WHERE schedule_id = ?
               ORDER BY started_at DESC LIMIT ?""",
            (schedule_id, limit),
        )
        return [dict(row) for row in rows]

    def _add_job(self, schedule: ScheduleEntry) -> None:
        """Add an APScheduler job for a schedule entry.

        Supports two trigger syntaxes:
        - 5-field cron string (e.g. ``0 9 * * *``) → CronTrigger
        - Short interval (e.g. ``30s``, ``5m``, ``2h``, ``1d``) →
          IntervalTrigger. Sub-minute cadence is only useful for
          direct-tool schedules (LLM-bearing cron jobs would burn
          tokens at that rate); the scheduler doesn't enforce that,
          but the trade-off is documented in SKILL + cron docs.
        """
        expr = schedule.cron_expression.strip()
        m = re.fullmatch(r"(\d+)\s*([smhd])", expr)
        if m:
            n = int(m.group(1))
            unit = m.group(2)
            kwargs = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[unit]
            trigger = IntervalTrigger(**{kwargs: n})
        else:
            trigger = CronTrigger.from_crontab(expr)
        job_id = f"schedule_{schedule.id}"
        self._scheduler.add_job(
            self._enqueue_for_execution,
            trigger=trigger,
            args=[schedule.id],
            id=job_id,
            replace_existing=True,
        )
        self._active_jobs[schedule.id] = job_id

    async def _enqueue_for_execution(self, schedule_id: str) -> None:
        """Cron-trigger handler: push the fire onto the run queue OR
        dispatch direct-tool fast path.

        For agent-loop schedules: enqueues + worker dispatches +
        per-schedule_id dedup against running/queued.

        For direct-tool schedules (``direct_tool`` is set): bypasses
        the queue entirely, fires ``_run_direct_tool`` as an
        ``asyncio.create_task`` so it runs concurrently with everything
        else on the event loop. Per-schedule_id dedup still applies via
        ``_direct_running`` so a slow tool can't pile up duplicate fires
        for itself.
        """
        if self._paused:
            logger.info("Scheduler paused — skipping enqueue of %s", schedule_id)
            return

        # Direct-tool fast path — skip the queue, skip the agent loop,
        # skip the action_queue. Pure tool invocation.
        schedule = await self.get_schedule(schedule_id)
        if schedule is not None and schedule.direct_tool:
            if schedule_id in self._direct_running:
                logger.info(
                    "Direct-tool schedule %s still running from previous fire "
                    "— skipping duplicate fire",
                    schedule_id,
                )
                return
            task = asyncio.create_task(self._run_direct_tool(schedule))
            self._direct_running[schedule_id] = task
            task.add_done_callback(
                lambda _t, sid=schedule_id: self._direct_running.pop(sid, None)
            )
            return

        async with self._queue_lock:
            if schedule_id in self._running_tasks:
                logger.info(
                    "Scheduled task %s still running from previous fire — "
                    "skipping new fire to avoid duplicate work",
                    schedule_id,
                )
                return
            if schedule_id in self._queued_ids:
                logger.info(
                    "Scheduled task %s already queued — skipping duplicate fire",
                    schedule_id,
                )
                return
            try:
                self._queue.put_nowait(schedule_id)
            except asyncio.QueueFull:
                logger.warning(
                    "Scheduler queue full (depth=%d) — dropping fire for %s. "
                    "This indicates the scheduler can't keep up; consider "
                    "raising max_concurrent_tasks or auditing slow tasks.",
                    self._queue.qsize(),
                    schedule_id,
                )
                return
            self._queued_ids.add(schedule_id)
            # INFO so an operator tailing logs can see queue activity.
            # The scheduler is the kind of thing where opaque is bad.
            logger.info(
                "Scheduler: enqueued %s (queue depth %d)",
                schedule_id,
                self._queue.qsize(),
            )

    async def _worker_loop(self) -> None:
        """Pop schedules from the queue and dispatch them through the
        resource manager. One worker is enough — concurrency lives
        inside `_run_one` via `asyncio.create_task` so the worker can
        keep popping while previous tasks are still acquiring their
        resources or running.
        """
        while True:
            try:
                schedule_id = await self._queue.get()
            except asyncio.CancelledError:
                return
            async with self._queue_lock:
                self._queued_ids.discard(schedule_id)
            # Don't await — fire and forget so the worker keeps popping.
            # _run_one itself blocks on resource acquisition so this is
            # where parallelism actually happens.
            asyncio.create_task(self._run_one(schedule_id))

    async def _run_direct_tool(self, schedule: ScheduleEntry) -> None:
        """Fast-path executor: invoke a registry tool directly.

        No agent loop, no LLM call, no action_queue acquisition. The
        tool runs as an ``asyncio.create_task`` and contends only with
        whatever resource semaphores it uses internally (httpx for
        network, ``Database._conn_lock`` for SQLite, etc.). Records
        the run in ``schedule_runs`` so observability stays identical
        to agent-loop schedules.

        Only fires when ``schedule.direct_tool`` is set + tool exists
        in the registry. If the tool was removed between schedule
        creation and fire time, marks the run as failed with a clear
        error message rather than silently dropping.
        """
        import json as _json

        schedule_id = schedule.id
        now = datetime.now(UTC).isoformat()
        run_id = await self._db.execute_insert(
            """INSERT INTO schedule_runs (schedule_id, started_at, status)
               VALUES (?, ?, 'running')""",
            (schedule_id, now),
        )

        tool_name = schedule.direct_tool or ""
        tool = self._registry.get(tool_name) if self._registry else None
        if tool is None:
            error_msg = (
                f"direct_tool {tool_name!r} not in registry — was the tool "
                "removed or renamed since the schedule was created?"
            )
            logger.warning("Schedule %s: %s", schedule_id, error_msg)
            completed_at = datetime.now(UTC).isoformat()
            await self._db.execute_insert(
                """UPDATE schedule_runs
                   SET completed_at = ?, status = 'failed', error = ?
                   WHERE id = ?""",
                (completed_at, error_msg, run_id),
            )
            await self._db.execute_insert(
                """UPDATE scheduled_tasks
                   SET last_run_at = ?, last_status = 'failed', updated_at = ?
                   WHERE id = ?""",
                (completed_at, completed_at, schedule_id),
            )
            return

        try:
            params = _json.loads(schedule.direct_params or "{}")
        except _json.JSONDecodeError as e:
            error_msg = f"direct_params malformed JSON: {e}"
            logger.warning("Schedule %s: %s", schedule_id, error_msg)
            completed_at = datetime.now(UTC).isoformat()
            await self._db.execute_insert(
                """UPDATE schedule_runs
                   SET completed_at = ?, status = 'failed', error = ?
                   WHERE id = ?""",
                (completed_at, error_msg, run_id),
            )
            return

        try:
            result = await tool.execute(params)
            success = bool(getattr(result, "success", True))
            data = getattr(result, "data", {}) or {}
            error = getattr(result, "error", None)
            # Summary line used in last_result + UI; keep small (5kb cap
            # in DB column matches agent-loop path).
            summary = (
                _json.dumps(data, default=str)[:5000]
                if success
                else (error or "tool failed")
            )

            completed_at = datetime.now(UTC).isoformat()
            status = "completed" if success else "failed"
            await self._db.execute_insert(
                """UPDATE schedule_runs
                   SET completed_at = ?, status = ?, result = ?, steps_taken = 1
                   WHERE id = ?""",
                (completed_at, status, summary, run_id),
            )
            await self._db.execute_insert(
                """UPDATE scheduled_tasks
                   SET last_run_at = ?, last_status = ?,
                       last_result = ?, updated_at = ?
                   WHERE id = ?""",
                (completed_at, status, summary[:1000], completed_at, schedule_id),
            )
            logger.info(
                "Direct-tool schedule %s (%s) %s in %s",
                schedule.name,
                tool_name,
                status,
                run_id,
            )
        except Exception as e:  # noqa: BLE001 — log and record any tool error
            logger.exception("Direct-tool schedule %s crashed", schedule.name)
            completed_at = datetime.now(UTC).isoformat()
            await self._db.execute_insert(
                """UPDATE schedule_runs
                   SET completed_at = ?, status = 'failed', error = ?
                   WHERE id = ?""",
                (completed_at, str(e)[:2000], run_id),
            )
            await self._db.execute_insert(
                """UPDATE scheduled_tasks
                   SET last_run_at = ?, last_status = 'failed', updated_at = ?
                   WHERE id = ?""",
                (completed_at, completed_at, schedule_id),
            )

    async def _run_one(self, schedule_id: str) -> None:
        """Run one scheduled task through the resource manager.

        Acquires the resources inferred from the task goal, executes,
        releases. The execution body is the same as the old
        ``_execute_schedule`` — only the entry path changed.
        """
        if self._paused:
            logger.info("Scheduler paused — skipping execution of %s", schedule_id)
            return

        schedule = await self.get_schedule(schedule_id)
        if not schedule or not schedule.enabled:
            return

        # Infer resources from task goal text. Conservative — when in
        # doubt, declare BROWSER. See core/task_resources.py.
        resources: list[TaskResource] = infer_resources(schedule.task_goal)
        logger.debug(
            "Schedule %s requesting resources: %s",
            schedule_id,
            [r.value for r in resources],
        )

        async with self._resources.acquire(resources):
            await self._execute_schedule_body(schedule_id, schedule)

    async def _execute_schedule_body(
        self, schedule_id: str, schedule: ScheduleEntry
    ) -> None:
        """The actual run-the-task body. Unchanged from the old
        ``_execute_schedule`` implementation; only the calling path
        moved (cron → enqueue → worker → resource-acquire → here).
        """
        now = datetime.now(UTC).isoformat()

        # Record run start
        run_id = await self._db.execute_insert(
            """INSERT INTO schedule_runs (schedule_id, started_at, status)
               VALUES (?, ?, 'running')""",
            (schedule_id, now),
        )

        # Wrap executor in a tracked task so we can cancel it on delete/disable
        executor_task: asyncio.Task[Any] = asyncio.create_task(
            self._task_executor(schedule.task_goal)
        )
        self._running_tasks[schedule_id] = executor_task
        try:
            result = await executor_task
            content = getattr(result, "content", str(result))
            steps = getattr(result, "steps_taken", 0)

            completed_at = datetime.now(UTC).isoformat()
            await self._db.execute_insert(
                """UPDATE schedule_runs
                   SET completed_at = ?, status = 'completed',
                       result = ?, steps_taken = ?
                   WHERE id = ?""",
                (completed_at, content[:5000], steps, run_id),
            )
            await self._db.execute_insert(
                """UPDATE scheduled_tasks
                   SET last_run_at = ?, last_status = 'completed',
                       last_result = ?, updated_at = ?
                   WHERE id = ?""",
                (completed_at, content[:1000], completed_at, schedule_id),
            )
            logger.info(f"Scheduled task '{schedule.name}' completed")

            # Notify connected channels
            if self._result_notifier:
                try:
                    await self._result_notifier(
                        schedule.name, "completed", content[:1000]
                    )
                except Exception:
                    logger.debug("Schedule notification failed", exc_info=True)

        except asyncio.CancelledError:
            logger.info("Scheduled task cancelled: %s", schedule.name)
            completed_at = datetime.now(UTC).isoformat()
            try:
                await self._db.execute_insert(
                    """UPDATE schedule_runs
                       SET completed_at = ?, status = 'cancelled'
                       WHERE id = ?""",
                    (completed_at, run_id),
                )
                await self._db.execute_insert(
                    """UPDATE scheduled_tasks
                       SET last_run_at = ?, last_status = 'cancelled',
                           updated_at = ?
                       WHERE id = ?""",
                    (completed_at, completed_at, schedule_id),
                )
            except Exception:
                pass
            return
        except Exception as e:
            completed_at = datetime.now(UTC).isoformat()
            await self._db.execute_insert(
                """UPDATE schedule_runs
                   SET completed_at = ?, status = 'failed', error = ?
                   WHERE id = ?""",
                (completed_at, str(e)[:2000], run_id),
            )
            await self._db.execute_insert(
                """UPDATE scheduled_tasks
                   SET last_run_at = ?, last_status = 'failed',
                       retry_count = retry_count + 1, updated_at = ?
                   WHERE id = ?""",
                (completed_at, completed_at, schedule_id),
            )

            # Notify connected channels of failure
            if self._result_notifier:
                try:
                    await self._result_notifier(schedule.name, "failed", str(e)[:500])
                except Exception:
                    logger.debug("Schedule failure notification failed", exc_info=True)

            # Check retry limit
            rows = await self._db.execute(
                "SELECT retry_count, max_retries FROM scheduled_tasks WHERE id = ?",
                (schedule_id,),
            )
            if rows:
                row = rows[0]
                if row["retry_count"] >= row["max_retries"]:
                    logger.error(
                        f"Schedule '{schedule.name}' exceeded max retries, disabling"
                    )
                    await self.disable_schedule(schedule_id)
        finally:
            self._running_tasks.pop(schedule_id, None)

    async def _load_from_db(self) -> list[ScheduleEntry]:
        """Load all schedules from the database."""
        rows = await self._db.execute(
            "SELECT * FROM scheduled_tasks ORDER BY created_at"
        )
        return [self._row_to_entry(row) for row in rows]

    @staticmethod
    def _row_to_entry(row: Any) -> ScheduleEntry:
        # row.keys() guard — direct_tool/direct_params arrive via the
        # 2026-05-11 migration; pre-migration rows return None via the
        # try/except.
        def _opt(key: str) -> Any:
            try:
                return row[key]
            except (KeyError, IndexError):
                return None

        return ScheduleEntry(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            cron_expression=row["cron_expression"],
            task_goal=row["task_goal"],
            enabled=bool(row["enabled"]),
            last_run_at=row["last_run_at"],
            next_run_at=row["next_run_at"],
            last_status=row["last_status"],
            max_retries=row["max_retries"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            direct_tool=_opt("direct_tool"),
            direct_params=_opt("direct_params"),
        )


# --- Natural language schedule parsing ---

_NL_PATTERNS: list[tuple[str, str]] = [
    (r"every\s+(\d+)\s+minutes?", "*/\\1 * * * *"),
    (r"every\s+hour", "0 * * * *"),
    (r"every\s+morning\s+at\s+(\d{1,2})\s*am", "0 \\1 * * *"),
    (r"every\s+evening\s+at\s+(\d{1,2})\s*pm", "0 _PM_ * * *"),
    (r"every\s+day\s+at\s+(\d{1,2}):(\d{2})", "\\2 \\1 * * *"),
    (r"daily\s+at\s+midnight", "0 0 * * *"),
    (r"daily\s+at\s+noon", "0 12 * * *"),
    (r"every\s+monday\s+at\s+(\d{1,2})\s*([ap]m)?", "_DAY_ 1"),
    (r"every\s+tuesday\s+at\s+(\d{1,2})\s*([ap]m)?", "_DAY_ 2"),
    (r"every\s+wednesday\s+at\s+(\d{1,2})\s*([ap]m)?", "_DAY_ 3"),
    (r"every\s+thursday\s+at\s+(\d{1,2})\s*([ap]m)?", "_DAY_ 4"),
    (r"every\s+friday\s+at\s+(\d{1,2})\s*([ap]m)?", "_DAY_ 5"),
    (r"every\s+saturday\s+at\s+(\d{1,2})\s*([ap]m)?", "_DAY_ 6"),
    (r"every\s+sunday\s+at\s+(\d{1,2})\s*([ap]m)?", "_DAY_ 0"),
]


def parse_delay(text: str) -> datetime | None:
    """Try to parse a one-time delay like 'in 5 minutes', 'in 1 hour'.

    Returns the target datetime if it's a one-time schedule, or None
    if it looks like a recurring schedule.
    """
    from datetime import timedelta

    text_lower = text.lower().strip()

    m = re.match(r"in\s+(\d+)\s+minutes?", text_lower)
    if m:
        return datetime.now(UTC) + timedelta(minutes=int(m.group(1)))

    m = re.match(r"in\s+(\d+)\s+hours?", text_lower)
    if m:
        return datetime.now(UTC) + timedelta(hours=int(m.group(1)))

    m = re.match(r"in\s+(\d+)\s+seconds?", text_lower)
    if m:
        return datetime.now(UTC) + timedelta(seconds=int(m.group(1)))

    m = re.match(r"in\s+(\d+)\s+days?", text_lower)
    if m:
        return datetime.now(UTC) + timedelta(days=int(m.group(1)))

    # "at 3pm" / "at 15:30" (today)
    m = re.match(r"at\s+(\d{1,2}):(\d{2})\s*([ap]m)?", text_lower)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        ampm = m.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        target = datetime.now(UTC).replace(hour=hour, minute=minute, second=0)
        if target <= datetime.now(UTC):
            target += timedelta(days=1)
        return target

    m = re.match(r"at\s+(\d{1,2})\s*([ap]m)", text_lower)
    if m:
        hour = int(m.group(1))
        ampm = m.group(2)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        target = datetime.now(UTC).replace(hour=hour, minute=0, second=0)
        if target <= datetime.now(UTC):
            target += timedelta(days=1)
        return target

    # "after 30 seconds"
    m = re.match(r"after\s+(\d+)\s+(\w+)", text_lower)
    if m:
        amount = int(m.group(1))
        unit = m.group(2).rstrip("s")
        deltas = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
        if unit in deltas:
            return datetime.now(UTC) + timedelta(seconds=amount * deltas[unit])

    return None


def parse_natural_language_schedule(text: str) -> str:
    """Convert natural language schedule to cron expression.

    Examples:
        'every morning at 9am' -> '0 9 * * *'
        'every hour' -> '0 * * * *'
        'every 2 hours' -> '0 */2 * * *'
        'every 6 hours' -> '0 */6 * * *'
        'every monday at 2pm' -> '0 14 * * 1'
        'every 5 minutes' -> '*/5 * * * *'
        'daily at midnight' -> '0 0 * * *'

    Falls back to treating input as a cron expression if no pattern matches.
    """
    text_lower = text.lower().strip()

    m = re.match(r"every\s+(\d+)\s+minutes?", text_lower)
    if m:
        return f"*/{m.group(1)} * * * *"

    m = re.match(r"every\s+(\d+)\s+hours?", text_lower)
    if m:
        n = int(m.group(1))
        return f"0 */{n} * * *"

    if re.match(r"every\s+hour", text_lower):
        return "0 * * * *"

    m = re.match(r"every\s+morning\s+at\s+(\d{1,2})\s*am", text_lower)
    if m:
        return f"0 {m.group(1)} * * *"

    m = re.match(r"every\s+(?:evening\s+at|night\s+at)\s+(\d{1,2})\s*pm", text_lower)
    if m:
        hour = int(m.group(1)) + 12
        return f"0 {hour} * * *"

    m = re.match(r"every\s+day\s+at\s+(\d{1,2}):(\d{2})", text_lower)
    if m:
        return f"{m.group(2)} {m.group(1)} * * *"

    if "daily at midnight" in text_lower:
        return "0 0 * * *"

    if "daily at noon" in text_lower:
        return "0 12 * * *"

    days = {
        "monday": "1",
        "tuesday": "2",
        "wednesday": "3",
        "thursday": "4",
        "friday": "5",
        "saturday": "6",
        "sunday": "0",
    }
    for day_name, day_num in days.items():
        m = re.match(
            rf"every\s+{day_name}\s+at\s+(\d{{1,2}})\s*([ap]m)?",
            text_lower,
        )
        if m:
            hour = int(m.group(1))
            ampm = m.group(2)
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            return f"0 {hour} * * {day_num}"

    parts = text.strip().split()
    if len(parts) == 5:
        return text.strip()

    raise ValueError(
        f"Cannot parse schedule: '{text}'. "
        f"Use a cron expression (e.g., '0 9 * * *'), natural language "
        f"recurring (e.g., 'every morning at 9am'), or one-time "
        f"(e.g., 'in 5 minutes', 'at 3pm')."
    )
