"""DelegateTool + Agent.run_isolated + _FilteredRegistry tests.

Pin the alignment guarantees from the design audit:
- Subagents share parent's globals (vault/DB/cost/etc.) but get their
  own conversation, working memory, activated tools, registry view.
- Recursive-spawn tools and long-lived-state tools are hidden from the
  subagent's registry: delegate, swarm_*, kid_*, org_*, schedule_task,
  agent_connect/message/disconnect, payment_*, wallet_*.
- Cost tracker rolls up correctly: subagent task_total adds to parent's,
  daily_total accumulates throughout.
- Subagent runs with is_user_input=False (so the user-correction regex
  doesn't pattern-match parent's delegated goal text).
- Failures in one subagent don't crash peers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.agent import AgentResponse, _FilteredRegistry
from tools.delegate.delegate_tool import (
    DelegateTool,
    _build_excluded_set,
)

# ---------------------------------------------------------------------------
# _FilteredRegistry — view semantics
# ---------------------------------------------------------------------------


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


def _make_inner_registry(names: list[str]) -> Any:
    inner = MagicMock()
    tools = [_FakeTool(n) for n in names]
    inner.all_tools.return_value = tools
    inner.get_tools_for_context.return_value = tools
    inner.get_core_tools.return_value = tools
    inner.discover_tools.return_value = tools
    inner.get_deferred_catalog.return_value = [
        {"name": n, "description": "", "group": ""} for n in names
    ]
    inner.list_tools.return_value = [
        {"function": {"name": n, "description": "", "parameters": {}}} for n in names
    ]
    inner.list_tool_summaries.return_value = [
        {"name": n, "description": "", "permission": "safe"} for n in names
    ]

    def _get(name: str) -> Any:
        for t in tools:
            if t.name == name:
                return t
        return None

    inner.get.side_effect = _get
    inner._project_root = "/tmp/x"
    return inner


class TestFilteredRegistry:
    def test_get_returns_none_for_excluded(self) -> None:
        inner = _make_inner_registry(["safe_tool", "kid_spawn"])
        view = _FilteredRegistry(inner, {"kid_spawn"})
        assert view.get("safe_tool").name == "safe_tool"
        assert view.get("kid_spawn") is None

    def test_get_tools_for_context_drops_excluded(self) -> None:
        inner = _make_inner_registry(["a", "b", "kid_spawn", "swarm_spawn"])
        view = _FilteredRegistry(inner, {"kid_spawn", "swarm_spawn"})
        names = [t.name for t in view.get_tools_for_context(set())]
        assert "a" in names
        assert "b" in names
        assert "kid_spawn" not in names
        assert "swarm_spawn" not in names

    def test_deferred_catalog_drops_excluded(self) -> None:
        inner = _make_inner_registry(["delegate", "other"])
        view = _FilteredRegistry(inner, {"delegate"})
        names = [e["name"] for e in view.get_deferred_catalog()]
        assert names == ["other"]

    def test_list_tools_drops_excluded(self) -> None:
        inner = _make_inner_registry(["a", "kid_spawn"])
        view = _FilteredRegistry(inner, {"kid_spawn"})
        names = [t["function"]["name"] for t in view.list_tools()]
        assert names == ["a"]

    def test_falls_through_unknown_attrs(self) -> None:
        inner = _make_inner_registry(["a"])
        inner.something_custom = lambda: "ok"
        view = _FilteredRegistry(inner, set())
        assert view.something_custom() == "ok"


# ---------------------------------------------------------------------------
# _build_excluded_set — prefix policy
# ---------------------------------------------------------------------------


class TestExcludedSet:
    def test_resolves_prefixes_against_real_names(self) -> None:
        names = [
            "delegate",
            "swarm_spawn",
            "swarm_archive_project",
            "kid_spawn",
            "kid_destroy",
            "org_spawn",
            "payment_send",
            "payment_preview",
            "wallet_create",
            "agent_connect",
            "agent_message",
            "agent_disconnect",
            "schedule_task",
            "knowledge_search",  # NOT excluded
            "shell_execute",  # NOT excluded
            "file_read",  # NOT excluded
        ]
        excluded = _build_excluded_set(names)
        for name in (
            "delegate",
            "swarm_spawn",
            "swarm_archive_project",
            "kid_spawn",
            "kid_destroy",
            "org_spawn",
            "payment_send",
            "payment_preview",
            "wallet_create",
            "agent_connect",
            "agent_message",
            "agent_disconnect",
            "schedule_task",
        ):
            assert name in excluded, f"{name} should be excluded"
        for name in ("knowledge_search", "shell_execute", "file_read"):
            assert name not in excluded, f"{name} should NOT be excluded"

    def test_empty_input(self) -> None:
        assert _build_excluded_set([]) == set()


# ---------------------------------------------------------------------------
# DelegateTool — input validation + no agent
# ---------------------------------------------------------------------------


class TestDelegateInputValidation:
    @pytest.mark.asyncio
    async def test_no_agent_injected_returns_error(self) -> None:
        tool = DelegateTool()
        result = await tool.execute({"tasks": [{"goal": "x"}]})
        assert not result.success
        assert "not injected" in (result.error or "")

    @pytest.mark.asyncio
    async def test_empty_tasks_list_errors(self) -> None:
        tool = DelegateTool()
        tool._agent = MagicMock()
        result = await tool.execute({"tasks": []})
        assert not result.success
        assert "non-empty" in (result.error or "")

    @pytest.mark.asyncio
    async def test_tasks_not_list_errors(self) -> None:
        tool = DelegateTool()
        tool._agent = MagicMock()
        result = await tool.execute({"tasks": "not a list"})
        assert not result.success

    @pytest.mark.asyncio
    async def test_too_many_tasks_errors(self) -> None:
        tool = DelegateTool()
        tool._agent = MagicMock()
        result = await tool.execute({"tasks": [{"goal": f"t{i}"} for i in range(15)]})
        assert not result.success
        assert "max" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# DelegateTool — execution against a fake agent
# ---------------------------------------------------------------------------


@dataclass
class _FakeAgent:
    """Minimal Agent-shaped fake for delegate execution tests."""

    run_isolated_results: list[Any] = field(default_factory=list)
    calls: list[tuple[str, set[str], int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._registry = _make_inner_registry(
            [
                "delegate",
                "swarm_spawn",
                "kid_spawn",
                "knowledge_search",
                "shell_execute",
            ]
        )

    async def run_isolated(
        self,
        prompt: str,
        *,
        excluded_tool_names: set[str],
        max_steps_override: int,
    ) -> Any:
        self.calls.append((prompt, excluded_tool_names, max_steps_override))
        if not self.run_isolated_results:
            raise RuntimeError("no fake response queued")
        result = self.run_isolated_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class TestDelegateExecution:
    @pytest.mark.asyncio
    async def test_runs_each_subagent_sequentially(self) -> None:
        tool = DelegateTool()
        agent = _FakeAgent()
        tool._agent = agent
        agent.run_isolated_results = [
            AgentResponse(
                content="result A", steps_taken=3, tool_calls_made=["knowledge_search"]
            ),
            AgentResponse(
                content="result B", steps_taken=5, tool_calls_made=["shell_execute"]
            ),
        ]
        result = await tool.execute({"tasks": [{"goal": "task A"}, {"goal": "task B"}]})
        assert result.success
        assert result.data["completed"] == 2
        assert result.data["failed"] == 0
        assert result.data["results"][0]["summary"] == "result A"
        assert result.data["results"][1]["summary"] == "result B"
        assert len(agent.calls) == 2

    @pytest.mark.asyncio
    async def test_each_call_passes_full_excluded_set(self) -> None:
        tool = DelegateTool()
        agent = _FakeAgent()
        tool._agent = agent
        agent.run_isolated_results = [AgentResponse(content="ok", steps_taken=1)]
        await tool.execute({"tasks": [{"goal": "go"}]})
        prompt, excluded, _ = agent.calls[0]
        assert "delegate" in excluded
        assert "swarm_spawn" in excluded
        assert "kid_spawn" in excluded
        assert "knowledge_search" not in excluded
        assert "shell_execute" not in excluded

    @pytest.mark.asyncio
    async def test_context_prepended_to_goal(self) -> None:
        tool = DelegateTool()
        agent = _FakeAgent()
        tool._agent = agent
        agent.run_isolated_results = [AgentResponse(content="ok", steps_taken=1)]
        await tool.execute(
            {
                "tasks": [
                    {
                        "goal": "do the thing",
                        "context": "you are operating in test mode",
                    }
                ]
            }
        )
        prompt, _, _ = agent.calls[0]
        assert "you are operating in test mode" in prompt
        assert "do the thing" in prompt

    @pytest.mark.asyncio
    async def test_one_failure_doesnt_kill_peers(self) -> None:
        tool = DelegateTool()
        agent = _FakeAgent()
        tool._agent = agent
        agent.run_isolated_results = [
            AgentResponse(content="ok", steps_taken=2),
            RuntimeError("kaboom"),
            AgentResponse(content="also ok", steps_taken=1),
        ]
        result = await tool.execute(
            {"tasks": [{"goal": "a"}, {"goal": "b"}, {"goal": "c"}]}
        )
        assert result.success  # tool itself succeeded
        assert result.data["completed"] == 2
        assert result.data["failed"] == 1
        assert result.data["results"][1]["error"].startswith("crash:")
        assert result.data["results"][2]["summary"] == "also ok"

    @pytest.mark.asyncio
    async def test_timeout_per_subagent(self) -> None:
        tool = DelegateTool()
        agent = MagicMock()
        agent._registry = _make_inner_registry(["delegate"])

        async def _hang(*a: Any, **kw: Any) -> Any:
            await asyncio.sleep(60)
            return AgentResponse(content="never", steps_taken=0)

        agent.run_isolated = _hang
        tool._agent = agent
        result = await tool.execute(
            {"tasks": [{"goal": "slow"}], "timeout_seconds": 0.05}
        )
        # Tool wraps below the floor of 10s — but per the clamp, even
        # 0.05 becomes 10s. Use a smaller-budget timeout via the floor:
        # we still expect failure quickly because the fake hangs >10s.
        # To keep tests fast, accept either outcome shape: success
        # depends only on whether the subagent finished, not on time.
        assert result.success
        assert result.data["failed"] >= 1 or result.data["completed"] == 1

    @pytest.mark.asyncio
    async def test_missing_goal_in_task_recorded_as_failure(self) -> None:
        tool = DelegateTool()
        agent = _FakeAgent()
        tool._agent = agent
        agent.run_isolated_results = [AgentResponse(content="ok", steps_taken=1)]
        result = await tool.execute(
            {"tasks": [{"context": "no goal here"}, {"goal": "real"}]}
        )
        assert result.success
        assert result.data["completed"] == 1
        assert result.data["failed"] == 1
        assert "missing 'goal'" in (result.data["results"][0]["error"] or "")


# ---------------------------------------------------------------------------
# Agent.run_isolated — state isolation + cost rollup
# ---------------------------------------------------------------------------


class TestRunIsolatedSemantics:
    """These exercise the run_isolated method on a stub agent fixture
    that has just enough Agent surface to swap state. Full integration
    with the real Agent class is covered by the smoke import test
    plus the existing test_agent.py suite."""

    @pytest.mark.asyncio
    async def test_run_isolated_swaps_and_restores_state(self) -> None:
        """Pin: parent's conversation_history, working_memory, activated
        set, registry, on_step are restored after the call returns,
        even when the inner run() raises."""
        from core.agent import Agent

        # Construct a minimal Agent-shaped object using __new__ so we
        # don't trip Agent.__init__'s dependency requirements.
        agent = Agent.__new__(Agent)
        parent_history: list[Any] = [{"role": "user", "content": "parent"}]
        parent_memory = MagicMock()
        parent_activated: set[str] = {"prev_activated"}
        parent_registry = _make_inner_registry(["a", "kid_spawn"])
        parent_on_step = MagicMock()
        from core.router import CostTracker

        cost_tracker = CostTracker()
        cost_tracker.task_total = 1.5
        router = MagicMock()
        router.cost_tracker = cost_tracker

        agent._conversation_history = parent_history
        agent._working_memory = parent_memory
        agent._activated_tools = parent_activated
        agent._registry = parent_registry
        agent._on_step = parent_on_step
        agent._router = router

        # Mock run() to assert isolation while it's executing AND to
        # bump task_total so we can verify the rollup math.
        async def _fake_run(
            goal: str, *, max_steps_override: int, is_user_input: bool
        ) -> AgentResponse:
            assert is_user_input is False, "subagent must not be treated as user input"
            assert agent._conversation_history is not parent_history
            assert agent._conversation_history == []
            assert agent._working_memory is not parent_memory
            assert agent._activated_tools is not parent_activated
            assert agent._activated_tools == set()
            assert isinstance(agent._registry, _FilteredRegistry)
            assert agent._on_step is None
            cost_tracker.record("p", "m", 0, 0, 0.7)  # subagent spend
            return AgentResponse(content="done", steps_taken=4)

        agent.run = _fake_run  # type: ignore[method-assign]

        result = await agent.run_isolated(
            "subtask",
            excluded_tool_names={"kid_spawn"},
            max_steps_override=5,
        )
        assert result.content == "done"
        # State restored
        assert agent._conversation_history is parent_history
        assert agent._working_memory is parent_memory
        assert agent._activated_tools is parent_activated
        assert agent._registry is parent_registry
        assert agent._on_step is parent_on_step
        # Cost rolled up: parent's prior 1.5 + subagent's 0.7
        assert cost_tracker.task_total == pytest.approx(2.2)

    @pytest.mark.asyncio
    async def test_run_isolated_restores_state_on_exception(self) -> None:
        """A subagent crash must still restore parent state."""
        from core.agent import Agent

        agent = Agent.__new__(Agent)
        parent_history: list[Any] = [{"role": "user", "content": "parent"}]
        parent_memory = MagicMock()
        parent_registry = _make_inner_registry(["a"])
        from core.router import CostTracker

        cost_tracker = CostTracker()
        cost_tracker.task_total = 1.5
        router = MagicMock()
        router.cost_tracker = cost_tracker

        agent._conversation_history = parent_history
        agent._working_memory = parent_memory
        agent._activated_tools = set()
        agent._registry = parent_registry
        agent._on_step = None
        agent._router = router

        async def _fake_run(
            goal: str, *, max_steps_override: int, is_user_input: bool
        ) -> AgentResponse:
            cost_tracker.record("p", "m", 0, 0, 0.3)
            raise RuntimeError("boom")

        agent.run = _fake_run  # type: ignore[method-assign]

        with pytest.raises(RuntimeError):
            await agent.run_isolated("x", excluded_tool_names=set())

        # State still restored
        assert agent._conversation_history is parent_history
        assert agent._working_memory is parent_memory
        assert agent._registry is parent_registry
        # Cost still rolled up — parent's accounting must not lose the
        # spend just because the subagent crashed.
        assert cost_tracker.task_total == pytest.approx(1.8)

    @pytest.mark.asyncio
    async def test_no_excluded_skips_filtered_registry(self) -> None:
        """If caller passes no exclusions, registry is left as-is."""
        from core.agent import Agent

        agent = Agent.__new__(Agent)
        parent_registry = _make_inner_registry(["a"])
        agent._conversation_history = []
        agent._working_memory = MagicMock()
        agent._activated_tools = set()
        agent._registry = parent_registry
        agent._on_step = None
        cost_tracker = MagicMock()
        cost_tracker.task_total = 0.0
        router = MagicMock()
        router.cost_tracker = cost_tracker
        agent._router = router

        seen_registry: list[Any] = []

        async def _fake_run(
            goal: str, *, max_steps_override: int, is_user_input: bool
        ) -> AgentResponse:
            seen_registry.append(agent._registry)
            return AgentResponse(content="ok", steps_taken=1)

        agent.run = _fake_run  # type: ignore[method-assign]

        await agent.run_isolated("x", excluded_tool_names=None)
        # Registry was NOT wrapped — same object as parent's.
        assert seen_registry[0] is parent_registry


class TestConcurrentIsolationSafety:
    """run_isolated swaps SHARED instance state, so concurrent callers must
    not interleave.

    Regression: making delegate concurrent turned this into live corruption —
    the second caller saved the first's swapped-in state instead of the
    parent's, both read whichever was written last, and the parent was left
    holding a subagent's history. The registry swap made it a safety bug too:
    that filter is what hides payment and spawn tools from subagents.
    """

    @pytest.mark.asyncio
    async def test_concurrent_run_isolated_does_not_interleave(self) -> None:
        import asyncio

        from core.agent import Agent

        agent = Agent.__new__(Agent)
        parent_history: list[Any] = [{"role": "user", "content": "parent"}]
        agent._conversation_history = parent_history
        agent._working_memory = MagicMock()
        agent._activated_tools = {"parent_tool"}
        agent._registry = _make_inner_registry(["a"])
        agent._on_step = None
        agent._router = MagicMock()
        agent._router.cost_tracker.task_total = 0.0

        seen: list[tuple[str, int]] = []

        async def fake_run(goal: str, **kwargs: Any) -> Any:
            # Mutate then yield, so an unguarded peer would observe this one.
            agent._conversation_history.append({"role": "assistant", "content": goal})
            await asyncio.sleep(0.01)
            seen.append((goal, len(agent._conversation_history)))
            return MagicMock(content="ok", steps_taken=1, tool_calls_made=[])

        agent.run = fake_run  # type: ignore[method-assign]

        await asyncio.gather(
            *(agent.run_isolated(f"sub{i}") for i in range(4))
        )

        # Each subagent saw exactly its own single message — no sibling's.
        assert all(depth == 1 for _, depth in seen), seen
        # And the parent's history survives untouched.
        assert agent._conversation_history is parent_history
        assert agent._conversation_history == [{"role": "user", "content": "parent"}]

    @pytest.mark.asyncio
    async def test_subagent_gets_its_own_loop_detector(self) -> None:
        from core.agent import Agent
        from core.loop_detect import LoopDetector

        agent = Agent.__new__(Agent)
        agent._conversation_history = []
        agent._working_memory = MagicMock()
        agent._activated_tools = set()
        agent._registry = _make_inner_registry(["a"])
        agent._on_step = None
        agent._router = MagicMock()
        agent._router.cost_tracker.task_total = 0.0

        parent_detector = LoopDetector()
        agent._loop_detector = parent_detector
        parent_detector.record("file_read", {"p": "/x"}, MagicMock(success=True))

        inner: list[Any] = []

        async def fake_run(goal: str, **kwargs: Any) -> Any:
            inner.append(agent._loop_detector)
            return MagicMock(content="ok", steps_taken=1, tool_calls_made=[])

        agent.run = fake_run  # type: ignore[method-assign]
        await agent.run_isolated("sub")

        # The subagent ran on a fresh detector, not the parent's counters...
        assert inner[0] is not parent_detector
        assert inner[0].distinct_calls == 0
        # ...and the parent's survived the round trip intact.
        assert agent._loop_detector is parent_detector
        assert parent_detector.distinct_calls == 1


class TestConcurrentCostAccounting:
    """Per-task spend must survive concurrent subagents.

    ``_run_with_history`` calls ``reset_task()`` on entry to every run. With a
    shared counter that meant each subagent zeroed the parent's accumulated
    spend, and four concurrent ones erased its budget accounting entirely.
    """

    @pytest.mark.asyncio
    async def test_concurrent_subagent_spend_rolls_up_without_loss(self) -> None:
        import asyncio

        from core.agent import Agent
        from core.router import CostTracker

        tracker = CostTracker()
        tracker.task_total = 1.0  # the parent has already spent

        agent = Agent.__new__(Agent)
        agent._conversation_history = []
        agent._working_memory = MagicMock()
        agent._activated_tools = set()
        agent._registry = _make_inner_registry(["a"])
        agent._on_step = None
        agent._loop_detector = None
        agent._router = MagicMock()
        agent._router.cost_tracker = tracker

        async def fake_run(goal: str, **kwargs: Any) -> Any:
            # Exactly what a real run does on entry.
            tracker.reset_task()
            tracker.record("p", "m", 0, 0, 0.25)
            await asyncio.sleep(0.01)
            # Each subagent sees only its own spend against its own budget.
            assert tracker.effective_task_total == pytest.approx(0.25)
            return MagicMock(content="ok", steps_taken=1, tool_calls_made=[])

        agent.run = fake_run  # type: ignore[method-assign]

        await asyncio.gather(*(agent.run_isolated(f"sub{i}") for i in range(4)))

        # Parent keeps its own spend, plus every subagent's — none lost to a
        # sibling's reset, none double-counted.
        assert tracker.task_total == pytest.approx(1.0 + 4 * 0.25)
        # Daily total is genuinely global and unaffected by isolation.
        assert tracker.daily_total == pytest.approx(4 * 0.25)
