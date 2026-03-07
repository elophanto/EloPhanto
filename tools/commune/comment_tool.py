"""commune_comment — Comment or reply on Agent Commune posts."""

from __future__ import annotations

import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_COMMUNE_API = "https://agentcommune.com/api/v1"


class CommuneCommentTool(BaseTool):
    """Comment on or read comments from Agent Commune posts."""

    @property
    def group(self) -> str:
        return "social"

    def __init__(self) -> None:
        self._vault: Any = None
        self._config: Any = None

    @property
    def name(self) -> str:
        return "commune_comment"

    @property
    def description(self) -> str:
        return (
            "Add a comment to an Agent Commune post, reply to an existing "
            "comment, or read all comments on a post. Write like a human "
            "texting — lowercase, casual, real. No '+1' or 'Great post!'."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "read"],
                    "description": "Action (default: 'create').",
                },
                "post_id": {
                    "type": "string",
                    "description": "Post ID to comment on or read comments from.",
                },
                "content": {
                    "type": "string",
                    "description": (
                        "Comment text. Write casually and authentically. "
                        "Share your own experience, add depth, or ask follow-up questions."
                    ),
                },
                "parent_id": {
                    "type": "string",
                    "description": "Parent comment ID for threaded replies (optional).",
                },
                "sort": {
                    "type": "string",
                    "enum": ["new", "top"],
                    "description": "Sort order for reading comments (default: 'new').",
                },
            },
            "required": ["post_id"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

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

        post_id = params.get("post_id", "")
        if not post_id:
            return ToolResult(success=False, error="'post_id' is required.")

        action = params.get("action", "create")
        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                if action == "read":
                    sort = params.get("sort", "new")
                    resp = await client.get(
                        f"{_COMMUNE_API}/posts/{post_id}/comments",
                        params={"sort": sort},
                        headers=headers,
                    )
                else:
                    content = params.get("content", "")
                    if not content:
                        return ToolResult(
                            success=False, error="'content' is required for comments."
                        )
                    body: dict[str, Any] = {"content": content}
                    if params.get("parent_id"):
                        body["parent_id"] = params["parent_id"]
                    resp = await client.post(
                        f"{_COMMUNE_API}/posts/{post_id}/comments",
                        json=body,
                        headers={**headers, "Content-Type": "application/json"},
                    )

                data = (
                    resp.json()
                    if resp.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else {}
                )
                if resp.status_code in (200, 201):
                    return ToolResult(success=True, data=data)
                return ToolResult(
                    success=False,
                    error=data.get("error", f"Request failed ({resp.status_code})."),
                )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
