"""Knowledge write tool: create or update markdown files with YAML frontmatter.

Manages the knowledge base by creating new files or updating existing ones,
automatically handling frontmatter generation and triggering re-indexing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from tools.base import BaseTool, PermissionLevel, ToolResult


class KnowledgeWriteTool(BaseTool):
    """Create or update markdown files in the knowledge base."""

    def __init__(self) -> None:
        self._knowledge_dir: Path | None = None  # Injected by agent
        self._indexer: Any = None  # Injected by agent

    @property
    def name(self) -> str:
        return "knowledge_write"

    @property
    def description(self) -> str:
        return (
            "Create or update a markdown file in the knowledge base. "
            "Automatically generates YAML frontmatter and triggers re-indexing. "
            "Use this to save new learnings, document patterns, or record task summaries."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Relative path within the knowledge directory "
                        "(e.g., 'learned/patterns/api-caching.md')"
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "Markdown content (without frontmatter)",
                },
                "title": {
                    "type": "string",
                    "description": "Title for the document",
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags for search",
                },
                "scope": {
                    "type": "string",
                    "description": "Scope of the knowledge",
                    "enum": ["system", "user", "learned", "plugin"],
                },
            },
            "required": ["path", "content"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._knowledge_dir:
            return ToolResult(success=False, error="Knowledge directory not configured")

        rel_path = params["path"]
        content = params["content"]
        title = params.get("title", "")
        tags = params.get("tags", "")
        scope = params.get("scope", "learned")

        file_path = self._knowledge_dir / rel_path

        try:
            # Build frontmatter
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            frontmatter: dict[str, Any] = {}

            # Preserve existing created date if updating
            if file_path.exists():
                existing = file_path.read_text(encoding="utf-8")
                if existing.startswith("---"):
                    parts = existing.split("---", 2)
                    if len(parts) >= 3:
                        try:
                            old_meta = yaml.safe_load(parts[1]) or {}
                            frontmatter["created"] = old_meta.get("created", now)
                        except yaml.YAMLError:
                            frontmatter["created"] = now
                    else:
                        frontmatter["created"] = now
                else:
                    frontmatter["created"] = now
            else:
                frontmatter["created"] = now

            if title:
                frontmatter["title"] = title
            frontmatter["updated"] = now
            if tags:
                frontmatter["tags"] = tags
            frontmatter["scope"] = scope

            # Build the full file
            fm_str = yaml.dump(frontmatter, default_flow_style=False).strip()
            full_content = f"---\n{fm_str}\n---\n\n{content}\n"

            # Write file
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(full_content, encoding="utf-8")

            # Trigger re-indexing if indexer is available
            chunks_created = 0
            if self._indexer:
                try:
                    chunks_created = await self._indexer.index_file(file_path)
                except Exception:
                    pass  # Non-fatal; file was written successfully

            return ToolResult(
                success=True,
                data={
                    "path": str(rel_path),
                    "size_bytes": file_path.stat().st_size,
                    "chunks_indexed": chunks_created,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to write: {e}")
