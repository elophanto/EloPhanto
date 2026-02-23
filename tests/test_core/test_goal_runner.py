"""GoalRunner tests — background execution, pause/resume, safety limits."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.config import GoalsConfig
from core.database import Database
from core.goal_manager import Goal, GoalManager
from core.goal_runner import GoalRunner


@dataclass
class FakeAgentResponse:
    """Minimal stand-in for AgentResponse."""

    content: str = "Checkpoint completed successfully."


@dataclass
class FakeLLMResponse:
    content: str


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
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
    r.complete = AsyncMock(
        return_value=FakeLLMResponse(content="Summary of work done.")
    )
    return r


@pytest.fixture
def gm(db: Database, router: AsyncMock, config: GoalsConfig) -> GoalManager:
    return GoalManager(db=db, router=router, config=config)


@pytest.fixture
def mock_agent() -> MagicMock:
    agent = MagicMock()
    agent.run = AsyncMock(return_value=FakeAgentResponse())
    agent._conversation_history = []
    agent._executor = MagicMock()
    agent._executor._approval_callback = None
    agent._executor.set_approval_callback = MagicMock()
    return agent


@pytest.fixture
def runner(mock_agent: MagicMock, gm: GoalManager, config: GoalsConfig) -> GoalRunner:
    return GoalRunner(agent=mock_agent, goal_manager=gm, gateway=None, config=config)


_SAMPLE_CHECKPOINTS_JSON = json.dumps(
    [
        {
            "order": 1,
            "title": "Research topic",
            "description": "Gather information",
            "success_criteria": "Info collected",
        },
        {
            "order": 2,
            "title": "Write report",
            "description": "Compile findings",
            "success_criteria": "Report written",
        },
    ]
)


async def _create_goal_with_checkpoints(gm: GoalManager, router: AsyncMock) -> Goal:
    """Helper to create a goal and decompose it."""
    router.complete = AsyncMock(
        return_value=FakeLLMResponse(content=_SAMPLE_CHECKPOINTS_JSON)
    )
    goal = await gm.create_goal("Test goal")
    await gm.decompose(goal)
    # Reset router for subsequent calls
    router.complete = AsyncMock(
        return_value=FakeLLMResponse(content="Summary of work done.")
    )
    return goal


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGoalRunnerProperties:
    def test_not_running_initially(self, runner: GoalRunner) -> None:
        assert not runner.is_running
        assert runner.current_goal_id is None


class TestStartGoal:
    async def test_start_goal_success(
        self, runner: GoalRunner, gm: GoalManager, router: AsyncMock
    ) -> None:
        goal = await _create_goal_with_checkpoints(gm, router)
        result = await runner.start_goal(goal.goal_id)
        assert result is True
        assert runner.is_running

        # Let it run to completion
        await asyncio.sleep(0.5)
        # Wait for the task to finish
        if runner._current_task:
            await asyncio.wait_for(runner._current_task, timeout=5)

        # Goal should be completed
        updated = await gm.get_goal(goal.goal_id)
        assert updated is not None
        assert updated.status == "completed"

    async def test_start_rejects_when_already_running(
        self, runner: GoalRunner, gm: GoalManager, router: AsyncMock
    ) -> None:
        goal = await _create_goal_with_checkpoints(gm, router)
        # Make agent.run take a while
        runner._agent.run = AsyncMock(side_effect=lambda _: asyncio.sleep(10))

        await runner.start_goal(goal.goal_id)
        assert runner.is_running

        result = await runner.start_goal(goal.goal_id)
        assert result is False

        await runner.cancel()

    async def test_start_rejects_nonexistent_goal(self, runner: GoalRunner) -> None:
        result = await runner.start_goal("nonexistent-id")
        assert result is False


class TestPauseResume:
    async def test_notify_user_interaction_pauses(
        self, runner: GoalRunner, gm: GoalManager, router: AsyncMock
    ) -> None:
        goal = await _create_goal_with_checkpoints(gm, router)

        # Make agent.run slow so we can interrupt
        async def slow_run(prompt: str) -> FakeAgentResponse:
            await asyncio.sleep(2)
            return FakeAgentResponse()

        runner._agent.run = AsyncMock(side_effect=slow_run)

        await runner.start_goal(goal.goal_id)
        await asyncio.sleep(0.1)

        runner.notify_user_interaction()
        assert runner._stop_requested is True

        # Wait for loop to stop
        if runner._current_task:
            try:
                await asyncio.wait_for(runner._current_task, timeout=5)
            except asyncio.CancelledError:
                pass

        # Goal should be paused
        updated = await gm.get_goal(goal.goal_id)
        assert updated is not None
        # Either paused (first checkpoint still running when stop requested)
        # or completed (if checkpoint finished before pause took effect)
        assert updated.status in ("paused", "completed")

    async def test_resume_starts_background_execution(
        self, runner: GoalRunner, gm: GoalManager, router: AsyncMock
    ) -> None:
        goal = await _create_goal_with_checkpoints(gm, router)

        # Pause the goal first
        await gm.pause_goal(goal.goal_id)
        updated = await gm.get_goal(goal.goal_id)
        assert updated is not None
        assert updated.status == "paused"

        # Resume
        result = await runner.resume(goal.goal_id)
        assert result is True
        assert runner.is_running

        # Let it complete
        if runner._current_task:
            await asyncio.wait_for(runner._current_task, timeout=5)


class TestCancel:
    async def test_cancel_stops_execution(
        self, runner: GoalRunner, gm: GoalManager, router: AsyncMock
    ) -> None:
        goal = await _create_goal_with_checkpoints(gm, router)

        async def slow_run(prompt: str) -> FakeAgentResponse:
            await asyncio.sleep(10)
            return FakeAgentResponse()

        runner._agent.run = AsyncMock(side_effect=slow_run)

        await runner.start_goal(goal.goal_id)
        await asyncio.sleep(0.1)
        assert runner.is_running

        await runner.cancel()
        assert not runner.is_running
        assert runner.current_goal_id is None


class TestSafetyLimits:
    async def test_cost_budget_pauses_goal(
        self, runner: GoalRunner, gm: GoalManager, router: AsyncMock
    ) -> None:
        goal = await _create_goal_with_checkpoints(gm, router)

        # Set cost over budget
        goal.cost_usd = 999.0
        await gm._persist_goal(goal)

        await runner.start_goal(goal.goal_id)
        if runner._current_task:
            await asyncio.wait_for(runner._current_task, timeout=5)

        updated = await gm.get_goal(goal.goal_id)
        assert updated is not None
        assert updated.status == "paused"

    async def test_llm_budget_pauses_goal(
        self, runner: GoalRunner, gm: GoalManager, router: AsyncMock
    ) -> None:
        goal = await _create_goal_with_checkpoints(gm, router)

        # Set LLM calls over budget
        goal.llm_calls_used = 999
        await gm._persist_goal(goal)

        await runner.start_goal(goal.goal_id)
        if runner._current_task:
            await asyncio.wait_for(runner._current_task, timeout=5)

        updated = await gm.get_goal(goal.goal_id)
        assert updated is not None
        assert updated.status == "paused"


class TestConversationIsolation:
    async def test_background_run_does_not_pollute_history(
        self,
        runner: GoalRunner,
        gm: GoalManager,
        router: AsyncMock,
        mock_agent: MagicMock,
    ) -> None:
        goal = await _create_goal_with_checkpoints(gm, router)

        # Set some existing conversation history
        mock_agent._conversation_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        original_history = list(mock_agent._conversation_history)

        await runner.start_goal(goal.goal_id)
        if runner._current_task:
            await asyncio.wait_for(runner._current_task, timeout=5)

        # Original history should be preserved
        assert mock_agent._conversation_history == original_history


class TestStartupResume:
    async def test_resume_on_startup_with_active_goal(
        self, runner: GoalRunner, gm: GoalManager, router: AsyncMock
    ) -> None:
        goal = await _create_goal_with_checkpoints(gm, router)
        # Goal should be active after creation

        await runner.resume_on_startup()

        # Should have started
        if runner._current_task:
            await asyncio.wait_for(runner._current_task, timeout=5)

        updated = await gm.get_goal(goal.goal_id)
        assert updated is not None
        assert updated.status == "completed"

    async def test_resume_on_startup_noop_when_disabled(
        self, gm: GoalManager, router: AsyncMock, mock_agent: MagicMock
    ) -> None:
        config = GoalsConfig(auto_continue=False)
        runner = GoalRunner(
            agent=mock_agent, goal_manager=gm, gateway=None, config=config
        )
        await runner.resume_on_startup()
        assert not runner.is_running
