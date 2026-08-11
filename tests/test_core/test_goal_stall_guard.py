"""The no-progress guard has to be able to fire.

`revisions_without_progress` was reset on every completed checkpoint. But
evaluation only runs after two checkpoints complete, and each of those
completions zeroed the counter — so it read 1/3 forever and the pause
branch never executed once. Observed 2026-08-11:

    12:44:46  Goal d2bcd9b7-c25 needs revision (1/3 without progress): …
    12:52:23  Goal d2bcd9b7-c25 needs revision (1/3 without progress): …
    …thirteen times over two hours, 55 checkpoints completed, always 1/3…
    14:44:51  Goal d2bcd9b7-c25 → budget_paused | Total time limit reached

The two senses of "progress" disagree, and checkpoint-level was the wrong
one: a goal can tick off checkpoints indefinitely while going nowhere. Only
a goal-level evaluation finding the goal on track resets the counter now.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.config import GoalsConfig
from core.database import Database
from core.goal_manager import EvaluationResult, GoalManager
from core.goal_runner import GoalRunner


@dataclass
class FakeAgentResponse:
    content: str = "Checkpoint completed successfully."


@dataclass
class FakeLLMResponse:
    content: str


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "stall.db")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def config() -> GoalsConfig:
    return GoalsConfig(
        max_time_per_checkpoint_seconds=10,
        max_total_time_per_goal_seconds=60,
        cost_budget_per_goal_usd=5.0,
        pause_between_checkpoints_seconds=0,
        auto_continue=True,
    )


@pytest.fixture
def router() -> AsyncMock:
    r = AsyncMock()
    r.complete = AsyncMock(return_value=FakeLLMResponse(content="Summary."))
    return r


@pytest.fixture
def gm(db: Database, router: AsyncMock, config: GoalsConfig) -> GoalManager:
    return GoalManager(db=db, router=router, config=config)


@pytest.fixture
def mock_agent() -> MagicMock:
    agent = MagicMock()

    async def _submit_with_tool_trail(*_a, **_kw):
        cb = getattr(agent._executor, "_on_tool_executed", None)
        if callable(cb):
            cb("knowledge_search", {"query": "x"}, None)
        return FakeAgentResponse()

    agent.run = AsyncMock(return_value=FakeAgentResponse())
    agent.submit_task = AsyncMock(side_effect=_submit_with_tool_trail)
    agent._conversation_history = []
    agent._executor = MagicMock()
    agent._executor._approval_callback = None
    agent._executor._on_tool_executed = None
    agent._executor.set_approval_callback = MagicMock()
    return agent


@pytest.fixture
def runner(mock_agent: MagicMock, gm: GoalManager, config: GoalsConfig) -> GoalRunner:
    return GoalRunner(agent=mock_agent, goal_manager=gm, gateway=None, config=config)


_MANY_CHECKPOINTS = json.dumps(
    [
        {
            "order": i,
            "title": f"Step {i}",
            "description": "work",
            "success_criteria": "Work done",
        }
        for i in range(1, 21)
    ]
)


async def _goal_with_many_checkpoints(gm: GoalManager, router: AsyncMock):
    router.complete = AsyncMock(return_value=FakeLLMResponse(_MANY_CHECKPOINTS))
    goal = await gm.create_goal("Long goal that never converges")
    await gm.decompose(goal)
    router.complete = AsyncMock(return_value=FakeLLMResponse("Summary."))
    return goal


async def _drain(runner: GoalRunner) -> None:
    if runner._current_task:
        await asyncio.wait_for(runner._current_task, timeout=20)


class TestTheGuardFires:
    async def test_perpetual_revision_pauses_the_goal(
        self, runner: GoalRunner, gm: GoalManager, router: AsyncMock
    ) -> None:
        """Checkpoints succeed, the goal goes nowhere — it must stop."""
        goal = await _goal_with_many_checkpoints(gm, router)
        gm.evaluate_progress = AsyncMock(
            return_value=EvaluationResult(
                on_track=False,
                revision_needed=True,
                reason="Not on track to reach the goal.",
            )
        )
        gm.revise_plan = AsyncMock(return_value=[])

        await runner.start_goal(goal.goal_id)
        await _drain(runner)

        updated = await gm.get_goal(goal.goal_id)
        assert updated is not None
        assert updated.status == "paused"
        assert gm.evaluate_progress.await_count == 3, "must stop at the 3rd, not later"

    async def test_it_does_not_run_to_the_budget_cap(
        self, runner: GoalRunner, gm: GoalManager, router: AsyncMock
    ) -> None:
        """The old behaviour: only the wall-clock limit ever stopped it."""
        goal = await _goal_with_many_checkpoints(gm, router)
        gm.evaluate_progress = AsyncMock(
            return_value=EvaluationResult(
                on_track=False, revision_needed=True, reason="Still not on track."
            )
        )
        gm.revise_plan = AsyncMock(return_value=[])

        await runner.start_goal(goal.goal_id)
        await _drain(runner)

        updated = await gm.get_goal(goal.goal_id)
        assert updated is not None
        assert updated.status != "budget_paused"


class TestProgressStillResets:
    async def test_an_on_track_evaluation_clears_the_counter(
        self, runner: GoalRunner, gm: GoalManager, router: AsyncMock
    ) -> None:
        """Alternating revise / on-track must never trip the guard."""
        verdicts = [
            EvaluationResult(False, True, "needs work"),
            EvaluationResult(True, False, "on track"),
            EvaluationResult(False, True, "needs work"),
            EvaluationResult(True, False, "on track"),
            EvaluationResult(False, True, "needs work"),
            EvaluationResult(True, False, "on track"),
        ]
        goal = await _goal_with_many_checkpoints(gm, router)
        gm.evaluate_progress = AsyncMock(side_effect=verdicts * 4)
        gm.revise_plan = AsyncMock(return_value=[])

        await runner.start_goal(goal.goal_id)
        await _drain(runner)

        updated = await gm.get_goal(goal.goal_id)
        assert updated is not None
        assert updated.status == "completed", "guard fired on a goal making progress"
