"""Tests for the task scheduler and natural language parsing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.database import Database
from core.scheduler import TaskScheduler, parse_natural_language_schedule

# ─── Natural Language Schedule Parsing ───


class TestParseNaturalLanguage:
    def test_every_5_minutes(self) -> None:
        assert parse_natural_language_schedule("every 5 minutes") == "*/5 * * * *"

    def test_every_1_minute(self) -> None:
        assert parse_natural_language_schedule("every 1 minute") == "*/1 * * * *"

    def test_every_hour(self) -> None:
        assert parse_natural_language_schedule("every hour") == "0 * * * *"

    def test_every_morning_at_9am(self) -> None:
        assert parse_natural_language_schedule("every morning at 9am") == "0 9 * * *"

    def test_every_evening_at_8pm(self) -> None:
        result = parse_natural_language_schedule("every evening at 8pm")
        assert result == "0 20 * * *"

    def test_every_day_at_time(self) -> None:
        result = parse_natural_language_schedule("every day at 14:30")
        assert result == "30 14 * * *"

    def test_daily_at_midnight(self) -> None:
        assert parse_natural_language_schedule("daily at midnight") == "0 0 * * *"

    def test_daily_at_noon(self) -> None:
        assert parse_natural_language_schedule("daily at noon") == "0 12 * * *"

    def test_every_monday_at_2pm(self) -> None:
        result = parse_natural_language_schedule("every monday at 2pm")
        assert result == "0 14 * * 1"

    def test_every_friday_at_9am(self) -> None:
        result = parse_natural_language_schedule("every friday at 9am")
        assert result == "0 9 * * 5"

    def test_every_sunday_at_10(self) -> None:
        result = parse_natural_language_schedule("every sunday at 10")
        assert result == "0 10 * * 0"

    def test_raw_cron_passthrough(self) -> None:
        assert parse_natural_language_schedule("0 9 * * *") == "0 9 * * *"

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_natural_language_schedule("sometime maybe")

    def test_case_insensitive(self) -> None:
        assert parse_natural_language_schedule("Every Hour") == "0 * * * *"


# ─── TaskScheduler ───


class TestTaskScheduler:
    @pytest.fixture
    async def db(self, tmp_path: Path) -> Database:
        db = Database(tmp_path / "test.db")
        await db.initialize()
        return db

    @pytest.fixture
    def mock_executor(self) -> AsyncMock:
        executor = AsyncMock()
        executor.return_value = type(
            "Result", (), {"content": "Done", "steps_taken": 1}
        )()
        return executor

    @pytest.fixture
    async def scheduler(self, db: Database, mock_executor: AsyncMock) -> TaskScheduler:
        s = TaskScheduler(db=db, task_executor=mock_executor)
        return s

    @pytest.mark.asyncio
    async def test_create_schedule(self, scheduler: TaskScheduler) -> None:
        entry = await scheduler.create_schedule(
            name="Test Task",
            task_goal="Do something useful",
            cron_expression="0 9 * * *",
            description="A test schedule",
        )
        assert entry.name == "Test Task"
        assert entry.cron_expression == "0 9 * * *"
        assert entry.enabled is True
        assert len(entry.id) > 0

    @pytest.mark.asyncio
    async def test_create_schedule_invalid_cron(self, scheduler: TaskScheduler) -> None:
        with pytest.raises(ValueError, match="Invalid cron"):
            await scheduler.create_schedule(
                name="Bad",
                task_goal="Fail",
                cron_expression="not a cron",
            )

    @pytest.mark.asyncio
    async def test_list_schedules(self, scheduler: TaskScheduler) -> None:
        await scheduler.create_schedule(
            name="A", task_goal="Do A", cron_expression="0 * * * *"
        )
        await scheduler.create_schedule(
            name="B", task_goal="Do B", cron_expression="0 12 * * *"
        )
        schedules = await scheduler.list_schedules()
        assert len(schedules) == 2
        names = [s.name for s in schedules]
        assert "A" in names
        assert "B" in names

    @pytest.mark.asyncio
    async def test_get_schedule(self, scheduler: TaskScheduler) -> None:
        entry = await scheduler.create_schedule(
            name="Fetch", task_goal="Fetch data", cron_expression="*/5 * * * *"
        )
        retrieved = await scheduler.get_schedule(entry.id)
        assert retrieved is not None
        assert retrieved.name == "Fetch"

    @pytest.mark.asyncio
    async def test_get_schedule_not_found(self, scheduler: TaskScheduler) -> None:
        result = await scheduler.get_schedule("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_schedule(self, scheduler: TaskScheduler) -> None:
        entry = await scheduler.create_schedule(
            name="Delete Me",
            task_goal="Will be deleted",
            cron_expression="0 0 * * *",
        )
        deleted = await scheduler.delete_schedule(entry.id)
        assert deleted is True
        assert await scheduler.get_schedule(entry.id) is None

    @pytest.mark.asyncio
    async def test_disable_enable_schedule(self, scheduler: TaskScheduler) -> None:
        entry = await scheduler.create_schedule(
            name="Toggle",
            task_goal="Toggle me",
            cron_expression="0 0 * * *",
        )
        await scheduler.disable_schedule(entry.id)
        s = await scheduler.get_schedule(entry.id)
        assert s is not None
        assert s.enabled is False

        await scheduler.enable_schedule(entry.id)
        s = await scheduler.get_schedule(entry.id)
        assert s is not None
        assert s.enabled is True

    @pytest.mark.asyncio
    async def test_get_run_history_empty(self, scheduler: TaskScheduler) -> None:
        entry = await scheduler.create_schedule(
            name="NoRuns",
            task_goal="Nothing yet",
            cron_expression="0 0 * * *",
        )
        history = await scheduler.get_run_history(entry.id)
        assert history == []
