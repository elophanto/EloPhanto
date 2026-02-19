"""Document collections tool — list, inspect, or delete document collections."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class DocumentCollectionsTool(BaseTool):
    """Manage document collections — list all, get info, or delete."""

    def __init__(self) -> None:
        self._store: Any = None  # DocumentStore, injected

    @property
    def name(self) -> str:
        return "document_collections"

    @property
    def description(self) -> str:
        return (
            "Manage document collections. List all collections, get detailed info "
            "about a specific collection (files, chunks, size), or delete a collection."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "info", "delete"],
                    "description": "Action to perform",
                },
                "collection": {
                    "type": "string",
                    "description": "Collection name or ID (required for info/delete)",
                },
            },
            "required": ["action"],
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

        action = params.get("action", "list")
        collection_ref = params.get("collection", "")

        if action == "list":
            return await self._list()
        elif action == "info":
            if not collection_ref:
                return ToolResult(success=False, error="No collection specified.")
            return await self._info(collection_ref)
        elif action == "delete":
            if not collection_ref:
                return ToolResult(success=False, error="No collection specified.")
            return await self._delete(collection_ref)
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}")

    async def _list(self) -> ToolResult:
        collections = await self._store.list_collections()
        if not collections:
            return ToolResult(
                success=True,
                data={"collections": [], "content": "No document collections found."},
            )

        lines: list[str] = []
        for c in collections:
            lines.append(
                f"- **{c['name']}** — {c['file_count']} files, "
                f"{c['chunk_count']} chunks, ~{c['total_tokens']} tokens "
                f"(created: {c['created_at'][:10]})"
            )

        return ToolResult(
            success=True,
            data={
                "collections": collections,
                "content": f"Document collections ({len(collections)}):\n\n" + "\n".join(lines),
            },
        )

    async def _info(self, collection_ref: str) -> ToolResult:
        info = await self._store.get_collection_info(collection_ref)
        if not info:
            return ToolResult(success=False, error=f"Collection not found: {collection_ref}")

        files = info.get("files", [])
        file_lines = []
        for f in files:
            file_lines.append(
                f"  - {f['filename']} ({f['mime_type']}, "
                f"{f.get('page_count', '?')} pages, "
                f"{f['size_bytes'] // 1024} KB)"
            )

        content = (
            f"**{info['name']}**\n"
            f"- Collection ID: {info['collection_id']}\n"
            f"- Files: {info['file_count']}\n"
            f"- Chunks: {info['chunk_count']}\n"
            f"- Total tokens: ~{info['total_tokens']}\n"
            f"- Created: {info['created_at']}\n\n"
            f"Files:\n" + "\n".join(file_lines)
        )

        return ToolResult(success=True, data={"info": info, "content": content})

    async def _delete(self, collection_ref: str) -> ToolResult:
        deleted = await self._store.delete_collection(collection_ref)
        if not deleted:
            return ToolResult(success=False, error=f"Collection not found: {collection_ref}")

        return ToolResult(
            success=True,
            data={"content": f"Deleted collection: {collection_ref}"},
        )
