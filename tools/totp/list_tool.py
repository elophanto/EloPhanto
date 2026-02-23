"""totp_list — list services with stored TOTP secrets."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class TotpListTool(BaseTool):
    """List all services with enrolled TOTP authenticator secrets."""

    def __init__(self) -> None:
        self._vault: Any = None

    @property
    def name(self) -> str:
        return "totp_list"

    @property
    def description(self) -> str:
        return (
            "List all services with stored TOTP authenticator secrets. "
            "Returns service names, accounts, and enrollment dates — "
            "never exposes the actual secrets."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._vault:
            return ToolResult(
                success=False,
                error="Vault not available — unlock the vault first.",
            )

        # Find all totp_ keys, excluding _meta and _backup suffixes
        all_keys = self._vault.list_keys()
        service_keys = [
            k
            for k in all_keys
            if k.startswith("totp_")
            and not k.endswith("_meta")
            and not k.endswith("_backup")
        ]

        services = []
        for key in sorted(service_keys):
            service_name = key[5:]  # Strip "totp_" prefix
            meta = self._vault.get(f"{key}_meta") or {}

            services.append(
                {
                    "service": service_name,
                    "account": meta.get("account", ""),
                    "enrolled_at": meta.get("enrolled_at", ""),
                }
            )

        return ToolResult(
            success=True,
            data={"services": services, "count": len(services)},
        )
