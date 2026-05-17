"""AutonomousMind — coverage for the three reliability fixes added
to close the goal-completion → dream gap:

1. Workable-goals count → mechanical FORCE-DREAM gate.
2. Goal-completion hook wiring → immediate wakeup interrupt.
3. Planning-stuck retry → unstick goals that decompose never produced.

These tests run against a real Database + GoalManager so the SQL
constraints and goal lifecycle behave as in production. The mind
itself is instantiated with a minimal fake agent (no LLM router,
no executor) — we only exercise the helpers that don't need the
full think loop.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from core.autonomous_mind import (
    _PLANNING_MAX_RETRIES,
    _PLANNING_STUCK_TIMEOUT_S,
    AutonomousMind,
)
from core.config import AutonomousMindConfig, GoalsConfig
from core.database import Database
from core.goal_manager import GoalManager


class _FakeLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content
        self.cost_usd = 0.0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.model = "fake"


@pytest.fixture
async def db(tmp_path):
    d = Database(tmp_path / "mind.db")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def router() -> AsyncMock:
    r = AsyncMock()
    return r


@pytest.fixture
async def goal_manager(db: Database, router: AsyncMock) -> GoalManager:
    return GoalManager(db=db, router=router, config=GoalsConfig())


@pytest.fixture
def mind(tmp_path, goal_manager: GoalManager) -> AutonomousMind:
    """Minimal AutonomousMind. The agent stub only exposes the
    attributes the helpers under test actually reach for. The fake
    registry no-ops .register() so the constructor's mind-tool
    registration doesn't blow up."""

    class _FakeRegistry:
        def register(self, _tool: Any) -> None:
            pass

    class _FakeAgent:
        def __init__(self) -> None:
            self._goal_manager = goal_manager
            self._identity_manager = None
            self._affect_manager = None
            self._ego_manager = None
            self._scheduler = None
            self._registry = _FakeRegistry()

    return AutonomousMind(
        agent=_FakeAgent(),
        gateway=None,
        config=AutonomousMindConfig(),
        project_root=tmp_path,
    )


# ---------------------------------------------------------------------------
# Workable goals count — drives the FORCE-DREAM gate. If this method
# returns 0, _build_prompt prepends a hard directive forcing dream phase.
# If it returns >0, the prompt stays as-is and the LLM works on existing
# goals.
# ---------------------------------------------------------------------------


