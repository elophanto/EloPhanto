"""commune_post — Create, browse, or delete posts on Agent Commune."""

from __future__ import annotations

import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_COMMUNE_API = "https://agentcommune.com/api/v1"

_POST_TYPES = (
    "general",
    "question",
    "news",
)

_MAX_POST_CHARS = 320
_MAX_TAG_LEN = 50
_MAX_TAGS = 10


class CommunePostTool(BaseTool):
    """Create, browse, or delete posts on Agent Commune."""

    @property
    def group(self) -> str:
        return "social"

    def __init__(self) -> None:
        self._vault: Any = None
        self._config: Any = None

    @property
    def name(self) -> str:
        return "commune_post"

    @property
    def description(self) -> str:
        return (
            "Create a new post, browse the feed, read a single post, or "
            "delete your own post on Agent Commune. Post types: general "
            "(workflows, insights, takes), question (specific help requests), "
            "news (reactions to tech news). Max 320 chars. No URLs in content."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "browse", "read", "delete"],
                    "description": "Action to perform (default: 'create').",
                },
                "type": {
                    "type": "string",
                    "enum": list(_POST_TYPES),
                    "description": "Post type (required for create).",
                },
                "content": {
                    "type": "string",
                    "maxLength": _MAX_POST_CHARS,
                    "description": (
                        "Post body (max 320 chars). First line is the hook. "
                        "Write in 1st person, no URLs, no AI marketing language."
                    ),
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": _MAX_TAG_LEN},
                    "maxItems": _MAX_TAGS,
                    "description": "Topic tags (required for create, max 10).",
                },
                "image_query": {
                    "type": "string",
                    "description": (
                        "Custom query for auto-generated cover image. Think of "
                        "a metaphor or evocative imagery. Avoid text/logos/UI."
                    ),
                },
                "media_url": {
                    "type": "string",
                    "description": "URL to an image or media to attach (optional).",
                },
                "post_id": {
                    "type": "string",
                    "description": "Post ID (for read/delete).",
                },
                "sort": {
                    "type": "string",
                    "enum": ["hot", "new", "top"],
                    "description": "Sort order for browse (default: 'hot').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results for browse (default: 15).",
                },
            },
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

        action = params.get("action", "create")
        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                if action == "browse":
                    sort = params.get("sort", "hot")
                    limit = params.get("limit", 15)
                    resp = await client.get(
                        f"{_COMMUNE_API}/posts",
                        params={"sort": sort, "limit": limit},
                        headers=headers,
                    )
                elif action == "read":
                    post_id = params.get("post_id", "")
                    if not post_id:
                        return ToolResult(
                            success=False, error="'post_id' required for read."
                        )
                    resp = await client.get(
                        f"{_COMMUNE_API}/posts/{post_id}",
                        headers=headers,
                    )
                elif action == "delete":
                    post_id = params.get("post_id", "")
                    if not post_id:
                        return ToolResult(
                            success=False, error="'post_id' required for delete."
                        )
                    resp = await client.delete(
                        f"{_COMMUNE_API}/posts/{post_id}",
                        headers=headers,
                    )
                else:
                    # create
                    post_type = params.get("type", "")
                    content = params.get("content", "")
                    tags = params.get("tags", [])
                    if not post_type or not content or not tags:
                        return ToolResult(
                            success=False,
                            error="'type', 'content', and 'tags' are required for creating a post.",
                        )
                    if len(content) > _MAX_POST_CHARS:
                        return ToolResult(
                            success=False,
                            error=f"Post content exceeds {_MAX_POST_CHARS} char limit ({len(content)} chars).",
                        )
                    if len(tags) > _MAX_TAGS:
                        return ToolResult(
                            success=False,
                            error=f"Max {_MAX_TAGS} tags allowed.",
                        )
                    body: dict[str, Any] = {
                        "type": post_type,
                        "content": content,
                        "tags": tags,
                    }
                    if params.get("image_query"):
                        body["imageQuery"] = params["image_query"]
                    if params.get("media_url"):
                        body["mediaUrl"] = params["media_url"]
                    resp = await client.post(
                        f"{_COMMUNE_API}/posts",
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
