"""Phase 3 of docs/94 — verification that is not the actor grading itself."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.checkpoint_verify import parse_checks, verify_checkpoint
from core.config import GoalsConfig
from core.database import Database
from core.goal_manager import GoalManager
from core.goal_runner import GoalRunner
from core.run_hooks import current_run_hooks
from core.run_ledger import RunLedger

OK_TRAIL = [
    {"tool": "watch_list", "status": "ok", "output": "{'count': 14, 'subjects': []}"},
    {"tool": "web_search", "status": "error", "error": "timeout", "output": "14"},
]


async def _verify(checks: Any, **kw: Any):
    base: dict[str, Any] = {
        "tool_trace": OK_TRAIL,
        "artifact_refs": ["/ws/reports/q3.md"],
        "workspace": "",
        "router": None,
        "criteria": "c",
        "result_text": "done",
    }
    base.update(kw)
    return await verify_checkpoint(checks, **base)


class TestCodeChecks:
    async def test_tool_output_reads_successful_results_only(self) -> None:
        assert (await _verify({"type": "tool_output", "tool": "watch_list", "contains": "14"})).ok
        r = await _verify({"type": "tool_output", "tool": "web_search", "contains": "14"})
        assert not r.ok and "web_search" in r.reason

    async def test_file_checks_resolve_against_the_workspace(self, tmp_path: Path) -> None:
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "q3.md").write_text("# Summary\n" + "x" * 300)
        ws = str(tmp_path)
        good = {"type": "file_exists", "path": "reports/q3.md", "contains": "summary", "min_bytes": 200}
        assert (await _verify(good, workspace=ws)).ok
        r = await _verify({"type": "file_exists", "path": "reports/missing.md"}, workspace=ws)
        assert not r.ok and "does not exist" in r.reason
        r = await _verify({**good, "min_bytes": 10_000}, workspace=ws)
        assert not r.ok and "bytes" in r.reason

    async def test_urls_must_be_public(self) -> None:
        r = await _verify({"type": "url_ok", "url": "http://127.0.0.1:8080/admin"})
        assert not r.ok and "not a public address" in r.reason
        r = await _verify({"type": "url_ok", "url": "file:///etc/passwd"})
        assert not r.ok

    async def test_artifacts_and_lists_and_unknown_types(self) -> None:
        checks = [
            {"type": "artifact", "contains": "q3.md"},
            {"type": "telepathy", "contains": "x"},  # ignored, not failed
        ]
        assert parse_checks(json.dumps(checks)) == [checks[0]]
        assert (await _verify(json.dumps(checks))).ok
        r = await _verify([{"type": "artifact", "contains": "q4.md"}])
        assert not r.ok and "q4.md" in r.reason
        assert (await _verify("")).ok and (await _verify("not json")).ok


class TestJudgment:
    async def test_a_panel_with_a_specific_blocking_finding_fails(self) -> None:
        router = MagicMock()
        router.complete = AsyncMock(
            return_value=MagicMock(
                content=json.dumps(
                    {
                        "score": 2,
                        "passed": False,
                        "findings": [
                            "The ranking puts Brand B first but its only source is a 2024 press release."
                        ],
                    }
                )
            )
        )
        r = await _verify({"type": "judgment", "pack": "analysis"}, router=router)
        assert not r.ok and r.findings and "Brand B" in r.findings[0]

    async def test_a_passing_panel_passes(self) -> None:
        router = MagicMock()
        router.complete = AsyncMock(
            return_value=MagicMock(content='{"score": 5, "passed": true, "findings": []}')
        )
        assert (await _verify({"type": "judgment", "pack": "writing"}, router=router)).ok


# ---------------------------------------------------------------------------
# Runner integration
# ---------------------------------------------------------------------------


@dataclass
class _Resp:
    content: str = "Did the work."
    preempted: bool = False
    stop_reason: str = "completed"
    steps_taken: int = 3


@dataclass
class _LLM:
    content: str


@pytest.fixture
async def db(tmp_path: Path):
    d = Database(tmp_path / "p3.db")
    await d.initialize()
    yield d
    await d.close()


def _cfg() -> GoalsConfig:
    return GoalsConfig(
        max_time_per_checkpoint_seconds=10,
        pause_between_checkpoints_seconds=0,
        cost_budget_per_goal_usd=100.0,
        plan_critique=False,
        deliberate=False,
    )


def _agent(outputs: list[str]) -> MagicMock:
    agent = MagicMock()
    queue = list(outputs)

    async def _submit(_source: Any, prompt: str, **kw: Any) -> _Resp:
        agent.prompts.append(prompt)
        hooks = current_run_hooks()
        out = queue.pop(0) if queue else "ok"
        if hooks and hooks.on_tool_executed:
            hooks.on_tool_executed("watch_list", {}, None)
        if hooks and hooks.on_tool_result:
            hooks.on_tool_result("watch_list", {}, MagicMock(to_dict=lambda o=out: o, data={}))
        return _Resp()

    agent.prompts = []
    agent.submit_task = AsyncMock(side_effect=_submit)
    agent._router.cost_tracker.task_total = 0.0
    agent._router.cost_tracker.daily_total = 0.0
    agent._stop_file_present = MagicMock(return_value=False)
    agent._config.workspace = ""
    return agent


def _plan(items: list[dict[str, Any]]) -> str:
    return json.dumps(
        [
            {"order": i, "title": it["title"], "description": "d",
             "success_criteria": "subjects listed", "verification": it.get("verification")}
            for i, it in enumerate(items, 1)
        ]
    )


async def _drain(runner: GoalRunner) -> None:
    for _ in range(60):
        t = runner._current_task
        if t is None:
            return
        await asyncio.wait_for(t, timeout=20)


class TestRunnerVerifies:
    async def test_a_failed_check_retries_with_the_reason(self, db: Database) -> None:
        router = AsyncMock()
        router.complete = AsyncMock(
            return_value=_LLM(_plan([{"title": "List", "verification": {"type": "tool_output", "tool": "watch_list", "contains": "14"}}]))
        )
        gm = GoalManager(db=db, router=router, config=_cfg())
        g = await gm.create_goal("List subjects")
        await gm.decompose(g)
        stored = (await gm.get_checkpoints(g.goal_id))[0].verification
        assert json.loads(stored)["tool"] == "watch_list"
        router.complete = AsyncMock(
            side_effect=lambda **kw: _LLM(
                '{"met": true, "evidence": "e", "missing": []}'
                if "You verify, independently" in kw["messages"][0]["content"]
                else "Summary."
            )
        )
        agent = _agent(["{'count': 12}", "{'count': 14}"])
        runner = GoalRunner(agent=agent, goal_manager=gm, gateway=None, config=_cfg())
        await runner.start_goal(g.goal_id)
        await _drain(runner)
        assert len(agent.prompts) == 2
        assert "verification: no successful 'watch_list'" in agent.prompts[1]
        assert (await gm.get_goal(g.goal_id)).status == "completed"

    async def test_the_goal_is_extended_when_the_final_check_finds_work_missing(
        self, db: Database
    ) -> None:
        router = AsyncMock()
        router.complete = AsyncMock(return_value=_LLM(_plan([{"title": "Draft report"}])))
        gm = GoalManager(db=db, router=router, config=_cfg())
        g = await gm.create_goal("Write and publish the report")
        await gm.decompose(g)
        verdicts = [
            '{"met": false, "evidence": "", "missing": ["the report was never published"]}',
            '{"met": true, "evidence": "published", "missing": []}',
        ]

        async def complete(**kw: Any) -> _LLM:
            system = kw["messages"][0]["content"]
            if "You verify, independently" in system:
                return _LLM(verdicts.pop(0))
            if "goal_revision" in system:
                return _LLM(_plan([{"title": "Publish the report"}]))
            return _LLM("Summary.")

        router.complete = AsyncMock(side_effect=complete)
        agent = _agent([])
        runner = GoalRunner(agent=agent, goal_manager=gm, gateway=None, config=_cfg())
        await runner.start_goal(g.goal_id)
        await _drain(runner)
        titles = [c.title for c in await gm.get_checkpoints(g.goal_id)]
        assert titles == ["Draft report", "Publish the report"]
        assert (await gm.get_goal(g.goal_id)).status == "completed"
        failures = await RunLedger(db).entries(g.goal_id, kinds=("failure",))
        assert any("never published" in f.content for f in failures)

    async def test_a_checkpoint_that_fails_out_is_replanned_once(self, db: Database) -> None:
        router = AsyncMock()
        router.complete = AsyncMock(
            return_value=_LLM(_plan([{"title": "Hard step", "verification": {"type": "artifact", "contains": "never.md"}}]))
        )
        gm = GoalManager(db=db, router=router, config=_cfg())
        g = await gm.create_goal("Do the hard thing")
        await gm.decompose(g)

        async def complete(**kw: Any) -> _LLM:
            system = kw["messages"][0]["content"]
            if "goal_revision" in system:
                return _LLM(_plan([{"title": "Smaller step"}]))
            if "You verify, independently" in system:
                return _LLM('{"met": true, "evidence": "e", "missing": []}')
            return _LLM("Summary.")

        router.complete = AsyncMock(side_effect=complete)
        agent = _agent([])
        runner = GoalRunner(agent=agent, goal_manager=gm, gateway=None, config=_cfg())
        await runner.start_goal(g.goal_id)
        await _drain(runner)
        cps = await gm.get_checkpoints(g.goal_id)
        assert [c.title for c in cps if c.status == "completed"] == ["Smaller step"]
        assert (await gm.get_goal(g.goal_id)).status == "completed"
        decisions = await RunLedger(db).entries(g.goal_id, kinds=("decision",))
        assert any(d.content.startswith("Automatic recovery") for d in decisions)
