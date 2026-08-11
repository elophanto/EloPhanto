"""Off means off: nothing in-band may start the autonomous mind.

Regression: `set_next_wakeup` called `mind.start()` whenever the loop was not
running. The agent called it mid-goal with reason="Continue the active
private writing-learning goal" and started its own background loop while
`autonomous_mind.enabled` was false:

    11:09:57  Executing tool 'set_next_wakeup' {'seconds': 300, ...}
    11:09:57  Autonomous mind started (first wakeup in 240s)

`autonomous_mind.enabled` is the operator's switch. A setting that a caller
can talk its way past — by asking nicely, or by clearing an approval prompt —
is not a setting. This tool now only paces a mind that is already running.
"""

from __future__ import annotations

from typing import Any

import pytest

from tools.base import PermissionLevel
from tools.mind.wakeup_tool import SetNextWakeupTool


class _Cfg:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.min_wakeup_seconds = 60
        self.max_wakeup_seconds = 3600


class _Mind:
    def __init__(self, running: bool, enabled: bool) -> None:
        self.is_running = running
        self._config = _Cfg(enabled)
        self._next_wakeup_sec = 0.0
        self.start_calls = 0

    async def start(self) -> None:  # pragma: no cover — must never be called
        self.start_calls += 1
        self.is_running = True


def _tool(mind: Any) -> SetNextWakeupTool:
    tool = SetNextWakeupTool()
    tool._mind = mind
    return tool


class TestTheRegression:
    @pytest.mark.asyncio
    async def test_the_exact_call_from_the_log_starts_nothing(self) -> None:
        mind = _Mind(running=False, enabled=False)
        result = await _tool(mind).execute(
            {"seconds": 300, "reason": "Continue the active learning goal"}
        )

        assert mind.start_calls == 0
        assert mind.is_running is False
        assert result.data["mind_started"] is False
        assert result.data["next_wakeup_seconds"] is None
        assert "Only the operator" in result.data["note"]

    @pytest.mark.asyncio
    async def test_no_parameter_can_make_it_start(self) -> None:
        """There is no in-band override, however the call is dressed up."""
        for extra in (
            {"start_if_stopped": True},
            {"force": True},
            {"enable": True},
            {"start": True},
        ):
            mind = _Mind(running=False, enabled=False)
            await _tool(mind).execute({"seconds": 300, **extra})
            assert mind.start_calls == 0, f"{extra} started the mind"

    @pytest.mark.asyncio
    async def test_does_not_start_even_when_config_is_enabled(self) -> None:
        """Starting is the runtime's job at boot, never this tool's."""
        mind = _Mind(running=False, enabled=True)
        await _tool(mind).execute({"seconds": 300})
        assert mind.start_calls == 0

    def test_has_no_escalating_permission_path(self) -> None:
        """Nothing to approve, because nothing here can start a loop."""
        tool = SetNextWakeupTool()
        assert tool.permission_level == PermissionLevel.SAFE
        assert tool.dynamic_permission_level({"seconds": 300}) is None


class TestPacingAnAlreadyRunningMind:
    @pytest.mark.asyncio
    async def test_adjusts_the_interval(self) -> None:
        mind = _Mind(running=True, enabled=True)
        result = await _tool(mind).execute({"seconds": 600})

        assert result.data["next_wakeup_seconds"] == 600
        assert mind._next_wakeup_sec == 600.0
        assert result.data["running"] is True
        assert mind.start_calls == 0

    @pytest.mark.asyncio
    async def test_interval_is_clamped_to_config_bounds(self) -> None:
        mind = _Mind(running=True, enabled=True)
        assert (await _tool(mind).execute({"seconds": 5})).data["next_wakeup_seconds"] == 60
        assert (await _tool(mind).execute({"seconds": 99999})).data["next_wakeup_seconds"] == 3600

    @pytest.mark.asyncio
    async def test_missing_mind_is_an_error(self) -> None:
        tool = SetNextWakeupTool()
        tool._mind = None
        assert not (await tool.execute({"seconds": 300})).success


class TestDescription:
    def test_tells_the_model_it_cannot_start_the_mind(self) -> None:
        text = SetNextWakeupTool.description.lower()
        assert "cannot start it" in text
        assert "off, it is off" in text
