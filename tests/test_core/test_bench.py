"""docs/95 Phase E — a benchmark from the agent's own history."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.bench import (
    BenchCase,
    Replay,
    capture,
    fingerprint,
    history,
    load_cases,
    run_bench,
    run_case,
)
from core.config import Config, GoalsConfig, RoutingConfig
from core.database import Database
from core.executor import Executor
from core.goal_manager import GoalManager
from core.goal_runner import GoalRunner
from core.run_hooks import current_run_hooks, run_hooks
from core.tool_traces import attempt_trace, prune, redact_params
from tools.base import ToolResult


@pytest.fixture
async def db(tmp_path: Path):
    d = Database(tmp_path / "bench.db")
    await d.initialize()
    yield d
    await d.close()


@dataclass
class _LLM:
    content: str
    reasoning: str = ""
    cost_estimate: float = 0.0


@dataclass
class _Resp:
    content: str = "Listed 14 subjects."
    preempted: bool = False
    stop_reason: str = "completed"
    steps_taken: int = 1


class _LiveTool:
    """A tool that must never run during a replay."""

    name = "watch_list"
    group = "watch"
    resources: frozenset[Any] = frozenset()

    def __init__(self) -> None:
        self.calls = 0

    def validate_input(self, params: dict[str, Any]) -> list[str]:
        return []

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        self.calls += 1
        raise AssertionError("a real tool ran during a replay")


class TestRedaction:
    def test_secrets_and_vault_values_are_never_stored(self) -> None:
        assert redact_params("vault_set", {"key": "openai", "value": "sk-1"}) == {
            "key": "[redacted]",
            "value": "[redacted]",
        }
        out = redact_params(
            "http_request",
            {"url": "u", "headers": {"Authorization": "x", "api_key": "k"}},
        )
        assert out["url"] == "u" and out["headers"]["api_key"] == "[redacted]"
        assert redact_params("t", {"password": "p", "token": "t", "n": 1}) == {
            "password": "[redacted]",
            "token": "[redacted]",
            "n": 1,
        }


class TestReplay:
    async def test_best_match_then_same_answer_then_miss(self) -> None:
        replay = Replay(
            [
                {
                    "tool": "web_fetch",
                    "params": {"url": "a"},
                    "status": "ok",
                    "output": '{"success": true, "body": "A"}',
                },
                {
                    "tool": "web_fetch",
                    "params": {"url": "b"},
                    "status": "ok",
                    "output": '{"success": true, "body": "B", "screenshot_path": "/x.png"}',
                },
                {
                    "tool": "file_write",
                    "params": {"path": "p"},
                    "status": "error",
                    "error": "disk full",
                    "output": "",
                },
            ]
        )
        b = await replay("web_fetch", {"url": "b"})
        assert b.success and b.data == {"body": "B"}  # no screenshot to look at
        assert (await replay("web_fetch", {"url": "b"})).data == {"body": "B"}
        a = await replay("web_fetch", {"url": "zzz"})
        assert a.data == {"body": "A"}
        failed = await replay("file_write", {"path": "p"})
        assert not failed.success and failed.error == "disk full"
        miss = await replay("shell_execute", {"command": "ls"})
        assert not miss.success and "web_fetch" in (miss.error or "")
        assert replay.misses == ["shell_execute"]

    async def test_the_executor_never_runs_the_tool(self) -> None:
        tool = _LiveTool()
        registry = MagicMock()
        registry.get = MagicMock(return_value=tool)
        ex = Executor(config=Config(permission_mode="ask_always"), registry=registry)
        seen: list[tuple[str, Any]] = []
        replay = Replay(
            [
                {
                    "tool": "watch_list",
                    "params": {},
                    "status": "ok",
                    "output": '{"success": true, "count": 14}',
                }
            ]
        )
        with run_hooks(
            tool_interceptor=replay,
            on_tool_executed=lambda n, p, e: seen.append((n, e)),
            record_memory=False,
        ):
            res = await ex.execute(
                {"id": "1", "function": {"name": "watch_list", "arguments": "{}"}}
            )
            assert current_run_hooks().record_memory is False
        assert tool.calls == 0
        assert res.result.data == {"count": 14}
        assert seen == [("watch_list", None)]

    async def test_a_replay_leaves_no_memory(self) -> None:
        from core.agent import Agent

        fake = MagicMock()
        fake._memory_manager.store_task_memory = AsyncMock()
        with run_hooks(record_memory=False):
            await Agent._store_task_memory(fake, "g", "s", "completed", ["t"])
        fake._memory_manager.store_task_memory.assert_not_awaited()


def _config(tmp_path: Path, model: str = "gpt-6-astra") -> Config:
    cfg = Config(project_root=tmp_path)
    cfg.llm.routing = {
        "planning": RoutingConfig(preferred_provider="codex", models={"codex": model})
    }
    return cfg


class TestRecordToReplay:
    async def _goal_with_history(self, db: Database, tmp_path: Path) -> str:
        """A goal whose checkpoint failed once (count 12) and then passed."""
        router = AsyncMock()
        router.complete = AsyncMock(
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
            deliberate=False,
        )
        gm = GoalManager(db=db, router=router, config=cfg)
        g = await gm.create_goal("List subjects")
        await gm.decompose(g)
        router.complete = AsyncMock(
            side_effect=lambda **kw: _LLM(
                '{"met": true, "evidence": "e", "missing": []}'
                if "You verify, independently" in kw["messages"][0]["content"]
                else "Summary."
            )
        )
        outputs = [12, 14]
        agent = MagicMock()

        async def _submit(_source: Any, prompt: str, **kw: Any) -> _Resp:
            count = outputs.pop(0)
            hooks = current_run_hooks()
            params = {"register": "main", "api_key": "secret-1"}
            hooks.on_tool_executed("watch_list", params, None)
            hooks.on_tool_result(
                "watch_list", params, ToolResult(success=True, data={"count": count})
            )
            return _Resp()

        agent.submit_task = AsyncMock(side_effect=_submit)
        agent._router.cost_tracker.task_total = 0.0
        agent._router.cost_tracker.daily_total = 0.0
        agent._stop_file_present = MagicMock(return_value=False)
        agent._config.workspace = ""
        agent._config.bench.enabled = False
        runner = GoalRunner(agent=agent, goal_manager=gm, gateway=None, config=cfg)
        await runner.start_goal(g.goal_id)
        for _ in range(60):
            if runner._current_task is None:
                break
            await asyncio.wait_for(runner._current_task, timeout=20)
        return g.goal_id

    async def test_traces_are_kept_redacted_and_marked(
        self, db: Database, tmp_path: Path
    ) -> None:
        goal_id = await self._goal_with_history(db, tmp_path)
        rows = await db.execute(
            "SELECT attempt, passed, params, output FROM tool_traces WHERE goal_id = ? ORDER BY id",
            (goal_id,),
        )
        assert [(r["attempt"], r["passed"]) for r in rows] == [(1, 0), (2, 1)]
        assert json.loads(rows[0]["params"]) == {
            "register": "main",
            "api_key": "[redacted]",
        }
        assert json.loads(rows[1]["output"]) == {"success": True, "count": 14}
        await db.execute("UPDATE tool_traces SET created_at = '2000-01-01'")
        await prune(db)
        left = await db.execute(
            "SELECT passed FROM tool_traces WHERE goal_id = ?", (goal_id,)
        )
        assert [r["passed"] for r in left] == [1]

    async def test_capture_then_replay_passes_without_running_a_tool(
        self, db: Database, tmp_path: Path
    ) -> None:
        goal_id = await self._goal_with_history(db, tmp_path)
        directory = tmp_path / "cases"
        written = await capture(db, directory)
        assert [p.name for p in written] == [f"{goal_id}-1.json"]
        assert await capture(db, directory) == []  # idempotent
        (case,) = load_cases(directory)
        assert case.criteria == "subjects listed" and case.source["attempt"] == 2
        assert case.recording == await attempt_trace(
            db, goal_id=goal_id, checkpoint_order=1, attempt=2
        )
        # The ledger is what attempt 2 started from: attempt 1's failure, no later entries.
        assert "verification" in case.ledger and "attempt 2" not in case.ledger.lower()

        tool = _LiveTool()
        registry = MagicMock()
        registry.get = MagicMock(return_value=tool)
        executor = Executor(
            config=Config(permission_mode="ask_always"), registry=registry
        )
        agent = MagicMock()
        agent._config = _config(tmp_path)
        agent._router.cost_tracker.daily_total = 0.0
        agent.prompts = []

        async def _submit(_source: Any, prompt: str, **kw: Any) -> _Resp:
            agent.prompts.append(prompt)
            await executor.execute(
                {
                    "id": "c1",
                    "function": {
                        "name": "watch_list",
                        "arguments": '{"register": "main"}',
                    },
                }
            )
            return _Resp()

        agent.submit_task = AsyncMock(side_effect=_submit)
        result = await run_case(agent, case)
        assert result["passed"], result
        assert (result["steps"], result["misses"]) == (1, 0)
        assert tool.calls == 0
        assert "CURRENT CHECKPOINT (1 of 1)" in agent.prompts[0]

        run = await run_bench(agent, [case], db=db)
        assert run.score == 1.0
        (row,) = await history(db)
        assert (row["passed"], row["cases"], row["fingerprint"]) == (
            1,
            1,
            run.fingerprint,
        )

    async def test_a_replay_that_misses_the_evidence_fails(
        self, tmp_path: Path
    ) -> None:
        case = BenchCase(
            id="c",
            goal="g",
            order=1,
            total=1,
            title="List subjects",
            stage="build",
            description="d",
            criteria="exactly 14 subjects listed",
            verification="",
            ledger="",
            recording=[
                {
                    "tool": "watch_list",
                    "params": {},
                    "status": "ok",
                    "output": '{"count": 14}',
                }
            ],
        )
        agent = MagicMock()
        agent._config = _config(tmp_path)
        agent._router.cost_tracker.daily_total = 0.0
        agent.submit_task = AsyncMock(return_value=_Resp(content="There are 14."))
        result = await run_case(agent, case)
        assert not result["passed"] and result["reason"].startswith("receipt gate")


class TestFingerprint:
    def test_a_model_change_changes_the_fingerprint(self, tmp_path: Path) -> None:
        a, detail = fingerprint(_config(tmp_path))
        b, _ = fingerprint(_config(tmp_path, model="gpt-6-sol"))
        assert a != b and detail["routing"]["planning"]["model"] == "gpt-6-astra"
        skill = tmp_path / "skills" / "learned-x" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("x")
        assert fingerprint(_config(tmp_path))[0] != a
