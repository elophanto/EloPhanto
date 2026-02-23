"""totp_delete — remove a stored TOTP secret."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class TotpDeleteTool(BaseTool):
    """Remove a stored TOTP authenticator secret for a service."""

    def __init__(self) -> None:
        self._vault: Any = None

    @property
    def name(self) -> str:
        return "totp_delete"

    @property
    def description(self) -> str:
        return (
            "Remove a stored TOTP authenticator secret for a service. "
            "Also removes associated backup codes and metadata. "
            "Use this when you've disabled 2FA on a service."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Service name to remove (e.g. 'github', 'aws')",
                },
            },
            "required": ["service"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._vault:
            return ToolResult(
                success=False,
                error="Vault not available — unlock the vault first.",
            )

        service = params["service"].lower().strip()
        deleted = self._vault.delete(f"totp_{service}")

        # Also clean up metadata and backup codes
        self._vault.delete(f"totp_{service}_meta")
        self._vault.delete(f"totp_{service}_backup")

        if deleted:
            return ToolResult(
                success=True,
                data={
                    "service": service,
                    "deleted": True,
                    "message": f"TOTP secret for '{service}' has been removed.",
                },
            )

        return ToolResult(
            success=True,
            data={
                "service": service,
                "deleted": False,
                "message": f"No TOTP secret found for '{service}'.",
            },
        )
