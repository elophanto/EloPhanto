"""Phase 0 of docs/94-LONG-RUN-AUTONOMY-REVIEW.md — the defects that broke
long unattended runs.

Each test pins one failure mode found in the code or the live DB on
2026-09-28, stated as the behaviour the operator relies on.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.checkpoint_receipt import verify_checkpoint_receipt
from core.config import GoalsConfig
from core.database import Database
from core.execution_context import current_context, execution_context
from core.goal_manager import GoalManager
from core.goal_runner import GoalRunner
from core.loop_detect import LoopDetector
from core.run_hooks import current_run_hooks, run_hooks

# ---------------------------------------------------------------------------
# F4 — per-task hooks
# ---------------------------------------------------------------------------


class TestRunHooksAreTaskLocal:
    async def test_two_waiting_loops_never_see_each_others_hooks(self) -> None:
        """The mind and the goal runner used to assign hooks on the shared
        executor before waiting for AGENT_LOOP, so two waiters restored each
        other's values. Task-local hooks cannot cross."""
        seen: dict[str, list[str]] = {"a": [], "b": []}
        gate = asyncio.Event()

        async def loop(name: str) -> None:
            with run_hooks(on_tool_executed=lambda t, p, e: seen[name].append(t)):
                await gate.wait()  # both "waiting for the slot" at once
                hooks = current_run_hooks()
                assert hooks is not None and hooks.on_tool_executed is not None
                hooks.on_tool_executed(f"tool_{name}", {}, None)

        ta = asyncio.create_task(loop("a"))
        tb = asyncio.create_task(loop("b"))
        await asyncio.sleep(0)
        gate.set()
        await asyncio.gather(ta, tb)
        assert seen == {"a": ["tool_a"], "b": ["tool_b"]}

    async def test_hooks_do_not_leak_past_the_block(self) -> None:
        with run_hooks(approval_callback=lambda *a: True):
            assert current_run_hooks() is not None
        assert current_run_hooks() is None

    async def test_executor_prefers_the_task_hook_and_reports_soft_failures(
        self,
    ) -> None:
        from core.executor import Executor

        ex = Executor.__new__(Executor)
        ex._on_tool_executed = None
        ex._on_tool_result = None
        calls: list[tuple[str, str | None]] = []
        with run_hooks(on_tool_executed=lambda t, p, e: calls.append((t, e))):
            ex._fire_tool_executed("x", {}, None)
            ex._fire_tool_executed("y", {}, "tool reported failure")
        ex._fire_tool_executed("z", {}, None)  # outside: no task hook
        assert calls == [("x", None), ("y", "tool reported failure")]


# ---------------------------------------------------------------------------
# F3 — which goal a run belongs to
# ---------------------------------------------------------------------------


class TestGoalIdTravelsWithTheTask:
    def test_goal_id_inherits_and_clears(self) -> None:
        assert current_context().goal_id is None
        with execution_context(goal_id="g1"):
            assert current_context().goal_id == "g1"
            with execution_context():
                assert current_context().goal_id == "g1"  # inherited
            with execution_context(goal_id=""):
                assert current_context().goal_id is None  # cleared
        assert current_context().goal_id is None


# ---------------------------------------------------------------------------
# F8 — receipts are what tools returned
# ---------------------------------------------------------------------------


class TestReceiptGate:
    def test_a_count_in_call_parameters_is_not_a_receipt(self) -> None:
        """'Publish 3 blog posts' used to pass on web_search max_results=3."""
        trail = [
            {
                "tool": "web_search",
                "status": "ok",
                "summary": "search max_results=3",
                "data": {"max_results": "3"},
                "output": "{'results': ['a', 'b']}",
            }
        ]
        v = verify_checkpoint_receipt("Publish 3 blog posts", tool_trace=trail)
        assert not v.ok and "returned" in v.reason

    def test_the_same_count_in_a_tool_result_is(self) -> None:
        trail = [
            {
                "tool": "blog_publish",
                "status": "ok",
                "summary": "publish",
                "data": {},
                "output": "{'published': 3}",
            }
        ]
        assert verify_checkpoint_receipt("Publish 3 blog posts", tool_trace=trail).ok

    def test_a_trail_of_failed_calls_is_not_a_receipt(self) -> None:
        trail = [
            {
                "tool": "blog_publish",
                "status": "error",
                "error": "401",
                "summary": "publish",
            }
        ]
        v = verify_checkpoint_receipt("Blog post is published", tool_trace=trail)
        assert not v.ok and "no successful tool call" in v.reason

    def test_zero_tools_never_passes_on_summary_prose(self) -> None:
        v = verify_checkpoint_receipt(
            "Evidence for 4 brands collected",
            tool_trace=[],
            assistant_summary="Collected evidence for 4 brands.",
        )
        assert not v.ok


