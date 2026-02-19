"""payment_validate — validate crypto address format."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class PaymentValidateTool(BaseTool):
    """Validate a crypto address format for a given chain."""

    def __init__(self) -> None:
        self._payments_manager: Any = None

    @property
    def name(self) -> str:
        return "payment_validate"

    @property
    def description(self) -> str:
        return (
            "Validate a crypto address format (Ethereum/Base: 0x + 40 hex chars, Solana: base58)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "The address to validate.",
                },
                "chain": {
                    "type": "string",
                    "description": "Chain to validate for (base, ethereum, solana). Default: base.",
                },
            },
            "required": ["address"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._payments_manager:
            return ToolResult(success=False, error="Payments system not initialized")

        address = params["address"]
        chain = params.get("chain", "base")
        valid = self._payments_manager.validate_address(address, chain)
        return ToolResult(
            success=True,
            data={"address": address, "chain": chain, "valid": valid},
        )
