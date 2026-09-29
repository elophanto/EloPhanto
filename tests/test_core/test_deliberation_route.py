"""docs/95 Phase B — the thinking steps route as ``deliberation``."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.config import (
    BudgetConfig,
    Config,
    GoalsConfig,
    LLMConfig,
    ProviderConfig,
    RoutingConfig,
)
from core.deliberation import judge_complete
from core.router import LLMResponse, LLMRouter


def _config(*, deliberation: bool, judge_model: str = "") -> Config:
    routing = {
        "planning": RoutingConfig(
            preferred_provider="zai",
            reasoning_effort="low",
            models={"zai": "glm-5.3-flash"},
        ),
    }
    if deliberation:
        routing["deliberation"] = RoutingConfig(
            preferred_provider="zai",
            reasoning_effort="xhigh",
            models={"zai": "glm-5.3"},
        )
    return Config(
        llm=LLMConfig(
            providers={
                "zai": ProviderConfig(
                    enabled=True, api_key="k", default_model="glm-5.3"
                )
            },
            provider_priority=["zai"],
            routing=routing,
            budget=BudgetConfig(daily_limit_usd=10.0, per_task_limit_usd=2.0),
            judge_model=judge_model,
        )
    )


def _resp(content: str, model: str = "m", provider: str = "p") -> LLMResponse:
    return LLMResponse(
        content=content,
        model_used=model,
        provider=provider,
        input_tokens=1,
        output_tokens=1,
        cost_estimate=0.0,
    )


def _capture(router: LLMRouter) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake(provider, model, messages, tools, temperature, max_tokens, **kw):
        calls.append({"provider": provider, "model": model, **kw})
        return _resp("{}", model, provider)

    router._call_with_retries = fake  # type: ignore[method-assign]
    return calls


class TestRouting:
    def test_without_a_route_it_borrows_planning_models(self) -> None:
        router = LLMRouter(_config(deliberation=False))
        assert router._select_provider_and_model("deliberation", None) == (
            "zai",
            "glm-5.3-flash",
        )

    def test_its_own_route_wins(self) -> None:
        router = LLMRouter(_config(deliberation=True))
        assert router._select_provider_and_model("deliberation", None) == (
            "zai",
            "glm-5.3",
        )

    @pytest.mark.asyncio
    async def test_borrowed_route_thinks_at_high_not_planning_effort(self) -> None:
        router = LLMRouter(_config(deliberation=False))
        calls = _capture(router)
        await router.complete(
            [{"role": "user", "content": "x"}], task_type="deliberation"
        )
        await router.complete([{"role": "user", "content": "x"}], task_type="planning")
        assert [c["reasoning_effort"] for c in calls] == ["high", "low"]

    @pytest.mark.asyncio
    async def test_route_effort_and_explicit_override(self) -> None:
        router = LLMRouter(_config(deliberation=True))
        calls = _capture(router)
        msgs = [{"role": "user", "content": "x"}]
        await router.complete(msgs, task_type="deliberation")
        await router.complete(msgs, task_type="deliberation", reasoning_effort="max")
        assert [c["reasoning_effort"] for c in calls] == ["xhigh", "max"]
        assert all(c["task_type"] == "deliberation" for c in calls)


class TestJudge:
    @pytest.mark.asyncio
    async def test_judge_model_is_used_when_set(self) -> None:
        router = LLMRouter(_config(deliberation=True, judge_model="zai/glm-4.7"))
        calls = _capture(router)
        await judge_complete(
            router, [{"role": "user", "content": "x"}], temperature=0.1
        )
        assert calls[0]["model"] == "glm-4.7"

    @pytest.mark.asyncio
    async def test_judge_model_failure_falls_back_to_the_route(self) -> None:
        router = MagicMock()
        router._config = _config(deliberation=True, judge_model="zai/glm-4.7")
        router.complete = AsyncMock(side_effect=[RuntimeError("down"), "ok"])
        assert await judge_complete(router, [{"role": "user", "content": "x"}]) == "ok"
        first, second = router.complete.call_args_list
        assert first.kwargs["model_override"] == "zai/glm-4.7"
        assert "model_override" not in second.kwargs
        assert second.kwargs["task_type"] == "deliberation"

    @pytest.mark.asyncio
    async def test_no_judge_model_uses_the_route(self) -> None:
        router = MagicMock()  # config attributes are mocks, not strings
        router.complete = AsyncMock(return_value="ok")
        await judge_complete(router, [{"role": "user", "content": "x"}])
        kw = router.complete.call_args.kwargs
        assert "model_override" not in kw and kw["task_type"] == "deliberation"


class TestCallers:
    def test_effort_override_is_empty_by_default(self) -> None:
        assert GoalsConfig().deliberation_effort == ""

    @pytest.mark.asyncio
    async def test_goal_manager_thinking_calls_route_as_deliberation(self) -> None:
        from core.goal_manager import Goal, GoalManager

        router = MagicMock()
        router.complete = AsyncMock(
            return_value=_resp("not json")
        )
        db = MagicMock()
        db.execute = AsyncMock(return_value=[])
        db.execute_insert = AsyncMock(return_value=1)
        gm = GoalManager(
            db, router, GoalsConfig(deliberation_effort="max", plan_critique=False)
        )
        goal = Goal(goal_id="g1", session_id="s", goal="Ship it")
        gm.get_checkpoints = AsyncMock(return_value=[])  # type: ignore[method-assign]
        await gm.evaluate_progress(goal)
        await gm.verify_goal_met(goal)
        kws = [c.kwargs for c in router.complete.call_args_list]
        assert [k["task_type"] for k in kws] == ["deliberation", "deliberation"]
        assert [k["reasoning_effort"] for k in kws] == ["max", "max"]
