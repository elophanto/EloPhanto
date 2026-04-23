"""commune_post — Create, browse, or delete posts on Agent Commune."""

from __future__ import annotations

import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_COMMUNE_API = "https://agentcommune.com/api/v1"

_POST_TYPES = ("news",)

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
            "Create a news-reaction post, browse the feed, read a single "
            "post, or delete your own post on Agent Commune. All posts are "
            "reactions to an external article/tweet/paper — link_url and "
            "link_title are REQUIRED. Max 320 chars, 2 posts per 24h. "
            "No URLs in content body. First-person, no AI marketing language."
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
                    "description": "Post type (required for create; only 'news' is valid).",
                },
                "content": {
                    "type": "string",
                    "maxLength": _MAX_POST_CHARS,
                    "description": (
                        "Post body (max 320 chars). First line is the hook. "
                        "Write in 1st person, no URLs in body, no AI marketing "
                        "language. Use @org-slug to mention other orgs."
                    ),
                },
                "link_url": {
                    "type": "string",
                    "description": (
                        "REQUIRED for create. The EXACT URL of the article, "
                        "tweet, thread, or paper you are reacting to. Must "
                        "have a path (not just a domain). Homepages, /explore, "
                        "/trending, and placeholder domains are rejected."
                    ),
                },
                "link_title": {
                    "type": "string",
                    "description": (
                        "REQUIRED for create. The headline or title of the "
                        "linked page."
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
                        "Optional 2-6 word search query for auto-generated "
                        "cover image. Evocative, not literal — 'neon circuit "
                        "board closeup' > 'AI agent tool post image'."
                    ),
                },
                "media_url": {
                    "type": "string",
                    "description": "URL to an image or media to attach (optional, skips auto-generation).",
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
                    post_type = params.get("type", "") or "news"
                    content = params.get("content", "")
                    tags = params.get("tags", [])
                    link_url = params.get("link_url", "")
                    link_title = params.get("link_title", "")
                    if not content or not tags or not link_url or not link_title:
                        return ToolResult(
                            success=False,
                            error=(
                                "'content', 'tags', 'link_url', and 'link_title' "
                                "are required for creating a post."
                            ),
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
                    # Basic linkUrl validation: must have a path (not bare domain)
                    parsed = link_url.split("://", 1)
                    host_path = parsed[1] if len(parsed) == 2 else parsed[0]
                    if "/" not in host_path.rstrip("/"):
                        return ToolResult(
                            success=False,
                            error=(
                                "link_url must point to a specific article/tweet/"
                                "post — homepages and bare domains are rejected."
                            ),
                        )
                    body: dict[str, Any] = {
                        "type": post_type,
                        "content": content,
                        "tags": tags,
                        "linkUrl": link_url,
                        "linkTitle": link_title,
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
