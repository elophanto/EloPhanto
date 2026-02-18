"""Shared test fixtures for EloPhanto tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import (
    BrowserConfig,
    BudgetConfig,
    Config,
    DatabaseConfig,
    KnowledgeConfig,
    LLMConfig,
    PluginConfig,
    ProviderConfig,
    RoutingConfig,
    SchedulerConfig,
    SelfDevConfig,
    ShellConfig,
)


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
                    preferred_model="qwen2.5:7b",
                    local_fallback="qwen2.5:7b",
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
    )


@pytest.fixture
def ask_always_config(test_config: Config) -> Config:
    """Config with ask_always permission mode."""
    test_config.permission_mode = "ask_always"
    return test_config
