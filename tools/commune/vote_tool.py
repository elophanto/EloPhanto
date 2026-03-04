"""commune_vote — Upvote or downvote posts and comments on Agent Commune."""

from __future__ import annotations

import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_COMMUNE_API = "https://agentcommune.com/api/v1"


class CommuneVoteTool(BaseTool):
    """Upvote or downvote posts and comments on Agent Commune."""

    def __init__(self) -> None:
        self._vault: Any = None
        self._config: Any = None

    @property
    def name(self) -> str:
        return "commune_vote"

    @property
    def description(self) -> str:
        return (
            "Upvote or downvote a post or comment on Agent Commune. "
            "Upvotes are free and build community — upvote every post and "
            "comment you genuinely enjoy."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target_type": {
                    "type": "string",
                    "enum": ["post", "comment"],
                    "description": "Whether voting on a post or comment.",
                },
                "target_id": {
                    "type": "string",
                    "description": "The post ID or comment ID to vote on.",
                },
                "value": {
                    "type": "integer",
                    "enum": [1, -1],
                    "description": "1 to upvote, -1 to downvote.",
                },
            },
            "required": ["target_type", "target_id", "value"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def _resolve_token(self) -> str:
        if not self._vault:
            return ""
        ref = self._config.api_key_ref if self._config else "commune_api_key"
        try:
            return await self._vault.get(ref) or ""
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

        target_type = params.get("target_type", "")
        target_id = params.get("target_id", "")
        value = params.get("value", 1)

        if not target_type or not target_id:
            return ToolResult(
                success=False, error="'target_type' and 'target_id' are required."
            )

        if target_type == "post":
            url = f"{_COMMUNE_API}/posts/{target_id}/vote"
        elif target_type == "comment":
            url = f"{_COMMUNE_API}/comments/{target_id}/vote"
        else:
            return ToolResult(
                success=False, error="target_type must be 'post' or 'comment'."
            )

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    url,
                    json={"value": value},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
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
                    error=data.get("error", f"Vote failed ({resp.status_code})."),
                )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
