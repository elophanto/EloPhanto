"""Phase 0 (docs/94) — the agent loop's side of long-run hardening.

Stop reasons, time budgets that start at the slot, private histories for
background loops, memory titles, and the right goal's plan in context.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent import Agent
from core.config import Config
from core.execution_context import execution_context
from core.router import LLMResponse


def _text(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model_used="test",
        provider="test",
        input_tokens=1,
        output_tokens=1,
        cost_estimate=0.0,
        tool_calls=None,
    )


def _tool_call(i: int) -> LLMResponse:
    return LLMResponse(
        content=None,
        model_used="test",
        provider="test",
        input_tokens=1,
        output_tokens=1,
        cost_estimate=0.0,
        tool_calls=[
            {
                "id": f"call_{i}",
                "type": "function",
                "function": {
                    "name": "shell_execute",
                    "arguments": f'{{"command": "echo {i}"}}',
                },
            }
        ],
    )


@pytest.fixture
async def agent(test_config: Config) -> Agent:
    a = Agent(test_config)
    await a.initialize()
    a.set_approval_callback(lambda *args: True)
    return a


class TestStopReasons:
    async def test_a_finished_run_says_completed(self, agent: Agent) -> None:
        with patch.object(agent._router, "complete", new_callable=AsyncMock) as m:
            m.return_value = _text("All done.")
            r = await agent.run("say done")
        assert r.stop_reason == "completed"

    async def test_the_time_budget_stops_the_loop_cooperatively(
        self, agent: Agent
    ) -> None:
        n = {"i": 0}

        async def slow(*_a: Any, **_kw: Any) -> LLMResponse:
            n["i"] += 1
            await asyncio.sleep(0.05)
            return _tool_call(n["i"])

        with patch.object(agent._router, "complete", side_effect=slow):
            r = await agent.run("keep going", time_budget_seconds=0.12)
        assert r.stop_reason == "time_limit"
        assert "time limit" in r.content

    async def test_the_step_cap_says_max_steps_and_records_why(
        self, agent: Agent
    ) -> None:
        n = {"i": 0}

        async def calls(*_a: Any, **_kw: Any) -> LLMResponse:
            n["i"] += 1
            return _tool_call(n["i"])

        stored: list[tuple[str, str, str]] = []

        async def _store(
            goal: str, summary: str, outcome: str, tools: list[str]
        ) -> None:
            stored.append((goal, summary, outcome))

        with (
            patch.object(agent._router, "complete", side_effect=calls),
            patch.object(agent, "_store_task_memory", side_effect=_store),
        ):
            r = await agent.run(
                "loop", max_steps_override=3, memory_label="Nightly sweep"
            )
            await asyncio.sleep(0.05)  # memory is written fire-and-forget
        assert r.stop_reason == "max_steps"
        title, summary, outcome = stored[-1]
        assert title == "Nightly sweep"
        assert outcome == "incomplete"
        assert "safety limit" in summary and "shell_execute" in summary
        assert summary != "Max steps reached"


class TestBackgroundHistoryIsPrivate:
    async def test_isolated_history_leaves_the_shared_history_alone(
        self, agent: Agent
    ) -> None:
        agent._conversation_history.extend(
            [
                {"role": "user", "content": "earlier"},
                {"role": "assistant", "content": "ok"},
            ]
        )
        before = list(agent._conversation_history)
        seen: list[list[dict[str, Any]]] = []

        async def capture(*_a: Any, **kw: Any) -> LLMResponse:
            seen.append(kw.get("messages") or _a[0])
            return _text("done")

        with patch.object(agent._router, "complete", side_effect=capture):
            await agent.run("background cycle", isolated_history=True)
        assert agent._conversation_history == before
        sent = seen[0]
        assert not any(m.get("content") == "earlier" for m in sent)


class TestTheRightGoalIsInContext:
    async def test_a_checkpoint_run_gets_its_own_goal(self, agent: Agent) -> None:
        gm = MagicMock()
        gm.build_goal_context = AsyncMock(
            return_value="<active_goal>mine</active_goal>"
        )
        gm.list_goals = AsyncMock(return_value=[MagicMock(goal_id="someone-else")])
        agent._goal_manager = gm
        with patch.object(agent._router, "complete", new_callable=AsyncMock) as m:
            m.return_value = _text("ok")
            with execution_context(goal_id="goal-A"):
                await agent.run("checkpoint work")
        gm.build_goal_context.assert_awaited_with("goal-A")
        gm.list_goals.assert_not_awaited()
