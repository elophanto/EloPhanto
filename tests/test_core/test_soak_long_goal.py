"""A long goal under production disturbances, in seconds (docs/94 §9).

Six checkpoints, each several tool steps. While they run, the operator
chats (preempting the lowest-priority goal work) and the runner is killed
mid-checkpoint and restarted — the three things that made past unattended
runs stall, redo work, or sit 'active' with nothing running them.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from core.agent import Agent
from core.config import Config
from core.goal_runner import GoalRunner
from core.run_ledger import RunLedger
from tests.soak.harness import ScriptedModel, SoakReportTool


async def _until(pred: Any, timeout: float = 60.0, every: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await pred():
            return True
        await asyncio.sleep(every)
    return False


@pytest.fixture
async def soak(test_config: Config, tmp_path: Path):
    test_config.max_steps = 30
    test_config.goals.pause_between_checkpoints_seconds = 0
    test_config.goals.max_time_per_checkpoint_seconds = 60
    test_config.goals.cost_budget_per_goal_usd = 100.0
    test_config.workspace = str(tmp_path / "workspace")
    agent = Agent(test_config)
    await agent.initialize()
    out = tmp_path / "out"
    tool = SoakReportTool(out)
    agent._registry.register(tool)
    model = ScriptedModel(out_dir=out, n_checkpoints=6, work_steps=3)
    with patch.object(agent._router, "complete", side_effect=model.complete):
        yield agent, model, tool
    if agent._goal_runner is not None:
        await agent._goal_runner.close()


class TestLongGoalUnderDisturbance:
    async def test_the_goal_finishes_with_nothing_lost_or_redone(self, soak) -> None:
        agent, model, tool = soak
        gm = agent._goal_manager
        goal = await gm.create_goal("Write a six-part report")
        assert await gm.decompose(goal)
        runner: GoalRunner = agent._goal_runner
        assert await runner.start_goal(goal.goal_id)

        async def completed_count() -> int:
            return sum(
                1
                for c in await gm.get_checkpoints(goal.goal_id)
                if c.status == "completed"
            )

        # 1) The operator chats twice while checkpoints run: USER outranks
        #    GOAL, so each chat preempts the checkpoint at a safe point.
        for _ in range(2):
            await asyncio.wait_for(tool.in_flight.wait(), timeout=30)
            reply = await agent.run("how is it going?")
            assert reply.stop_reason == "completed"

        # 2) The process dies mid-checkpoint (hard cancel), and restarts.
        assert await _until(lambda: _gte(completed_count, 3))
        await asyncio.wait_for(tool.in_flight.wait(), timeout=30)
        await runner.close()
        restarted = GoalRunner(
            agent=agent, goal_manager=gm, gateway=None, config=agent._config.goals
        )
        agent._goal_runner = restarted
        await restarted.resume_on_startup()

        # 3) It finishes.
        async def goal_done() -> bool:
            g = await gm.get_goal(goal.goal_id)
            return g is not None and g.status == "completed"

        assert await _until(goal_done, timeout=90), await _state(gm, goal.goal_id)

        cps = await gm.get_checkpoints(goal.goal_id)
        ledger = RunLedger(agent._db)
        entries = await ledger.entries(goal.goal_id)

        # No attempt was burned by a disturbance: preemptions and the
        # restart are refunded, and nothing failed.
        assert all(c.status == "completed" for c in cps)
        assert all(c.attempts == 1 for c in cps), [(c.order, c.attempts) for c in cps]
        assert not [e for e in entries if e.kind == "failure"]

        # Every interruption left a handoff saying why it stopped.
        handoffs = [e for e in entries if e.kind == "handoff"]
        assert len(handoffs) >= 2
        assert all(h.content.startswith("[preempted]") for h in handoffs)

        # What the work produced is on the record, by code, not paraphrase.
        artifacts = {e.ref for e in entries if e.kind == "artifact"}
        for order in range(1, 7):
            assert any(f"cp{order}_part" in a for a in artifacts), (order, artifacts)

        # Every checkpoint run saw its own goal's plan.
        assert model.goal_ids_seen
        assert {gid for _, gid in model.goal_ids_seen} == {goal.goal_id}

        # Nothing is left 'active' with no runner, and memory says what ran.
        async def idle() -> bool:
            return not restarted.is_running

        assert await _until(idle, timeout=10)  # finished, and nothing else queued
        await asyncio.sleep(0.1)  # fire-and-forget memory writes
        rows = await agent._db.execute("SELECT task_goal, task_summary FROM memory")
        assert rows
        assert not [r for r in rows if r["task_summary"] == "Max steps reached"]
        assert any(
            r["task_goal"].startswith(f"Goal {goal.goal_id} checkpoint") for r in rows
        )

        # The readable mirror exists in the workspace.
        ledger_md = Path(agent._config.workspace) / "goals" / goal.goal_id / "LEDGER.md"
        assert ledger_md.exists() and "artifact" in ledger_md.read_text()


async def _running(runner: GoalRunner) -> bool:
    return runner.is_running


async def _gte(fn: Any, n: int) -> bool:
    return (await fn()) >= n


async def _state(gm: Any, goal_id: str) -> str:
    g = await gm.get_goal(goal_id)
    cps = await gm.get_checkpoints(goal_id)
    return f"goal={g.status if g else None} " + ", ".join(
        f"{c.order}:{c.status}/{c.attempts}" for c in cps
    )