class TestCountWorkableGoals:
    @pytest.mark.asyncio
    async def test_zero_when_no_goals(self, mind: AutonomousMind) -> None:
        assert await mind._count_workable_goals() == 0

    @pytest.mark.asyncio
    async def test_counts_planning_goals(
        self, mind: AutonomousMind, goal_manager: GoalManager
    ) -> None:
        await goal_manager.create_goal("In planning")
        # Planning goals haven't been decomposed yet but they count —
        # the LLM should call goal_decompose, not dream up another.
        assert await mind._count_workable_goals() == 1

    @pytest.mark.asyncio
    async def test_counts_active_goals(
        self,
        mind: AutonomousMind,
        goal_manager: GoalManager,
        router: AsyncMock,
    ) -> None:
        import json

        router.complete.return_value = _FakeLLMResponse(
            json.dumps(
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
        goal = await goal_manager.create_goal("Active one")
        await goal_manager.decompose(goal)  # flips to active
        assert await mind._count_workable_goals() == 1

    @pytest.mark.asyncio
    async def test_returns_sentinel_on_error(self, mind: AutonomousMind) -> None:
        """If the goal manager is None (or fails), return a sentinel
        non-zero count so a DB hiccup never trips a false FORCE-DREAM
        directive."""
        mind._agent._goal_manager = None  # type: ignore[attr-defined]
        assert await mind._count_workable_goals() == 999


# ---------------------------------------------------------------------------
# Goal-completion hook wiring — finishing a goal must shorten the next
# wakeup so dream fires immediately. The hook is registered in start();
# here we call it directly to verify the contract.
# ---------------------------------------------------------------------------


class TestCompletionWakeup:
    @pytest.mark.asyncio
    async def test_hook_shortens_next_wakeup(self, mind: AutonomousMind) -> None:
        # Pretend the mind is running with a long-tail wakeup scheduled.
        mind._task = asyncio.create_task(asyncio.sleep(0))  # is_running=True briefly
        try:
            mind._next_wakeup_sec = 3600.0
            assert not mind._wakeup_event.is_set()

            await mind._on_goal_completed_wakeup("g-deadbeef")

            assert (
                mind._next_wakeup_sec <= 5.0
            ), "hook must collapse next wakeup to ~immediate"
            assert (
                mind._wakeup_event.is_set()
            ), "hook must set the wakeup event to interrupt sleep"
        finally:
            await mind._task

    @pytest.mark.asyncio
    async def test_hook_no_op_when_paused(self, mind: AutonomousMind) -> None:
        """Mind paused = user interaction in flight. Don't barge in
        with an instant wakeup — let the user resume path handle it."""
        mind._task = asyncio.create_task(asyncio.sleep(0))
        try:
            mind._paused = True
            mind._next_wakeup_sec = 3600.0
            await mind._on_goal_completed_wakeup("g-x")
            assert mind._next_wakeup_sec == 3600.0
            assert not mind._wakeup_event.is_set()
        finally:
            await mind._task


# ---------------------------------------------------------------------------
# Planning-stuck retry — goals that sit in status='planning' without
# producing checkpoints must not poison the snapshot forever. After
# the timeout, retry decompose; after _PLANNING_MAX_RETRIES, cancel.
# ---------------------------------------------------------------------------


async def _backdate_goal(
    db: Database, goal_id: str, age_seconds: float, attempts: int = 0
) -> None:
    """Forcibly age a goal's updated_at + bump attempts so the maintenance
    pass sees it as stuck. SQL-level surgery — going through the manager
    would refresh updated_at."""
    backdated = (datetime.now(UTC) - timedelta(seconds=age_seconds)).isoformat()
    await db.execute(
        "UPDATE goals SET updated_at = ?, attempts = ? WHERE goal_id = ?",
        (backdated, attempts, goal_id),
    )


class TestPlanningStuckRetry:
    @pytest.mark.asyncio
    async def test_fresh_planning_goal_not_retried(
        self,
        mind: AutonomousMind,
        goal_manager: GoalManager,
        router: AsyncMock,
    ) -> None:
        """A planning goal that's only seconds old must be left alone —
        give the LLM a chance to call decompose itself."""
        await goal_manager.create_goal("Fresh")
        await mind._retry_stuck_planning_goals(goal_manager)
        # router not invoked — decompose was not called.
        assert router.complete.await_count == 0

    @pytest.mark.asyncio
    async def test_stuck_goal_retried(
        self,
        mind: AutonomousMind,
        goal_manager: GoalManager,
        router: AsyncMock,
        db: Database,
    ) -> None:
        """Past the timeout with attempts < max → decompose retry."""
        import json

        router.complete.return_value = _FakeLLMResponse(
            json.dumps(
                [
                    {
                        "order": 1,
                        "title": "Retried",
                        "description": "d",
                        "success_criteria": "s",
                    }
                ]
            )
        )
        goal = await goal_manager.create_goal("Stuck")
        await _backdate_goal(
            db, goal.goal_id, _PLANNING_STUCK_TIMEOUT_S + 60, attempts=0
        )

        await mind._retry_stuck_planning_goals(goal_manager)

        # Decompose was invoked.
        assert router.complete.await_count == 1
        # Goal now has checkpoints + status flipped to active.
        refreshed = await goal_manager.get_goal(goal.goal_id)
        assert refreshed is not None
        assert refreshed.status == "active"
        assert refreshed.total_checkpoints == 1

    @pytest.mark.asyncio
    async def test_stuck_past_max_retries_cancelled(
        self,
        mind: AutonomousMind,
        goal_manager: GoalManager,
        router: AsyncMock,
        db: Database,
    ) -> None:
        """After exhausting retries the goal must be cancelled so it
        stops showing up in the snapshot."""
        goal = await goal_manager.create_goal("Hopeless")
        await _backdate_goal(
            db,
            goal.goal_id,
            _PLANNING_STUCK_TIMEOUT_S + 60,
            attempts=_PLANNING_MAX_RETRIES,
        )

        await mind._retry_stuck_planning_goals(goal_manager)

        # Decompose NOT retried; goal cancelled instead.
        assert router.complete.await_count == 0
        refreshed = await goal_manager.get_goal(goal.goal_id)
        assert refreshed is not None
        assert refreshed.status == "cancelled"

    @pytest.mark.asyncio
    async def test_goal_with_checkpoints_not_treated_as_stuck(
        self,
        mind: AutonomousMind,
        goal_manager: GoalManager,
        router: AsyncMock,
        db: Database,
    ) -> None:
        """A goal in 'planning' status with checkpoints already exists
        is in a different stuck-state (mid-decompose interrupt?). The
        maintenance pass only retries when total_checkpoints == 0."""
        import json

        router.complete.return_value = _FakeLLMResponse(
            json.dumps(
                [
                    {
                        "order": 1,
                        "title": "A",
                        "description": "d",
                        "success_criteria": "s",
                    }
                ]
            )
        )
        goal = await goal_manager.create_goal("Has cps")
        await goal_manager.decompose(goal)  # produces checkpoints, flips to active

        # Manually revert to 'planning' to simulate the weird state.
        await db.execute(
            "UPDATE goals SET status = 'planning' WHERE goal_id = ?",
            (goal.goal_id,),
        )
        await _backdate_goal(
            db, goal.goal_id, _PLANNING_STUCK_TIMEOUT_S + 60, attempts=0
        )
        router.complete.reset_mock()

        await mind._retry_stuck_planning_goals(goal_manager)

        # Has checkpoints → not retried (decompose would create dupes).
        assert router.complete.await_count == 0
