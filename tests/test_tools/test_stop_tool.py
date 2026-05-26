"""agent_stop LLM-callable tool (cancel current session task only).

Locks in the corrected semantic after the 2026-05-26 redesign:
- agent_stop cancels ONLY the in-flight run_session task for THIS
  session via the gateway's _inflight_run_tasks dict.
- No data/STOP sentinel write. No goal cancellation. No schedule
  disabling. Autonomous mind + other sessions unaffected.
- Refuses cleanly when there's no gateway (direct-mode agents must
  use Ctrl+C) or when the current task isn't a tracked session run
  (autonomous mind, scheduled jobs, etc.).
"""

from __future__ import annotations

import asyncio

import pytest

from tools.base import PermissionLevel
from tools.system.stop_tool import AgentStopTool


class FakeGateway:
    """Minimal gateway stub exposing the inflight task dict."""

    def __init__(self) -> None:
        self._inflight_run_tasks: dict[str, asyncio.Task[None]] = {}


class TestAgentStop:
    @pytest.mark.asyncio
    async def test_cancels_current_session_task(self) -> None:
        gateway = FakeGateway()
        tool = AgentStopTool()
        tool._gateway = gateway

        # We need a scenario where the running task IS the one in the
        # gateway dict. Pattern: launch a task whose body is the tool
        # invocation; register it under a session id; await its result.
        result_holder: dict[str, object] = {}

        async def body() -> None:
            r = await tool.execute({})
            result_holder["r"] = r
            # Allow the cancellation to propagate (next await)
            try:
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                result_holder["cancelled_via_await"] = True
                raise

        task = asyncio.create_task(body())
        gateway._inflight_run_tasks["sess-1"] = task
        try:
            await task
        except asyncio.CancelledError:
            pass
        r = result_holder["r"]  # type: ignore[index]
        assert r.success is True  # type: ignore[attr-defined]
        assert r.data["cancelled"] is True  # type: ignore[attr-defined,index]
        assert r.data["session_id"] == "sess-1"  # type: ignore[attr-defined,index]
        # The await after tool returned raised CancelledError
        assert result_holder.get("cancelled_via_await") is True

    @pytest.mark.asyncio
    async def test_refuses_when_not_in_tracked_session(self) -> None:
        gateway = FakeGateway()
        tool = AgentStopTool()
        tool._gateway = gateway

        # Tool is called from a task that is NOT in the gateway dict
        # (simulating autonomous mind, scheduled job, or test fixture).
        # The tool must refuse rather than cancel the wrong loop.
        result = await tool.execute({})
        assert result.success is False
        assert "not a chat session" in (result.error or "")

    @pytest.mark.asyncio
    async def test_refuses_when_no_gateway(self) -> None:
        tool = AgentStopTool()
        tool._gateway = None
        result = await tool.execute({})
        assert result.success is False
        assert "gateway reference missing" in (result.error or "")

    @pytest.mark.asyncio
    async def test_permission_level_moderate(self) -> None:
        # Operators approve agent_stop explicitly. The deterministic
        # `/stop` slash-command bypasses the LLM entirely so this
        # MODERATE gate only fires for natural-language phrasing.
        assert AgentStopTool().permission_level == PermissionLevel.MODERATE


class TestSchema:
    @pytest.mark.asyncio
    async def test_no_input_args(self) -> None:
        # agent_stop takes no params — the scope is implicit
        # ("cancel the current chat action").
        tool = AgentStopTool()
        assert tool.input_schema == {"type": "object", "properties": {}}

    @pytest.mark.asyncio
    async def test_description_mentions_scope(self) -> None:
        # The LLM must understand this is session-scoped, not a hard
        # halt. Pin the language in the description.
        desc = AgentStopTool().description.lower()
        assert "current chat action" in desc
        assert "stay running" in desc
        assert "stop --hard" in desc
