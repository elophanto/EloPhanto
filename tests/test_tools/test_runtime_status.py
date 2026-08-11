"""`runtime_status` must see the loops that start themselves.

Regression: asked "are the multiagents still running?", the agent checked
swarm/kid/organization, found zero, and reported nothing was running — while
the goal runner was mid-checkpoint, having auto-resumed on startup. The spawn
tiers genuinely were empty; nothing the agent could call knew about the rest.
"""

from __future__ import annotations

from typing import Any

import pytest

from tools.base import ToolTier
from tools.system.runtime_status_tool import RuntimeStatusTool


class _Runner:
    def __init__(self, running: bool, goal_id: str | None = None) -> None:
        self.is_running = running
        self.current_goal_id = goal_id


class _Heartbeat:
    def __init__(self, running: bool, interval: int = 1800) -> None:
        self.is_running = running

        class _Cfg:
            check_interval_seconds = interval

        self._config = _Cfg()


class _Mind:
    def __init__(self, running: bool, paused: bool = False) -> None:
        self.is_running = running
        self.is_paused = paused


class _Agent:
    """Only what the tool reads — everything else stays absent on purpose."""

    def __init__(self, **kw: Any) -> None:
        self._goal_runner = kw.get("runner")
        self._heartbeat_engine = kw.get("heartbeat")
        self._autonomous_mind = kw.get("mind")
        self._scheduler = kw.get("scheduler")
        self._goal_manager = None
        self._swarm_manager = None
        self._kid_manager = None
        self._organization_manager = None
        self._config = kw.get("config")


def _tool(agent: Any) -> RuntimeStatusTool:
    tool = RuntimeStatusTool()
    tool._agent = agent
    return tool


class TestVisibility:
    def test_is_core_tier(self) -> None:
        """A trimmed profile must never make this question unanswerable."""
        assert RuntimeStatusTool().tier == ToolTier.CORE

    def test_description_tells_the_model_to_call_it_first(self) -> None:
        text = RuntimeStatusTool().description.lower()
        assert "always call this before" in text
        assert "goal runner" in text


class TestTheRegression:
    @pytest.mark.asyncio
    async def test_reports_a_goal_runner_the_spawn_tiers_cannot_see(self) -> None:
        """The exact case that produced a false 'nothing is running'."""
        tool = _tool(
            _Agent(runner=_Runner(True, "d2bcd9b7-c25"), heartbeat=_Heartbeat(True))
        )
        result = await tool.execute({})

        assert result.success
        assert result.data["anything_running"] is True
        assert "goal_runner" in result.data["active"]

        goal = next(
            entry for entry in result.data["loops"] if entry["name"] == "goal_runner"
        )
        assert goal["running"] is True
        assert goal["goal_id"] == "d2bcd9b7-c25"
        # Spawn tiers are genuinely zero — that was never the wrong part.
        assert result.data["spawned_agents"]["swarm"] == 0
        assert result.data["spawned_agents"]["kids"] == 0

    @pytest.mark.asyncio
    async def test_quiet_agent_reports_nothing_running(self) -> None:
        tool = _tool(
            _Agent(
                runner=_Runner(False),
                heartbeat=_Heartbeat(False),
                mind=_Mind(False),
            )
        )
        result = await tool.execute({})
        assert result.data["anything_running"] is False
        assert result.data["active"] == []


class TestEveryLoopIsCovered:
    @pytest.mark.asyncio
    async def test_all_four_self_starting_loops_are_reported(self) -> None:
        result = await _tool(_Agent()).execute({})
        names = {entry["name"] for entry in result.data["loops"]}
        assert names == {
            "goal_runner",
            "heartbeat",
            "autonomous_mind",
            "scheduler",
        }

    @pytest.mark.asyncio
    async def test_every_loop_carries_a_stop_command(self) -> None:
        """A status report the operator cannot act on is half an answer."""
        result = await _tool(_Agent()).execute({})
        for entry in result.data["loops"]:
            assert entry["stop_with"], f"{entry['name']} has no stop lever"
        assert "stop" in result.data["how_to_stop_everything"]

    @pytest.mark.asyncio
    async def test_paused_mind_is_distinguished_from_stopped(self) -> None:
        result = await _tool(_Agent(mind=_Mind(True, paused=True))).execute({})
        mind = next(
            entry
            for entry in result.data["loops"]
            if entry["name"] == "autonomous_mind"
        )
        assert mind["running"] is True
        assert mind["paused"] is True
        assert mind["detail"] == "paused"

    @pytest.mark.asyncio
    async def test_heartbeat_reports_its_interval(self) -> None:
        result = await _tool(_Agent(heartbeat=_Heartbeat(True, 900))).execute({})
        hb = next(
            entry for entry in result.data["loops"] if entry["name"] == "heartbeat"
        )
        assert "900" in hb["detail"]


class TestDegradesHonestly:
    @pytest.mark.asyncio
    async def test_a_broken_subsystem_is_not_reported_as_zero(self) -> None:
        """'Unavailable' and 'nothing running' must not look alike."""

        class Exploding:
            @property
            def is_running(self) -> bool:
                raise RuntimeError("subsystem is wedged")

        result = await _tool(_Agent(runner=Exploding())).execute({})
        goal = next(
            entry for entry in result.data["loops"] if entry["name"] == "goal_runner"
        )
        assert "unavailable" in goal["detail"]

    @pytest.mark.asyncio
    async def test_missing_agent_context_is_an_error_not_an_all_clear(self) -> None:
        tool = RuntimeStatusTool()
        result = await tool.execute({})
        assert not result.success
        assert "agent context" in result.error
