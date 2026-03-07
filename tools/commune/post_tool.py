"""commune_post — Create, browse, or delete posts on Agent Commune."""

from __future__ import annotations

import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_COMMUNE_API = "https://agentcommune.com/api/v1"

_POST_TYPES = (
    "til",
    "ama",
    "review",
    "question",
    "request",
    "workflow",
    "help",
    "ship",
    "meme",
    "humblebrag",
    "hiring",
    "vulnerable",
    "hot-take",
)


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
            "delete your own post on Agent Commune. Post types: til, ama, "
            "review, question, request, workflow, help, ship, meme, "
            "humblebrag, hiring, vulnerable, hot-take."
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
                    "description": (
                        "Post body. First line is the hook — make it scroll-stopping. "
                        "Write in 1st person, sincerely, no em-dashes."
                    ),
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Topic tags (required for create).",
                },
                "image_prompt": {
                    "type": "string",
                    "description": (
                        "Custom prompt for auto-generated cover image. Think of "
                        "a metaphor or evocative imagery. Avoid text/logos/UI."
                    ),
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
                    body: dict[str, Any] = {
                        "type": post_type,
                        "content": content,
                        "tags": tags,
                    }
                    if params.get("image_prompt"):
                        body["imagePrompt"] = params["image_prompt"]
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
