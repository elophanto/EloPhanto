"""Tests for the shell_execute tool."""

from __future__ import annotations

import pytest

from core.config import Config
from tools.system.shell import ShellExecuteTool


class TestShellExecute:
    @pytest.fixture
    def shell_tool(self, test_config: Config) -> ShellExecuteTool:
        return ShellExecuteTool(test_config)

    @pytest.mark.asyncio
    async def test_simple_command(self, shell_tool: ShellExecuteTool) -> None:
        result = await shell_tool.execute({"command": "echo hello"})
        assert result.success
        assert "hello" in result.data["stdout"]
        assert result.data["exit_code"] == 0
        assert result.data["timed_out"] is False

    @pytest.mark.asyncio
    async def test_command_with_stderr(self, shell_tool: ShellExecuteTool) -> None:
        result = await shell_tool.execute({"command": "echo error >&2"})
        assert result.success
        assert "error" in result.data["stderr"]

    @pytest.mark.asyncio
    async def test_nonexistent_command(self, shell_tool: ShellExecuteTool) -> None:
        result = await shell_tool.execute({"command": "nonexistent_cmd_xyz_123"})
        assert result.success  # Process ran, just with non-zero exit
        assert result.data["exit_code"] != 0

    @pytest.mark.asyncio
    async def test_blacklisted_command_blocked(
        self, shell_tool: ShellExecuteTool
    ) -> None:
        result = await shell_tool.execute({"command": "rm -rf /"})
        assert not result.success
        assert result.error is not None
        assert "blocked" in result.error.lower() or "blacklist" in result.error.lower()

    @pytest.mark.asyncio
    async def test_blacklisted_pattern_in_longer_command(
        self, shell_tool: ShellExecuteTool
    ) -> None:
        result = await shell_tool.execute(
            {"command": "sudo rm -rf / --no-preserve-root"}
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_timeout(self, test_config: Config) -> None:
        test_config.shell.timeout = 1
        tool = ShellExecuteTool(test_config)
        result = await tool.execute({"command": "sleep 10", "timeout": 1})
        assert result.success
        assert result.data["timed_out"] is True

    def test_is_safe_command(self, shell_tool: ShellExecuteTool) -> None:
        assert shell_tool.is_safe_command("ls -la")
        assert shell_tool.is_safe_command("cat /etc/hosts")
        assert shell_tool.is_safe_command("pwd")
        assert not shell_tool.is_safe_command("rm file.txt")
        assert not shell_tool.is_safe_command("python script.py")

    def test_is_blacklisted(self, shell_tool: ShellExecuteTool) -> None:
        assert shell_tool.is_blacklisted("rm -rf /")
        assert shell_tool.is_blacklisted("sudo mkfs.ext4 /dev/sda1")
        assert not shell_tool.is_blacklisted("rm file.txt")
        assert not shell_tool.is_blacklisted("ls -la")
