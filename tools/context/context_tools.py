"""Context tools — RLM Phase 2 context-as-variable tools.

Provides context_ingest, context_query, context_slice, context_index,
and context_transform tools for managing the ContextStore.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class ContextIngestTool(BaseTool):
    """Ingest files or text into a context store for queryable access."""

    def __init__(self) -> None:
        self._context_store: Any = None

    @property
    def group(self) -> str:
        return "context"

    @property
    def name(self) -> str:
        return "context_ingest"

    @property
    def description(self) -> str:
        return (
            "Ingest files or text into a context store for later querying. "
            "Creates a new context store if no context_id is provided. "
            "Content is chunked, embedded, and indexed for semantic search. "
            "Use this to load large codebases, documents, or research into "
            "a queryable store that avoids filling the context window."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "context_id": {
                    "type": "string",
                    "description": (
                        "ID of an existing context store. "
                        "If omitted, a new store is created."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Name for a new context store (required if context_id omitted)."
                    ),
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File paths to ingest.",
                },
                "text": {
                    "type": "string",
                    "description": "Raw text to ingest (provide source_label too).",
                },
                "source_label": {
                    "type": "string",
                    "description": "Label for raw text source (e.g. 'search results').",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._context_store:
            return ToolResult(success=False, error="ContextStore not available.")

        context_id = params.get("context_id")
        files = params.get("files", [])
        text = params.get("text", "")
        source_label = params.get("source_label", "inline_text")

        # Create new store if needed
        if not context_id:
            name = params.get("name", "unnamed")
            context_id = await self._context_store.create(name)

        all_chunk_ids: list[str] = []

        # Ingest files
        for file_path in files:
            try:
                chunk_ids = await self._context_store.ingest_file(context_id, file_path)
                all_chunk_ids.extend(chunk_ids)
            except FileNotFoundError:
                return ToolResult(success=False, error=f"File not found: {file_path}")
            except Exception as e:
                return ToolResult(
                    success=False, error=f"Failed to ingest {file_path}: {e}"
                )

        # Ingest raw text
        if text:
            chunk_ids = await self._context_store.ingest_text(
                context_id, source_label, text
            )
            all_chunk_ids.extend(chunk_ids)

        if not files and not text:
            return ToolResult(
                success=False,
                error="Provide at least one of 'files' or 'text' to ingest.",
            )

        return ToolResult(
            success=True,
            data={
                "context_id": context_id,
                "chunks_created": len(all_chunk_ids),
                "sources_ingested": len(files) + (1 if text else 0),
            },
        )


class ContextQueryTool(BaseTool):
    """Semantic search over a context store."""

    def __init__(self) -> None:
        self._context_store: Any = None

    @property
    def group(self) -> str:
        return "context"

    @property
    def name(self) -> str:
        return "context_query"

    @property
    def description(self) -> str:
        return (
            "Semantic search over a context store. Returns the most relevant "
            "chunks matching your query. Use this instead of loading entire "
            "files when you need specific information from a large context."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "context_id": {
                    "type": "string",
                    "description": "ID of the context store to search.",
                },
                "query": {
                    "type": "string",
                    "description": "What to search for.",
                },
                "max_chunks": {
                    "type": "integer",
                    "description": "Maximum chunks to return (default 5).",
                },
            },
            "required": ["context_id", "query"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._context_store:
            return ToolResult(success=False, error="ContextStore not available.")

        context_id = params["context_id"]
        query = params["query"]
        max_chunks = params.get("max_chunks", 5)

        results = await self._context_store.query(context_id, query, max_chunks)

        return ToolResult(
            success=True,
            data={
                "results": results,
                "count": len(results),
                "context_id": context_id,
            },
        )


class ContextSliceTool(BaseTool):
    """Get exact content from a context store by source and line range."""

    def __init__(self) -> None:
        self._context_store: Any = None

    @property
    def group(self) -> str:
        return "context"

    @property
    def name(self) -> str:
        return "context_slice"

    @property
    def description(self) -> str:
        return (
            "Get exact content from a context store by source path and optional "
            "line range. Use this when you know which source you need and want "
            "the full or partial content rather than search results."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "context_id": {
                    "type": "string",
                    "description": "ID of the context store.",
                },
                "source": {
                    "type": "string",
                    "description": "Source path or partial match (e.g. 'agent.py').",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Start line (1-indexed, optional).",
                },
                "end_line": {
                    "type": "integer",
                    "description": "End line (inclusive, optional).",
                },
            },
            "required": ["context_id", "source"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._context_store:
            return ToolResult(success=False, error="ContextStore not available.")

        content = await self._context_store.slice(
            context_id=params["context_id"],
            source=params["source"],
            start_line=params.get("start_line"),
            end_line=params.get("end_line"),
        )

        if not content:
            return ToolResult(
                success=False,
                error=f"No content found for source '{params['source']}'.",
            )

        return ToolResult(
            success=True,
            data={
                "content": content,
                "source": params["source"],
                "token_count": len(content) // 4,
            },
        )


class ContextIndexTool(BaseTool):
    """Get a table of contents for a context store."""

    def __init__(self) -> None:
        self._context_store: Any = None

    @property
    def group(self) -> str:
        return "context"

    @property
    def name(self) -> str:
        return "context_index"

    @property
    def description(self) -> str:
        return (
            "Get a table of contents for a context store, showing all "
            "ingested sources, their sizes, and section headings. Use this "
            "to understand what's in a context before querying or slicing."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "context_id": {
                    "type": "string",
                    "description": "ID of the context store (omit to list all stores).",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._context_store:
            return ToolResult(success=False, error="ContextStore not available.")

        context_id = params.get("context_id")

        if not context_id:
            # List all contexts
            contexts = await self._context_store.list_contexts()
            return ToolResult(
                success=True,
                data={"contexts": contexts, "count": len(contexts)},
            )

        index_text = await self._context_store.index(context_id)
        return ToolResult(success=True, data={"index": index_text})


class ContextTransformTool(BaseTool):
    """Apply transformations to context: filter, group, stats."""

    def __init__(self) -> None:
        self._context_store: Any = None

    @property
    def group(self) -> str:
        return "context"

    @property
    def name(self) -> str:
        return "context_transform"

    @property
    def description(self) -> str:
        return (
            "Apply transformations to a context store. Operations: "
            "'filter' (by keyword/source), 'group' (chunks by source), "
            "'stats' (store statistics), 'sources' (list all sources)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "context_id": {
                    "type": "string",
                    "description": "ID of the context store.",
                },
                "operation": {
                    "type": "string",
                    "enum": ["filter", "group", "stats", "sources"],
                    "description": "Transformation to apply.",
                },
                "keyword": {
                    "type": "string",
                    "description": "Keyword to filter by (for 'filter' operation).",
                },
                "source": {
                    "type": "string",
                    "description": "Source pattern to filter by (for 'filter' operation).",
                },
            },
            "required": ["context_id", "operation"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._context_store:
            return ToolResult(success=False, error="ContextStore not available.")

        transform_params: dict[str, Any] = {}
        if "keyword" in params:
            transform_params["keyword"] = params["keyword"]
        if "source" in params:
            transform_params["source"] = params["source"]

        result = await self._context_store.transform(
            context_id=params["context_id"],
            operation=params["operation"],
            params=transform_params,
        )

        return ToolResult(success=True, data={"result": result})
