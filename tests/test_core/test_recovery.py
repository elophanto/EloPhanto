"""Tests for Recovery Mode — command handling, health checks, config ops."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.recovery import (
    RecoveryHandler,
    _get_nested_attr,
    _is_safe_key,
    _set_nested_attr,
)

# ---------------------------------------------------------------------------
# Test fixtures — minimal config/router stubs
# ---------------------------------------------------------------------------


@dataclass
class _StubProviderConfig:
    api_key: str = ""
    enabled: bool = True
    base_url: str = ""


@dataclass
class _StubBudgetConfig:
    daily_limit_usd: float = 10.0
    per_task_limit_usd: float = 2.0


@dataclass
class _StubLLMConfig:
    providers: dict[str, _StubProviderConfig] = field(default_factory=dict)
    provider_priority: list[str] = field(default_factory=list)
    budget: _StubBudgetConfig = field(default_factory=_StubBudgetConfig)


@dataclass
class _StubBrowserConfig:
    enabled: bool = False


@dataclass
class _StubConfig:
    llm: _StubLLMConfig = field(default_factory=_StubLLMConfig)
    browser: _StubBrowserConfig = field(default_factory=_StubBrowserConfig)
    permission_mode: str = "ask_always"
    project_root: str = "/tmp/test"


def _make_config(**provider_overrides: bool) -> _StubConfig:
    """Create a config with providers: ollama, openrouter, zai."""
    providers = {
        "ollama": _StubProviderConfig(enabled=provider_overrides.get("ollama", True)),
        "openrouter": _StubProviderConfig(
            enabled=provider_overrides.get("openrouter", True)
        ),
        "zai": _StubProviderConfig(enabled=provider_overrides.get("zai", True)),
    }
    return _StubConfig(
        llm=_StubLLMConfig(
            providers=providers,
            provider_priority=["ollama", "openrouter", "zai"],
        )
    )


class _StubCostTracker:
    daily_total: float = 1.23
    task_total: float = 0.45


class _StubRouter:
    """Minimal router mock with health tracking."""

    def __init__(self, health: dict[str, bool] | None = None) -> None:
        self._provider_health: dict[str, bool] = health or {}
        self._provider_failed_at: dict[str, float] = {}
        self._cost_tracker = _StubCostTracker()

    @property
    def cost_tracker(self) -> _StubCostTracker:
        return self._cost_tracker

    def _is_healthy(self, name: str) -> bool:
        return self._provider_health.get(name, True)

    async def health_check(self) -> dict[str, bool]:
        return dict(self._provider_health)


# ---------------------------------------------------------------------------
# Safe key validation
# ---------------------------------------------------------------------------


class TestSafeKeyValidation:
    def test_safe_llm_provider_key(self) -> None:
        assert _is_safe_key("llm.providers.openrouter.api_key") is True

    def test_safe_provider_priority(self) -> None:
        assert _is_safe_key("llm.provider_priority") is True

    def test_safe_budget_key(self) -> None:
        assert _is_safe_key("llm.budget.daily_limit_usd") is True

    def test_safe_browser_enabled(self) -> None:
        assert _is_safe_key("browser.enabled") is True

    def test_blocked_permission_mode(self) -> None:
        assert _is_safe_key("permission_mode") is False

    def test_blocked_shell_blacklist(self) -> None:
        assert _is_safe_key("shell.blacklist_patterns") is False

    def test_blocked_allowed_users(self) -> None:
        assert _is_safe_key("telegram.allowed_users") is False

    def test_blocked_allowed_guilds(self) -> None:
        assert _is_safe_key("discord.allowed_guilds") is False

    def test_blocked_allowed_channels(self) -> None:
        assert _is_safe_key("slack.allowed_channels") is False

    def test_random_key_blocked(self) -> None:
        assert _is_safe_key("agent_name") is False


# ---------------------------------------------------------------------------
# Nested attribute access
# ---------------------------------------------------------------------------


class TestNestedAttr:
    def test_get_simple(self) -> None:
        config = _make_config()
        assert _get_nested_attr(config, "permission_mode") == "ask_always"

    def test_get_nested(self) -> None:
        config = _make_config()
        assert isinstance(_get_nested_attr(config, "llm.providers"), dict)

    def test_get_deep_nested(self) -> None:
        config = _make_config()
        result = _get_nested_attr(config, "llm.providers.ollama.enabled")
        assert result is True

    def test_get_missing_raises(self) -> None:
        config = _make_config()
        with pytest.raises(KeyError):
            _get_nested_attr(config, "nonexistent.key")

    def test_set_simple(self) -> None:
        config = _make_config()
        _set_nested_attr(config, "permission_mode", "full_auto")
        assert config.permission_mode == "full_auto"

    def test_set_nested(self) -> None:
        config = _make_config()
        _set_nested_attr(config, "llm.provider_priority", ["zai", "ollama"])
        assert config.llm.provider_priority == ["zai", "ollama"]

    def test_set_dict_value(self) -> None:
        config = _make_config()
        _set_nested_attr(config, "llm.providers.ollama.enabled", False)
        assert config.llm.providers["ollama"].enabled is False


# ---------------------------------------------------------------------------
# Recovery mode state
# ---------------------------------------------------------------------------


class TestRecoveryState:
    def test_starts_inactive(self) -> None:
        handler = RecoveryHandler(_make_config(), _StubRouter())
        assert handler.recovery_mode is False

    def test_enter_exit(self) -> None:
        handler = RecoveryHandler(_make_config(), _StubRouter())
        result = handler.enter_recovery("test")
        assert handler.recovery_mode is True
        assert "ACTIVE" in result

        result = handler.exit_recovery()
        assert handler.recovery_mode is False
        assert "OFF" in result

    def test_double_enter(self) -> None:
        handler = RecoveryHandler(_make_config(), _StubRouter())
        handler.enter_recovery()
        result = handler.enter_recovery()
        assert "Already" in result

    def test_exit_when_not_active(self) -> None:
        handler = RecoveryHandler(_make_config(), _StubRouter())
        result = handler.exit_recovery()
        assert "Not in" in result


# ---------------------------------------------------------------------------
# /health command
# ---------------------------------------------------------------------------


class TestHealthCommand:
    @pytest.mark.asyncio
    async def test_health_report(self) -> None:
        config = _make_config()
        router = _StubRouter({"ollama": True, "openrouter": False, "zai": True})
        handler = RecoveryHandler(config, router)

        result = await handler.handle("health")
        assert result is not None
        assert "ollama" in result
        assert "healthy" in result
        assert "UNHEALTHY" in result

    @pytest.mark.asyncio
    async def test_health_shows_budget(self) -> None:
        handler = RecoveryHandler(_make_config(), _StubRouter())
        result = await handler.handle("health")
        assert "$1.23" in result

    @pytest.mark.asyncio
    async def test_health_shows_priority(self) -> None:
        handler = RecoveryHandler(_make_config(), _StubRouter())
        result = await handler.handle("health")
        assert "ollama -> openrouter -> zai" in result

    @pytest.mark.asyncio
    async def test_health_recheck(self) -> None:
        router = _StubRouter({"ollama": True, "openrouter": True})
        handler = RecoveryHandler(_make_config(), router)
        result = await handler.handle("health recheck")
        assert "Recheck" in result

    @pytest.mark.asyncio
    async def test_health_recheck_auto_recovery(self) -> None:
        """If recheck finds all down, auto-enters recovery mode."""
        router = _StubRouter({"ollama": False, "openrouter": False, "zai": False})
        handler = RecoveryHandler(_make_config(), router)
        result = await handler.handle("health recheck")
        assert handler.recovery_mode is True
        assert "auto-entered" in result


# ---------------------------------------------------------------------------
# /config command
# ---------------------------------------------------------------------------


class TestConfigCommand:
    @pytest.mark.asyncio
    async def test_config_get(self) -> None:
        config = _make_config()
        handler = RecoveryHandler(config, _StubRouter())
        result = await handler.handle("config get llm.provider_priority")
        assert "ollama" in result
        assert "openrouter" in result

    @pytest.mark.asyncio
    async def test_config_get_missing(self) -> None:
        handler = RecoveryHandler(_make_config(), _StubRouter())
        result = await handler.handle("config get nonexistent")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_config_set_safe_key(self) -> None:
        config = _make_config()
        handler = RecoveryHandler(config, _StubRouter())
        result = await handler.handle(
            'config set llm.provider_priority ["zai","ollama"]'
        )
        assert "Updated" in result
        assert config.llm.provider_priority == ["zai", "ollama"]

    @pytest.mark.asyncio
    async def test_config_set_blocked_key(self) -> None:
        config = _make_config()
        handler = RecoveryHandler(config, _StubRouter())
        result = await handler.handle("config set permission_mode full_auto")
        assert "Blocked" in result
        # Should NOT have changed
        assert config.permission_mode == "ask_always"

    @pytest.mark.asyncio
    async def test_config_usage_on_empty(self) -> None:
        handler = RecoveryHandler(_make_config(), _StubRouter())
        result = await handler.handle("config")
        assert "Usage" in result


# ---------------------------------------------------------------------------
# /provider command
# ---------------------------------------------------------------------------


class TestProviderCommand:
    @pytest.mark.asyncio
    async def test_provider_disable(self) -> None:
        config = _make_config()
        handler = RecoveryHandler(config, _StubRouter())
        result = await handler.handle("provider disable ollama")
        assert "disabled" in result
        assert config.llm.providers["ollama"].enabled is False

    @pytest.mark.asyncio
    async def test_provider_enable(self) -> None:
        config = _make_config(ollama=False)
        router = _StubRouter({"ollama": False})
        handler = RecoveryHandler(config, router)
        result = await handler.handle("provider enable ollama")
        assert "enabled" in result
        assert config.llm.providers["ollama"].enabled is True
        # Health should be reset so router tries it
        assert "ollama" not in router._provider_health

    @pytest.mark.asyncio
    async def test_provider_unknown(self) -> None:
        handler = RecoveryHandler(_make_config(), _StubRouter())
        result = await handler.handle("provider enable nonexistent")
        assert "Unknown" in result

    @pytest.mark.asyncio
    async def test_provider_priority_comma(self) -> None:
        config = _make_config()
        handler = RecoveryHandler(config, _StubRouter())
        result = await handler.handle("provider priority zai,openrouter,ollama")
        assert "updated" in result
        assert config.llm.provider_priority == ["zai", "openrouter", "ollama"]

    @pytest.mark.asyncio
    async def test_provider_priority_spaces(self) -> None:
        config = _make_config()
        handler = RecoveryHandler(config, _StubRouter())
        result = await handler.handle("provider priority zai openrouter ollama")
        assert "updated" in result
        assert config.llm.provider_priority == ["zai", "openrouter", "ollama"]

    @pytest.mark.asyncio
    async def test_provider_priority_invalid(self) -> None:
        handler = RecoveryHandler(_make_config(), _StubRouter())
        result = await handler.handle("provider priority unknown_provider")
        assert "Unknown" in result

    @pytest.mark.asyncio
    async def test_provider_usage_on_empty(self) -> None:
        handler = RecoveryHandler(_make_config(), _StubRouter())
        result = await handler.handle("provider")
        assert "Usage" in result


# ---------------------------------------------------------------------------
# /recovery command
# ---------------------------------------------------------------------------


class TestRecoveryCommand:
    @pytest.mark.asyncio
    async def test_recovery_on(self) -> None:
        handler = RecoveryHandler(_make_config(), _StubRouter())
        result = await handler.handle("recovery on")
        assert handler.recovery_mode is True
        assert "ACTIVE" in result

    @pytest.mark.asyncio
    async def test_recovery_off(self) -> None:
        handler = RecoveryHandler(_make_config(), _StubRouter())
        handler.enter_recovery()
        result = await handler.handle("recovery off")
        assert handler.recovery_mode is False
        assert "OFF" in result

    @pytest.mark.asyncio
    async def test_recovery_log(self) -> None:
        handler = RecoveryHandler(_make_config(), _StubRouter())
        handler.enter_recovery()
        handler.exit_recovery()
        result = await handler.handle("recovery log")
        assert "recovery on" in result
        assert "recovery off" in result

    @pytest.mark.asyncio
    async def test_recovery_status_display(self) -> None:
        handler = RecoveryHandler(_make_config(), _StubRouter())
        result = await handler.handle("recovery")
        assert "off" in result
        assert "Usage" in result


# ---------------------------------------------------------------------------
# /restart command
# ---------------------------------------------------------------------------


class TestRestartCommand:
    @pytest.mark.asyncio
    async def test_restart_calls_initialize(self) -> None:
        agent = MagicMock()
        agent.initialize = AsyncMock()
        handler = RecoveryHandler(_make_config(), _StubRouter(), agent=agent)
        result = await handler.handle("restart")
        agent.initialize.assert_called_once()
        assert "re-initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_restart_exits_recovery(self) -> None:
        agent = MagicMock()
        agent.initialize = AsyncMock()
        handler = RecoveryHandler(_make_config(), _StubRouter(), agent=agent)
        handler.enter_recovery()
        await handler.handle("restart")
        assert handler.recovery_mode is False

    @pytest.mark.asyncio
    async def test_restart_no_agent(self) -> None:
        handler = RecoveryHandler(_make_config(), _StubRouter(), agent=None)
        result = await handler.handle("restart")
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_restart_failure(self) -> None:
        agent = MagicMock()
        agent.initialize = AsyncMock(side_effect=RuntimeError("init failed"))
        handler = RecoveryHandler(_make_config(), _StubRouter(), agent=agent)
        result = await handler.handle("restart")
        assert "failed" in result.lower()


# ---------------------------------------------------------------------------
# Unknown command returns None
# ---------------------------------------------------------------------------


class TestUnknownCommand:
    @pytest.mark.asyncio
    async def test_unknown_returns_none(self) -> None:
        handler = RecoveryHandler(_make_config(), _StubRouter())
        result = await handler.handle("unknown_command")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_returns_none(self) -> None:
        handler = RecoveryHandler(_make_config(), _StubRouter())
        result = await handler.handle("")
        assert result is None


# ---------------------------------------------------------------------------
# Auto-recovery check
# ---------------------------------------------------------------------------


class TestAutoRecovery:
    def test_auto_recovery_all_down(self) -> None:
        config = _make_config()
        router = _StubRouter({"ollama": False, "openrouter": False, "zai": False})
        handler = RecoveryHandler(config, router)

        notification = handler.check_auto_recovery()
        assert notification is not None
        assert "recovery mode" in notification.lower()
        assert handler.recovery_mode is True

    def test_no_auto_recovery_some_healthy(self) -> None:
        config = _make_config()
        router = _StubRouter({"ollama": False, "openrouter": True, "zai": False})
        handler = RecoveryHandler(config, router)

        notification = handler.check_auto_recovery()
        assert notification is None
        assert handler.recovery_mode is False

    def test_no_double_auto_recovery(self) -> None:
        config = _make_config()
        router = _StubRouter({"ollama": False, "openrouter": False, "zai": False})
        handler = RecoveryHandler(config, router)

        handler.enter_recovery()
        # Should return None since already in recovery
        notification = handler.check_auto_recovery()
        assert notification is None
