"""crypto_swap — swap tokens on DEX from agent wallet."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class CryptoSwapTool(BaseTool):
    """Swap tokens on a DEX from the agent's wallet."""

    def __init__(self) -> None:
        self._payments_manager: Any = None

    @property
    def name(self) -> str:
        return "crypto_swap"

    @property
    def description(self) -> str:
        return (
            "Swap tokens on a DEX from the agent's wallet (e.g., ETH → USDC). "
            "Requires explicit user approval. Use payment_preview first for a quote."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "from_token": {
                    "type": "string",
                    "description": "Token to sell (e.g., ETH).",
                },
                "to_token": {
                    "type": "string",
                    "description": "Token to buy (e.g., USDC).",
                },
                "amount": {
                    "type": "number",
                    "description": "Amount of from_token to swap.",
                },
            },
            "required": ["from_token", "to_token", "amount"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.CRITICAL

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._payments_manager:
            return ToolResult(success=False, error="Payments system not initialized")

        try:
            result = await self._payments_manager.swap(
                from_token=params["from_token"],
                to_token=params["to_token"],
                amount=params["amount"],
                task_context=params.get("context"),
            )
            return ToolResult(success=True, data=result)
        except Exception as e:
            return ToolResult(success=False, error=str(e))
