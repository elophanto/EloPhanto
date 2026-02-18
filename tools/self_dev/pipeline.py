"""Shared self-development pipeline utilities."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


async def render_template(
    template_dir: Path,
    output_dir: Path,
    context: dict[str, str],
) -> list[str]:
    """Render plugin template files with {{variable}} substitution.

    Returns list of created file paths (relative to output_dir).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []

    for template_file in template_dir.iterdir():
        if template_file.name.startswith("."):
            continue

        content = template_file.read_text(encoding="utf-8")
        for key, value in context.items():
            content = content.replace("{{" + key + "}}", value)

        out_path = output_dir / template_file.name
        out_path.write_text(content, encoding="utf-8")
        created.append(template_file.name)

    return created


async def git_commit(
    project_root: Path,
    files: list[str],
    message: str,
) -> tuple[bool, str]:
    """Stage files and create a git commit.

    Returns:
        Tuple of (success, commit_hash_or_error).
    """
    try:
        # Stage files
        for f in files:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "add",
                f,
                cwd=str(project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

        # Commit
        proc = await asyncio.create_subprocess_exec(
            "git",
            "commit",
            "-m",
            message,
            cwd=str(project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace")
            return False, f"git commit failed: {err}"

        # Get commit hash
        proc = await asyncio.create_subprocess_exec(
            "git",
            "rev-parse",
            "--short",
            "HEAD",
            cwd=str(project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        commit_hash = stdout.decode().strip()

        return True, commit_hash

    except Exception as e:
        return False, str(e)


def sanitize_plugin_name(name: str) -> str:
    """Convert a name to valid snake_case plugin directory name."""
    # Remove non-alphanumeric except spaces and underscores
    cleaned = re.sub(r"[^a-zA-Z0-9\s_]", "", name)
    # Replace spaces with underscores, lowercase
    cleaned = re.sub(r"\s+", "_", cleaned).lower().strip("_")
    return cleaned or "unnamed_plugin"


def check_name_available(name: str, registry: Any) -> bool:
    """Check that a tool name doesn't conflict with existing tools."""
    return registry.get(name) is None


def get_timestamp() -> str:
    """Return ISO timestamp for documentation."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
