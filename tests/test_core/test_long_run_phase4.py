"""Phase 4 of docs/94 — scheduling for long work."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import core.task_resources as tr
from core.config import GoalsConfig
from core.database import Database
from core.goal_manager import GoalManager
from core.goal_runner import GoalRunner
from core.run_hooks import current_run_hooks
from core.task_resources import TaskPriority, _PrioritySemaphore, effective_priority


class TestAging:
    def test_waiting_raises_priority_but_never_to_user(self) -> None:
        goal = TaskPriority.GOAL.value
        assert effective_priority(goal, 0) == goal
        assert effective_priority(goal, 61) == goal - 1
        assert effective_priority(goal, 3600) == TaskPriority.SCHEDULED.value
        assert effective_priority(TaskPriority.USER.value, 3600) == TaskPriority.USER.value

    async def test_long_waiting_goal_work_beats_a_fresh_mind_cycle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sem = _PrioritySemaphore(1)
        holder = await sem.acquire(TaskPriority.USER.value)
        order: list[str] = []
        clock = {"t": 1000.0}
        monkeypatch.setattr(tr.time, "monotonic", lambda: clock["t"])

        async def wait(name: str, pri: int) -> None:
            slot = await sem.acquire(pri)
            order.append(f"{name}@{slot.priority}")
            sem.release(slot)

        goal = asyncio.create_task(wait("goal", TaskPriority.GOAL.value))
        await asyncio.sleep(0)
        clock["t"] += 300  # the goal has waited five minutes
        mind = asyncio.create_task(wait("mind", TaskPriority.MIND.value))
        await asyncio.sleep(0)
        sem.release(holder)
        await asyncio.gather(goal, mind)
        # Aged to SCHEDULED, it outranks MIND and holds at its aged level,
        # so a mind arrival does not immediately preempt it back out.
        assert order == ["goal@1", "mind@2"]


@dataclass
class _Resp:
    content: str = "ok"
    preempted: bool = False
    stop_reason: str = "completed"
    steps_taken: int = 2
    elapsed_seconds: float = 30.0


@dataclass
class _LLM:
    content: str


@pytest.fixture
async def db(tmp_path: Path):
    d = Database(tmp_path / "p4.db")
    await d.initialize()
    yield d
    await d.close()


def _cfg(**kw: Any) -> GoalsConfig:
    base: dict[str, Any] = dict(
        max_time_per_checkpoint_seconds=10,
        pause_between_checkpoints_seconds=0,
        cost_budget_per_goal_usd=100.0,
        plan_critique=False,
        deliberate=False,
    )
    base.update(kw)
    return GoalsConfig(**base)


def _router() -> AsyncMock:
    async def complete(**kw: Any) -> _LLM:
        system = kw["messages"][0]["content"]
        if "You verify, independently" in system:
            return _LLM('{"met": true, "evidence": "e", "missing": []}')
        return _LLM("Summary.")

    r = AsyncMock()
    r.complete = AsyncMock(side_effect=complete)
    return r


async def _goal(gm: GoalManager, text: str, n: int) -> Any:
    plan = json.dumps(
        [{"order": i, "title": f"{text} {i}", "description": "d", "success_criteria": "c"}
         for i in range(1, n + 1)]
    )
    saved = gm._router.complete
    gm._router.complete = AsyncMock(return_value=_LLM(plan))
    g = await gm.create_goal(text)
    await gm.decompose(g)
    gm._router.complete = saved
    return g


def _agent(cost: float = 0.0) -> MagicMock:
    agent = MagicMock()
    agent.order = []

    async def _submit(_s: Any, prompt: str, **kw: Any) -> _Resp:
        agent.order.append(prompt.split("GOAL: ")[1].split("\n")[0])
        hooks = current_run_hooks()
        if hooks and hooks.on_tool_executed:
            hooks.on_tool_executed("knowledge_search", {}, None)
        agent._router.cost_tracker.task_total = cost
        return _Resp()

    agent.submit_task = AsyncMock(side_effect=_submit)
    agent._router.cost_tracker.task_total = 0.0
    agent._router.cost_tracker.daily_total = 0.0
    agent._stop_file_present = MagicMock(return_value=False)
    agent._config.workspace = ""
    return agent


async def _drain(runner: GoalRunner) -> None:
    for _ in range(80):
        t = runner._current_task
        if t is None:
            return
        await asyncio.wait_for(t, timeout=20)


class TestUsageAndEnvelopes:
    async def test_work_time_accumulates_across_runs(self, db: Database) -> None:
        gm = GoalManager(db=db, router=_router(), config=_cfg())
        g = await _goal(gm, "Long", 3)
        runner = GoalRunner(agent=_agent(cost=0.5), goal_manager=gm, gateway=None, config=_cfg())
        await runner.start_goal(g.goal_id)
        await _drain(runner)
        u = await gm.usage(g.goal_id)
        assert u["total_seconds"] == pytest.approx(90.0)
        assert u["today_cost_usd"] == pytest.approx(1.5)

    async def test_a_daily_envelope_pauses_today_and_lifts_tomorrow(self, db: Database) -> None:
        cfg = _cfg(daily_cost_envelope_usd=1.0)
        gm = GoalManager(db=db, router=_router(), config=cfg)
        g = await _goal(gm, "Multi-day", 4)
        runner = GoalRunner(agent=_agent(cost=0.6), goal_manager=gm, gateway=None, config=cfg)
        await runner.start_goal(g.goal_id)
        await _drain(runner)
        paused = await gm.get_goal(g.goal_id)
        assert paused.status == "budget_paused" and "envelope_day=" in paused.context_summary
        done = [c for c in await gm.get_checkpoints(g.goal_id) if c.status == "completed"]
        assert len(done) == 2  # $0.60 + $0.60 crossed the $1 envelope
        # Next day: the envelope row is yesterday's.
        await db.execute("UPDATE goal_usage SET day = '2000-01-01'")
        await db.execute(
            "UPDATE goals SET context_summary = replace(context_summary, "
            "substr(context_summary, instr(context_summary, 'envelope_day=') + 13, 10), "
            "'2000-01-01') WHERE goal_id = ?",
            (g.goal_id,),
        )
        assert await gm.resume_envelope_paused() == [g.goal_id]
        assert (await gm.get_goal(g.goal_id)).status == "active"


class TestRoundRobin:
    async def test_two_goals_take_turns(self, db: Database) -> None:
        cfg = _cfg(round_robin=True)
        gm = GoalManager(db=db, router=_router(), config=cfg)
        a = await _goal(gm, "Alpha", 2)
        await _goal(gm, "Beta", 2)
        agent = _agent()
        runner = GoalRunner(agent=agent, goal_manager=gm, gateway=None, config=cfg)
        await runner.start_goal(a.goal_id)
        await _drain(runner)
        assert agent.order[:3] == ["Alpha", "Beta", "Alpha"]


class TestCapabilityReviewClock:
    async def test_it_is_due_only_after_the_period(self, db: Database) -> None:
        from datetime import UTC, datetime, timedelta

        from core.mind_candidates import CandidateContext, _capability_review_due

        ctx = CandidateContext(goal_manager=MagicMock(_db=db))
        assert await _capability_review_due(ctx) == (1.0, "never recorded")
        await db.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("mind_last_capability_review", datetime.now(UTC).isoformat()),
        )
        assert await _capability_review_due(ctx) is None
        await db.execute(
            "UPDATE metadata SET value = ? WHERE key = 'mind_last_capability_review'",
            ((datetime.now(UTC) - timedelta(days=10)).isoformat(),),
        )
        due = await _capability_review_due(ctx)
        assert due is not None and due[0] == pytest.approx(4.0, abs=0.1)


class TestAttractor:
    def test_a_pick_repeated_three_of_five_times_is_ranked_last(self) -> None:
        from core.autonomous_mind import demote_attractor
        from core.mind_arbiter import Candidate

        stuck = MagicMock(candidate=Candidate(source="x", action_spec="Reconcile goal", dedup_key="k1"))
        other = MagicMock(candidate=Candidate(source="y", action_spec="Send offer", dedup_key="k2"))
        out, note = demote_attractor([stuck, other], ["k1", "k3", "k1", "k1"])
        assert out == [other, stuck] and "ATTRACTOR" in note and "Reconcile goal" in note
        out, note = demote_attractor([stuck, other], ["k1", "k3", "k1"])
        assert out == [stuck, other] and note == ""
