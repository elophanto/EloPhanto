"""commune_register — Register on Agent Commune."""

from __future__ import annotations

import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_COMMUNE_API = "https://agentcommune.com/api/v1"


class CommuneRegisterTool(BaseTool):
    """Register on Agent Commune with a work email."""

    @property
    def group(self) -> str:
        return "social"

    def __init__(self) -> None:
        self._vault: Any = None
        self._config: Any = None  # CommuneConfig

    @property
    def name(self) -> str:
        return "commune_register"

    @property
    def description(self) -> str:
        return (
            "Register on Agent Commune (LinkedIn for AI agents). Requires a "
            "work email — consumer domains (Gmail, Yahoo, Outlook) are not "
            "allowed. Your human will receive a verification email with a "
            "magic link. After clicking it, they get an API key to give you."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "description": (
                        "Work email address (e.g. you@startup.com). "
                        "Consumer domains are not allowed."
                    ),
                },
                "agent_name": {
                    "type": "string",
                    "description": (
                        "Your display name on Agent Commune. If it's already "
                        "a proper name, use as-is (e.g. 'Atlas'). If it's a "
                        "role, add 'agent' (e.g. 'Engineering agent')."
                    ),
                },
                "org_name": {
                    "type": "string",
                    "description": "Organization display name (recommended).",
                },
                "logo_url": {
                    "type": "string",
                    "description": "URL to organization logo (optional).",
                },
            },
            "required": ["email"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        import httpx

        email = params.get("email", "")
        if not email:
            return ToolResult(success=False, error="'email' is required.")

        body: dict[str, Any] = {"email": email}
        if params.get("agent_name"):
            body["agentName"] = params["agent_name"]
        if params.get("org_name"):
            body["orgName"] = params["org_name"]
        if params.get("logo_url"):
            body["logoUrl"] = params["logo_url"]

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{_COMMUNE_API}/register",
                    json=body,
                )
                data = resp.json()
                if resp.status_code in (200, 201):
                    return ToolResult(
                        success=True,
                        data={
                            "message": data.get("message", "Registration submitted."),
                            "next_step": (
                                "Your human will receive a verification email. "
                                "After clicking the magic link, they'll get an "
                                "API key. Save it with: vault_set key=commune_api_key value=THE_KEY"
                            ),
                        },
                    )
                return ToolResult(
                    success=False,
                    error=data.get(
                        "error", f"Registration failed ({resp.status_code})."
                    ),
                )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
