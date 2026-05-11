"""Tests for the task scheduler and natural language parsing."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
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
    async def test_update_schedule_changes_fields(
        self, scheduler: TaskScheduler
    ) -> None:
        entry = await scheduler.create_schedule(
            name="Original",
            task_goal="old goal",
            cron_expression="0 9 * * *",
        )
        updated = await scheduler.update_schedule(
            entry.id,
            name="Renamed",
            task_goal="new goal",
            cron_expression="0 10 * * *",
        )
        assert updated is not None
        assert updated.id == entry.id
        assert updated.name == "Renamed"
        assert updated.task_goal == "new goal"
        assert updated.cron_expression == "0 10 * * *"

    @pytest.mark.asyncio
    async def test_update_schedule_invalid_cron(self, scheduler: TaskScheduler) -> None:
        entry = await scheduler.create_schedule(
            name="X", task_goal="g", cron_expression="0 9 * * *"
        )
        with pytest.raises(ValueError, match="Invalid cron"):
            await scheduler.update_schedule(entry.id, cron_expression="not a cron")
        # Original unchanged
        s = await scheduler.get_schedule(entry.id)
        assert s is not None
        assert s.cron_expression == "0 9 * * *"

    @pytest.mark.asyncio
    async def test_update_schedule_missing_returns_none(
        self, scheduler: TaskScheduler
    ) -> None:
        result = await scheduler.update_schedule("nope", name="x")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_schedule_partial_keeps_other_fields(
        self, scheduler: TaskScheduler
    ) -> None:
        entry = await scheduler.create_schedule(
            name="Keep",
            task_goal="keep this goal",
            cron_expression="0 9 * * *",
            description="orig desc",
        )
        updated = await scheduler.update_schedule(entry.id, name="NewName")
        assert updated is not None
        assert updated.name == "NewName"
        assert updated.task_goal == "keep this goal"
        assert updated.cron_expression == "0 9 * * *"
        assert updated.description == "orig desc"

    @pytest.mark.asyncio
    async def test_get_run_history_empty(self, scheduler: TaskScheduler) -> None:
        entry = await scheduler.create_schedule(
            name="NoRuns",
            task_goal="Nothing yet",
            cron_expression="0 0 * * *",
        )
        history = await scheduler.get_run_history(entry.id)
        assert history == []

    @pytest.mark.asyncio
    async def test_stop_running_when_idle(self, scheduler: TaskScheduler) -> None:
        """Stopping a non-running schedule should return False."""
        result = await scheduler.stop_running("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_stop_running_cancels_in_flight(self, db: Database) -> None:
        """A running task should be cancelled by stop_running."""
        import asyncio

        started = asyncio.Event()

        async def slow_executor(goal: str):
            started.set()
            await asyncio.sleep(60)
            return type("Result", (), {"content": "done", "steps_taken": 1})()

        scheduler = TaskScheduler(db=db, task_executor=slow_executor)
        entry = await scheduler.create_schedule(
            name="Slow", task_goal="Slow task", cron_expression="0 0 * * *"
        )

        # Manually start an execution and wait until the executor is actually running
        task = asyncio.create_task(scheduler._run_one(entry.id))
        await asyncio.wait_for(started.wait(), timeout=5)

        # Stop it
        was_running = await scheduler.stop_running(entry.id)
        assert was_running is True

        # Wait for the wrapped execution to settle
        try:
            await asyncio.wait_for(task, timeout=2)
        except (TimeoutError, asyncio.CancelledError):
            pass

        # Should no longer be tracked
        assert entry.id not in scheduler._running_tasks

    @pytest.mark.asyncio
    async def test_stop_all_running(self, db: Database) -> None:
        """stop_all_running cancels every in-flight task."""
        import asyncio

        started = asyncio.Semaphore(0)

        async def slow_executor(goal: str):
            started.release()
            await asyncio.sleep(60)
            return type("Result", (), {"content": "done", "steps_taken": 1})()

        scheduler = TaskScheduler(db=db, task_executor=slow_executor)
        entry1 = await scheduler.create_schedule(
            name="A", task_goal="A", cron_expression="0 0 * * *"
        )
        entry2 = await scheduler.create_schedule(
            name="B", task_goal="B", cron_expression="0 0 * * *"
        )

        # Start two executions and wait until both executors are actually running.
        # Semaphore + acquire-twice avoids the race where both tasks bump a shared
        # counter non-atomically; on slow CI the event could be missed.
        t1 = asyncio.create_task(scheduler._run_one(entry1.id))
        t2 = asyncio.create_task(scheduler._run_one(entry2.id))
        await asyncio.wait_for(started.acquire(), timeout=15)
        await asyncio.wait_for(started.acquire(), timeout=15)

        count = await scheduler.stop_all_running()
        assert count == 2

        # Settle outer wrappers
        for task in (t1, t2):
            try:
                await asyncio.wait_for(task, timeout=2)
            except (TimeoutError, asyncio.CancelledError):
                pass

        assert len(scheduler._running_tasks) == 0

    @pytest.mark.asyncio
    async def test_delete_cancels_running(self, db: Database) -> None:
        """delete_schedule should cancel an in-flight task."""
        import asyncio

        started = asyncio.Event()

        async def slow_executor(goal: str):
            started.set()
            await asyncio.sleep(60)
            return type("Result", (), {"content": "done", "steps_taken": 1})()

        scheduler = TaskScheduler(db=db, task_executor=slow_executor)
        entry = await scheduler.create_schedule(
            name="Slow", task_goal="Slow", cron_expression="0 0 * * *"
        )

        task = asyncio.create_task(scheduler._run_one(entry.id))
        await asyncio.wait_for(started.wait(), timeout=5)

        await scheduler.delete_schedule(entry.id)

        try:
            await asyncio.wait_for(task, timeout=2)
        except (TimeoutError, asyncio.CancelledError):
            pass

        # Schedule deleted from DB
        assert await scheduler.get_schedule(entry.id) is None
        # No longer tracked as running
        assert entry.id not in scheduler._running_tasks


class TestDirectTool:
    """Pin the direct-tool fast path (bypasses agent loop + LLM)."""

    @pytest.fixture
    async def db(self, tmp_path: Path) -> Database:
        d = Database(tmp_path / "test.db")
        await d.initialize()
        return d

    @pytest.fixture
    def registry(self) -> Any:
        """Minimal registry with a SAFE tool and a DESTRUCTIVE tool."""
        from tools.base import PermissionLevel

        class _SafeTool:
            name = "safe_probe"
            permission_level = PermissionLevel.SAFE

            def __init__(self) -> None:
                self.calls: list[dict] = []

            async def execute(self, params: dict) -> Any:
                self.calls.append(params)
                from tools.base import ToolResult

                return ToolResult(
                    success=True, data={"echo": params, "calls_so_far": len(self.calls)}
                )

        class _DestructiveTool:
            name = "burn_it_down"
            permission_level = PermissionLevel.DESTRUCTIVE

            async def execute(self, params: dict) -> Any:  # pragma: no cover
                raise AssertionError("must not be invoked")

        safe_tool = _SafeTool()
        destructive_tool = _DestructiveTool()
        tools = {safe_tool.name: safe_tool, destructive_tool.name: destructive_tool}

        class _Registry:
            def get(self, name: str) -> Any:
                return tools.get(name)

        return _Registry()

    @pytest.fixture
    async def scheduler(self, db: Database, registry: Any) -> TaskScheduler:
        # Agent-loop executor that should NEVER fire for direct-tool schedules.
        async def never_called(_goal: str) -> Any:
            raise AssertionError("agent-loop executor must not run for direct-tool")

        return TaskScheduler(
            db=db,
            task_executor=never_called,
            registry=registry,
        )

    @pytest.mark.asyncio
    async def test_create_direct_schedule_persists_tool_and_params(
        self, scheduler: TaskScheduler
    ) -> None:
        entry = await scheduler.create_schedule(
            name="Resolve Pending",
            task_goal="",
            cron_expression="5m",
            direct_tool="safe_probe",
            direct_params={"limit": 200},
        )
        assert entry.direct_tool == "safe_probe"
        assert entry.direct_params == '{"limit": 200}'
        # task_goal gets a trace string when omitted
        assert "[direct-tool] safe_probe" in entry.task_goal

    @pytest.mark.asyncio
    async def test_create_refuses_destructive_tool(
        self, scheduler: TaskScheduler
    ) -> None:
        with pytest.raises(ValueError, match="refuses non-SAFE"):
            await scheduler.create_schedule(
                name="bad",
                task_goal="",
                cron_expression="5m",
                direct_tool="burn_it_down",
            )

    @pytest.mark.asyncio
    async def test_create_refuses_unknown_tool(self, scheduler: TaskScheduler) -> None:
        with pytest.raises(ValueError, match="Unknown tool"):
            await scheduler.create_schedule(
                name="bad",
                task_goal="",
                cron_expression="5m",
                direct_tool="does_not_exist",
            )

    @pytest.mark.asyncio
    async def test_create_rejects_malformed_json_params(
        self, scheduler: TaskScheduler
    ) -> None:
        with pytest.raises(ValueError, match="not valid JSON"):
            await scheduler.create_schedule(
                name="bad",
                task_goal="",
                cron_expression="5m",
                direct_tool="safe_probe",
                direct_params="{not-json",
            )

    @pytest.mark.asyncio
    async def test_direct_tool_executes_and_records(
        self, scheduler: TaskScheduler, db: Database, registry: Any
    ) -> None:
        entry = await scheduler.create_schedule(
            name="Probe",
            task_goal="",
            cron_expression="5m",
            direct_tool="safe_probe",
            direct_params={"k": "v"},
        )
        # Fire the dispatch path directly — bypasses APScheduler.
        await scheduler._enqueue_for_execution(entry.id)
        # _enqueue_for_execution fires _run_direct_tool as a task; await
        # the task it tracked so the run row settles.
        in_flight = scheduler._direct_running.get(entry.id)
        if in_flight is not None:
            await in_flight

        # SAFE tool was actually invoked
        tool = registry.get("safe_probe")
        assert tool.calls == [{"k": "v"}]

        # schedule_runs row recorded as 'completed'
        runs = await scheduler.get_run_history(entry.id, limit=5)
        assert len(runs) == 1
        assert runs[0]["status"] == "completed"
        # Result is JSON of tool data
        assert '"echo"' in runs[0]["result"]

    @pytest.mark.asyncio
    async def test_direct_tool_dedup_skips_duplicate_fire(
        self, scheduler: TaskScheduler, db: Database, registry: Any
    ) -> None:
        """Per-schedule_id dedup: if a previous direct-tool fire is
        still running, the next fire is skipped (not queued)."""
        from tools.base import PermissionLevel, ToolResult

        # Replace safe_probe with a slow version we can hold open.
        gate = asyncio.Event()

        class _SlowTool:
            name = "safe_probe"
            permission_level = PermissionLevel.SAFE
            calls = 0

            async def execute(self, params: dict) -> Any:
                _SlowTool.calls += 1
                await gate.wait()
                return ToolResult(success=True, data={})

        slow = _SlowTool()
        registry_mock = type(
            "R",
            (),
            {"get": staticmethod(lambda n: slow if n == "safe_probe" else None)},
        )
        scheduler._registry = registry_mock

        entry = await scheduler.create_schedule(
            name="Slow",
            task_goal="",
            cron_expression="5m",
            direct_tool="safe_probe",
        )
        # Fire once — starts running, waits on gate
        await scheduler._enqueue_for_execution(entry.id)
        # Fire again while first is still running — must be deduped
        await scheduler._enqueue_for_execution(entry.id)
        # Release gate, drain
        gate.set()
        in_flight = scheduler._direct_running.get(entry.id)
        if in_flight is not None:
            await in_flight
        assert _SlowTool.calls == 1  # second fire was dropped

    @pytest.mark.asyncio
    async def test_direct_tool_failure_recorded(
        self, scheduler: TaskScheduler, db: Database
    ) -> None:
        """Tool crash → schedule_run status='failed', error captured."""
        from tools.base import PermissionLevel

        class _Crasher:
            name = "safe_probe"
            permission_level = PermissionLevel.SAFE

            async def execute(self, _params: dict) -> Any:
                raise RuntimeError("boom")

        scheduler._registry = type(
            "R",
            (),
            {"get": staticmethod(lambda n: _Crasher() if n == "safe_probe" else None)},
        )
        entry = await scheduler.create_schedule(
            name="Boom",
            task_goal="",
            cron_expression="5m",
            direct_tool="safe_probe",
        )
        await scheduler._enqueue_for_execution(entry.id)
        in_flight = scheduler._direct_running.get(entry.id)
        if in_flight is not None:
            await in_flight

        runs = await scheduler.get_run_history(entry.id, limit=5)
        assert len(runs) == 1
        assert runs[0]["status"] == "failed"
        assert "boom" in (runs[0]["error"] or "")

    @pytest.mark.asyncio
    async def test_interval_trigger_syntax_accepted(self) -> None:
        TaskScheduler._validate_trigger("30s")
        TaskScheduler._validate_trigger("5m")
        TaskScheduler._validate_trigger("2h")
        TaskScheduler._validate_trigger("1d")
        with pytest.raises(ValueError):
            TaskScheduler._validate_trigger("0s")
        with pytest.raises(ValueError):
            TaskScheduler._validate_trigger("garbage")

    @pytest.mark.asyncio
    async def test_agent_loop_path_unchanged_for_no_direct_tool(
        self, db: Database
    ) -> None:
        """Smoke: schedules without direct_tool still go through
        the task_executor (agent.run path), unaffected by the new fork."""
        called = asyncio.Event()

        async def task_exec(_goal: str) -> Any:
            called.set()
            return type("R", (), {"content": "ok", "steps_taken": 0})()

        s = TaskScheduler(db=db, task_executor=task_exec)
        entry = await s.create_schedule(
            name="Agent Loop", task_goal="do x", cron_expression="0 9 * * *"
        )
        assert entry.direct_tool is None
        # Drive the same code path as a cron fire
        await s._enqueue_for_execution(entry.id)
        # Worker is not running in this fixture; drain queue manually
        if s._queue.qsize() > 0:
            schedule_id = await s._queue.get()
            await s._run_one(schedule_id)
        await asyncio.wait_for(called.wait(), timeout=3)
