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


class TestPreemptionIsAYieldNotAResult:
    """Regression 2026-08-15: three checkpoints were marked complete with the
    summary 'Task stopped: preempted by higher-priority task…' — the runner
    verified receipts on the partial tool trail of a preempted response and
    stamped completion; a fourth checkpoint was hard-cancelled mid-run and
    stranded 'active', which get_next_checkpoint silently skips forever. The
    plan reviser then spent its limited revisions re-adding work preemption
    had eaten. Preempted = reset to pending with the attempt refunded;
    stranded active = re-picked at loop start."""

    @pytest.mark.asyncio
    async def test_preempted_response_never_completes_a_checkpoint(
        self, runner, gm, router, mock_agent, gateway
    ) -> None:
        calls = {"n": 0}

        async def _submit(*_a, **_kw):
            calls["n"] += 1
            cb = getattr(mock_agent._executor, "_on_tool_executed", None)
            if callable(cb):
                cb("watch_analyze", {"subject": "Pulsz"}, None)
            if calls["n"] == 1:
                # First slot request yields to a higher-priority task —
                # with a partial-but-real tool trail, like the live run.
                return type(
                    "PreemptedResponse",
                    (),
                    {"content": "Task stopped: preempted", "preempted": True},
                )()
            return FakeAgentResponse(content="rows=4 receipts present")

        mock_agent.submit_task = AsyncMock(side_effect=_submit)
        router.complete = AsyncMock(
            return_value=FakeLLMResponse(_checkpoints("evidence rows exist", n=1))
        )
        goal = await gm.create_goal("Collect brands")
        await gm.decompose(goal)
        router.complete = AsyncMock(return_value=FakeLLMResponse("Summary."))
        await runner.start_goal(goal.goal_id)
        await asyncio.wait_for(runner._current_task, timeout=20)

        cps = await gm.get_checkpoints(goal.goal_id)
        cp = cps[0]
        # Completed only by the SECOND (real) execution — and the preempted
        # attempt was refunded, so attempts records one real run.
        assert cp.status == "completed"
        assert calls["n"] == 2
        assert cp.attempts == 1
        assert "preempted" not in (cp.result_summary or "")

    @pytest.mark.asyncio
    async def test_stranded_active_checkpoint_is_repicked_on_start(
        self, runner, gm, router, mock_agent
    ) -> None:
        router.complete = AsyncMock(
            return_value=FakeLLMResponse(_checkpoints("done", n=2))
        )
        goal = await gm.create_goal("Two steps")
        await gm.decompose(goal)
        router.complete = AsyncMock(return_value=FakeLLMResponse("Summary."))
        # Simulate a dead run: checkpoint 1 stranded active with an attempt.
        await gm._db.execute(
            "UPDATE goal_checkpoints SET status='active', attempts=1 "
            "WHERE goal_id=? AND checkpoint_order=1",
            (goal.goal_id,),
        )
        await runner.start_goal(goal.goal_id)
        await asyncio.wait_for(runner._current_task, timeout=20)
        cps = await gm.get_checkpoints(goal.goal_id)
        assert [c.status for c in cps] == ["completed", "completed"]
        # The stranded attempt was refunded before the re-run recorded its own.
        assert cps[0].attempts == 1

    @pytest.mark.asyncio
    async def test_refund_never_goes_below_zero(self, runner, gm, router) -> None:
        router.complete = AsyncMock(
            return_value=FakeLLMResponse(_checkpoints("done", n=1))
        )
        goal = await gm.create_goal("One step")
        await gm.decompose(goal)
        await runner._reset_checkpoint_pending(
            goal.goal_id, 1, refund_attempt=True
        )
        cps = await gm.get_checkpoints(goal.goal_id)
        assert cps[0].attempts == 0
