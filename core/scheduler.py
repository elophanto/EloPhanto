"""Task scheduler — APScheduler wrapper with database persistence.

Manages scheduled tasks using APScheduler's AsyncIOScheduler.
Schedules are persisted to SQLite and restored on restart.
"""

from __future__ import annotations

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
    """Manages scheduled task execution using APScheduler."""

    def __init__(
        self,
        db: Database,
        task_executor: Callable[[str], Coroutine[Any, Any, Any]],
    ) -> None:
        self._db = db
        self._task_executor = task_executor
        self._scheduler = AsyncIOScheduler()
        self._active_jobs: dict[str, str] = {}

    async def start(self) -> None:
        """Start the scheduler and restore persisted schedules."""
        schedules = await self._load_from_db()
        for schedule in schedules:
            if schedule.enabled:
                self._add_job(schedule)
        self._scheduler.start()
        logger.info(f"Scheduler started with {len(schedules)} schedule(s)")

    async def stop(self) -> None:
        """Gracefully stop the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

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
        """Execute a one-time task and then clean it up."""
        await self._execute_schedule(schedule_id)
        try:
            await self.delete_schedule(schedule_id)
        except Exception:
            pass

    async def delete_schedule(self, schedule_id: str) -> bool:
        """Delete a scheduled task."""
        job_id = self._active_jobs.pop(schedule_id, None)
        if job_id:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass

        await self._db.execute_insert("DELETE FROM scheduled_tasks WHERE id = ?", (schedule_id,))
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
        """Disable a schedule."""
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

    async def list_schedules(self) -> list[ScheduleEntry]:
        """List all schedules from the database."""
        return await self._load_from_db()

    async def get_schedule(self, schedule_id: str) -> ScheduleEntry | None:
        """Get a single schedule by ID."""
        rows = await self._db.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (schedule_id,))
        if not rows:
            return None
        return self._row_to_entry(rows[0])

    async def get_run_history(self, schedule_id: str, limit: int = 10) -> list[dict[str, Any]]:
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
            self._execute_schedule,
            trigger=trigger,
            args=[schedule.id],
            id=job_id,
            replace_existing=True,
        )
        self._active_jobs[schedule.id] = job_id

    async def _execute_schedule(self, schedule_id: str) -> None:
        """Execute a scheduled task through the agent loop."""
        schedule = await self.get_schedule(schedule_id)
        if not schedule or not schedule.enabled:
            return

        now = datetime.now(UTC).isoformat()

        # Record run start
        run_id = await self._db.execute_insert(
            """INSERT INTO schedule_runs (schedule_id, started_at, status)
               VALUES (?, ?, 'running')""",
            (schedule_id, now),
        )

        try:
            result = await self._task_executor(schedule.task_goal)
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

            # Check retry limit
            rows = await self._db.execute(
                "SELECT retry_count, max_retries FROM scheduled_tasks WHERE id = ?",
                (schedule_id,),
            )
            if rows:
                row = rows[0]
                if row["retry_count"] >= row["max_retries"]:
                    logger.error(f"Schedule '{schedule.name}' exceeded max retries, disabling")
                    await self.disable_schedule(schedule_id)

    async def _load_from_db(self) -> list[ScheduleEntry]:
        """Load all schedules from the database."""
        rows = await self._db.execute("SELECT * FROM scheduled_tasks ORDER BY created_at")
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
        'every monday at 2pm' -> '0 14 * * 1'
        'every 5 minutes' -> '*/5 * * * *'
        'daily at midnight' -> '0 0 * * *'

    Falls back to treating input as a cron expression if no pattern matches.
    """
    text_lower = text.lower().strip()

    m = re.match(r"every\s+(\d+)\s+minutes?", text_lower)
    if m:
        return f"*/{m.group(1)} * * * *"

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
