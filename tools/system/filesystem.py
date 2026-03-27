"""File system tools — read, write, list, delete, move, and patch files."""

from __future__ import annotations

import difflib
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.protected import check_config_content, is_protected
from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

# ── Read Loop Detection ──────────────────────────────────────────────
# Tracks consecutive identical reads to prevent infinite re-read loops.
# Resets when any other tool is called (tracked externally via executor).
_read_tracker: dict[str, int] = {}  # "path:start:end" -> consecutive count
_READ_WARN_THRESHOLD = 3
_READ_BLOCK_THRESHOLD = 4


def _read_key(path: str, start: int | None, end: int | None) -> str:
    return f"{path}:{start or 0}:{end or 0}"


def reset_read_tracker() -> None:
    """Reset the read loop tracker. Call when any non-read tool executes."""
    _read_tracker.clear()


class FileReadTool(BaseTool):
    """Reads file contents with loop detection."""

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

        # Loop detection: block consecutive identical reads
        key = _read_key(str(file_path), start_line, end_line)
        _read_tracker[key] = _read_tracker.get(key, 0) + 1
        if _read_tracker[key] >= _READ_BLOCK_THRESHOLD:
            return ToolResult(
                success=False,
                error=(
                    f"Blocked: you've read the same region of {file_path.name} "
                    f"{_read_tracker[key]} times consecutively. The file hasn't "
                    f"changed. Use a different tool or edit the file first."
                ),
            )

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

            warning = ""
            if _read_tracker[key] >= _READ_WARN_THRESHOLD:
                warning = (
                    f"Warning: you've read this same region {_read_tracker[key]} "
                    f"times. Consider editing or moving on."
                )

            data: dict[str, Any] = {
                "content": content,
                "size_bytes": file_path.stat().st_size,
                "line_count": total_lines,
            }
            if warning:
                data["warning"] = warning

            return ToolResult(success=True, data=data)
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

        # Check for protected config keys when writing config.yaml
        if file_path.name == "config.yaml":
            config_err = check_config_content(content)
            if config_err:
                return ToolResult(success=False, error=config_err)

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


