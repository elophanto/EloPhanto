"""Stale shame must not pin the self-model, and the gate must explain itself.

Production state that motivated this: 6,314 outcomes with a 100% success rate,
coherence 1.00 — and felt_state 'shame', because the newest 5 humbling events
of ALL TIME were loaded with no date filter and the freshest was a month old.
The dashboard showed FAULT permanently and the operator could not tell a
deliberate caution from a broken permission mode.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.ego import _HUMBLING_RECENT_DAYS, Ego, EgoManager, HumblingEvent


def _mgr() -> EgoManager:
    return EgoManager.__new__(EgoManager)


def _event(days_ago: float) -> HumblingEvent:
    ts = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    return HumblingEvent(
        capability="skill_read", claimed="c", actual="a", task_goal="g", created_at=ts
    )


def _clean_ego() -> Ego:
    ego = Ego()
    ego.coherence_score = 1.0
    ego.recent_outcomes = [True] * 10
    return ego


class TestFeltStateRecency:
    def test_stale_shame_does_not_pin_the_mood(self) -> None:
        """The production bug, exactly."""
        ego = _clean_ego()
        ego.humbling_events = [_event(30) for _ in range(5)]
        _mgr()._refresh_felt_state(ego)
        assert ego.felt_state == "pride"

    def test_fresh_shame_still_registers(self) -> None:
        ego = _clean_ego()
        ego.humbling_events = [_event(1) for _ in range(3)]
        _mgr()._refresh_felt_state(ego)
        assert ego.felt_state == "shame"

    def test_boundary_is_the_configured_window(self) -> None:
        just_inside = _clean_ego()
        just_inside.humbling_events = [_event(_HUMBLING_RECENT_DAYS - 1) for _ in range(3)]
        _mgr()._refresh_felt_state(just_inside)
        assert just_inside.felt_state == "shame"

        just_outside = _clean_ego()
        just_outside.humbling_events = [_event(_HUMBLING_RECENT_DAYS + 1) for _ in range(3)]
        _mgr()._refresh_felt_state(just_outside)
        assert just_outside.felt_state == "pride"

    def test_pride_is_reachable_at_all(self) -> None:
        """Previously unreachable for any agent with 3+ lifetime humblings —
        the softener required fewer than 3, but the list is capped at the
        newest 5 of all time."""
        ego = _clean_ego()
        ego.humbling_events = [_event(60) for _ in range(5)]
        _mgr()._refresh_felt_state(ego)
        assert ego.felt_state == "pride"

    def test_undated_event_counts_as_recent(self) -> None:
        # Fail cautious: a parse failure must not silently clear real shame.
        ego = _clean_ego()
        ego.humbling_events = [
            HumblingEvent(capability="c", claimed="x", actual="y", task_goal="g",
                          created_at="not-a-date")
            for _ in range(3)
        ]
        _mgr()._refresh_felt_state(ego)
        assert ego.felt_state == "shame"

    def test_poor_recent_rate_still_shames_without_any_humbling(self) -> None:
        ego = Ego()
        ego.coherence_score = 1.0
        ego.recent_outcomes = [False] * 8 + [True] * 2
        _mgr()._refresh_felt_state(ego)
        assert ego.felt_state == "shame"


class TestSoftGateOverride:
    def test_soft_gate_defaults_on(self) -> None:
        from core.config import EgoConfig

        assert EgoConfig().soft_gate is True

    def test_config_can_disable_it(self, tmp_path) -> None:
        from core.config import load_config

        p = tmp_path / "config.yaml"
        p.write_text("agent:\n  name: T\nego:\n  soft_gate: false\n")
        assert load_config(str(p)).ego.soft_gate is False

    @pytest.mark.asyncio
    async def test_disabled_gate_lets_full_auto_mean_full_auto(self) -> None:
        """The operator's escape hatch: full_auto stops being overridden."""
        from unittest.mock import MagicMock

        from core.executor import Executor
        from tools.base import PermissionLevel

        cfg = MagicMock()
        cfg.permission_mode = "full_auto"
        cfg.ego.soft_gate = False
        cfg.project_root = "."

        ex = Executor.__new__(Executor)
        ex._config = cfg
        ex._tool_overrides = {}
        ex._disabled_tools = set()
        ex._approval_callback = lambda *a: False  # would DENY if consulted
        ex._role_manager = None

        # An ego that would otherwise force the ask.
        class _Ego:
            async def should_attempt(self, cap, difficulty=0.5):
                return "decline"

            async def get_ego(self):
                return Ego()

        ex._ego_manager = _Ego()

        tool = MagicMock()
        tool.name = "browser_navigate"
        tool.permission_level = PermissionLevel.MODERATE

        assert await ex._check_permission(tool, {}) is True