# ---------------------------------------------------------------------------
# Loop detector — "Blocked" means blocked
# ---------------------------------------------------------------------------


class TestLoopBlockIsEnforced:
    def test_a_blocked_call_is_reported_blocked(self) -> None:
        d = LoopDetector(warn_at=2, block_at=3, abort_at=4)
        for _ in range(3):
            d.record("file_read", {"path": "a"}, "same")
        assert d.is_blocked("file_read", {"path": "a"})
        assert not d.is_blocked("file_read", {"path": "b"})
        d.reset()
        assert not d.is_blocked("file_read", {"path": "a"})


# ---------------------------------------------------------------------------
# F6 — a stopped run leaves something to resume from
# ---------------------------------------------------------------------------


class TestStoppedRunMemory:
    def test_the_summary_says_why_and_where(self) -> None:
        from core.agent import _describe_stopped_run

        text = _describe_stopped_run(
            "preempted by higher-priority task",
            42,
            ["web_search", "file_write", "web_search", "watch_analyze"],
            [
                {"role": "user", "content": "go"},
                {
                    "role": "assistant",
                    "content": "Collected 3 of 4 brands; Brand D next.",
                },
                {"role": "tool", "content": "{}"},
            ],
        )
        assert "preempted" in text and "42 steps" in text
        assert "watch_analyze" in text and "Brand D next" in text
        assert "Max steps reached" not in text


# ---------------------------------------------------------------------------
# F12 — a provider out of credit is parked, not retried every minute
# ---------------------------------------------------------------------------


class TestBillingErrorsParkTheProvider:
    def test_cooldown_is_per_failure(self) -> None:
        from core.router import LLMRouter

        r = LLMRouter.__new__(LLMRouter)
        r._provider_health = {}
        r._provider_failed_at = {}
        r._provider_cooldown = {}
        r._mark_unhealthy("zai", cooldown=LLMRouter.BILLING_RECOVERY_SECONDS)
        r._provider_failed_at["zai"] = time.time() - 120  # two minutes ago
        assert not r._is_healthy("zai")  # a rate limit would have recovered
        r._mark_unhealthy("codex")
        r._provider_failed_at["codex"] = time.time() - 120
        assert r._is_healthy("codex")


# ---------------------------------------------------------------------------
# F11 — compression sees the real size and its breaker can trip
# ---------------------------------------------------------------------------


class TestCompression:
    def test_tool_call_arguments_count(self) -> None:
        from core.context_compressor import _message_tokens

        big = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"function": {"name": "file_write", "arguments": "x" * 40_000}}
            ],
        }
        assert _message_tokens(big) >= 10_000

    async def test_a_failed_summary_trips_the_breaker(self) -> None:
        from core.context_compressor import CompactionCircuitBreaker, tiered_compress

        router = MagicMock()
        router.complete = AsyncMock(side_effect=RuntimeError("provider down"))
        breaker = CompactionCircuitBreaker()
        msgs: list[dict[str, Any]] = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": "y" * 4000}
            for i in range(40)
        ]
        for _ in range(3):
            await tiered_compress(
                msgs, router, context_window=40_000, circuit_breaker=breaker
            )
        assert breaker.is_tripped()


# ---------------------------------------------------------------------------
# Goal manager / runner fixtures
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
    d = Database(tmp_path / "phase0.db")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def goals_config() -> GoalsConfig:
    return GoalsConfig(
        max_time_per_checkpoint_seconds=10,
        max_total_time_per_goal_seconds=600,
        cost_budget_per_goal_usd=5.0,
        pause_between_checkpoints_seconds=0,
        auto_continue=True,
    )


