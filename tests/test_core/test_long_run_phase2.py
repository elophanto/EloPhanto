"""Phase 2 of docs/94 — thinking before acting.

Reasoning parameters reach the provider, reasoning is kept with the turn,
and separate thinking steps run before a checkpoint attempt, before the
mind acts, before an unattended CRITICAL call, and before a plan is used.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import GoalsConfig
from core.database import Database
from core.deliberation import decide_mind_action, plan_checkpoint, review_action
from core.execution_context import TaskSource, execution_context
from core.goal_manager import GoalManager
from core.router import LLMResponse, _strip_private_keys
from core.run_ledger import RunLedger


def _llm(content: str, reasoning: str = "") -> LLMResponse:
    return LLMResponse(
        content=content,
        model_used="m",
        provider="p",
        input_tokens=1,
        output_tokens=1,
        cost_estimate=0.01,
        reasoning=reasoning,
    )


@pytest.fixture
async def db(tmp_path: Path):
    d = Database(tmp_path / "p2.db")
    await d.initialize()
    yield d
    await d.close()


# ---------------------------------------------------------------------------
# Provider layer
# ---------------------------------------------------------------------------


class TestZaiReasoning:
    async def _payload(self, **kw: Any) -> tuple[dict[str, Any], Any]:
        from core.zai_adapter import ZaiAdapter

        adapter = ZaiAdapter.__new__(ZaiAdapter)
        adapter._api_key = "k"
        adapter._base_url = "https://example.invalid"
        sent: dict[str, Any] = {}

        async def post(url: str, headers: Any = None, json: Any = None) -> Any:
            sent.update(json)
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {
                "choices": [
                    {
                        "message": {
                            "content": "ok",
                            "reasoning_content": "thought it through",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }
            return r

        adapter._client = MagicMock()
        adapter._client.post = post
        msgs = kw.pop("messages", [{"role": "user", "content": "hi"}])
        resp = await adapter.complete(msgs, "glm-5.3", **kw)
        return sent, resp

    async def test_the_configured_effort_reaches_the_api(self) -> None:
        sent, resp = await self._payload(reasoning_effort="medium")
        assert sent["thinking"] == {"type": "enabled"}
        assert sent["reasoning_effort"] == "medium"
        assert resp.reasoning == "thought it through"

    async def test_none_turns_thinking_off_and_empty_leaves_the_default(self) -> None:
        sent, _ = await self._payload(reasoning_effort="none")
        assert (
            sent["thinking"] == {"type": "disabled"} and "reasoning_effort" not in sent
        )
        sent, _ = await self._payload()
        assert "thinking" not in sent and "clear_thinking" not in sent

    async def test_preserved_reasoning_goes_back_as_reasoning_content(self) -> None:
        msgs = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "step", "_reasoning": "why step"},
        ]
        sent, _ = await self._payload(messages=msgs, preserve_reasoning=True)
        assert sent["clear_thinking"] is False
        assert sent["messages"][-1]["reasoning_content"] == "why step"
        assert "_reasoning" not in sent["messages"][-1]
        sent, _ = await self._payload(messages=msgs)
        assert "reasoning_content" not in sent["messages"][-1]

    def test_other_providers_never_see_private_keys(self) -> None:
        msgs = [{"role": "assistant", "content": "x", "_reasoning": "r"}]
        assert _strip_private_keys(msgs) == [{"role": "assistant", "content": "x"}]
        clean = [{"role": "user", "content": "x"}]
        assert _strip_private_keys(clean) is clean


# ---------------------------------------------------------------------------
# Thinking steps
# ---------------------------------------------------------------------------


class TestDeliberationCalls:
    async def test_a_checkpoint_plan_is_structured_and_asks_for_diagnosis_on_retry(
        self,
    ) -> None:
        router = MagicMock()
        router.complete = AsyncMock(
            return_value=_llm(
                json.dumps(
                    {
                        "diagnosis": "the count came from a parameter, not a result",
                        "approach": "List the register, then analyze the 3 missing brands.",
                        "steps": ["watch_list", "watch_analyze x3", "watch_list again"],
                        "assumptions": ["register has 14 subjects"],
                        "risks": ["geo exit fails — retry via the verified exit"],
                        "verification": "watch_list output shows 14",
                        "reuse": ["/w/scorecard.xlsx"],
                    }
                ),
                reasoning="considered two orders",
            )
        )
        plan = await plan_checkpoint(
            router,
            goal="Refresh the pack",
            order=2,
            total=4,
            title="Collect",
            description="d",
            criteria="14 subjects",
            stage="build",
            ledger_text="FAILED ATTEMPTS: ...",
            attempt=2,
            last_failure="receipt_gate: no count from [14]",
            effort="high",
        )
        assert plan is not None and plan.reasoning == "considered two orders"
        text = plan.render()
        assert text.startswith("DIAGNOSIS OF THE LAST ATTEMPT")
        assert "VERIFY BY: watch_list output shows 14" in text
        kw = router.complete.call_args.kwargs
        assert kw["task_type"] == "deliberation" and kw["reasoning_effort"] == "high"
        assert "THIS IS ATTEMPT 2" in kw["messages"][1]["content"]

    async def test_planning_failure_is_not_fatal(self) -> None:
        router = MagicMock()
        router.complete = AsyncMock(side_effect=RuntimeError("down"))
        assert (
            await plan_checkpoint(
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
            )
            is None
        )

    async def test_the_mind_pick_must_be_on_the_menu(self) -> None:
        router = MagicMock()
        router.complete = AsyncMock(return_value=_llm('{"pick": 7, "why": "x"}'))
        assert (
            await decide_mind_action(
                router, menu="m", n_candidates=3, state="", recent=""
            )
            is None
        )
        router.complete = AsyncMock(
            return_value=_llm(
                '{"pick": 2, "why": "unblocks revenue", "done_when": "draft sent"}'
            )
        )
        d = await decide_mind_action(
            router, menu="m", n_candidates=3, state="", recent=""
        )
        assert d is not None and d.pick == 2
        assert "Done when: draft sent" in d.render("Send the draft")

    async def test_review_needs_a_verdict(self) -> None:
        router = MagicMock()
        router.complete = AsyncMock(return_value=_llm("not json"))
        assert (
            await review_action(router, task="t", tool_name="x", args={}, recent="")
            is None
        )
        router.complete = AsyncMock(
            return_value=_llm('{"proceed": false, "objection": "wrong recipient"}')
        )
        r = await review_action(router, task="t", tool_name="x", args={}, recent="")
        assert r is not None and not r.proceed and r.objection == "wrong recipient"


# ---------------------------------------------------------------------------
# Plan critique at decomposition
# ---------------------------------------------------------------------------


def _plan(titles: list[str], critique: str | None = None) -> str:
    body: dict[str, Any] = {
        "kill_criterion": "If fewer than 3 replies in 14 days, abandon.",
        "checkpoints": [
            {
                "order": i,
                "title": t,
                "description": "d",
                "success_criteria": "c",
                "stage": "build",
            }
            for i, t in enumerate(titles, 1)
        ],
    }
    if critique is not None:
        body["critique"] = critique
    return json.dumps(body)


class TestPlanCritique:
    async def test_the_revised_plan_is_used_and_the_critique_recorded(
        self, db: Database
    ) -> None:
        router = MagicMock()
        router.complete = AsyncMock(
            side_effect=[
                _llm(_plan(["Verify proxy works", "Collect data"])),
                _llm(
                    _plan(
                        ["Collect data with watch_analyze"],
                        critique="Dropped a plumbing step.",
                    )
                ),
            ]
        )
        gm = GoalManager(db=db, router=router, config=GoalsConfig())
        gm.set_context_provider(
            AsyncMock(return_value="RELATED PAST RUNS: - [incomplete] x")
        )
        g = await gm.create_goal("Collect data")
        cps = await gm.decompose(g)
        assert [c.title for c in cps] == ["Collect data with watch_analyze"]
        assert g.kill_criterion  # kept from the draft
        first_user = router.complete.call_args_list[0].kwargs["messages"][1]["content"]
        assert "RELATED PAST RUNS" in first_user
        notes = await RunLedger(db).entries(g.goal_id, kinds=("decision",))
        assert notes and "plumbing" in notes[0].content

    async def test_an_unusable_critique_keeps_the_draft(self, db: Database) -> None:
        router = MagicMock()
        router.complete = AsyncMock(
            side_effect=[_llm(_plan(["A", "B"])), _llm("I think it's fine.")]
        )
        gm = GoalManager(db=db, router=router, config=GoalsConfig())
        g = await gm.create_goal("Do A and B")
        assert [c.title for c in await gm.decompose(g)] == ["A", "B"]


# ---------------------------------------------------------------------------
# Pre-action review in the agent loop
# ---------------------------------------------------------------------------


class TestPreActionReview:
    async def _agent(self, test_config: Any) -> Any:
        from core.agent import Agent
        from tools.base import BaseTool, PermissionLevel, ToolResult

        class Payout(BaseTool):
            ran: list[dict[str, Any]] = []

            @property
            def name(self) -> str:
                return "test_payout"

            @property
            def description(self) -> str:
                return "moves money"

            @property
            def input_schema(self) -> dict[str, Any]:
                return {"type": "object", "properties": {"amount": {"type": "number"}}}

            @property
            def permission_level(self) -> PermissionLevel:
                return PermissionLevel.CRITICAL

            async def execute(self, params: dict[str, Any]) -> ToolResult:
                Payout.ran.append(params)
                return ToolResult(success=True, data={"paid": params.get("amount")})

        test_config.permission_mode = "nuclear"
        agent = Agent(test_config)
        await agent.initialize()
        Payout.ran = []
        agent._registry.register(Payout())
        return agent, Payout

    @staticmethod
    def _call(i: int) -> LLMResponse:
        return LLMResponse(
            content=None,
            model_used="m",
            provider="p",
            input_tokens=1,
            output_tokens=1,
            cost_estimate=0.0,
            tool_calls=[
                {
                    "id": f"c{i}",
                    "type": "function",
                    "function": {"name": "test_payout", "arguments": '{"amount": 500}'},
                }
            ],
        )

    async def test_declined_once_then_the_repeat_proceeds(
        self, test_config: Any
    ) -> None:
        agent, payout = await self._agent(test_config)
        n = {"i": 0}

        async def complete(*_a: Any, **kw: Any) -> LLMResponse:
            msgs = kw.get("messages") or _a[0]
            system = msgs[0]["content"] if msgs else ""
            if "You review ONE tool call" in system:
                return _llm(
                    '{"proceed": false, "objection": "amount looks 10x too high"}'
                )
            n["i"] += 1
            return self._call(n["i"]) if n["i"] <= 2 else _llm("paid")

        with patch.object(agent._router, "complete", side_effect=complete):
            with execution_context(source=TaskSource.GOAL):
                await agent.run("pay the invoice", is_user_input=False)
        assert len(payout.ran) == 1  # the first call was held, the repeat ran

    async def test_chat_is_not_reviewed(self, test_config: Any) -> None:
        agent, payout = await self._agent(test_config)
        reviews = {"n": 0}
        n = {"i": 0}

        async def complete(*_a: Any, **kw: Any) -> LLMResponse:
            msgs = kw.get("messages") or _a[0]
            if msgs and "You review ONE tool call" in (msgs[0]["content"] or ""):
                reviews["n"] += 1
                return _llm('{"proceed": false, "objection": "x"}')
            n["i"] += 1
            return self._call(n["i"]) if n["i"] == 1 else _llm("paid")

        with patch.object(agent._router, "complete", side_effect=complete):
            await agent.run("pay the invoice")
        assert reviews["n"] == 0 and len(payout.ran) == 1


class TestMindDecides:
    async def test_the_decision_overrides_the_top_score_and_is_recorded(self) -> None:
        from core.autonomous_mind import AutonomousMind
        from core.mind_arbiter import Candidate

        mind = AutonomousMind.__new__(AutonomousMind)
        mind._config = MagicMock(deliberate=True)
        top = Candidate(source="dream", action_spec="Dream a new goal")
        second = Candidate(source="workable_checkpoint", action_spec="Send the pilot offer")
        mind._last_menu = [top, second]
        mind._last_menu_text = "1. dream\n2. send offer"
        mind._last_state_text = "state"
        mind._last_posture = "balance"
        mind._recent_actions = [{"ts": "10:00", "summary": "goal_dream"}]
        mind._last_arbiter_top = top
        mind._last_decision = None
        mind._role_pin_token = None
        mind._spent_today_usd = 0.0
        mind._agent = MagicMock()
        mind._agent._router.complete = AsyncMock(
            return_value=_llm(
                '{"pick": 2, "why": "dreamed an hour ago; the offer moves revenue", '
                '"done_when": "offer email sent"}'
            )
        )
        prompt = await mind._decide("BASE PROMPT")
        assert mind._last_arbiter_top is second
        assert "candidate 2: Send the pilot offer" in prompt
        assert "Done when: offer email sent" in prompt
        assert mind._spent_today_usd > 0
