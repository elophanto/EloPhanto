"""Goal tool tests — interface compliance and execution paths."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from tools.base import PermissionLevel
from tools.goals.create_tool import GoalCreateTool
from tools.goals.manage_tool import GoalManageTool
from tools.goals.status_tool import GoalStatusTool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeCheckpoint:
    order: int
    title: str
    success_criteria: str
    status: str = "pending"
    result_summary: str | None = None
    attempts: int = 0


@dataclass
class FakeGoal:
    goal_id: str = "abc123"
    goal: str = "Test goal"
    status: str = "active"
    current_checkpoint: int = 1
    total_checkpoints: int = 3
    context_summary: str = "Some context"
    llm_calls_used: int = 5
    updated_at: str = "2026-01-01"


def _mock_goal_manager() -> AsyncMock:
    mgr = AsyncMock()
    mgr.create_goal.return_value = FakeGoal()
    mgr.decompose.return_value = [
        FakeCheckpoint(order=1, title="Research", success_criteria="summary written"),
        FakeCheckpoint(order=2, title="Execute", success_criteria="done"),
        FakeCheckpoint(order=3, title="Verify", success_criteria="confirmed"),
    ]
    return mgr


# ---------------------------------------------------------------------------
# Interface compliance
# ---------------------------------------------------------------------------


class TestGoalToolInterface:
    def test_create_tool_interface(self) -> None:
        t = GoalCreateTool()
        assert t.name == "goal_create"
        assert isinstance(t.description, str) and len(t.description) > 10
        assert t.input_schema["type"] == "object"
        assert "goal" in t.input_schema["properties"]
        assert t.permission_level == PermissionLevel.MODERATE

    def test_status_tool_interface(self) -> None:
        t = GoalStatusTool()
        assert t.name == "goal_status"
        assert t.input_schema["type"] == "object"
        assert t.permission_level == PermissionLevel.SAFE

    def test_manage_tool_interface(self) -> None:
        t = GoalManageTool()
        assert t.name == "goal_manage"
        assert t.input_schema["type"] == "object"
        assert "action" in t.input_schema["properties"]
        assert t.permission_level == PermissionLevel.MODERATE

    def test_llm_schema_format(self) -> None:
        for tool_cls in (GoalCreateTool, GoalStatusTool, GoalManageTool):
            tool = tool_cls()
            schema = tool.to_llm_schema()
            assert schema["type"] == "function"
            assert "function" in schema
            assert "name" in schema["function"]
            assert "parameters" in schema["function"]


# ---------------------------------------------------------------------------
# GoalCreateTool execution
# ---------------------------------------------------------------------------


class TestGoalCreateTool:
    @pytest.mark.asyncio
    async def test_not_initialized(self) -> None:
        t = GoalCreateTool()
        result = await t.execute({"goal": "Test"})
        assert not result.success
        assert "not initialized" in result.error.lower()

    @pytest.mark.asyncio
    async def test_empty_goal(self) -> None:
        t = GoalCreateTool()
        t._goal_manager = _mock_goal_manager()
        result = await t.execute({"goal": "  "})
        assert not result.success
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_create_success(self) -> None:
        t = GoalCreateTool()
        t._goal_manager = _mock_goal_manager()
        result = await t.execute({"goal": "Get a job at X"})
        assert result.success
        assert result.data["goal_id"] == "abc123"
        assert result.data["total_checkpoints"] == 3
        assert len(result.data["checkpoints"]) == 3

    @pytest.mark.asyncio
    async def test_create_decompose_fails(self) -> None:
        t = GoalCreateTool()
        mgr = _mock_goal_manager()
        mgr.decompose.return_value = []
        t._goal_manager = mgr
        result = await t.execute({"goal": "Bad goal"})
        assert not result.success
        assert "decompose" in result.error.lower() or "checkpoint" in result.error.lower()


# ---------------------------------------------------------------------------
# GoalStatusTool execution
# ---------------------------------------------------------------------------


class TestGoalStatusTool:
    @pytest.mark.asyncio
    async def test_not_initialized(self) -> None:
        t = GoalStatusTool()
        result = await t.execute({})
        assert not result.success

    @pytest.mark.asyncio
    async def test_list_goals(self) -> None:
        t = GoalStatusTool()
        mgr = AsyncMock()
        mgr.list_goals.return_value = [FakeGoal(), FakeGoal(goal_id="def456")]
        t._goal_manager = mgr
        result = await t.execute({"action": "list"})
        assert result.success
        assert result.data["total"] == 2

    @pytest.mark.asyncio
    async def test_detail_goal(self) -> None:
        t = GoalStatusTool()
        mgr = AsyncMock()
        mgr.get_goal.return_value = FakeGoal()
        mgr.get_checkpoints.return_value = [
            FakeCheckpoint(order=1, title="Research", success_criteria="done"),
        ]
        t._goal_manager = mgr
        result = await t.execute({"action": "detail", "goal_id": "abc123"})
        assert result.success
        assert result.data["goal_id"] == "abc123"
        assert len(result.data["checkpoints"]) == 1

    @pytest.mark.asyncio
    async def test_detail_not_found(self) -> None:
        t = GoalStatusTool()
        mgr = AsyncMock()
        mgr.get_goal.return_value = None
        t._goal_manager = mgr
        result = await t.execute({"action": "detail", "goal_id": "nope"})
        assert not result.success


# ---------------------------------------------------------------------------
# GoalManageTool execution
# ---------------------------------------------------------------------------


class TestGoalManageTool:
    @pytest.mark.asyncio
    async def test_not_initialized(self) -> None:
        t = GoalManageTool()
        result = await t.execute({"goal_id": "x", "action": "pause"})
        assert not result.success

    @pytest.mark.asyncio
    async def test_missing_goal_id(self) -> None:
        t = GoalManageTool()
        t._goal_manager = AsyncMock()
        result = await t.execute({"action": "pause"})
        assert not result.success

    @pytest.mark.asyncio
    async def test_missing_action(self) -> None:
        t = GoalManageTool()
        t._goal_manager = AsyncMock()
        result = await t.execute({"goal_id": "x"})
        assert not result.success

    @pytest.mark.asyncio
    async def test_pause(self) -> None:
        t = GoalManageTool()
        mgr = AsyncMock()
        mgr.pause_goal.return_value = True
        t._goal_manager = mgr
        result = await t.execute({"goal_id": "x", "action": "pause"})
        assert result.success
        assert result.data["action"] == "paused"

    @pytest.mark.asyncio
    async def test_resume(self) -> None:
        t = GoalManageTool()
        mgr = AsyncMock()
        mgr.resume_goal.return_value = True
        t._goal_manager = mgr
        result = await t.execute({"goal_id": "x", "action": "resume"})
        assert result.success
        assert result.data["action"] == "resumed"

    @pytest.mark.asyncio
    async def test_cancel(self) -> None:
        t = GoalManageTool()
        mgr = AsyncMock()
        mgr.cancel_goal.return_value = True
        t._goal_manager = mgr
        result = await t.execute({"goal_id": "x", "action": "cancel"})
        assert result.success

    @pytest.mark.asyncio
    async def test_revise_requires_reason(self) -> None:
        t = GoalManageTool()
        t._goal_manager = AsyncMock()
        result = await t.execute({"goal_id": "x", "action": "revise"})
        assert not result.success
        assert "reason" in result.error.lower()

    @pytest.mark.asyncio
    async def test_revise_success(self) -> None:
        t = GoalManageTool()
        mgr = AsyncMock()
        mgr.get_goal.return_value = FakeGoal(total_checkpoints=3)
        mgr.revise_plan.return_value = [
            FakeCheckpoint(order=2, title="New step", success_criteria="done"),
        ]
        t._goal_manager = mgr
        result = await t.execute({"goal_id": "x", "action": "revise", "reason": "new info"})
        assert result.success
        assert result.data["action"] == "revised"

    @pytest.mark.asyncio
    async def test_unknown_action(self) -> None:
        t = GoalManageTool()
        t._goal_manager = AsyncMock()
        result = await t.execute({"goal_id": "x", "action": "explode"})
        assert not result.success
        assert "unknown" in result.error.lower()
