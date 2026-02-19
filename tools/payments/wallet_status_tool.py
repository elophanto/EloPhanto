"""wallet_status — view agent's crypto wallet details."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class WalletStatusTool(BaseTool):
    """Show the agent's crypto wallet address, chain, and token balances."""

    def __init__(self) -> None:
        self._payments_manager: Any = None  # Injected by agent

    @property
    def name(self) -> str:
        return "wallet_status"

    @property
    def description(self) -> str:
        return (
            "Show the agent's crypto wallet address, chain, token balances, "
            "and spending summary (daily/monthly spent vs limits)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._payments_manager:
            return ToolResult(success=False, error="Payments system not initialized")

        details = await self._payments_manager.get_wallet_details()
        return ToolResult(success=True, data=details)
