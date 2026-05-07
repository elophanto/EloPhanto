"""``polymarket_quantize_order`` — fix the precision-rejection failure mode.

Live trade history showed 6 of 8 failed Polymarket orders rejected with::

    invalid amounts, the market buy orders maker amount supports a
    max accuracy of 2 decimals, taker amount a max of 5 decimals

The price × size product (USDC notional) must land on exactly 2
decimals. ``42.85 × 0.35 = 14.9975`` → 4 decimals → rejected. This
tool snaps a desired (price, size) onto the precision grid so the
order is accepted.

Always rounds DOWN — never sizes a position larger than the caller
asked for.

SAFE permission level — pure math, no I/O.
"""

from __future__ import annotations

from typing import Any

from core.polymarket_engine import quantize_order
from tools.base import BaseTool, PermissionLevel, ToolResult


class PolymarketQuantizeOrderTool(BaseTool):
    """Snap (price, size) onto Polymarket's precision grid."""

    @property
    def group(self) -> str:
        return "polymarket"

    @property
    def name(self) -> str:
        return "polymarket_quantize_order"

    @property
    def description(self) -> str:
        return (
            "Snap a desired (price, size) onto Polymarket's precision "
            "grid before calling create_and_post_order. Polymarket "
            "rejects orders whose `price × size` (USDC notional) has "
            "more than 2 decimals — 6 of 8 failed orders in live "
            "history hit this exact rule. This tool returns the "
            "(price, size, notional_usdc) that will be accepted, "
            "always rounded DOWN so the position is never larger than "
            "the caller asked for. Call this BEFORE every "
            "create_and_post_order with the price + your intended size."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "price": {
                    "type": "number",
                    "description": ("Order price [0.01, 0.99]. Polymarket prices."),
                },
                "desired_size": {
                    "type": "number",
                    "description": (
                        "Number of shares you intended to trade. The "
                        "tool may snap this DOWN to satisfy precision."
                    ),
                },
                "side": {
                    "type": "string",
                    "enum": ["BUY", "SELL"],
                    "description": (
                        "Order side. BUY uses 5-decimal taker; SELL "
                        "uses 4-decimal taker per Polymarket's rules."
                    ),
                },
            },
            "required": ["price", "desired_size"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        price = float(params.get("price", 0.0))
        desired_size = float(params.get("desired_size", 0.0))
        side = str(params.get("side", "BUY"))
        try:
            result = quantize_order(price=price, desired_size=desired_size, side=side)
        except ValueError as e:
            return ToolResult(success=False, data={}, error=str(e))
        return ToolResult(
            success=True,
            data={
                "price": result.price,
                "size": result.size,
                "notional_usdc": result.notional_usdc,
                "side": result.side,
                "rationale": result.rationale,
            },
        )
