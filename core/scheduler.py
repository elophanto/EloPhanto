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

from core.database import Database
from core.task_resources import TaskResource, TaskResourceManager, infer_resources

logger = logging.getLogger(__name__)


@dataclass
class ScheduleEntry:
    """A single scheduled task definition."""

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
    ) -> ScheduleEntry:
        """Create a new scheduled task and persist it."""
        # Validate cron expression
        try:
            CronTrigger.from_crontab(cron_expression)
        except ValueError as e:
            raise ValueError(f"Invalid cron expression: {e}") from e

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

        self._add_job(entry)
        return entry

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
        # Cancel in-flight task if running
        running = self._running_tasks.pop(schedule_id, None)
        if running and not running.done():
            running.cancel()
            try:
                await running
            except (asyncio.CancelledError, Exception):
                pass
            logger.info("Cancelled running task for schedule %s", schedule_id)

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
        """Add an APScheduler job for a schedule entry."""
        trigger = CronTrigger.from_crontab(schedule.cron_expression)
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
        """Cron-trigger handler: push the fire onto the run queue.

        Replaces the old "drop on the floor when busy" behavior.
        Per-task dedup: if the same schedule_id is already running OR
        already queued, the new fire is logged + skipped — prevents a
        slow task that always exceeds its cron interval from spiraling
        into a queue full of duplicate fires for itself.

        If the queue is full (queue_depth_cap), the fire is logged and
        skipped. That only happens when the entire pipeline is jammed,
        which is itself a real failure worth surfacing.
        """
        if self._paused:
            logger.info("Scheduler paused — skipping enqueue of %s", schedule_id)
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
