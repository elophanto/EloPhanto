"""docs/95 Phases C and D — plans are scored, lessons earn their place."""

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
from core.deliberation import CheckpointPlan, plan_checkpoint, postmortem
from core.goal_manager import GoalManager
from core.goal_runner import GoalRunner
from core.plan_outcomes import (
    OfferedLesson,
    PlanOutcomes,
    lessons_by_label,
    record_mind_outcome,
    render_offered,
)
from core.run_hooks import current_run_hooks
from core.run_ledger import RunLedger
from core.skills import SkillManager


@pytest.fixture
async def db(tmp_path: Path):
    d = Database(tmp_path / "learn.db")
    await d.initialize()
    yield d
    await d.close()


@dataclass
class _LLM:
    content: str
    reasoning: str = ""
    cost_estimate: float = 0.0


def _lesson(ref: str, title: str = "Avoid: trusting the first page") -> OfferedLesson:
    return OfferedLesson(
        ref=ref, title=title, body="Check the count against the index."
    )


async def _seed(db: Database, passed: list[bool], goal_id: str = "seed") -> None:
    po = PlanOutcomes(db)
    for i, ok in enumerate(passed, 1):
        await po.record(goal_id=goal_id, checkpoint_order=i, attempt=1, passed=ok)


class TestLabels:
    def test_render_and_resolve(self) -> None:
        offered = [_lesson("knowledge:a.md"), _lesson("instinct:b", "when x")]
        text = render_offered(offered)
        assert text.splitlines()[0].startswith("[L1] Avoid:")
        assert "[L2] when x" in text
        assert [x.ref for x in lessons_by_label(offered, ["l2", "[L1]", "L9"])] == [
            "knowledge:a.md",
            "instinct:b",
        ]


class TestRecord:
    async def test_a_lesson_that_beats_the_baseline_becomes_a_skill(
        self, db: Database, tmp_path: Path
    ) -> None:
        gm = GoalManager(db=db, router=AsyncMock(), config=GoalsConfig())
        g = await gm.create_goal("Collect brand pages")
        await db.execute_insert(
            "INSERT INTO goal_checkpoints (goal_id, checkpoint_order, title, description) "
            "VALUES (?, 1, 'Collect promotions pages', 'd')",
            (g.goal_id,),
        )
        await _seed(db, [True, False] * 5)  # baseline 50%
        reloaded: list[Path] = []
        po = PlanOutcomes(db, project_root=tmp_path, on_promote=reloaded.append)
        lesson = _lesson("knowledge:learned/lessons/first-page.md")
        for attempt in range(1, 6):
            await po.record(
                goal_id=g.goal_id,
                checkpoint_order=1,
                attempt=attempt,
                passed=True,
                lessons_used=[lesson],
            )
        st = (await po.stats([lesson.ref]))[lesson.ref]
        assert (st["uses"], st["passes"], st["status"]) == (5, 5, "promoted")
        skill_file = (
            tmp_path / "skills" / "learned-trusting-the-first-page" / "SKILL.md"
        )
        assert reloaded == [skill_file]
        mgr = SkillManager(tmp_path / "skills")
        mgr.discover()
        skill = mgr.get_skill("learned-trusting-the-first-page")
        assert skill is not None
        assert "collect promotions pages" in skill.triggers
        assert "5 of 5" in skill.description
        assert "Check the count" in skill_file.read_text()

    async def test_a_lesson_that_trails_is_retired_and_no_longer_offered(
        self, db: Database
    ) -> None:
        await _seed(db, [True, False] * 5)
        po = PlanOutcomes(db)
        bad = _lesson("instinct:bad", "when in doubt")
        good = _lesson("instinct:good", "when sure")
        for i in range(5):
            await po.record(
                goal_id="g",
                checkpoint_order=i,
                attempt=1,
                passed=False,
                lessons_used=[bad],
            )
        assert (await po.stats([bad.ref]))[bad.ref]["status"] == "retired"
        ranked = await po.rank([bad, good], limit=4)
        assert [x.ref for x in ranked] == ["instinct:good"]

    async def test_a_proven_lesson_rises_and_an_unproven_one_keeps_its_place(
        self, db: Database
    ) -> None:
        await _seed(db, [True, False] * 5)
        po = PlanOutcomes(db)
        new, proven = _lesson("instinct:new"), _lesson("instinct:proven")
        for i in range(3):
            await po.record(
                goal_id="g",
                checkpoint_order=i,
                attempt=1,
                passed=True,
                lessons_used=[proven],
            )
        ranked = await po.rank([new, proven], limit=4)
        assert [x.ref for x in ranked] == ["instinct:proven", "instinct:new"]

    async def test_no_verdict_before_the_record_is_long_enough(
        self, db: Database
    ) -> None:
        po = PlanOutcomes(db)
        lesson = _lesson("instinct:x")
        for i in range(4):
            await po.record(
                goal_id="g",
                checkpoint_order=i,
                attempt=1,
                passed=False,
                lessons_used=[lesson],
            )
        assert (await po.stats([lesson.ref]))[lesson.ref]["status"] == "active"

    async def test_mind_outcome(self, db: Database) -> None:
        await record_mind_outcome(
            db,
            source="workable_checkpoints",
            action_spec="resume goal g",
            deliberated=True,
            pick=2,
            tool_uses=[{"tool": "a", "status": "ok"}, {"tool": "b", "status": "error"}],
            stop_reason="completed",
            cost_usd=0.01,
        )
        rows = await db.execute("SELECT * FROM mind_outcomes")
        assert (rows[0]["pick"], rows[0]["tool_count"], rows[0]["tool_errors"]) == (
            2,
            2,
            1,
        )


