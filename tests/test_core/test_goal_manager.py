"""GoalManager tests — CRUD, decomposition, checkpoints, context, evaluation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.config import GoalsConfig
from core.database import Database
from core.goal_manager import EvaluationResult, Goal, GoalManager


@dataclass
class FakeLLMResponse:
    """Minimal stand-in for the router's response object."""

    content: str


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def config() -> GoalsConfig:
    return GoalsConfig()


@pytest.fixture
def router() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def gm(db: Database, router: AsyncMock, config: GoalsConfig) -> GoalManager:
    return GoalManager(db=db, router=router, config=config)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_CHECKPOINTS_JSON = json.dumps(
    [
        {
            "order": 1,
            "title": "Research company",
            "description": "Look up company info",
            "success_criteria": "Summary written",
        },
        {
            "order": 2,
            "title": "Find positions",
            "description": "Search job boards",
            "success_criteria": "3+ positions listed",
        },
        {
            "order": 3,
            "title": "Apply",
            "description": "Submit application",
            "success_criteria": "Confirmation received",
        },
    ]
)


# ---------------------------------------------------------------------------
# Goal CRUD
# ---------------------------------------------------------------------------


class TestGoalCRUD:
    @pytest.mark.asyncio
    async def test_create_goal(self, gm: GoalManager) -> None:
        goal = await gm.create_goal("Get a job at X", session_id="s1")
        assert goal.goal == "Get a job at X"
        assert goal.session_id == "s1"
        assert goal.status == "planning"
        assert len(goal.goal_id) == 12

    @pytest.mark.asyncio
    async def test_get_goal(self, gm: GoalManager) -> None:
        created = await gm.create_goal("Test goal")
        fetched = await gm.get_goal(created.goal_id)
        assert fetched is not None
        assert fetched.goal == "Test goal"
        assert fetched.goal_id == created.goal_id

    @pytest.mark.asyncio
    async def test_get_goal_not_found(self, gm: GoalManager) -> None:
        assert await gm.get_goal("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_active_goal(self, gm: GoalManager, router: AsyncMock) -> None:
        router.complete.return_value = FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON)
        goal = await gm.create_goal("Active goal", session_id="sess1")
        await gm.decompose(goal)  # sets status to "active"
        active = await gm.get_active_goal("sess1")
        assert active is not None
        assert active.goal_id == goal.goal_id

    @pytest.mark.asyncio
    async def test_get_active_goal_none(self, gm: GoalManager) -> None:
        assert await gm.get_active_goal("no-session") is None

    @pytest.mark.asyncio
    async def test_list_goals(self, gm: GoalManager) -> None:
        await gm.create_goal("Goal A")
        await gm.create_goal("Goal B")
        goals = await gm.list_goals()
        assert len(goals) == 2

    @pytest.mark.asyncio
    async def test_list_goals_filter_status(self, gm: GoalManager) -> None:
        await gm.create_goal("Planning goal")
        goals = await gm.list_goals(status="planning")
        assert len(goals) == 1
        assert await gm.list_goals(status="completed") == []

    @pytest.mark.asyncio
    async def test_cancel_goal(self, gm: GoalManager) -> None:
        goal = await gm.create_goal("Cancel me")
        ok = await gm.cancel_goal(goal.goal_id)
        assert ok
        cancelled = await gm.get_goal(goal.goal_id)
        assert cancelled is not None
        assert cancelled.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_goal_not_found(self, gm: GoalManager) -> None:
        assert not await gm.cancel_goal("nonexistent")

    @pytest.mark.asyncio
    async def test_pause_resume(self, gm: GoalManager, router: AsyncMock) -> None:
        router.complete.return_value = FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON)
        goal = await gm.create_goal("Pause me")
        await gm.decompose(goal)  # active

        assert await gm.pause_goal(goal.goal_id)
        paused = await gm.get_goal(goal.goal_id)
        assert paused is not None
        assert paused.status == "paused"

        assert await gm.resume_goal(goal.goal_id)
        resumed = await gm.get_goal(goal.goal_id)
        assert resumed is not None
        assert resumed.status == "active"

    @pytest.mark.asyncio
    async def test_pause_requires_active(self, gm: GoalManager) -> None:
        goal = await gm.create_goal("Still planning")
        assert not await gm.pause_goal(goal.goal_id)  # status is "planning"

    @pytest.mark.asyncio
    async def test_resume_requires_paused(self, gm: GoalManager, router: AsyncMock) -> None:
        router.complete.return_value = FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON)
        goal = await gm.create_goal("Active goal")
        await gm.decompose(goal)
        assert not await gm.resume_goal(goal.goal_id)  # status is "active"


# ---------------------------------------------------------------------------
# Decomposition
# ---------------------------------------------------------------------------


