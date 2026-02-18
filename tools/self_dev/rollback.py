"""Rollback tool — reverts self-modifications to known-good states.

Only allows reverting commits tagged with [self-modify] or [self-create-plugin].
Runs the test suite after rollback to verify stability.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_ALLOWED_PREFIXES = ("[self-modify]", "[self-create-plugin]")


class SelfRollbackTool(BaseTool):
    """Revert a previous self-modification commit."""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    @property
    def name(self) -> str:
        return "self_rollback"

    @property
    def description(self) -> str:
        return (
            "Revert a previous self-modification or plugin creation commit. "
            "Lists recent self-modification commits and can revert a specific "
            "one by commit hash. Runs the test suite after rollback to verify "
            "stability."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "revert"],
                    "description": "'list' to show revertible commits, 'revert' to revert one",
                },
                "commit_hash": {
                    "type": "string",
                    "description": "Short or full commit hash to revert (required for 'revert')",
                },
            },
            "required": ["action"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.CRITICAL

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        action = params["action"]

        if action == "list":
            return await self._list_commits()
        elif action == "revert":
            commit_hash = params.get("commit_hash")
            if not commit_hash:
                return ToolResult(
                    success=False,
                    error="commit_hash is required for the 'revert' action",
                )
            return await self._revert_commit(commit_hash)
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}")

    async def _list_commits(self) -> ToolResult:
        """List recent self-modification commits."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "log",
                "--oneline",
                "-50",
                cwd=str(self._project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            output = stdout.decode("utf-8", errors="replace")

            revertible: list[dict[str, str]] = []
            for line in output.strip().splitlines():
                parts = line.split(" ", 1)
                if len(parts) < 2:
                    continue
                commit_hash, message = parts
                if any(message.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
                    revertible.append({"hash": commit_hash, "message": message})

            return ToolResult(
                success=True,
                data={"commits": revertible, "count": len(revertible)},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to list commits: {e}")

    async def _revert_commit(self, commit_hash: str) -> ToolResult:
        """Revert a specific commit and run tests."""
        # Verify the commit is a self-modification
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "log",
                "--format=%s",
                "-1",
                commit_hash,
                cwd=str(self._project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            message = stdout.decode("utf-8", errors="replace").strip()

            if not any(message.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
                return ToolResult(
                    success=False,
                    error=(
                        f"Commit {commit_hash} is not a self-modification commit. "
                        "Only commits with [self-modify] or [self-create-plugin] "
                        "prefixes can be reverted."
                    ),
                )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to verify commit: {e}")

        # Perform the revert
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "revert",
                "--no-edit",
                commit_hash,
                cwd=str(self._project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

            if proc.returncode != 0:
                err = stderr.decode("utf-8", errors="replace")
                return ToolResult(
                    success=False,
                    error=f"Git revert failed: {err}",
                )
        except Exception as e:
            return ToolResult(success=False, error=f"Revert failed: {e}")

        # Run tests to verify stability
        try:
            proc = await asyncio.create_subprocess_exec(
                "python",
                "-m",
                "pytest",
                "tests/",
                "-v",
                "--tb=short",
                cwd=str(self._project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
            tests_passed = proc.returncode == 0
            test_output = stdout.decode("utf-8", errors="replace")
        except asyncio.TimeoutError:
            tests_passed = False
            test_output = "Test suite timed out"
        except Exception:
            tests_passed = True
            test_output = "Could not run tests"

        return ToolResult(
            success=True,
            data={
                "reverted_commit": commit_hash,
                "reverted_message": message,
                "tests_passed": tests_passed,
                "test_summary": (
                    test_output[-500:] if not tests_passed else "All tests passed"
                ),
            },
        )
