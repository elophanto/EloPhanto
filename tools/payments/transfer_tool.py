"""crypto_transfer — send tokens from agent wallet."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class CryptoTransferTool(BaseTool):
    """Send tokens from the agent's wallet to a recipient address."""

    def __init__(self) -> None:
        self._payments_manager: Any = None

    @property
    def name(self) -> str:
        return "crypto_transfer"

    @property
    def description(self) -> str:
        return (
            "Send tokens from the agent's crypto wallet to a recipient address. "
            "Requires explicit user approval. Check balance and preview first."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient address (0x... for EVM, base58 for Solana).",
                },
                "amount": {
                    "type": "number",
                    "description": "Amount to send.",
                },
                "token": {
                    "type": "string",
                    "description": "Token symbol (e.g., USDC, ETH). Default: USDC.",
                },
            },
            "required": ["to", "amount", "token"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.CRITICAL

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._payments_manager:
            return ToolResult(success=False, error="Payments system not initialized")

        try:
            result = await self._payments_manager.transfer(
                to=params["to"],
                amount=params["amount"],
                token=params["token"],
                task_context=params.get("context"),
            )
            return ToolResult(success=True, data=result)
        except Exception as e:
            return ToolResult(success=False, error=str(e))
