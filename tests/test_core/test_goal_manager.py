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
    async def test_resume_requires_paused(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
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
    async def test_decompose_empty_response(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        router.complete.return_value = FakeLLMResponse(content="[]")
        goal = await gm.create_goal("Bad goal")
        cps = await gm.decompose(goal)
        assert cps == []

    @pytest.mark.asyncio
    async def test_decompose_invalid_json(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        router.complete.return_value = FakeLLMResponse(content="not json at all")
        goal = await gm.create_goal("Invalid")
        cps = await gm.decompose(goal)
        assert cps == []

    @pytest.mark.asyncio
    async def test_decompose_markdown_wrapped(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        wrapped = f"```json\n{_SAMPLE_CHECKPOINTS_JSON}\n```"
        router.complete.return_value = FakeLLMResponse(content=wrapped)
        goal = await gm.create_goal("Wrapped")
        cps = await gm.decompose(goal)
        assert len(cps) == 3

    @pytest.mark.asyncio
    async def test_decompose_caps_at_max(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        many = [
            {
                "order": i,
                "title": f"CP {i}",
                "description": "d",
                "success_criteria": "s",
            }
            for i in range(1, 30)
        ]
        router.complete.return_value = FakeLLMResponse(content=json.dumps(many))
        goal = await gm.create_goal("Big goal")
        cps = await gm.decompose(goal)
        assert len(cps) == 20  # max_checkpoints default

    @pytest.mark.asyncio
    async def test_decompose_increments_llm_calls(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
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
    async def test_get_next_checkpoint(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        router.complete.return_value = FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON)
        goal = await gm.create_goal("Next CP")
        await gm.decompose(goal)
        nxt = await gm.get_next_checkpoint(goal.goal_id)
        assert nxt is not None
        assert nxt.order == 1

    @pytest.mark.asyncio
    async def test_mark_checkpoint_active(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
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
    async def test_mark_checkpoint_failed_retries(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
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
        router.complete.return_value = FakeLLMResponse(
            content="Summary of progress so far."
        )
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
    async def test_build_goal_context_xml(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
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
    async def test_evaluate_invalid_json(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
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


# ---------------------------------------------------------------------------
# UNIQUE(goal_id, checkpoint_order) regression — the LLM cannot be trusted
# to emit collision-free order numbers. Production hit "UNIQUE constraint
# failed: goal_checkpoints.goal_id, goal_checkpoints.checkpoint_order" on
# 2026-05-17; these tests pin the Python-side renumbering that prevents it.
# ---------------------------------------------------------------------------


class TestCheckpointOrderRenumber:
    @pytest.mark.asyncio
    async def test_decompose_with_duplicate_order_does_not_violate_unique(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        """LLM emits two checkpoints both claiming order=1. Pre-fix this
        crashed on INSERT. Post-fix the parser renumbers and both land."""
        bad_json = json.dumps(
            [
                {"order": 1, "title": "A", "description": "d", "success_criteria": "s"},
                {"order": 1, "title": "B", "description": "d", "success_criteria": "s"},
                {"order": 1, "title": "C", "description": "d", "success_criteria": "s"},
            ]
        )
        router.complete.return_value = FakeLLMResponse(content=bad_json)
        goal = await gm.create_goal("Dup orders")
        cps = await gm.decompose(goal)
        assert [c.order for c in cps] == [1, 2, 3]
        assert [c.title for c in cps] == ["A", "B", "C"]

    @pytest.mark.asyncio
    async def test_decompose_ignores_llm_order_field(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        """LLM emits weird/out-of-band order numbers (7, 99, 0). The
        parser ignores them and renumbers 1..N. This is the contract:
        Python owns ordering, the LLM owns content."""
        weird_json = json.dumps(
            [
                {
                    "order": 7,
                    "title": "First",
                    "description": "d",
                    "success_criteria": "s",
                },
                {
                    "order": 99,
                    "title": "Second",
                    "description": "d",
                    "success_criteria": "s",
                },
                {
                    "order": 0,
                    "title": "Third",
                    "description": "d",
                    "success_criteria": "s",
                },
            ]
        )
        router.complete.return_value = FakeLLMResponse(content=weird_json)
        goal = await gm.create_goal("Weird orders")
        cps = await gm.decompose(goal)
        assert [c.order for c in cps] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_revise_starts_after_max_completed_order(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        """After completing checkpoints 1 and 2, a revision must
        produce new checkpoints starting at order=3 — even if the LLM
        emits them with orders 1 and 2 (overlapping the completed
        rows that revise_plan does NOT delete). Pre-fix this was the
        exact bug surfaced in production."""
        initial = json.dumps(
            [
                {
                    "order": 1,
                    "title": "Step 1",
                    "description": "d",
                    "success_criteria": "s",
                },
                {
                    "order": 2,
                    "title": "Step 2",
                    "description": "d",
                    "success_criteria": "s",
                },
                {
                    "order": 3,
                    "title": "Step 3",
                    "description": "d",
                    "success_criteria": "s",
                },
            ]
        )
        # Adversarial: LLM emits orders 1 and 2, which would collide
        # with the completed rows 1 and 2 if we trusted its numbering.
        revised = json.dumps(
            [
                {
                    "order": 1,
                    "title": "New A",
                    "description": "d",
                    "success_criteria": "s",
                },
                {
                    "order": 2,
                    "title": "New B",
                    "description": "d",
                    "success_criteria": "s",
                },
            ]
        )
        router.complete.side_effect = [
            FakeLLMResponse(content=initial),
            FakeLLMResponse(content=revised),
        ]
        goal = await gm.create_goal("Revise w/ collision")
        await gm.decompose(goal)
        await gm.mark_checkpoint_complete(goal.goal_id, 1, "Done")
        await gm.mark_checkpoint_complete(goal.goal_id, 2, "Done")
        goal = await gm.get_goal(goal.goal_id)
        assert goal is not None

        new_cps = await gm.revise_plan(goal, "rethink")
        assert [c.order for c in new_cps] == [3, 4], (
            f"new checkpoints must start after max completed order; "
            f"got {[c.order for c in new_cps]}"
        )

        # End-state check: all checkpoints in DB have distinct orders.
        all_cps = await gm.get_checkpoints(goal.goal_id)
        orders = [c.order for c in all_cps]
        assert len(orders) == len(set(orders)), f"duplicate orders in DB: {orders}"


class TestReviseCollisionRegressions:
    """2026-06-01 production crash: revise_plan hit UNIQUE constraint
    failure when a checkpoint with status='active' was holding the
    order slot revise wanted to use. Also: mark_checkpoint_complete
    auto-flipped status='completed' when there were no pending rows
    left, even though only 5 of 15 total were actually done."""

    @pytest.mark.asyncio
    async def test_revise_skips_active_checkpoint_order(
        self,
        gm: GoalManager,
        router: AsyncMock,
        db: Database,
    ) -> None:
        # 3 checkpoints planned; complete 1, manually flip 2 to 'active'
        # (simulating an in-flight cycle), 3 stays pending.
        initial = json.dumps(
            [
                {
                    "order": 1,
                    "title": "Step 1",
                    "description": "d",
                    "success_criteria": "s",
                },
                {
                    "order": 2,
                    "title": "Step 2",
                    "description": "d",
                    "success_criteria": "s",
                },
                {
                    "order": 3,
                    "title": "Step 3",
                    "description": "d",
                    "success_criteria": "s",
                },
            ]
        )
        revised = json.dumps(
            [
                {
                    "order": 1,
                    "title": "New A",
                    "description": "d",
                    "success_criteria": "s",
                },
            ]
        )
        router.complete.side_effect = [
            FakeLLMResponse(content=initial),
            FakeLLMResponse(content=revised),
        ]
        goal = await gm.create_goal("active-row revise")
        await gm.decompose(goal)
        await gm.mark_checkpoint_complete(goal.goal_id, 1, "Done")
        # Flip order 2 to active (in-flight on the agent's loop).
        await db.execute(
            "UPDATE goal_checkpoints SET status = 'active' "
            "WHERE goal_id = ? AND checkpoint_order = ?",
            (goal.goal_id, 2),
        )
        goal = await gm.get_goal(goal.goal_id)
        assert goal is not None

        # revise_plan must NOT crash with UNIQUE constraint failure.
        new_cps = await gm.revise_plan(goal, "rethink")
        # New checkpoint must land AFTER the surviving active row (2),
        # not collide with it. Order 3 was pending → deleted. New = 3.
        assert [c.order for c in new_cps] == [3], (
            f"new checkpoint must start after max(completed+active); "
            f"got {[c.order for c in new_cps]}"
        )
        all_cps = await gm.get_checkpoints(goal.goal_id)
        orders = [c.order for c in all_cps]
        assert len(orders) == len(set(orders)), f"duplicate orders: {orders}"

    @pytest.mark.asyncio
    async def test_mark_complete_does_not_auto_finish_orphaned_goal(
        self,
        gm: GoalManager,
        router: AsyncMock,
        db: Database,
    ) -> None:
        """If pending rows were lost (e.g. a prior revise_plan crashed
        after DELETE but before INSERT), the next mark_checkpoint_complete
        sees no pending row and used to flip status='completed' even
        though only N of M total were actually done. Now it stays
        active and logs a warning."""
        initial = json.dumps(
            [
                {
                    "order": 1,
                    "title": "Step 1",
                    "description": "d",
                    "success_criteria": "s",
                },
                {
                    "order": 2,
                    "title": "Step 2",
                    "description": "d",
                    "success_criteria": "s",
                },
                {
                    "order": 3,
                    "title": "Step 3",
                    "description": "d",
                    "success_criteria": "s",
                },
            ]
        )
        router.complete.return_value = FakeLLMResponse(content=initial)
        goal = await gm.create_goal("orphan-detection")
        await gm.decompose(goal)
        # Simulate the production failure: pending rows 2 + 3 were
        # deleted by a crashed revise_plan, leaving only completed-1
        # and the goal claiming total_checkpoints=3.
        await db.execute(
            "DELETE FROM goal_checkpoints WHERE goal_id = ? " "AND status = 'pending'",
            (goal.goal_id,),
        )

        await gm.mark_checkpoint_complete(goal.goal_id, 1, "Done")
        goal = await gm.get_goal(goal.goal_id)
        assert goal is not None
        # Must NOT be 'completed' — only 1 of 3 actually done.
        assert (
            goal.status != "completed"
        ), f"goal wrongly auto-completed at 1/3; status={goal.status}"
        assert goal.completed_at is None


# ---------------------------------------------------------------------------
# Completion hooks — autonomous mind subscribes here so finishing a goal
# triggers an immediate dream-cycle wakeup instead of waiting for the
# next scheduled tick. These tests pin the contract: fires once on
# goal-completion, swallows hook failures, supports multiple subscribers.
# ---------------------------------------------------------------------------


class TestCompletionHooks:
    @pytest.mark.asyncio
    async def test_hook_fires_on_goal_completion(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        router.complete.return_value = FakeLLMResponse(
            content=json.dumps(
                [
                    {
                        "order": 1,
                        "title": "Step 1",
                        "description": "d",
                        "success_criteria": "s",
                    },
                ]
            )
        )
        captured: list[str] = []

        async def hook(goal_id: str) -> None:
            captured.append(goal_id)

        gm.add_completion_hook(hook)
        goal = await gm.create_goal("One-step goal")
        await gm.decompose(goal)

        # Completing the only checkpoint flips the goal to 'completed'.
        await gm.mark_checkpoint_complete(goal.goal_id, 1, "Done")

        assert captured == [
            goal.goal_id
        ], f"hook should fire exactly once with the goal_id; got {captured}"

    @pytest.mark.asyncio
    async def test_hook_does_not_fire_on_intermediate_checkpoint(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        """Hook must only fire when the GOAL completes, not on every
        checkpoint. Otherwise the mind would wake up between every step."""
        router.complete.return_value = FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON)
        captured: list[str] = []

        async def hook(goal_id: str) -> None:
            captured.append(goal_id)

        gm.add_completion_hook(hook)
        goal = await gm.create_goal("Multi-step")
        await gm.decompose(goal)  # 3 checkpoints

        await gm.mark_checkpoint_complete(goal.goal_id, 1, "Done")
        await gm.mark_checkpoint_complete(goal.goal_id, 2, "Done")
        assert captured == [], "hook must not fire on intermediate checkpoints"

        await gm.mark_checkpoint_complete(goal.goal_id, 3, "Done")
        assert captured == [goal.goal_id], "hook must fire on the final checkpoint"

    @pytest.mark.asyncio
    async def test_hook_failure_does_not_break_completion(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        """One bad subscriber must not stop the goal from completing."""
        router.complete.return_value = FakeLLMResponse(
            content=json.dumps(
                [
                    {
                        "order": 1,
                        "title": "Step 1",
                        "description": "d",
                        "success_criteria": "s",
                    },
                ]
            )
        )

        async def broken_hook(goal_id: str) -> None:
            raise RuntimeError("hook is on fire")

        gm.add_completion_hook(broken_hook)
        goal = await gm.create_goal("With broken hook")
        await gm.decompose(goal)

        # Must not raise.
        await gm.mark_checkpoint_complete(goal.goal_id, 1, "Done")

        # Goal still ends up completed in the DB.
        refreshed = await gm.get_goal(goal.goal_id)
        assert refreshed is not None
        assert refreshed.status == "completed"

    @pytest.mark.asyncio
    async def test_multiple_hooks_all_fire(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        """Mind + analytics + anything else can subscribe in parallel."""
        router.complete.return_value = FakeLLMResponse(
            content=json.dumps(
                [
                    {
                        "order": 1,
                        "title": "S",
                        "description": "d",
                        "success_criteria": "s",
                    }
                ]
            )
        )
        a: list[str] = []
        b: list[str] = []

        async def hook_a(goal_id: str) -> None:
            a.append(goal_id)

        async def hook_b(goal_id: str) -> None:
            b.append(goal_id)

        gm.add_completion_hook(hook_a)
        gm.add_completion_hook(hook_b)
        goal = await gm.create_goal("Two subscribers")
        await gm.decompose(goal)
        await gm.mark_checkpoint_complete(goal.goal_id, 1, "Done")

        assert a == [goal.goal_id]
        assert b == [goal.goal_id]


# ---------------------------------------------------------------------------
# Company scoping (Tier 1 #1, 2026-06-18)
# ---------------------------------------------------------------------------


class TestCompanyScoping:
    """Every read defaults to the contextvar company; writes stamp it at
    INSERT. Operators in company A must not see / modify company B's
    goals by accident. Long-running goals survive context flips via the
    ALL_COMPANIES bypass on the internal mark_checkpoint_* path."""

    @pytest.mark.asyncio
    async def test_create_stamps_current_company(self, gm: GoalManager) -> None:
        from core.company import (
            DEFAULT_COMPANY_ID,
            reset_current_company,
            set_current_company,
        )

        token = set_current_company("acme-inc")
        try:
            g = await gm.create_goal("Acme goal", session_id="s")
            assert g.company_id == "acme-inc"
        finally:
            reset_current_company(token)

        # After reset, default-context get refuses to see acme's row.
        assert await gm.get_goal(g.goal_id) is None
        assert await gm.list_goals() == []
        # Default-context creates land in DEFAULT_COMPANY_ID.
        self_goal = await gm.create_goal("Self goal", session_id="s")
        assert self_goal.company_id == DEFAULT_COMPANY_ID

    @pytest.mark.asyncio
    async def test_list_filters_by_active_company(self, gm: GoalManager) -> None:
        from core.company import reset_current_company, set_current_company

        a = set_current_company("acme-inc")
        try:
            await gm.create_goal("Acme A")
            await gm.create_goal("Acme B")
        finally:
            reset_current_company(a)
        b = set_current_company("beta-co")
        try:
            await gm.create_goal("Beta only")
        finally:
            reset_current_company(b)

        a2 = set_current_company("acme-inc")
        try:
            seen = await gm.list_goals()
            assert {g.goal for g in seen} == {"Acme A", "Acme B"}
        finally:
            reset_current_company(a2)

        b2 = set_current_company("beta-co")
        try:
            seen = await gm.list_goals()
            assert {g.goal for g in seen} == {"Beta only"}
        finally:
            reset_current_company(b2)

    @pytest.mark.asyncio
    async def test_all_companies_sentinel_bypasses_filter(
        self, gm: GoalManager
    ) -> None:
        from core.company import (
            ALL_COMPANIES,
            reset_current_company,
            set_current_company,
        )

        a = set_current_company("acme-inc")
        try:
            ag = await gm.create_goal("A")
        finally:
            reset_current_company(a)
        b = set_current_company("beta-co")
        try:
            await gm.create_goal("B")
        finally:
            reset_current_company(b)

        assert await gm.list_goals() == []
        seen = await gm.list_goals(company_id=ALL_COMPANIES)
        assert {g.goal for g in seen} == {"A", "B"}
        assert (await gm.get_goal(ag.goal_id, company_id=ALL_COMPANIES)).goal == "A"

    @pytest.mark.asyncio
    async def test_cross_company_cancel_pause_refused_softly(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        """cancel/pause/resume go through _update_status → get_goal which
        now filters by current company. Cross-tenant mutations return
        False without touching the other tenant's row."""
        from core.company import (
            ALL_COMPANIES,
            reset_current_company,
            set_current_company,
        )

        router.complete.return_value = FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON)

        a = set_current_company("acme-inc")
        try:
            g = await gm.create_goal("Acme goal")
            await gm.decompose(g)  # status -> active
        finally:
            reset_current_company(a)

        # Default context — can't cancel acme's goal.
        assert await gm.cancel_goal(g.goal_id) is False
        assert await gm.pause_goal(g.goal_id) is False

        # The goal is untouched.
        survivor = await gm.get_goal(g.goal_id, company_id=ALL_COMPANIES)
        assert survivor.status == "active"

    @pytest.mark.asyncio
    async def test_mark_checkpoint_complete_survives_context_flip(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        """A goal created in company A, then the operator flips to B
        (e.g. via company_use), then a long-running tool finally calls
        mark_checkpoint_complete. The internal goal fetch must use
        ALL_COMPANIES so the goal advance lands, or the DB ends up
        half-updated (checkpoint=complete, goal=stale)."""
        from core.company import reset_current_company, set_current_company

        router.complete.return_value = FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON)

        a = set_current_company("acme-inc")
        try:
            g = await gm.create_goal("Long task")
            await gm.decompose(g)
            await gm.mark_checkpoint_active(g.goal_id, 1)
        finally:
            reset_current_company(a)

        # Operator switched companies mid-run.
        b = set_current_company("beta-co")
        try:
            await gm.mark_checkpoint_complete(g.goal_id, 1, "done")
        finally:
            reset_current_company(b)

        # The goal advanced — current_checkpoint = 2 — despite the flip.
        from core.company import ALL_COMPANIES

        after = await gm.get_goal(g.goal_id, company_id=ALL_COMPANIES)
        assert after is not None
        assert after.current_checkpoint == 2

    @pytest.mark.asyncio
    async def test_persist_does_not_move_goal_between_companies(
        self, gm: GoalManager
    ) -> None:
        """_persist_goal omits company_id from the ON CONFLICT update
        set, so subsequent persist calls (status flip, checkpoint
        advance) can never relocate a goal to another tenant even if
        someone hands us a Goal object with a tampered company_id."""
        from core.company import (
            ALL_COMPANIES,
            reset_current_company,
            set_current_company,
        )

        a = set_current_company("acme-inc")
        try:
            g = await gm.create_goal("Anchored")
        finally:
            reset_current_company(a)

        # Tamper in-memory: pretend a subsequent persist tries to move it.
        g.company_id = "beta-co"
        g.status = "cancelled"
        await gm._persist_goal(g)

        row = await gm.get_goal(g.goal_id, company_id=ALL_COMPANIES)
        assert row is not None
        assert row.company_id == "acme-inc"  # stayed
        assert row.status == "cancelled"  # status DID advance