class TestDecomposition:
    @pytest.mark.asyncio
    async def test_decompose_success(self, gm: GoalManager, router: AsyncMock) -> None:
        router.complete.return_value = FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON)
        goal = await gm.create_goal("Get a job")
        cps = await gm.decompose(goal)

        assert len(cps) == 3
        assert cps[0].title == "Research company"
        assert cps[2].title == "Apply"
        assert goal.status == "active"
        assert goal.total_checkpoints == 3
        assert goal.current_checkpoint == 1

    @pytest.mark.asyncio
    async def test_decompose_empty_response(self, gm: GoalManager, router: AsyncMock) -> None:
        router.complete.return_value = FakeLLMResponse(content="[]")
        goal = await gm.create_goal("Bad goal")
        cps = await gm.decompose(goal)
        assert cps == []

    @pytest.mark.asyncio
    async def test_decompose_invalid_json(self, gm: GoalManager, router: AsyncMock) -> None:
        router.complete.return_value = FakeLLMResponse(content="not json at all")
        goal = await gm.create_goal("Invalid")
        cps = await gm.decompose(goal)
        assert cps == []

    @pytest.mark.asyncio
    async def test_decompose_markdown_wrapped(self, gm: GoalManager, router: AsyncMock) -> None:
        wrapped = f"```json\n{_SAMPLE_CHECKPOINTS_JSON}\n```"
        router.complete.return_value = FakeLLMResponse(content=wrapped)
        goal = await gm.create_goal("Wrapped")
        cps = await gm.decompose(goal)
        assert len(cps) == 3

    @pytest.mark.asyncio
    async def test_decompose_caps_at_max(self, gm: GoalManager, router: AsyncMock) -> None:
        many = [
            {"order": i, "title": f"CP {i}", "description": "d", "success_criteria": "s"}
            for i in range(1, 30)
        ]
        router.complete.return_value = FakeLLMResponse(content=json.dumps(many))
        goal = await gm.create_goal("Big goal")
        cps = await gm.decompose(goal)
        assert len(cps) == 20  # max_checkpoints default

    @pytest.mark.asyncio
    async def test_decompose_increments_llm_calls(self, gm: GoalManager, router: AsyncMock) -> None:
        router.complete.return_value = FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON)
        goal = await gm.create_goal("Track calls")
        assert goal.llm_calls_used == 0
        await gm.decompose(goal)
        assert goal.llm_calls_used == 1


# ---------------------------------------------------------------------------
# Checkpoint tracking
# ---------------------------------------------------------------------------


class TestCheckpoints:
    @pytest.mark.asyncio
    async def test_get_checkpoints(self, gm: GoalManager, router: AsyncMock) -> None:
        router.complete.return_value = FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON)
        goal = await gm.create_goal("CP test")
        await gm.decompose(goal)
        cps = await gm.get_checkpoints(goal.goal_id)
        assert len(cps) == 3
        assert all(c.status == "pending" for c in cps)

    @pytest.mark.asyncio
    async def test_get_next_checkpoint(self, gm: GoalManager, router: AsyncMock) -> None:
        router.complete.return_value = FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON)
        goal = await gm.create_goal("Next CP")
        await gm.decompose(goal)
        nxt = await gm.get_next_checkpoint(goal.goal_id)
        assert nxt is not None
        assert nxt.order == 1

    @pytest.mark.asyncio
    async def test_mark_checkpoint_active(self, gm: GoalManager, router: AsyncMock) -> None:
        router.complete.return_value = FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON)
        goal = await gm.create_goal("Active CP")
        await gm.decompose(goal)
        await gm.mark_checkpoint_active(goal.goal_id, 1)
        cps = await gm.get_checkpoints(goal.goal_id)
        assert cps[0].status == "active"
        assert cps[0].attempts == 1

    @pytest.mark.asyncio
    async def test_mark_checkpoint_complete_advances(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        router.complete.return_value = FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON)
        goal = await gm.create_goal("Advance CP")
        await gm.decompose(goal)
        await gm.mark_checkpoint_complete(goal.goal_id, 1, "Done researching")
        cps = await gm.get_checkpoints(goal.goal_id)
        assert cps[0].status == "completed"
        assert cps[0].result_summary == "Done researching"

        updated = await gm.get_goal(goal.goal_id)
        assert updated is not None
        assert updated.current_checkpoint == 2

    @pytest.mark.asyncio
    async def test_all_checkpoints_complete_finishes_goal(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        router.complete.return_value = FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON)
        goal = await gm.create_goal("Finish all")
        await gm.decompose(goal)

        for i in range(1, 4):
            await gm.mark_checkpoint_complete(goal.goal_id, i, f"Done {i}")

        final = await gm.get_goal(goal.goal_id)
        assert final is not None
        assert final.status == "completed"
        assert final.completed_at is not None

    @pytest.mark.asyncio
    async def test_mark_checkpoint_failed_retries(self, gm: GoalManager, router: AsyncMock) -> None:
        router.complete.return_value = FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON)
        goal = await gm.create_goal("Fail retry")
        await gm.decompose(goal)
        await gm.mark_checkpoint_failed(goal.goal_id, 1, "Something broke")
        # Should reset to pending for retry (attempts < max)
        cps = await gm.get_checkpoints(goal.goal_id)
        assert cps[0].status == "pending"

    @pytest.mark.asyncio
    async def test_mark_checkpoint_failed_pauses_goal(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        config = GoalsConfig(max_checkpoint_attempts=1)
        gm_strict = GoalManager(db=gm._db, router=router, config=config)
        router.complete.return_value = FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON)

        goal = await gm_strict.create_goal("Fail pause")
        await gm_strict.decompose(goal)
        # Activate to get attempts=1
        await gm_strict.mark_checkpoint_active(goal.goal_id, 1)
        await gm_strict.mark_checkpoint_failed(goal.goal_id, 1, "Too many failures")

        goal_after = await gm_strict.get_goal(goal.goal_id)
        assert goal_after is not None
        assert goal_after.status == "paused"