class FilePatchTool(BaseTool):
    """Fuzzy find-and-replace patching for files."""

    @property
    def name(self) -> str:
        return "file_patch"

    @property
    def description(self) -> str:
        return (
            "Find and replace text in a file using fuzzy matching. More "
            "reliable than exact string replacement — handles minor whitespace "
            "and indentation differences. Use for targeted edits instead of "
            "rewriting entire files. Returns a unified diff of changes."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to patch",
                },
                "old": {
                    "type": "string",
                    "description": "Text to find (fuzzy matched — minor whitespace differences OK)",
                },
                "new": {
                    "type": "string",
                    "description": "Replacement text",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences (default: false, first only)",
                },
            },
            "required": ["path", "old", "new"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        file_path = Path(params["path"]).expanduser()
        old_text = params["old"]
        new_text = params["new"]
        replace_all = params.get("replace_all", False)

        if is_protected(file_path):
            return ToolResult(
                success=False,
                error=f"Cannot patch protected file: {file_path}",
            )

        if not file_path.exists():
            return ToolResult(success=False, error=f"File not found: {file_path}")

        try:
            original = file_path.read_text(encoding="utf-8")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to read file: {e}")

        # Try exact match first
        if old_text in original:
            if replace_all:
                patched = original.replace(old_text, new_text)
            else:
                patched = original.replace(old_text, new_text, 1)
            return self._apply_patch(file_path, original, patched)

        # Fuzzy match: normalize whitespace and try again
        match_pos = self._fuzzy_find(original, old_text)
        if match_pos is None:
            return ToolResult(
                success=False,
                error=(
                    f"Could not find a match for the 'old' text in {file_path.name}. "
                    f"The text may have changed or the context is too different. "
                    f"Try reading the file first to get the exact current content."
                ),
            )

        start, end = match_pos
        patched = original[:start] + new_text + original[end:]

        if replace_all:
            # Continue replacing from after the first replacement
            while True:
                remaining_pos = self._fuzzy_find(
                    patched[start + len(new_text) :], old_text
                )
                if remaining_pos is None:
                    break
                r_start, r_end = remaining_pos
                abs_start = start + len(new_text) + r_start
                abs_end = start + len(new_text) + r_end
                patched = patched[:abs_start] + new_text + patched[abs_end:]
                start = abs_start

        return self._apply_patch(file_path, original, patched)

    def _fuzzy_find(self, content: str, target: str) -> tuple[int, int] | None:
        """Find target in content using fuzzy matching.

        Tries progressively looser matching:
        1. Normalized whitespace (collapse runs of whitespace)
        2. Line-by-line sequence matching (handles indentation changes)
        """
        # Strategy 1: Normalize whitespace
        import re as _re

        norm_content = _re.sub(r"[ \t]+", " ", content)
        norm_target = _re.sub(r"[ \t]+", " ", target)

        if norm_target in norm_content:
            # Find the position in the original content
            norm_pos = norm_content.index(norm_target)
            # Map back to original by counting characters
            orig_pos = 0
            norm_idx = 0
            while norm_idx < norm_pos and orig_pos < len(content):
                if content[orig_pos] in " \t" and norm_content[norm_idx] == " ":
                    # Skip extra whitespace in original
                    while orig_pos < len(content) and content[orig_pos] in " \t":
                        orig_pos += 1
                    norm_idx += 1
                else:
                    orig_pos += 1
                    norm_idx += 1
            start = orig_pos

            # Find end similarly
            end = start
            norm_end_idx = norm_idx
            while norm_end_idx < norm_pos + len(norm_target) and end < len(content):
                if content[end] in " \t" and norm_content[norm_end_idx] == " ":
                    while end < len(content) and content[end] in " \t":
                        end += 1
                    norm_end_idx += 1
                else:
                    end += 1
                    norm_end_idx += 1
            return (start, end)

        # Strategy 2: Line-level sequence matching
        content_lines = content.splitlines(keepends=True)
        target_lines = target.splitlines(keepends=True)
        if len(target_lines) < 2:
            return None

        matcher = difflib.SequenceMatcher(
            None,
            [ln.strip() for ln in content_lines],
            [ln.strip() for ln in target_lines],
            autojunk=False,
        )
        # Find the best matching block
        best_block = None
        best_size = 0
        for block in matcher.get_matching_blocks():
            if block.size > best_size:
                best_size = block.size
                best_block = block

        if best_block and best_size >= len(target_lines) * 0.6:
            # Good enough match — find character positions
            start_line = best_block.a
            end_line = best_block.a + best_size
            # Extend to cover the full target range
            if best_block.b > 0:
                start_line = max(0, start_line - best_block.b)
            remaining = len(target_lines) - (best_block.b + best_size)
            if remaining > 0:
                end_line = min(len(content_lines), end_line + remaining)

            start_char = sum(len(ln) for ln in content_lines[:start_line])
            end_char = sum(len(ln) for ln in content_lines[:end_line])
            return (start_char, end_char)

        return None

    def _apply_patch(self, file_path: Path, original: str, patched: str) -> ToolResult:
        """Write the patched content and return a diff."""
        if original == patched:
            return ToolResult(
                success=False, error="No changes — old and new text are identical."
            )

        # Backup
        backup_path = file_path.with_suffix(file_path.suffix + ".bak")
        shutil.copy2(file_path, backup_path)

        # Write
        file_path.write_text(patched, encoding="utf-8")

        # Generate diff
        diff = difflib.unified_diff(
            original.splitlines(keepends=True),
            patched.splitlines(keepends=True),
            fromfile=f"a/{file_path.name}",
            tofile=f"b/{file_path.name}",
            n=3,
        )
        diff_text = "".join(diff)

        return ToolResult(
            success=True,
            data={
                "path": str(file_path),
                "diff": diff_text[:3000],
                "backed_up": True,
            },
        )


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
