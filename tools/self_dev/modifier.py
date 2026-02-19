"""Self-modify source tool — allows the agent to modify its own core code.

Stricter than plugin creation: requires impact analysis, full test suite,
and git-tagged commits for rollback support.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from core.protected import is_protected
from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class SelfModifySourceTool(BaseTool):
    """Modify the agent's own source code with full QA pipeline."""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        self._router: Any = None

    @property
    def name(self) -> str:
        return "self_modify_source"

    @property
    def description(self) -> str:
        return (
            "Modify the agent's own source code. This is an expensive, high-risk "
            "operation that runs impact analysis, applies the change, runs the full "
            "test suite, and creates a tagged git commit for rollback. Only use when "
            "the user explicitly requests a core modification."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative path to the file to modify (e.g., 'core/agent.py')",
                },
                "goal": {
                    "type": "string",
                    "description": "What the modification should accomplish",
                },
                "new_content": {
                    "type": "string",
                    "description": "The complete new file contents",
                },
            },
            "required": ["file_path", "goal", "new_content"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.CRITICAL

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        file_path = params["file_path"]
        goal = params["goal"]
        new_content = params["new_content"]

        target = self._project_root / file_path
        if not target.exists():
            return ToolResult(success=False, error=f"File not found: {file_path}")

        if is_protected(file_path):
            return ToolResult(
                success=False,
                error=f"Cannot modify protected file: {file_path}",
            )

        # Read original content for diff
        original = target.read_text(encoding="utf-8")

        # Impact analysis: find files that import from the target
        impacted = await self._find_dependents(file_path)

        # Run tests BEFORE the change to establish baseline
        pre_tests = await self._run_tests()
        if not pre_tests["passed"]:
            return ToolResult(
                success=False,
                data={"test_output": pre_tests["output"]},
                error="Tests already failing before modification. Fix existing issues first.",
            )

        # Apply the change
        try:
            target.write_text(new_content, encoding="utf-8")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to write file: {e}")

        # Run tests AFTER the change
        post_tests = await self._run_tests()
        if not post_tests["passed"]:
            # Rollback the change
            target.write_text(original, encoding="utf-8")
            return ToolResult(
                success=False,
                data={"test_output": post_tests["output"]},
                error="Tests failed after modification. Change has been rolled back.",
            )

        # Generate diff for the result
        diff = self._simple_diff(original, new_content, file_path)

        # Git commit with tag
        commit_msg = f"[self-modify] {file_path}: {goal}"
        await self._git_commit(file_path, commit_msg)

        return ToolResult(
            success=True,
            data={
                "file_path": file_path,
                "diff_preview": diff[:2000],
                "impacted_files": impacted,
                "tests_passed": True,
                "commit_message": commit_msg,
            },
        )

    async def _find_dependents(self, file_path: str) -> list[str]:
        """Find files that import from the modified file."""
        module_name = file_path.replace("/", ".").replace(".py", "")
        dependents: list[str] = []

        for py_file in self._project_root.rglob("*.py"):
            if py_file.name.startswith("_"):
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
                if module_name in content or f"from {module_name}" in content:
                    rel = str(py_file.relative_to(self._project_root))
                    if rel != file_path:
                        dependents.append(rel)
            except Exception:
                continue

        return dependents

    async def _run_tests(self) -> dict[str, Any]:
        """Run the full test suite."""
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
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            return {"passed": False, "output": "Test suite timed out"}

        output = stdout.decode("utf-8", errors="replace")
        return {"passed": proc.returncode == 0, "output": output}

    def _simple_diff(self, old: str, new: str, path: str) -> str:
        """Generate a simple unified-style diff."""
        old_lines = old.splitlines()
        new_lines = new.splitlines()
        lines: list[str] = [f"--- a/{path}", f"+++ b/{path}"]
        import difflib

        for line in difflib.unified_diff(old_lines, new_lines, lineterm=""):
            if line.startswith("---") or line.startswith("+++"):
                continue
            lines.append(line)
        return "\n".join(lines[:100])

    async def _git_commit(self, file_path: str, message: str) -> None:
        """Stage and commit the modified file."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "add",
                file_path,
                cwd=str(self._project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)

            proc = await asyncio.create_subprocess_exec(
                "git",
                "commit",
                "-m",
                message,
                cwd=str(self._project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
            logger.info(f"Git commit: {message}")
        except Exception as e:
            logger.warning(f"Git commit failed (non-fatal): {e}")
