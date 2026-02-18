"""Knowledge index tool: manual trigger for re-indexing the knowledge base.

Allows the agent to explicitly request re-indexing of all or changed
knowledge files.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class KnowledgeIndexTool(BaseTool):
    """Re-index the knowledge base for search."""

    def __init__(self) -> None:
        self._indexer: Any = None  # Injected by agent

    @property
    def name(self) -> str:
        return "knowledge_index"

    @property
    def description(self) -> str:
        return (
            "Re-index the knowledge base. Run this after bulk changes to "
            "knowledge files. Uses incremental indexing by default (only "
            "changed files). Pass full=true to force a complete re-index."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "full": {
                    "type": "boolean",
                    "description": "Force full re-index (default: false)",
                },
            },
            "required": [],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._indexer:
            return ToolResult(success=False, error="Knowledge indexer not initialized")

        full = params.get("full", False)

        try:
            if full:
                result = await self._indexer.index_all()
            else:
                result = await self._indexer.index_incremental()

            return ToolResult(
                success=True,
                data={
                    "files_indexed": result.files_indexed,
                    "chunks_created": result.chunks_created,
                    "duration_seconds": round(result.duration_seconds, 2),
                    "mode": "full" if full else "incremental",
                    "errors": result.errors,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Indexing failed: {e}")
