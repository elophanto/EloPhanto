"""Self-read source tool — reads EloPhanto's own source code."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

# Directories the agent is allowed to read
_ALLOWED_DIRS = {"core", "tools", "plugins", "knowledge", "cli", "tests", "docs"}


class SelfReadSourceTool(BaseTool):
    """Reads EloPhanto's own source code files."""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    @property
    def name(self) -> str:
        return "self_read_source"

    @property
    def description(self) -> str:
        return (
            "Read EloPhanto's own source code. Use this to understand how existing "
            "tools work, find patterns to follow, or inspect the current implementation "
            "of any module. Accepts relative paths from the project root."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Relative path from project root "
                        "(e.g., 'tools/base.py', 'core/agent.py')"
                    ),
                },
                "list_dir": {
                    "type": "boolean",
                    "description": "If true, list files in directory instead of reading",
                },
            },
            "required": ["path"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        rel_path = params["path"]
        list_dir = params.get("list_dir", False)

        # Security: block path traversal
        if ".." in rel_path:
            return ToolResult(success=False, error="Path traversal (..) is not allowed")

        target = self._project_root / rel_path
        resolved = target.resolve()

        # Ensure resolved path is under project root
        try:
            resolved.relative_to(self._project_root.resolve())
        except ValueError:
            return ToolResult(
                success=False, error="Path is outside the project directory"
            )

        # Check it's in an allowed top-level directory (or is a root file)
        parts = Path(rel_path).parts
        if parts and parts[0] not in _ALLOWED_DIRS:
            # Allow root-level files like pyproject.toml, config.yaml
            if not resolved.is_file() or len(parts) > 1:
                return ToolResult(
                    success=False,
                    error=(f"Access restricted. Allowed directories: {_ALLOWED_DIRS}"),
                )

        if list_dir:
            if not resolved.is_dir():
                return ToolResult(success=False, error=f"Not a directory: {rel_path}")
            entries = []
            for child in sorted(resolved.iterdir()):
                entries.append(
                    {
                        "name": child.name,
                        "type": "dir" if child.is_dir() else "file",
                        "size": child.stat().st_size if child.is_file() else 0,
                    }
                )
            return ToolResult(
                success=True,
                data={"path": rel_path, "entries": entries, "count": len(entries)},
            )

        if not resolved.is_file():
            return ToolResult(success=False, error=f"File not found: {rel_path}")

        try:
            content = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult(
                success=False, error="File is binary, cannot read as text"
            )

        return ToolResult(
            success=True,
            data={
                "path": rel_path,
                "content": content,
                "language": resolved.suffix.lstrip(".") or "text",
                "line_count": content.count("\n") + 1,
            },
        )
