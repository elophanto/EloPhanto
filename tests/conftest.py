"""Shared test fixtures for EloPhanto tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import (
    BudgetConfig,
    Config,
    DatabaseConfig,
    KnowledgeConfig,
    LLMConfig,
    ProviderConfig,
    RoutingConfig,
    ShellConfig,
    SocietyConfig,
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "society: the test starts the Society from an Agent on purpose "
        "(it must still pass open_browser=False)",
    )


@pytest.fixture(autouse=True)
def _no_society_from_test_agents(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An Agent started by a test must never launch the Society campus.

    ``society.enabled`` and ``open_browser`` default to True, so every test
    that initialized an Agent started a campus server and opened a browser
    window on the operator's screen. Tests that exercise the Agent's own
    Society lifecycle opt in with ``@pytest.mark.society``; the Society's
    unit tests construct ``core.society.SocietyService`` directly.
    """
    if request.node.get_closest_marker("society"):
        return
    import core.agent

    class _SocietyOff:
        def __init__(self, *_a: object, **_kw: object) -> None:
            pass

        def start(self) -> bool:
            return False

    monkeypatch.setattr(core.agent, "SocietyService", _SocietyOff)


@pytest.fixture
def test_config(tmp_path: Path) -> Config:
    """Minimal config for testing."""
    return Config(
        agent_name="TestAgent",
        permission_mode="full_auto",
        max_steps=5,
        llm=LLMConfig(
            providers={
                "ollama": ProviderConfig(
                    enabled=True, base_url="http://localhost:11434"
                ),
            },
            provider_priority=["ollama"],
            routing={
                "planning": RoutingConfig(
                    preferred_provider="ollama",
                    models={"ollama": "qwen2.5:7b"},
                ),
            },
            budget=BudgetConfig(daily_limit_usd=10.0, per_task_limit_usd=2.0),
        ),
        shell=ShellConfig(
            timeout=10,
            blacklist_patterns=["rm -rf /", "mkfs", "dd if="],
            safe_commands=["ls", "cat", "pwd", "echo"],
        ),
        knowledge=KnowledgeConfig(
            knowledge_dir=str(tmp_path / "knowledge"),
            auto_index_on_startup=False,
        ),
        database=DatabaseConfig(
            db_path=str(tmp_path / "test.db"),
        ),
        project_root=tmp_path,
        society=SocietyConfig(enabled=False, open_browser=False),
    )


@pytest.fixture
def ask_always_config(test_config: Config) -> Config:
    """Config with ask_always permission mode."""
    test_config.permission_mode = "ask_always"
    return test_config
