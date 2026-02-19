"""Document query tool — query an existing document collection via RAG."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class DocumentQueryTool(BaseTool):
    """Query an existing document collection for specific information."""

    def __init__(self) -> None:
        self._store: Any = None  # DocumentStore, injected

    @property
    def name(self) -> str:
        return "document_query"

    @property
    def description(self) -> str:
        return (
            "Query a previously analyzed document collection. "
            "Searches through stored document chunks using semantic similarity "
            "and returns relevant passages with source citations (filename, page number)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "collection": {
                    "type": "string",
                    "description": "Collection name or ID to search in",
                },
                "question": {
                    "type": "string",
                    "description": "The question to answer from the documents",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of relevant passages to retrieve (default: 10)",
                },
            },
            "required": ["collection", "question"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._store:
            return ToolResult(
                success=False,
                error="Document store not initialized.",
            )

        collection_ref = params.get("collection", "")
        question = params.get("question", "")
        top_k = params.get("top_k", 10)

        if not collection_ref:
            return ToolResult(success=False, error="No collection specified.")
        if not question:
            return ToolResult(success=False, error="No question provided.")

        # Resolve collection
        info = await self._store.get_collection_info(collection_ref)
        if not info:
            return ToolResult(
                success=False,
                error=f"Collection not found: {collection_ref}",
            )

        collection_id = info["collection_id"]
        results = await self._store.query(collection_id, question, top_k)

        if not results:
            return ToolResult(
                success=True,
                data={
                    "collection": info["name"],
                    "question": question,
                    "results": [],
                    "content": "No relevant passages found for your question.",
                },
            )

        # Format results with citations
        passages: list[str] = []
        for i, r in enumerate(results, 1):
            source = r["filename"]
            if r.get("page_number"):
                source += f", p.{r['page_number']}"
            if r.get("section_title"):
                source += f" — {r['section_title']}"
            passages.append(f"**[{i}] {source}** (score: {r['score']})\n{r['content']}")

        content = (
            f"Found {len(results)} relevant passages in \"{info['name']}\":\n\n"
            + "\n\n---\n\n".join(passages)
        )

        return ToolResult(
            success=True,
            data={
                "collection": info["name"],
                "question": question,
                "result_count": len(results),
                "results": results,
                "content": content,
            },
        )
