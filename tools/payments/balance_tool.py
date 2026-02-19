"""payment_balance — check token balance in agent wallet."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class PaymentBalanceTool(BaseTool):
    """Check the balance of a specific token in the agent's wallet."""

    def __init__(self) -> None:
        self._payments_manager: Any = None

    @property
    def name(self) -> str:
        return "payment_balance"

    @property
    def description(self) -> str:
        return "Check the balance of a specific token in the agent's crypto wallet."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "token": {
                    "type": "string",
                    "description": "Token symbol (e.g., USDC, ETH). Default: USDC.",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._payments_manager:
            return ToolResult(success=False, error="Payments system not initialized")

        token = params.get("token", "USDC")
        try:
            balance = await self._payments_manager.get_balance(token)
            return ToolResult(success=True, data=balance)
        except Exception as e:
            return ToolResult(success=False, error=str(e))
