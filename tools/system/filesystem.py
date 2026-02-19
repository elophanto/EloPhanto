"""File system tools — read, write, list, delete, and move files."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.protected import is_protected
from tools.base import BaseTool, PermissionLevel, ToolResult


class FileReadTool(BaseTool):
    """Reads file contents."""

    @property
    def name(self) -> str:
        return "file_read"

    @property
    def description(self) -> str:
        return (
            "Reads the contents of a file and returns the text. "
            "Supports reading specific line ranges. Use this for "
            "inspecting files, reading configuration, or examining code."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file",
                },
                "encoding": {
                    "type": "string",
                    "description": "File encoding (default: utf-8)",
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to read (1-based, optional)",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to read (1-based, inclusive, optional)",
                },
            },
            "required": ["path"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        file_path = Path(params["path"]).expanduser()
        encoding = params.get("encoding", "utf-8")
        start_line = params.get("start_line")
        end_line = params.get("end_line")

        if not file_path.exists():
            return ToolResult(success=False, error=f"File not found: {file_path}")

        if not file_path.is_file():
            return ToolResult(success=False, error=f"Not a file: {file_path}")

        try:
            content = file_path.read_text(encoding=encoding)
            lines = content.splitlines()
            total_lines = len(lines)

            if start_line is not None or end_line is not None:
                s = (start_line or 1) - 1
                e = end_line or total_lines
                content = "\n".join(lines[s:e])

            return ToolResult(
                success=True,
                data={
                    "content": content,
                    "size_bytes": file_path.stat().st_size,
                    "line_count": total_lines,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to read file: {e}")


class FileWriteTool(BaseTool):
    """Creates or overwrites files."""

    @property
    def name(self) -> str:
        return "file_write"

    @property
    def description(self) -> str:
        return (
            "Creates or overwrites a file with the given content. "
            "Automatically creates parent directories if needed. "
            "Creates a .bak backup before overwriting existing files."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path for the file",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
                "create_directories": {
                    "type": "boolean",
                    "description": "Create parent directories if they don't exist (default: true)",
                },
                "backup": {
                    "type": "boolean",
                    "description": "Create .bak backup before overwriting (default: true)",
                },
            },
            "required": ["path", "content"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        file_path = Path(params["path"]).expanduser()
        content = params["content"]
        create_dirs = params.get("create_directories", True)
        backup = params.get("backup", True)

        if is_protected(file_path):
            return ToolResult(
                success=False,
                error=f"Cannot write to protected file: {file_path}",
            )

        try:
            if create_dirs:
                file_path.parent.mkdir(parents=True, exist_ok=True)

            backed_up = False
            if backup and file_path.exists():
                backup_path = file_path.with_suffix(file_path.suffix + ".bak")
                shutil.copy2(file_path, backup_path)
                backed_up = True

            file_path.write_text(content, encoding="utf-8")

            return ToolResult(
                success=True,
                data={
                    "path": str(file_path),
                    "size_bytes": file_path.stat().st_size,
                    "backed_up": backed_up,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to write file: {e}")


class FileListTool(BaseTool):
    """Lists files and directories."""

    @property
    def name(self) -> str:
        return "file_list"

    @property
    def description(self) -> str:
        return (
            "Lists files and directories at a given path. "
            "Supports recursive listing and glob pattern filtering. "
            "Use this to explore directory structures and find files."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to list",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "List recursively (default: false)",
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to filter results (e.g., '*.py')",
                },
                "include_hidden": {
                    "type": "boolean",
                    "description": "Include hidden files/directories (default: false)",
                },
            },
            "required": ["path"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        dir_path = Path(params["path"]).expanduser()
        recursive = params.get("recursive", False)
        pattern = params.get("pattern")
        include_hidden = params.get("include_hidden", False)

        if not dir_path.exists():
            return ToolResult(success=False, error=f"Path not found: {dir_path}")

        if not dir_path.is_dir():
            return ToolResult(success=False, error=f"Not a directory: {dir_path}")

        try:
            entries: list[dict[str, Any]] = []

            if pattern:
                glob_pattern = f"**/{pattern}" if recursive else pattern
                items = list(dir_path.glob(glob_pattern))
            elif recursive:
                items = list(dir_path.rglob("*"))
            else:
                items = list(dir_path.iterdir())

            for item in sorted(items):
                if not include_hidden and item.name.startswith("."):
                    continue

                try:
                    stat = item.stat()
                    entries.append(
                        {
                            "name": item.name,
                            "path": str(item),
                            "type": "directory" if item.is_dir() else "file",
                            "size_bytes": stat.st_size if item.is_file() else 0,
                            "modified_at": datetime.fromtimestamp(
                                stat.st_mtime, tz=UTC
                            ).isoformat(),
                        }
                    )
                except (PermissionError, OSError):
                    continue

            return ToolResult(
                success=True,
                data={"entries": entries, "count": len(entries)},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to list directory: {e}")


class FileDeleteTool(BaseTool):
    """Deletes files or directories."""

    @property
    def name(self) -> str:
        return "file_delete"

    @property
    def description(self) -> str:
        return (
            "Deletes a file or directory. For directories, set recursive=true "
            "to delete non-empty directories. Returns what was deleted and its size."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file or directory to delete",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Delete directories recursively (default: false)",
                },
            },
            "required": ["path"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        target = Path(params["path"]).expanduser()
        recursive = params.get("recursive", False)

        if not target.exists():
            return ToolResult(success=False, error=f"Path not found: {target}")

        if is_protected(target):
            return ToolResult(
                success=False,
                error=f"Cannot delete protected file: {target}",
            )

        try:
            if target.is_file() or target.is_symlink():
                size = target.stat().st_size
                target.unlink()
                return ToolResult(
                    success=True,
                    data={
                        "deleted": str(target),
                        "type": "file",
                        "size_bytes": size,
                    },
                )

            if target.is_dir():
                if not recursive:
                    try:
                        target.rmdir()
                    except OSError:
                        return ToolResult(
                            success=False,
                            error=(
                                f"Directory not empty: {target}. "
                                "Set recursive=true to delete non-empty directories."
                            ),
                        )
                else:
                    shutil.rmtree(target)

                return ToolResult(
                    success=True,
                    data={"deleted": str(target), "type": "directory"},
                )

            return ToolResult(success=False, error=f"Unsupported file type: {target}")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to delete: {e}")


class FileMoveTool(BaseTool):
    """Moves or renames files and directories."""

    @property
    def name(self) -> str:
        return "file_move"

    @property
    def description(self) -> str:
        return (
            "Moves or renames a file or directory. Creates parent directories "
            "for the destination if needed. Use this for renaming or reorganizing files."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Path to the source file or directory",
                },
                "destination": {
                    "type": "string",
                    "description": "Path to the destination",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Overwrite destination if it exists (default: false)",
                },
            },
            "required": ["source", "destination"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        source = Path(params["source"]).expanduser()
        destination = Path(params["destination"]).expanduser()
        overwrite = params.get("overwrite", False)

        if not source.exists():
            return ToolResult(success=False, error=f"Source not found: {source}")

        if is_protected(source):
            return ToolResult(
                success=False,
                error=f"Cannot move protected file: {source}",
            )

        if destination.exists() and not overwrite:
            return ToolResult(
                success=False,
                error=(
                    f"Destination already exists: {destination}. "
                    "Set overwrite=true to replace it."
                ),
            )

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            return ToolResult(
                success=True,
                data={
                    "source": str(source),
                    "destination": str(destination),
                    "type": "directory" if destination.is_dir() else "file",
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to move: {e}")