@pytest.fixture
def router() -> AsyncMock:
    r = AsyncMock()
    r.complete = AsyncMock(return_value=_LLM("Summary."))
    return r


@pytest.fixture
def gm(db: Database, router: AsyncMock, goals_config: GoalsConfig) -> GoalManager:
    return GoalManager(db=db, router=router, config=goals_config)


def _plan(n: int, criteria: str = "work recorded") -> str:
    return json.dumps(
        [
            {"order": i, "title": f"Step {i}", "description": "d", "success_criteria": criteria}
            for i in range(1, n + 1)
        ]
    )


async def _goal(gm: GoalManager, router: AsyncMock, n: int = 2, text: str = "A goal"):
    router.complete = AsyncMock(return_value=_LLM(_plan(n)))
    g = await gm.create_goal(text)
    await gm.decompose(g)
    router.complete = AsyncMock(return_value=_LLM("Summary."))
    return g


def _agent(responses: list[_Resp] | None = None, *, cost: float = 0.0) -> MagicMock:
    """A fake agent whose runs fire the task's tool hook like real work."""
    agent = MagicMock()
    queue = list(responses or [])
    prompts: list[str] = []
    kwargs_seen: list[dict[str, Any]] = []

    async def _submit(_source: Any, prompt: str, **kw: Any) -> _Resp:
        prompts.append(prompt)
        kwargs_seen.append(kw)
        hooks = current_run_hooks()
        if hooks and hooks.on_tool_executed:
            hooks.on_tool_executed("knowledge_search", {"query": "x"}, None)
        agent._router.cost_tracker.task_total = cost
        return queue.pop(0) if queue else _Resp()

    agent.submit_task = AsyncMock(side_effect=_submit)
    agent._router.cost_tracker.task_total = 0.0
    agent._router.cost_tracker.daily_total = 0.0
    agent._stop_file_present = MagicMock(return_value=False)
    agent.prompts = prompts
    agent.kwargs_seen = kwargs_seen
    return agent


async def _drain(runner: GoalRunner) -> None:
    for _ in range(50):
        task = runner._current_task
        if task is None:
            return
        await asyncio.wait_for(task, timeout=20)


# ---------------------------------------------------------------------------
# F1 — cost is charged to the goal; F2 — the budget starts at the slot
# ---------------------------------------------------------------------------


class TestGoalAccounting:
    async def test_each_checkpoint_charges_its_run_to_the_goal(
        self, gm: GoalManager, router: AsyncMock, goals_config: GoalsConfig
    ) -> None:
        g = await _goal(gm, router, n=2)
        agent = _agent(cost=1.25)
        runner = GoalRunner(agent=agent, goal_manager=gm, gateway=None, config=goals_config)
        await runner.start_goal(g.goal_id)
        await _drain(runner)
        refreshed = await gm.get_goal(g.goal_id)
        assert refreshed is not None and abs(refreshed.cost_usd - 2.5) < 1e-6

    async def test_the_checkpoint_budget_is_handed_to_the_loop_not_wrapped_around_the_queue(
        self, gm: GoalManager, router: AsyncMock, goals_config: GoalsConfig
    ) -> None:
        g = await _goal(gm, router, n=1)
        agent = _agent()
        runner = GoalRunner(agent=agent, goal_manager=gm, gateway=None, config=goals_config)
        await runner.start_goal(g.goal_id)
        await _drain(runner)
        kw = agent.kwargs_seen[0]
        assert kw["time_budget_seconds"] == 10.0
        assert kw["isolated_history"] is True
        assert "checkpoint 1/1: Step 1" in kw["memory_label"]

    async def test_a_spent_budget_is_a_timeout_failure_with_a_retry(
        self, gm: GoalManager, router: AsyncMock, goals_config: GoalsConfig
    ) -> None:
        g = await _goal(gm, router, n=1)
        agent = _agent([_Resp(stop_reason="time_limit", content="Task stopped")])
        runner = GoalRunner(agent=agent, goal_manager=gm, gateway=None, config=goals_config)
        await runner.start_goal(g.goal_id)
        await _drain(runner)
        assert len(agent.prompts) == 2  # retried once, then passed
        assert "timed out" in agent.prompts[1].lower()


