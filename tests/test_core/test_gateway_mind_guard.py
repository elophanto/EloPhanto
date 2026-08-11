"""The gateway may not start a mind the operator disabled.

Both start paths — the `/mind start` chat command and the dashboard's
`mind_control` button — guarded on `if not mind`, i.e. on whether the
`AutonomousMind` *object* existed. It is constructed at boot regardless of
`autonomous_mind.enabled`, so the guard never fired and its own "not enabled"
message was unreachable. Checking that a thing exists is not a check on
whether it is permitted.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from core.gateway import Gateway
from core.protocol import GatewayMessage, MessageType


class _MindCfg:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled


class _Cfg:
    def __init__(self, enabled: bool) -> None:
        self.autonomous_mind = _MindCfg(enabled)


class _Mind:
    """Always constructed — that is the whole point of the regression."""

    def __init__(self) -> None:
        self.is_running = False
        self.started = 0
        self.cancelled = 0

    async def start(self) -> None:
        self.started += 1
        self.is_running = True

    async def cancel(self) -> None:
        self.cancelled += 1
        self.is_running = False

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self.is_running,
            "paused": False,
            "cycle_count": 0,
            "next_wakeup_sec": 300.0,
            "last_wakeup": None,
            "last_action": "",
            "budget_spent": 0.0,
            "budget_total": 0.0,
            "pending_events": 0,
        }


class _Agent:
    def __init__(self, enabled: bool) -> None:
        self._autonomous_mind = _Mind()
        self._config = _Cfg(enabled)


class _Socket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, payload: str) -> None:
        self.sent.append(payload)


class _Client:
    def __init__(self) -> None:
        self.websocket = _Socket()
        self.session_id = "s-1"
        self.user_id = "owner"
        self.channel = "cli"


def _server(enabled: bool) -> tuple[Gateway, _Agent, _Client]:
    """Bypass __init__ — only the handler's own reads are needed here."""
    server = Gateway.__new__(Gateway)
    agent = _Agent(enabled)
    server._agent = agent  # type: ignore[attr-defined]
    server._peer_verification_check = lambda client: (True, "")  # type: ignore[assignment]
    server._OWNER_ONLY_COMMANDS = frozenset()  # type: ignore[attr-defined]
    return server, agent, _Client()


async def _command(server: Gateway, client: _Client, command: str, args: dict[str, Any]) -> str:
    msg = GatewayMessage(
        type=MessageType.COMMAND,
        session_id="s-1",
        user_id="owner",
        channel="cli",
        data={"command": command, "args": args},
    )
    await server._handle_command(client, msg)  # type: ignore[arg-type]
    return " ".join(client.websocket.sent)


class TestMindCommandStart:
    @pytest.mark.asyncio
    async def test_refuses_when_autonomy_is_off(self) -> None:
        server, agent, client = _server(enabled=False)
        text = await _command(server, client, "mind", {"subcommand": "start"})

        assert agent._autonomous_mind.started == 0
        assert agent._autonomous_mind.is_running is False
        assert "autonomous_mind.enabled" in text

    @pytest.mark.asyncio
    async def test_starts_when_autonomy_is_on(self) -> None:
        server, agent, client = _server(enabled=True)
        await _command(server, client, "mind", {"subcommand": "start"})
        assert agent._autonomous_mind.started == 1

    @pytest.mark.asyncio
    async def test_stop_still_works_while_disabled(self) -> None:
        """Off is a floor, not a lock — stopping must never be blocked."""
        server, agent, client = _server(enabled=False)
        agent._autonomous_mind.is_running = True
        await _command(server, client, "mind", {"subcommand": "stop"})
        assert agent._autonomous_mind.cancelled == 1

    @pytest.mark.asyncio
    async def test_status_still_works_while_disabled(self) -> None:
        server, _agent, client = _server(enabled=False)
        text = await _command(server, client, "mind", {})
        assert "stopped" in text


class TestDashboardMindControl:
    @staticmethod
    def _result(text: str) -> dict[str, Any]:
        payload = json.loads(text)["data"]["content"]
        return json.loads(payload) if isinstance(payload, str) else payload

    @pytest.mark.asyncio
    async def test_start_button_refuses_when_autonomy_is_off(self) -> None:
        server, agent, client = _server(enabled=False)
        text = await _command(server, client, "mind_control", {"action": "start"})

        assert agent._autonomous_mind.started == 0
        assert "autonomous_mind.enabled" in text

    @pytest.mark.asyncio
    async def test_start_button_works_when_autonomy_is_on(self) -> None:
        server, agent, client = _server(enabled=True)
        await _command(server, client, "mind_control", {"action": "start"})
        assert agent._autonomous_mind.started == 1

    @pytest.mark.asyncio
    async def test_stop_button_works_while_disabled(self) -> None:
        server, agent, client = _server(enabled=False)
        agent._autonomous_mind.is_running = True
        await _command(server, client, "mind_control", {"action": "stop"})
        assert agent._autonomous_mind.cancelled == 1


class TestTheSwitchIsEnforcedAtTheLoop:
    """Defence in depth: `start()` itself refuses, so no caller is exempt."""

    @pytest.mark.asyncio
    async def test_start_refuses_when_disabled(self) -> None:
        from core.autonomous_mind import AutonomousMind

        mind = AutonomousMind.__new__(AutonomousMind)
        mind._config = _MindCfg(enabled=False)  # type: ignore[attr-defined]
        mind._task = None  # type: ignore[attr-defined]

        assert await AutonomousMind.start(mind) is False
        assert mind._task is None
