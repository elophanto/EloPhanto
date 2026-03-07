"""commune_profile — View or update Agent Commune profile."""

from __future__ import annotations

import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_COMMUNE_API = "https://agentcommune.com/api/v1"


class CommuneProfileTool(BaseTool):
    """View or update your Agent Commune profile."""

    @property
    def group(self) -> str:
        return "social"

    def __init__(self) -> None:
        self._vault: Any = None
        self._config: Any = None

    @property
    def name(self) -> str:
        return "commune_profile"

    @property
    def description(self) -> str:
        return (
            "View or update your Agent Commune profile. View returns your "
            "likes, engagement count, org info, and public key. Update lets "
            "you change your agent name, avatar, and org details."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["view", "update", "introspect"],
                    "description": (
                        "Action: 'view' (GET /me), 'update' (PATCH /me), "
                        "'introspect' (verify token + get public key). Default: 'view'."
                    ),
                },
                "agent_name": {
                    "type": "string",
                    "description": "New display name (for update).",
                },
                "avatar_url": {
                    "type": "string",
                    "description": "URL to profile picture (for update).",
                },
                "org_name": {
                    "type": "string",
                    "description": "Organization display name (for update).",
                },
                "org_slug": {
                    "type": "string",
                    "description": "URL-friendly org identifier (for update).",
                },
                "org_logo_url": {
                    "type": "string",
                    "description": "Organization logo URL (for update).",
                },
            },
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

        action = params.get("action", "view")
        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                if action == "introspect":
                    resp = await client.get(
                        f"{_COMMUNE_API}/introspect", headers=headers
                    )
                elif action == "update":
                    body: dict[str, Any] = {}
                    if params.get("agent_name") is not None:
                        body["agentName"] = params["agent_name"]
                    if params.get("avatar_url") is not None:
                        body["avatarUrl"] = params["avatar_url"]
                    if params.get("org_name") is not None:
                        body["name"] = params["org_name"]
                    if params.get("org_slug") is not None:
                        body["slug"] = params["org_slug"]
                    if params.get("org_logo_url") is not None:
                        body["logoUrl"] = params["org_logo_url"]
                    if not body:
                        return ToolResult(
                            success=False,
                            error="No fields provided for update.",
                        )
                    resp = await client.patch(
                        f"{_COMMUNE_API}/me",
                        json=body,
                        headers={**headers, "Content-Type": "application/json"},
                    )
                else:
                    resp = await client.get(f"{_COMMUNE_API}/me", headers=headers)

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
                    error=data.get("error", f"Request failed ({resp.status_code})."),
                )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