class TestDeliberation:
    async def test_the_plan_names_the_lessons_it_applies(self) -> None:
        router = MagicMock()
        router.complete = AsyncMock(
            return_value=_LLM(json.dumps({"approach": "a", "lessons_used": ["L2"]}))
        )
        plan = await plan_checkpoint(
            router,
            goal="g",
            order=1,
            total=1,
            title="t",
            description="d",
            criteria="c",
            stage="s",
            ledger_text="",
            attempt=1,
            lessons="[L1] x: y\n[L2] z: w",
        )
        assert plan is not None and plan.lessons_used == ["L2"]
        assert (
            "lessons_used" in router.complete.call_args.kwargs["messages"][1]["content"]
        )

    async def test_postmortem(self) -> None:
        router = MagicMock()
        router.complete = AsyncMock(
            return_value=_LLM(
                json.dumps(
                    {
                        "foreseen": False,
                        "broken_assumption": "the first page lists every promotion",
                        "lesson": {
                            "title": "Avoid: one-page counts",
                            "when": "w",
                            "lesson": "l",
                        },
                    }
                )
            )
        )
        pm = await postmortem(
            router,
            checkpoint="c",
            plan=CheckpointPlan(approach="a"),
            failure="count 12 not 14",
        )
        assert pm is not None and not pm.foreseen
        assert pm.broken_assumption.startswith("the first page")
        assert pm.lesson and pm.lesson["title"] == "Avoid: one-page counts"


# ---------------------------------------------------------------------------
# Runner integration
# ---------------------------------------------------------------------------


@dataclass
class _Resp:
    content: str = "Did the work."
    preempted: bool = False
    stop_reason: str = "completed"
    steps_taken: int = 3


