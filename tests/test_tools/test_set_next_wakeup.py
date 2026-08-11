"""The agent must not switch its own autonomy on.

Regression: `set_next_wakeup` called `mind.start()` whenever the loop was not
running, unconditionally. The agent called it mid-goal with
reason="Continue the active private writing-learning goal" and started a
background loop while `autonomous_mind.enabled` was false:

    11:09:57  Executing tool 'set_next_wakeup' {'seconds': 300, ...}
    11:09:57  Autonomous mind started (first wakeup in 240s)

`autonomous_mind.enabled` is in PROTECTED_CONFIG_KEYS so the agent cannot turn
autonomy off. The protection was one-directional — nothing stopped it turning
autonomy on, which is the direction that spends money unattended.
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

    async def start(self) -> None:
        self.start_calls += 1
        self.is_running = True


def _tool(mind: Any) -> SetNextWakeupTool:
    tool = SetNextWakeupTool()
    tool._mind = mind
    return tool


class TestTheRegression:
    @pytest.mark.asyncio
    async def test_does_not_self_start_when_operator_disabled_it(self) -> None:
        """The exact call from the log must no longer boot the loop."""
        mind = _Mind(running=False, enabled=False)
        result = await _tool(mind).execute(
            {"seconds": 300, "reason": "Continue the active learning goal"}
        )

        assert result.success
        assert mind.start_calls == 0
        assert mind.is_running is False
        assert result.data["mind_started"] is False
        assert "operator's choice" in result.data["note"]

    @pytest.mark.asyncio
    async def test_explicit_start_request_still_works(self) -> None:
        """'Turn on autonomous mode' from chat must keep working."""
        mind = _Mind(running=False, enabled=False)
        result = await _tool(mind).execute(
            {"seconds": 300, "start_if_stopped": True, "reason": "operator asked"}
        )

        assert mind.start_calls == 1
        assert result.data["mind_started"] is True
        assert "stop --hard" in result.data["note"]

    def test_starting_a_disabled_mind_requires_approval(self) -> None:
        mind = _Mind(running=False, enabled=False)
        level = _tool(mind).dynamic_permission_level(
            {"seconds": 300, "start_if_stopped": True}
        )
        assert level == PermissionLevel.CRITICAL


class TestNormalOperation:
    @pytest.mark.asyncio
    async def test_adjusting_a_running_mind_is_unchanged(self) -> None:
        mind = _Mind(running=True, enabled=True)
        result = await _tool(mind).execute({"seconds": 600})

        assert result.data["next_wakeup_seconds"] == 600
        assert mind._next_wakeup_sec == 600.0
        assert mind.start_calls == 0

    @pytest.mark.asyncio
    async def test_starts_without_asking_when_config_enables_it(self) -> None:
        """Configured-on means the operator already opted in."""
        mind = _Mind(running=False, enabled=True)
        result = await _tool(mind).execute({"seconds": 300})

        assert mind.start_calls == 1
        assert result.data["mind_started"] is True

    def test_interval_adjustment_stays_safe(self) -> None:
        mind = _Mind(running=True, enabled=True)
        assert (
            _tool(mind).dynamic_permission_level({"seconds": 300})
            == PermissionLevel.SAFE
        )

    @pytest.mark.asyncio
    async def test_interval_is_clamped_to_config_bounds(self) -> None:
        mind = _Mind(running=True, enabled=True)
        assert (await _tool(mind).execute({"seconds": 5})).data[
            "next_wakeup_seconds"
        ] == 60
        assert (await _tool(mind).execute({"seconds": 99999})).data[
            "next_wakeup_seconds"
        ] == 3600

    @pytest.mark.asyncio
    async def test_missing_mind_is_an_error(self) -> None:
        tool = SetNextWakeupTool()
        tool._mind = None
        result = await tool.execute({"seconds": 300})
        assert not result.success


class TestDescription:
    def test_tells_the_model_not_to_override_the_operator(self) -> None:
        text = SetNextWakeupTool.description.lower()
        assert "does not start the mind on its own" in text
        assert "only when the operator" in text
