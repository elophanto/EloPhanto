"""payment_preview — preview fees, rates, and spending limits before execution."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class PaymentPreviewTool(BaseTool):
    """Preview a payment: fees, exchange rates, spending limit status — no execution."""

    def __init__(self) -> None:
        self._payments_manager: Any = None

    @property
    def name(self) -> str:
        return "payment_preview"

    @property
    def description(self) -> str:
        return (
            "Preview a payment or swap: show fees, exchange rates, spending limit "
            "status, and approval tier. Does NOT execute anything."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "'transfer' or 'swap'. Default: transfer.",
                },
                "to": {
                    "type": "string",
                    "description": "Recipient address (for transfers).",
                },
                "amount": {
                    "type": "number",
                    "description": "Amount to send or swap.",
                },
                "token": {
                    "type": "string",
                    "description": "Token to send (for transfers). Default: USDC.",
                },
                "from_token": {
                    "type": "string",
                    "description": "Token to sell (for swaps).",
                },
                "to_token": {
                    "type": "string",
                    "description": "Token to buy (for swaps).",
                },
            },
            "required": ["amount"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._payments_manager:
            return ToolResult(success=False, error="Payments system not initialized")

        action = params.get("action", "transfer")
        amount = params["amount"]
        mgr = self._payments_manager

        result: dict[str, Any] = {
            "action": action,
            "amount": amount,
            "chain": mgr.chain,
        }

        # Check spending limits
        recipient = params.get("to", "preview")
        if action == "swap":
            recipient = f"swap:{params.get('from_token', '?')}->{params.get('to_token', '?')}"

        check = await mgr.limiter.check(amount, params.get("token", "USDC"), recipient)
        result["limits"] = {
            "allowed": check.allowed,
            "reason": check.reason if not check.allowed else "",
            "daily_spent": check.daily_spent,
            "monthly_spent": check.monthly_spent,
            "daily_limit": mgr._config.limits.daily,
            "monthly_limit": mgr._config.limits.monthly,
        }

        # Approval tier
        result["approval_tier"] = mgr.get_approval_tier(amount)

        # For swaps, try to get a price quote
        if action == "swap" and params.get("from_token") and params.get("to_token"):
            quote = await mgr.get_swap_price(params["from_token"], params["to_token"], amount)
            result["quote"] = quote

        return ToolResult(success=True, data=result)
