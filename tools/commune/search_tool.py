"""commune_search — Search Agent Commune for posts, comments, and orgs."""

from __future__ import annotations

import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_COMMUNE_API = "https://agentcommune.com/api/v1"


class CommuneSearchTool(BaseTool):
    """Search Agent Commune for posts, comments, and organizations."""

    @property
    def group(self) -> str:
        return "social"

    def __init__(self) -> None:
        self._vault: Any = None
        self._config: Any = None

    @property
    def name(self) -> str:
        return "commune_search"

    @property
    def description(self) -> str:
        return (
            "Search Agent Commune for posts, comments, and organizations. "
            "Be descriptive in queries. Search before posting to avoid "
            "duplicates — comment on existing threads instead."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (be descriptive).",
                },
                "type": {
                    "type": "string",
                    "enum": ["posts", "comments", "orgs"],
                    "description": "Filter to specific content type (optional).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results per type (default: 10, max: 25).",
                },
            },
            "required": ["query"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def _resolve_token(self) -> str:
        if not self._vault:
            return ""
        ref = self._config.api_key_ref if self._config else "commune_api_key"
        try:
            return self._vault.get(ref) or ""
        except Exception:
            return ""

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        import httpx

        token = await self._resolve_token()
        if not token:
            return ToolResult(
                success=False,
                error="No Agent Commune API key. Register first with commune_register.",
            )

        query = params.get("query", "")
        if not query:
            return ToolResult(success=False, error="'query' is required.")

        query_params: dict[str, Any] = {"q": query}
        if params.get("type"):
            query_params["type"] = params["type"]
        if params.get("limit"):
            query_params["limit"] = params["limit"]

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{_COMMUNE_API}/search",
                    params=query_params,
                    headers={"Authorization": f"Bearer {token}"},
                )
                data = (
                    resp.json()
                    if resp.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else {}
                )
                if resp.status_code == 200:
                    return ToolResult(success=True, data=data)
                return ToolResult(
                    success=False,
                    error=data.get("error", f"Search failed ({resp.status_code})."),
                )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
