"""Self-run tests tool — runs pytest in a subprocess with timeout."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class SelfRunTestsTool(BaseTool):
    """Runs tests using pytest in a subprocess."""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    @property
    def name(self) -> str:
        return "self_run_tests"

    @property
    def description(self) -> str:
        return (
            "Run tests using pytest. Can run all tests, a specific test file, or "
            "a specific test class/method. Returns pass/fail status and output."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": (
                        "Test target: 'all', a file path, or specific test "
                        "(e.g., 'tests/test_tools/test_shell.py::TestShell::test_echo')"
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 60, max: 300)",
                },
                "verbose": {
                    "type": "boolean",
                    "description": "Show verbose output (default: false)",
                },
            },
            "required": ["target"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        target = params["target"]
        timeout = min(params.get("timeout", 60), 300)
        verbose = params.get("verbose", False)

        # Build pytest command
        cmd = ["python", "-m", "pytest"]
        if verbose:
            cmd.append("-v")
        cmd.append("--tb=short")
        cmd.append("--no-header")

        if target != "all":
            cmd.append(target)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._project_root),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except TimeoutError:
                process.kill()
                await process.communicate()
                return ToolResult(
                    success=False,
                    data={"timed_out": True, "timeout": timeout},
                    error=f"Tests timed out after {timeout}s",
                )

            output = stdout.decode("utf-8", errors="replace")
            error_output = stderr.decode("utf-8", errors="replace")
            exit_code = process.returncode or 0

            # Parse results from pytest output
            passed, failed, errors, skipped = _parse_pytest_summary(output)

            return ToolResult(
                success=exit_code == 0,
                data={
                    "passed": passed,
                    "failed": failed,
                    "errors": errors,
                    "skipped": skipped,
                    "exit_code": exit_code,
                    "output": output[-3000:] if len(output) > 3000 else output,
                    "stderr": error_output[-1000:] if error_output else "",
                },
            )

        except FileNotFoundError:
            return ToolResult(
                success=False,
                error="pytest not found. Install with: pip install pytest",
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to run tests: {e}")


def _parse_pytest_summary(output: str) -> tuple[int, int, int, int]:
    """Parse pytest output for pass/fail/error/skipped counts."""
    passed = failed = errors = skipped = 0

    # Match patterns like "5 passed", "2 failed", "1 error", "3 skipped"
    match = re.search(r"(\d+) passed", output)
    if match:
        passed = int(match.group(1))

    match = re.search(r"(\d+) failed", output)
    if match:
        failed = int(match.group(1))

    match = re.search(r"(\d+) error", output)
    if match:
        errors = int(match.group(1))

    match = re.search(r"(\d+) skipped", output)
    if match:
        skipped = int(match.group(1))

    return passed, failed, errors, skipped
