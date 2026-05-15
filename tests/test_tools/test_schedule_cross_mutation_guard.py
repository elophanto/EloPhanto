"""Cross-schedule mutation guard — a scheduled task cannot enable /
disable / stop / delete / create another schedule.

Pinned after the 2026-05-15 incident: a Daily Review schedule
autonomously disabled three other schedules right after operator
policy was updated. Schedule lifecycle is operator policy; the
scheduler queues runs; schedules don't get to meddle with each other.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

from core.agent import _in_scheduled_task
from tools.scheduling.list_tool import ScheduleListTool
from tools.scheduling.schedule_tool import ScheduleTaskTool


@contextmanager
def _inside_scheduled_task():
    """Simulate being called from inside a scheduled task run."""
    token = _in_scheduled_task.set(True)
    try:
        yield
    finally:
        _in_scheduled_task.reset(token)


class _StubScheduler:
    """Minimal stub — the tool should refuse BEFORE calling any method,
    so any call here would be a failure."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def enable_schedule(self, sid: str) -> None:
        self.calls.append(f"enable:{sid}")

    async def disable_schedule(self, sid: str) -> None:
        self.calls.append(f"disable:{sid}")

    async def delete_schedule(self, sid: str) -> None:
        self.calls.append(f"delete:{sid}")

    async def stop_running(self, sid: str) -> bool:
        self.calls.append(f"stop:{sid}")
        return True

    async def stop_all_running(self) -> int:
        self.calls.append("stop_all")
        return 0

    async def list_schedules(self) -> list[Any]:
        self.calls.append("list")
        return []

    async def get_run_history(self, sid: str, limit: int) -> list[Any]:
        self.calls.append(f"history:{sid}")
        return []


class TestListToolGuard:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "action,extra",
        [
            ("disable", {"schedule_id": "abc"}),
            ("enable", {"schedule_id": "abc"}),
            ("stop", {"schedule_id": "abc"}),
            ("delete", {"schedule_id": "abc"}),
            ("stop_all", {}),
            ("update", {"schedule_id": "abc", "name": "x"}),
        ],
    )
    async def test_mutating_actions_refused_inside_scheduled_task(
        self, action: str, extra: dict[str, Any]
    ) -> None:
        tool = ScheduleListTool()
        scheduler = _StubScheduler()
        tool._scheduler = scheduler

        with _inside_scheduled_task():
            result = await tool.execute({"action": action, **extra})

        assert result.success is False
        assert "refused" in (result.error or "").lower()
        assert action in (result.error or "")
        # Scheduler MUST NOT have been called — refusal happens before.
        assert (
            scheduler.calls == []
        ), f"scheduler called when it should have been refused: {scheduler.calls}"

    @pytest.mark.asyncio
    async def test_list_action_allowed_inside_scheduled_task(self) -> None:
        """Read-only ``list`` stays allowed — legitimate dedupe checks
        need it. Same for ``history``."""
        tool = ScheduleListTool()
        scheduler = _StubScheduler()
        tool._scheduler = scheduler

        with _inside_scheduled_task():
            result = await tool.execute({"action": "list"})

        assert result.success is True
        assert scheduler.calls == ["list"]

    @pytest.mark.asyncio
    async def test_history_action_allowed_inside_scheduled_task(self) -> None:
        tool = ScheduleListTool()
        scheduler = _StubScheduler()
        tool._scheduler = scheduler

        with _inside_scheduled_task():
            result = await tool.execute({"action": "history", "schedule_id": "abc"})

        assert result.success is True
        assert scheduler.calls == ["history:abc"]

    @pytest.mark.asyncio
    async def test_mutating_actions_allowed_from_operator_chat(self) -> None:
        """Operator-driven chat (no _in_scheduled_task contextvar) keeps
        full control — this is what scheduled tasks are losing, not
        what operators lose."""
        tool = ScheduleListTool()
        scheduler = _StubScheduler()
        tool._scheduler = scheduler

        # NOT inside _inside_scheduled_task() — simulates operator path.
        result = await tool.execute({"action": "disable", "schedule_id": "abc"})

        assert result.success is True
        assert "disable:abc" in scheduler.calls


class TestCreateToolGuard:
    @pytest.mark.asyncio
    async def test_create_refused_inside_scheduled_task(self) -> None:
        tool = ScheduleTaskTool()

        # Truthy stub — refusal must happen BEFORE scheduler is used.
        class _S:
            def __getattr__(self, name: str) -> Any:
                raise AssertionError(
                    f"scheduler.{name} called — refusal should happen first"
                )

        tool._scheduler = _S()

        with _inside_scheduled_task():
            result = await tool.execute(
                {
                    "schedule": "every 1 hour",
                    "task_goal": "x",
                    "name": "spawned",
                    "description": "",
                    "max_retries": 1,
                }
            )

        assert result.success is False
        assert "refused" in (result.error or "").lower()
        assert "schedule_task" in (result.error or "")