# ---------------------------------------------------------------------------
# Context management
# ---------------------------------------------------------------------------


class TestContext:
    @pytest.mark.asyncio
    async def test_summarize_context(self, gm: GoalManager, router: AsyncMock) -> None:
        router.complete.return_value = FakeLLMResponse(content="Summary of progress so far.")
        goal = await gm.create_goal("Summarize me")
        messages = [
            {"role": "user", "content": "Research the company"},
            {"role": "assistant", "content": "I found that..."},
        ]
        summary = await gm.summarize_context(goal, messages)
        assert summary == "Summary of progress so far."
        assert goal.context_summary == summary

    @pytest.mark.asyncio
    async def test_summarize_empty_messages(self, gm: GoalManager) -> None:
        goal = await gm.create_goal("No messages")
        goal.context_summary = "existing"
        summary = await gm.summarize_context(goal, [])
        assert summary == "existing"

    @pytest.mark.asyncio
    async def test_build_goal_context_xml(self, gm: GoalManager, router: AsyncMock) -> None:
        router.complete.return_value = FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON)
        goal = await gm.create_goal("XML test")
        await gm.decompose(goal)
        goal.context_summary = "Did some research"
        await gm._persist_goal(goal)

        xml = await gm.build_goal_context(goal.goal_id)
        assert "<active_goal>" in xml
        assert "</active_goal>" in xml
        assert goal.goal_id in xml
        assert "XML test" in xml
        assert "<remaining_checkpoints>" in xml

    @pytest.mark.asyncio
    async def test_build_goal_context_not_found(self, gm: GoalManager) -> None:
        xml = await gm.build_goal_context("nonexistent")
        assert xml == ""


# ---------------------------------------------------------------------------
# Self-evaluation
# ---------------------------------------------------------------------------


class TestEvaluation:
    @pytest.mark.asyncio
    async def test_evaluate_on_track(self, gm: GoalManager, router: AsyncMock) -> None:
        eval_response = json.dumps(
            {"on_track": True, "revision_needed": False, "reason": "Going well"}
        )
        # First call for decompose, second for evaluate
        router.complete.side_effect = [
            FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON),
            FakeLLMResponse(content=eval_response),
        ]
        goal = await gm.create_goal("Evaluate me")
        await gm.decompose(goal)
        result = await gm.evaluate_progress(goal)
        assert isinstance(result, EvaluationResult)
        assert result.on_track is True
        assert result.revision_needed is False

    @pytest.mark.asyncio
    async def test_evaluate_invalid_json(self, gm: GoalManager, router: AsyncMock) -> None:
        router.complete.side_effect = [
            FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON),
            FakeLLMResponse(content="not json"),
        ]
        goal = await gm.create_goal("Bad eval")
        await gm.decompose(goal)
        result = await gm.evaluate_progress(goal)
        assert result.on_track is True  # safe fallback
        assert result.revision_needed is False


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


class TestBudget:
    def test_check_budget_ok(self, gm: GoalManager) -> None:
        goal = Goal(
            goal_id="test",
            session_id=None,
            goal="test",
            llm_calls_used=10,
            created_at="",
            updated_at="",
        )
        ok, msg = gm.check_budget(goal)
        assert ok
        assert msg == ""

    def test_check_budget_exceeded(self, gm: GoalManager) -> None:
        goal = Goal(
            goal_id="test",
            session_id=None,
            goal="test",
            llm_calls_used=200,
            created_at="",
            updated_at="",
        )
        ok, msg = gm.check_budget(goal)
        assert not ok
        assert "limit" in msg.lower()


# ---------------------------------------------------------------------------
# Revision
# ---------------------------------------------------------------------------


class TestRevision:
    @pytest.mark.asyncio
    async def test_revise_plan(self, gm: GoalManager, router: AsyncMock) -> None:
        revised_json = json.dumps(
            [
                {
                    "order": 2,
                    "title": "New step 2",
                    "description": "Revised",
                    "success_criteria": "Done",
                },
                {
                    "order": 3,
                    "title": "New step 3",
                    "description": "Revised",
                    "success_criteria": "Done",
                },
            ]
        )
        router.complete.side_effect = [
            FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON),
            FakeLLMResponse(content=revised_json),
        ]
        goal = await gm.create_goal("Revise me")
        await gm.decompose(goal)

        # Complete first checkpoint
        await gm.mark_checkpoint_complete(goal.goal_id, 1, "Done")
        goal = await gm.get_goal(goal.goal_id)
        assert goal is not None

        new_cps = await gm.revise_plan(goal, "New information found")
        assert len(new_cps) == 2
        assert new_cps[0].title == "New step 2"
