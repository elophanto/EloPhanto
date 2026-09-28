"""Phase 5 of docs/94 — learning that closes, a health digest, a cacheable prompt."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.autonomy_health import alerts, collect, render
from core.config import GoalsConfig
from core.database import Database
from core.goal_manager import GoalManager
from core.goal_runner import GoalRunner
from core.run_ledger import RunLedger


@pytest.fixture
async def db(tmp_path: Path):
    d = Database(tmp_path / "p5.db")
    await d.initialize()
    yield d
    await d.close()


class TestFailuresTeach:
    def _learner(self, tmp_path: Path, reply: str) -> Any:
        from core.learner import LessonExtractor

        router = MagicMock()
        router.complete = AsyncMock(return_value=MagicMock(content=reply))
        learner = LessonExtractor.__new__(LessonExtractor)
        learner._enabled = True
        learner._router = router
        learner._instinct_store = None
        learner.written = []

        async def write(lesson: dict[str, Any], goal: str) -> None:
            learner.written.append(lesson)

        learner._write_lesson = write
        return learner

    async def test_a_looping_run_yields_an_avoid_lesson(self, tmp_path: Path) -> None:
        reply = json.dumps(
            {"lessons": [{"title": "Avoid: re-reading the same page", "when": "w", "lesson": "l"}]}
        )
        learner = self._learner(tmp_path, reply)
        await learner.extract_and_store(
            "Collect prices",
            "Stopped (loop detected on browser_navigate (x4)) after 30 steps.",
            "incomplete",
            ["browser_navigate"],
        )
        assert len(learner.written) == 1 and "failure" in learner.written[0]["tags"]

    async def test_an_interruption_teaches_nothing(self, tmp_path: Path) -> None:
        learner = self._learner(tmp_path, '{"lessons": []}')
        await learner.extract_and_store(
            "Collect prices",
            "Stopped (preempted by higher-priority task) after 3 steps.",
            "incomplete",
            [],
        )
        learner._router.complete.assert_not_awaited()


class TestInstinctReadPath:
    def test_only_confirmed_instincts_and_cached(self, tmp_path: Path) -> None:
        from core.instinct import Instinct, InstinctStore

        store = InstinctStore(tmp_path, project_hash="p")
        store.save(Instinct(id="a", trigger="t1", action="a1", observation_count=1))
        store.save(Instinct(id="b", trigger="t2", action="a2", observation_count=4))
        assert [i.id for i in store.confirmed()] == ["b"]
        store.save(Instinct(id="c", trigger="t3", action="a3", observation_count=9))
        assert [i.id for i in store.confirmed()] == ["b"]  # cached
        assert sorted(i.id for i in store.confirmed(ttl_seconds=0)) == ["b", "c"]


class TestPlanUsesLessons:
    async def test_lessons_reach_the_planner(self) -> None:
        from core.deliberation import plan_checkpoint

        router = MagicMock()
        router.complete = AsyncMock(return_value=MagicMock(content='{"approach": "x"}', reasoning="", cost_estimate=0))
        await plan_checkpoint(
            router, goal="g", order=1, total=1, title="t", description="d", criteria="c",
            stage="s", ledger_text="", attempt=1, lessons="LESSONS:\n- Avoid: x: never do y",
        )
        assert "never do y" in router.complete.call_args.kwargs["messages"][1]["content"]


class TestHealthDigest:
    async def test_it_names_what_needs_the_operator(self, db: Database) -> None:
        gm = GoalManager(db=db, router=AsyncMock(), config=GoalsConfig())
        stalled = await gm.create_goal("Stalled goal")
        await gm._update_status(stalled.goal_id, "active")
        busy = await gm.create_goal("Busy goal")
        await db.execute_insert(
            "INSERT INTO goal_checkpoints (goal_id, checkpoint_order, title, description) "
            "VALUES (?, 1, 't', 'd')",
            (busy.goal_id,),
        )
        await gm._update_status(busy.goal_id, "active")
        led = RunLedger(db)
        for _ in range(3):
            await led.add(busy.goal_id, "failure", "receipt gate refused: x", checkpoint_order=1)
        await led.add(busy.goal_id, "handoff", "[preempted] ...", checkpoint_order=1)
        runner = MagicMock(current_goal_id=None)
        report = await collect(db, runner=runner)
        problems = alerts(report)
        assert any("Stalled goal" in p for p in problems)
        assert any("failing repeatedly" in p for p in problems)
        assert any("waiting while the runner is idle" in p for p in problems)
        text = render(report)
        assert "NEEDS YOU" in text and "receipt gate 3" in text and "preempted 1" in text

    async def test_the_daily_broadcast_is_sent_once(self, db: Database) -> None:
        gm = GoalManager(db=db, router=AsyncMock(), config=GoalsConfig())
        gateway = MagicMock()
        gateway.broadcast = AsyncMock()
        cfg = GoalsConfig(health_digest_hour_utc=0)
        runner = GoalRunner(agent=MagicMock(), goal_manager=gm, gateway=gateway, config=cfg)
        assert await runner.maybe_send_health_digest() is True
        assert await runner.maybe_send_health_digest() is False
        data = gateway.broadcast.call_args.args[0].data
        assert data["notification_type"] == "autonomy_health" and "Autonomy health" in data["text"]


class TestCacheablePrompt:
    def test_static_first_clock_and_task_last(self) -> None:
        from core.planner import build_system_prompt

        prompt = build_system_prompt(
            identity_context="<identity_state>mood</identity_state>",
            runtime_state="<runtime_state>procs=3</runtime_state>",
            current_goal="Write the report",
            available_skills="<skill>x</skill>",
        )
        behavior = prompt.index("<behavior>")
        assert prompt.index("<identity_state>") > behavior
        assert prompt.index("<runtime_state>") > behavior
        assert prompt.rstrip().endswith("</runtime_context>")
        assert prompt.index("CURRENT TASK: Write the report") > prompt.index("<skill>x</skill>")
        # Two different tasks share everything up to the dynamic tail.
        other = build_system_prompt(
            identity_context="<identity_state>other</identity_state>",
            runtime_state="<runtime_state>procs=9</runtime_state>",
            current_goal="Something else",
        )
        shared = 0
        for a, b in zip(prompt, other, strict=False):
            if a != b:
                break
            shared += 1
        assert shared >= behavior

    async def test_cached_tokens_are_read_and_billed_at_half(self) -> None:
        from core.zai_adapter import ZaiAdapter

        adapter = ZaiAdapter.__new__(ZaiAdapter)
        adapter._api_key = "k"
        adapter._base_url = "https://example.invalid"
        cached = {"n": 800}

        async def post(url: str, headers: Any = None, json: Any = None) -> Any:
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 0,
                    "prompt_tokens_details": {"cached_tokens": cached["n"]},
                },
            }
            return r

        adapter._client = MagicMock()
        adapter._client.post = post
        hit = await adapter.complete([{"role": "user", "content": "hi"}], "glm-5.3")
        cached["n"] = 0
        miss = await adapter.complete([{"role": "user", "content": "hi"}], "glm-5.3")
        assert hit.cached_tokens == 800 and miss.cached_tokens == 0
        assert hit.cost_estimate == pytest.approx(miss.cost_estimate * 0.6)
