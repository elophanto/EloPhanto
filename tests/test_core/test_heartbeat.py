"""Heartbeat engine tests.

Tests the periodic HEARTBEAT.md reader without making actual LLM calls.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.config import Config, HeartbeatConfig
from core.heartbeat import HeartbeatEngine


@pytest.fixture
def heartbeat_config() -> HeartbeatConfig:
    return HeartbeatConfig(
        enabled=True,
        file_path="HEARTBEAT.md",
        check_interval_seconds=10,
        max_rounds=4,
        suppress_idle=True,
    )


@pytest.fixture
def mock_agent() -> MagicMock:
    agent = MagicMock()
    agent._conversation_history = []
    agent._executor = MagicMock()
    agent._executor._approval_callback = None
    agent._executor.set_approval_callback = MagicMock()
    agent.run = AsyncMock(return_value=MagicMock(content="Task completed successfully"))
    return agent


@pytest.fixture
def engine(
    heartbeat_config: HeartbeatConfig,
    mock_agent: MagicMock,
    tmp_path: Path,
) -> HeartbeatEngine:
    return HeartbeatEngine(
        agent=mock_agent,
        gateway=None,
        config=heartbeat_config,
        project_root=tmp_path,
    )


class TestHeartbeatEngine:
    def test_init_sets_file_path(self, engine: HeartbeatEngine, tmp_path: Path) -> None:
        assert engine._file_path == tmp_path / "HEARTBEAT.md"

    def test_init_not_running(self, engine: HeartbeatEngine) -> None:
        assert not engine.is_running
        assert not engine.is_paused

    def test_read_heartbeat_missing_file(self, engine: HeartbeatEngine) -> None:
        assert engine._read_heartbeat_file() == ""

    def test_read_heartbeat_empty_file(
        self, engine: HeartbeatEngine, tmp_path: Path
    ) -> None:
        (tmp_path / "HEARTBEAT.md").write_text("", encoding="utf-8")
        assert engine._read_heartbeat_file() == ""

    def test_read_heartbeat_with_content(
        self, engine: HeartbeatEngine, tmp_path: Path
    ) -> None:
        (tmp_path / "HEARTBEAT.md").write_text("Check email", encoding="utf-8")
        assert engine._read_heartbeat_file() == "Check email"

    def test_read_heartbeat_strips_whitespace(
        self, engine: HeartbeatEngine, tmp_path: Path
    ) -> None:
        (tmp_path / "HEARTBEAT.md").write_text(
            "  \n  Check email  \n  ", encoding="utf-8"
        )
        assert engine._read_heartbeat_file() == "Check email"

    def test_pause_and_resume(self, engine: HeartbeatEngine) -> None:
        # Can't pause when not running
        engine.notify_user_interaction()
        assert not engine.is_paused

    def test_get_status(self, engine: HeartbeatEngine, tmp_path: Path) -> None:
        status = engine.get_status()
        assert status["running"] is False
        assert status["paused"] is False
        assert status["cycle_count"] == 0
        assert status["tasks_executed"] == 0
        assert status["file_exists"] is False
        assert status["interval_seconds"] == 10

    @pytest.mark.asyncio
    async def test_check_and_execute_empty_file(
        self, engine: HeartbeatEngine, mock_agent: MagicMock
    ) -> None:
        """No LLM call when HEARTBEAT.md is empty/missing."""
        await engine._check_and_execute()
        mock_agent.run.assert_not_called()
        assert engine._tasks_executed == 0

    @pytest.mark.asyncio
    async def test_check_and_execute_with_content(
        self,
        engine: HeartbeatEngine,
        mock_agent: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Calls agent.run when HEARTBEAT.md has content."""
        (tmp_path / "HEARTBEAT.md").write_text("Send daily report", encoding="utf-8")
        await engine._check_and_execute()
        mock_agent.run.assert_called_once()
        call_args = mock_agent.run.call_args
        assert "Send daily report" in call_args[0][0]
        assert call_args[1]["max_steps_override"] == 4
        assert engine._tasks_executed == 1

    @pytest.mark.asyncio
    async def test_check_and_execute_heartbeat_ok(
        self,
        engine: HeartbeatEngine,
        mock_agent: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Agent responding HEARTBEAT_OK counts as idle, not as task executed."""
        mock_agent.run = AsyncMock(
            return_value=MagicMock(content="HEARTBEAT_OK — nothing to do")
        )
        (tmp_path / "HEARTBEAT.md").write_text("Check for updates", encoding="utf-8")
        await engine._check_and_execute()
        assert engine._tasks_executed == 0
        assert "HEARTBEAT_OK" in engine._last_action

    @pytest.mark.asyncio
    async def test_conversation_history_isolated(
        self,
        engine: HeartbeatEngine,
        mock_agent: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Heartbeat execution doesn't pollute conversation history."""
        mock_agent._conversation_history = [{"role": "user", "content": "hello"}]
        (tmp_path / "HEARTBEAT.md").write_text("Do something", encoding="utf-8")
        await engine._check_and_execute()
        # History should be restored
        assert len(mock_agent._conversation_history) == 1
        assert mock_agent._conversation_history[0]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_start_and_cancel(self, engine: HeartbeatEngine) -> None:
        """Engine can start and cancel cleanly."""
        started = await engine.start()
        assert started is True
        assert engine.is_running
        await engine.cancel()
        assert not engine.is_running

    @pytest.mark.asyncio
    async def test_start_twice_returns_false(self, engine: HeartbeatEngine) -> None:
        """Starting when already running returns False."""
        await engine.start()
        assert await engine.start() is False
        await engine.cancel()


class TestHeartbeatConfig:
    def test_defaults(self) -> None:
        cfg = HeartbeatConfig()
        assert cfg.enabled is False
        assert cfg.file_path == "HEARTBEAT.md"
        assert cfg.check_interval_seconds == 1800
        assert cfg.max_rounds == 8
        assert cfg.suppress_idle is True

    def test_config_parsing(self) -> None:
        """HeartbeatConfig is accessible on the Config object."""
        config = Config()
        assert hasattr(config, "heartbeat")
        assert isinstance(config.heartbeat, HeartbeatConfig)