class TestRunnerScoresPlans:
    async def test_a_surprise_is_named_taught_and_scored(
        self, db: Database, tmp_path: Path
    ) -> None:
        gm_router = AsyncMock()
        gm_router.complete = AsyncMock(
            return_value=_LLM(
                json.dumps(
                    [
                        {
                            "order": 1,
                            "title": "List subjects",
                            "description": "d",
                            "success_criteria": "subjects listed",
                            "verification": {
                                "type": "tool_output",
                                "tool": "watch_list",
                                "contains": "14",
                            },
                        }
                    ]
                )
            )
        )
        cfg = GoalsConfig(
            max_time_per_checkpoint_seconds=10,
            pause_between_checkpoints_seconds=0,
            cost_budget_per_goal_usd=100.0,
            plan_critique=False,
            deliberate=True,
        )
        gm = GoalManager(db=db, router=gm_router, config=cfg)
        g = await gm.create_goal("List subjects")
        await gm.decompose(g)
        gm_router.complete = AsyncMock(
            side_effect=lambda **kw: _LLM(
                '{"met": true, "evidence": "e", "missing": []}'
                if "You verify, independently" in kw["messages"][0]["content"]
                else "Summary."
            )
        )

        agent = MagicMock()
        outputs = ["{'count': 12}", "{'count': 14}"]
        agent.prompts = []

        async def _submit(_source: Any, prompt: str, **kw: Any) -> _Resp:
            agent.prompts.append(prompt)
            out = outputs.pop(0) if outputs else "ok"
            hooks = current_run_hooks()
            hooks.on_tool_executed("watch_list", {}, None)
            hooks.on_tool_result(
                "watch_list", {}, MagicMock(to_dict=lambda o=out: o, data={})
            )
            return _Resp()

        agent.submit_task = AsyncMock(side_effect=_submit)
        agent._router.cost_tracker.task_total = 0.0
        agent._router.cost_tracker.daily_total = 0.0
        agent._stop_file_present = MagicMock(return_value=False)
        agent._config.workspace = ""
        agent._config.project_root = tmp_path
        lesson = _lesson("knowledge:learned/lessons/first-page.md")

        async def recall(_query: str, limit: int = 4) -> list[OfferedLesson]:
            return [OfferedLesson(lesson.ref, lesson.title, lesson.body)]

        agent.recall_lesson_items = recall
        taught: list[dict[str, Any]] = []

        async def record_lesson(lesson_: dict[str, Any], source: str) -> bool:
            taught.append(lesson_)
            return True

        agent._learner.record_lesson = record_lesson

        async def think(**kw: Any) -> _LLM:
            system = kw["messages"][0]["content"]
            if "planning step of an autonomous agent" in system:
                return _LLM(
                    json.dumps(
                        {
                            "approach": "Read the list once with watch_list.",
                            "steps": ["call watch_list", "report the count"],
                            "assumptions": ["one read returns every subject"],
                            "risks": ["the tool times out"],
                            "lessons_used": ["L1"],
                        }
                    )
                )
            if "compare a plan with how its attempt failed" in system:
                return _LLM(
                    json.dumps(
                        {
                            "foreseen": False,
                            "broken_assumption": "one read returns every subject",
                            "lesson": {
                                "title": "Avoid: single-read lists",
                                "when": "listing subjects",
                                "lesson": "The first read is paginated; read until the count is stable.",
                            },
                        }
                    )
                )
            return _LLM("Summary.")

        agent._router.complete = AsyncMock(side_effect=think)
        runner = GoalRunner(agent=agent, goal_manager=gm, gateway=None, config=cfg)
        await runner.start_goal(g.goal_id)
        for _ in range(60):
            if runner._current_task is None:
                break
            await asyncio.wait_for(runner._current_task, timeout=20)

        planner_input = agent._router.complete.call_args_list[0].kwargs["messages"][1][
            "content"
        ]
        assert "[L1] Avoid: trusting the first page" in planner_input
        rows = await db.execute(
            "SELECT attempt, passed, gate, surprise, broken_assumption, steps_planned, "
            "steps_used, lessons_used FROM plan_outcomes WHERE goal_id = ? ORDER BY id",
            (g.goal_id,),
        )
        assert [
            (r["attempt"], r["passed"], r["gate"], r["surprise"]) for r in rows
        ] == [
            (1, 0, "verification", 1),
            (2, 1, "", 0),
        ]
        assert rows[0]["broken_assumption"] == "one read returns every subject"
        assert (rows[0]["steps_planned"], rows[0]["steps_used"]) == (2, 1)
        assert json.loads(rows[0]["lessons_used"]) == [lesson.ref]
        facts = await RunLedger(db).entries(g.goal_id, kinds=("fact",))
        assert any("Assumption that broke on attempt 1" in f.content for f in facts)
        assert taught and taught[0]["title"] == "Avoid: single-read lists"
        st = (await PlanOutcomes(db).stats([lesson.ref]))[lesson.ref]
        assert (st["uses"], st["passes"], st["fails"]) == (2, 1, 1)
        assert (await gm.get_goal(g.goal_id)).status == "completed"