# ---------------------------------------------------------------------------
# F9 — preemption resumes, it does not restart blind
# ---------------------------------------------------------------------------


class TestPreemptionLeavesANote:
    async def test_the_next_attempt_is_told_what_was_already_done(
        self, gm: GoalManager, router: AsyncMock, goals_config: GoalsConfig
    ) -> None:
        g = await _goal(gm, router, n=1)
        agent = _agent([_Resp(preempted=True, stop_reason="preempted", steps_taken=17)])
        runner = GoalRunner(agent=agent, goal_manager=gm, gateway=None, config=goals_config)
        await runner.start_goal(g.goal_id)
        await _drain(runner)
        assert len(agent.prompts) == 2
        assert "RESUME NOTE" in agent.prompts[1]
        assert "17 steps" in agent.prompts[1] and "knowledge_search" in agent.prompts[1]
        cp = (await gm.get_checkpoints(g.goal_id))[0]
        assert cp.status == "completed" and cp.attempts == 1


# ---------------------------------------------------------------------------
# F10 — a goal never sits 'active' with nothing running it
# ---------------------------------------------------------------------------


class TestNoSilentStalls:
    async def test_resume_retries_the_checkpoint_that_failed_out(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        g = await _goal(gm, router, n=2)
        for _ in range(3):
            await gm.mark_checkpoint_active(g.goal_id, 1)
            await gm.mark_checkpoint_failed(g.goal_id, 1, "boom")
        assert (await gm.get_goal(g.goal_id)).status == "paused"
        assert await gm.resume_goal(g.goal_id)
        cp = (await gm.get_checkpoints(g.goal_id))[0]
        assert cp.status == "pending" and cp.attempts == 0
        assert "boom" in (cp.result_summary or "")  # the reason survives

    async def test_no_pending_work_is_diagnosed_not_ignored(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        g = await _goal(gm, router, n=2)
        await gm.mark_checkpoint_complete(g.goal_id, 1, "done")
        await gm._db.execute(
            "UPDATE goal_checkpoints SET status = 'failed', result_summary = 'x' "
            "WHERE goal_id = ? AND checkpoint_order = 2",
            (g.goal_id,),
        )
        state, detail = await gm.diagnose_no_pending(g.goal_id)
        assert state == "failed_checkpoint" and "checkpoint 2" in detail

        await gm._db.execute(
            "DELETE FROM goal_checkpoints WHERE goal_id = ? AND checkpoint_order = 2",
            (g.goal_id,),
        )
        state, _ = await gm.diagnose_no_pending(g.goal_id)
        # Every checkpoint done is "verify the goal now", not "completed"
        # (docs/94 §11): the runner's final verification decides.
        assert state == "all_done"
        assert (await gm.get_goal(g.goal_id)).status == "active"

    async def test_the_runner_moves_on_to_the_next_active_goal(
        self, gm: GoalManager, router: AsyncMock, goals_config: GoalsConfig
    ) -> None:
        first = await _goal(gm, router, n=1, text="first")
        second = await _goal(gm, router, n=1, text="second")
        agent = _agent()
        runner = GoalRunner(agent=agent, goal_manager=gm, gateway=None, config=goals_config)
        await runner.start_goal(first.goal_id)
        await _drain(runner)
        assert (await gm.get_goal(first.goal_id)).status == "completed"
        assert (await gm.get_goal(second.goal_id)).status == "completed"

    async def test_resume_while_busy_queues_instead_of_stranding(
        self, gm: GoalManager, router: AsyncMock, goals_config: GoalsConfig
    ) -> None:
        running = await _goal(gm, router, n=1, text="running")
        waiting = await _goal(gm, router, n=1, text="waiting")
        await gm.pause_goal(waiting.goal_id, reason="paused by operator")
        gate = asyncio.Event()
        agent = _agent()
        original = agent.submit_task.side_effect

        async def _slow(*a: Any, **kw: Any) -> _Resp:
            await gate.wait()
            return await original(*a, **kw)

        agent.submit_task = AsyncMock(side_effect=_slow)
        runner = GoalRunner(agent=agent, goal_manager=gm, gateway=None, config=goals_config)
        await runner.start_goal(running.goal_id)
        await asyncio.sleep(0.05)
        assert await runner.resume(waiting.goal_id) is True  # queued, not refused
        gate.set()
        await _drain(runner)
        assert (await gm.get_goal(waiting.goal_id)).status == "completed"

    async def test_the_stop_sentinel_refunds_and_leaves_the_goal_active(
        self, gm: GoalManager, router: AsyncMock, goals_config: GoalsConfig
    ) -> None:
        g = await _goal(gm, router, n=1)
        agent = _agent([_Resp(stop_reason="stop_file", content="Hard-stopped")])
        runner = GoalRunner(agent=agent, goal_manager=gm, gateway=None, config=goals_config)
        await runner.start_goal(g.goal_id)
        await _drain(runner)
        assert len(agent.prompts) == 1
        cp = (await gm.get_checkpoints(g.goal_id))[0]
        assert cp.status == "pending" and cp.attempts == 0
        assert (await gm.get_goal(g.goal_id)).status == "active"


# ---------------------------------------------------------------------------
# Kill criterion reads evidence, not its own wording
# ---------------------------------------------------------------------------


class TestKillCriterion:
    async def test_it_ignores_its_own_numbers_and_absent_evidence(
        self, gm: GoalManager, router: AsyncMock
    ) -> None:
        g = await _goal(gm, router, n=1)
        g.kill_criterion = "If fewer than 5 pre-orders in 14 days, abandon."
        g.created_at = "2020-01-01T00:00:00+00:00"
        killed, _ = await gm.evaluate_kill_criterion(g, evidence_text="")
        assert not killed  # no measured count → no kill on phrasing
        killed, reason = await gm.evaluate_kill_criterion(g, evidence_text="pre-orders: 2")
        assert killed and "observed=2" in reason
        killed, _ = await gm.evaluate_kill_criterion(g, evidence_text="pre-orders: 7")
        assert not killed

    def test_an_infinite_budget_snapshot_parses(self) -> None:
        ctx = "[budget_paused] limit_cost=inf limit_time=inf limit_llm=200 | LLM call limit"
        assert GoalManager._budget_limits_raised(
            ctx, cost_budget_usd=float("inf"), max_time_seconds=float("inf"), max_llm_calls=400
        )
        assert not GoalManager._budget_limits_raised(
            ctx, cost_budget_usd=float("inf"), max_time_seconds=float("inf"), max_llm_calls=200
        )


# ---------------------------------------------------------------------------
# F5 — the consolidator keeps the index honest and never deletes files
# ---------------------------------------------------------------------------


class TestConsolidatorNeverDeletesKnowledge:
    async def test_files_survive_and_only_missing_files_leave_the_index(
        self, db: Database, tmp_path: Path
    ) -> None:
        from core.knowledge_consolidator import KnowledgeConsolidator

        kdir = tmp_path / "knowledge" / "learned" / "lessons"
        kdir.mkdir(parents=True)
        kept = kdir / "kept.md"
        kept.write_text("# Lesson\nnever redo receipted work\n")
        now = "2019-01-01T00:00:00+00:00"  # ancient: the old age cap/prune target
        for fp, heading, content in [
            ("learned/lessons/kept.md", "Lesson", "part one"),
            ("learned/lessons/kept.md", "Lesson", "part two"),  # same heading, new text
            ("learned/lessons/gone.md", "Old", "file was deleted"),
        ]:
            await db.execute_insert(
                "INSERT INTO knowledge_chunks (file_path, heading_path, content, scope, "
                "file_updated_at, indexed_at) VALUES (?, ?, ?, 'learned', ?, ?)",
                (fp, heading, content, now, now),
            )
        stats = await KnowledgeConsolidator(db, tmp_path).consolidate()
        assert kept.exists()
        rows = await db.execute("SELECT file_path, content FROM knowledge_chunks")
        assert sorted(r["content"] for r in rows) == ["part one", "part two"]
        assert stats["pruned"] == 1 and stats["merged"] == 0
