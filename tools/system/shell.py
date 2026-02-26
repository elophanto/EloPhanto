"""Shell command execution tool."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from typing import Any

from core.config import Config
from core.protected import check_command_for_protected
from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class ShellExecuteTool(BaseTool):
    """Runs shell commands on the user's system."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._process_registry: Any | None = None

    def set_process_registry(self, registry: Any) -> None:
        """Inject process registry for resource tracking."""
        self._process_registry = registry

    @property
    def name(self) -> str:
        return "shell_execute"

    @property
    def description(self) -> str:
        return (
            "Runs a shell command on the user's system and returns stdout, stderr, "
            "and exit code. Use this for system operations like running scripts, "
            "checking system state, installing packages, or any command-line task."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "working_directory": {
                    "type": "string",
                    "description": "Working directory for the command (optional)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: from config)",
                },
            },
            "required": ["command"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    def is_blacklisted(self, command: str) -> bool:
        """Check if a command matches any blacklist pattern."""
        cmd_lower = command.lower().strip()
        for pattern in self._config.shell.blacklist_patterns:
            if pattern.lower() in cmd_lower:
                return True
        return False

    def is_safe_command(self, command: str) -> bool:
        """Check if a command starts with a known safe command."""
        cmd_stripped = command.strip()
        first_word = cmd_stripped.split()[0] if cmd_stripped else ""
        return first_word in self._config.shell.safe_commands

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        command = params["command"]
        working_dir = params.get("working_directory")
        timeout = params.get("timeout", self._config.shell.timeout)

        if self.is_blacklisted(command):
            return ToolResult(
                success=False,
                error=(
                    "Command blocked: matches a blacklisted pattern. "
                    "This command is considered dangerous and cannot be executed."
                ),
            )

        protected_msg = check_command_for_protected(command)
        if protected_msg:
            return ToolResult(success=False, error=protected_msg)

        # Process registry: prune dead entries and check capacity
        if self._process_registry:
            self._process_registry.cleanup_dead()
            if self._process_registry.at_capacity:
                return ToolResult(
                    success=False,
                    error=(
                        f"Too many concurrent processes "
                        f"({self._process_registry.count}). "
                        f"Wait for running commands to complete."
                    ),
                )

        cmd_short = command[:120] + ("…" if len(command) > 120 else "")
        logger.info(
            "[shell] START: %s (timeout=%ss, cwd=%s)",
            cmd_short,
            timeout,
            working_dir or ".",
        )
        t0 = time.monotonic()

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                start_new_session=True,
            )

            if self._process_registry and process.pid:
                self._process_registry.register(process.pid, command[:100])

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
                timed_out = False
            except TimeoutError:
                elapsed = time.monotonic() - t0
                # Kill entire process group (shell + all children)
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    process.kill()
                await process.communicate()
                if self._process_registry and process.pid:
                    self._process_registry.unregister(process.pid)
                logger.warning(
                    "[shell] TIMEOUT after %.1fs: %s (pid=%s)",
                    elapsed,
                    cmd_short,
                    process.pid,
                )
                return ToolResult(
                    success=True,
                    data={
                        "stdout": "",
                        "stderr": f"Command timed out after {timeout} seconds",
                        "exit_code": -1,
                        "timed_out": True,
                    },
                )

            if self._process_registry and process.pid:
                self._process_registry.unregister(process.pid)

            elapsed = time.monotonic() - t0
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = process.returncode or 0

            # Log completion with key details
            stdout_preview = stdout.strip()[-200:] if stdout.strip() else "(empty)"
            stderr_preview = stderr.strip()[-200:] if stderr.strip() else "(empty)"
            logger.info(
                "[shell] DONE in %.1fs: exit_code=%d | %s",
                elapsed,
                exit_code,
                cmd_short,
            )
            if exit_code != 0 or stderr.strip():
                logger.info("[shell] stderr: %s", stderr_preview)
            logger.debug("[shell] stdout: %s", stdout_preview)

            return ToolResult(
                success=True,
                data={
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": exit_code,
                    "timed_out": timed_out,
                },
            )

        except Exception as e:
            elapsed = time.monotonic() - t0
            logger.error("[shell] FAILED after %.1fs: %s — %s", elapsed, cmd_short, e)
            return ToolResult(success=False, error=f"Failed to execute command: {e}")
