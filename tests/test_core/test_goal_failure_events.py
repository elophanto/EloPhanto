"""Failures have to reach the operator, not just the log file.

`goal_runner` broadcast started / checkpoint_complete / completed / failed /
paused / resumed. Receipt-gate refusals, checkpoint timeouts and plan
revisions were `logger.warning` only, and there was no
`GOAL_CHECKPOINT_FAILED` in `EventType` at all — so from any channel, a goal
failing the same checkpoint for the fifth time looked exactly like a goal
thinking. The operator's only way to find out was to read the log:

    16:59:00  Checkpoint 1 receipt failed for goal a98d7c91-30f …
    17:00:09  Checkpoint 1 receipt failed for goal a98d7c91-30f …
    17:02:09  Checkpoint 1 receipt failed for goal a98d7c91-30f …
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.config import GoalsConfig
from core.database import Database
from core.goal_manager import EvaluationResult, GoalManager
from core.goal_runner import GoalRunner


@dataclass
class FakeAgentResponse:
    content: str = "Did the work."


@dataclass
class FakeLLMResponse:
    content: str


class RecordingGateway:
    """Captures what the operator would actually have seen."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def broadcast(self, message: Any, session_id: str | None = None) -> None:
        data = message.data or {}
        self.events.append((str(data.get("event", "")), data))

    def kinds(self) -> list[str]:
        return [e for e, _ in self.events]

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [d for e, d in self.events if e == kind]


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "events.db")
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
    r.complete = AsyncMock(return_value=FakeLLMResponse("Summary."))
    return r


@pytest.fixture
def gm(db: Database, router: AsyncMock, config: GoalsConfig) -> GoalManager:
    return GoalManager(db=db, router=router, config=config)


@pytest.fixture
def mock_agent() -> MagicMock:
    agent = MagicMock()

    async def _submit(*_a, **_kw):
        cb = getattr(agent._executor, "_on_tool_executed", None)
        if callable(cb):
            cb("knowledge_search", {"query": "x"}, None)
        return FakeAgentResponse()

    agent.run = AsyncMock(return_value=FakeAgentResponse())
    agent.submit_task = AsyncMock(side_effect=_submit)
    agent._conversation_history = []
    agent._executor = MagicMock()
    agent._executor._approval_callback = None
    agent._executor._on_tool_executed = None
    agent._executor.set_approval_callback = MagicMock()
    return agent


@pytest.fixture
def gateway() -> RecordingGateway:
    return RecordingGateway()


@pytest.fixture
def runner(
    mock_agent: MagicMock,
    gm: GoalManager,
    config: GoalsConfig,
    gateway: RecordingGateway,
) -> GoalRunner:
    return GoalRunner(agent=mock_agent, goal_manager=gm, gateway=gateway, config=config)


def _checkpoints(criteria: str, n: int = 6) -> str:
    return json.dumps(
        [
            {
                "order": i,
                "title": f"Step {i}",
                "description": "work",
                "success_criteria": criteria,
            }
            for i in range(1, n + 1)
        ]
    )


async def _run(runner: GoalRunner, gm: GoalManager, router: AsyncMock, criteria: str):
    router.complete = AsyncMock(return_value=FakeLLMResponse(_checkpoints(criteria)))
    goal = await gm.create_goal("A goal")
    await gm.decompose(goal)
    router.complete = AsyncMock(return_value=FakeLLMResponse("Summary."))
    await runner.start_goal(goal.goal_id)
    if runner._current_task:
        await asyncio.wait_for(runner._current_task, timeout=20)
    return goal


class TestCheckpointFailureIsAnnounced:
    async def test_a_receipt_refusal_reaches_the_operator(
        self,
        runner: GoalRunner,
        gm: GoalManager,
        router: AsyncMock,
        gateway: RecordingGateway,
    ) -> None:
        # An ungrounded count — the tool trail never mentions 500.
        await _run(runner, gm, router, "Exactly 500 records are imported.")

        failures = gateway.of("goal_checkpoint_failed")
        assert failures, f"only saw {sorted(set(gateway.kinds()))}"
        assert "receipt gate" in failures[0]["reason"]
        assert failures[0]["checkpoint_order"] == 1
        assert failures[0]["checkpoint_title"] == "Step 1"

    async def test_the_repeat_count_is_carried(
        self,
        runner: GoalRunner,
        gm: GoalManager,
        router: AsyncMock,
        gateway: RecordingGateway,
    ) -> None:
        """One failure is work; the third in a row is a loop."""
        await _run(runner, gm, router, "Exactly 500 records are imported.")
        failures = gateway.of("goal_checkpoint_failed")
        assert all("attempts" in f for f in failures)
        assert max(f["attempts"] for f in failures) >= 1

    async def test_success_still_announces_completion(
        self,
        runner: GoalRunner,
        gm: GoalManager,
        router: AsyncMock,
        gateway: RecordingGateway,
    ) -> None:
        await _run(runner, gm, router, "The work is recorded via knowledge_search.")
        assert gateway.of("goal_checkpoint_complete")
        assert not gateway.of("goal_checkpoint_failed")


class TestRevisionIsAnnounced:
    async def test_each_revision_is_broadcast_with_its_position(
        self,
        runner: GoalRunner,
        gm: GoalManager,
        router: AsyncMock,
        gateway: RecordingGateway,
    ) -> None:
        gm.evaluate_progress = AsyncMock(
            return_value=EvaluationResult(False, True, "Not on track.")
        )
        gm.revise_plan = AsyncMock(return_value=[])

        await _run(runner, gm, router, "The work is recorded via knowledge_search.")

        revisions = gateway.of("goal_revised")
        assert [r["revision"] for r in revisions] == [1, 2, 3]
        assert all(r["max_revisions"] == 3 for r in revisions)
        assert "Not on track." in revisions[0]["reason"]
        # And the guard's pause is announced too, so the loop visibly ends.
        assert any(
            "revised 3 times" in p.get("reason", "") for p in gateway.of("goal_paused")
        )
