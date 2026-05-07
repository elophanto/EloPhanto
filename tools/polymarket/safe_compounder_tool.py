"""``polymarket_safe_compounder`` — score a market for the NO-side baseline.

Single-market evaluator for the safe-compounder strategy ported from
zostaff/poly-trading-bot. The agent loops candidate markets through
this tool; for each ``qualifies=True`` it then runs
``polymarket_pre_trade`` for the standard edge/skip/stop-loss pass
and places the maker order at ``suggested_limit_price`` with size
``suggested_size_usdc``.

Strategy in one sentence: trade NO on markets where the lowest NO ask
is already > $0.80 (high-probability NO wins), the time-decay-amplified
estimated NO probability beats the live ask by ≥ 3%, and Kelly sizing
returns a positive fraction. Maker orders 1¢ inside the ask earn
rebates instead of paying taker fees.

This is the structural-edge baseline that runs in parallel with the
LLM directional bot. Different risk profile, different cadence,
both managed by the resource-typed scheduler.

SAFE permission level — pure scoring, no I/O.
"""

from __future__ import annotations

from typing import Any

from core.polymarket_engine import score_safe_compounder
from tools.base import BaseTool, PermissionLevel, ToolResult


class PolymarketSafeCompounderTool(BaseTool):
    """Score one Polymarket market for the safe-compounder strategy."""

    @property
    def group(self) -> str:
        return "polymarket"

    def __init__(self) -> None:
        # Reserved for future per-strategy config overrides. The
        # current implementation uses module-level defaults.
        self._polymarket_config: Any = None

    @property
    def name(self) -> str:
        return "polymarket_safe_compounder"

    @property
    def description(self) -> str:
        return (
            "Score one Polymarket market for the safe-compounder "
            "(NO-side, high-certainty, edge-gated) baseline strategy. "
            "Returns `qualifies: true` plus a suggested maker limit "
            "price + Kelly-capped size when ALL bars clear: lowest NO "
            "ask > $0.80, 24h volume > $10, days-to-expiry between "
            "0.5 and 60, and time-decay-amplified estimated NO "
            "probability beats the live ask by ≥ 3%. Returns "
            "`qualifies: false` plus a `rationale` listing every "
            "constraint that was violated. After this tool says yes, "
            "still run `polymarket_pre_trade` for the universal "
            "edge/skip/stop-loss gate before placing the order."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "yes_last_price": {
                    "type": "number",
                    "description": (
                        "Most recent YES price for this market [0, 1]. "
                        "Lower = stronger signal that NO will win."
                    ),
                },
                "lowest_no_ask": {
                    "type": "number",
                    "description": (
                        "Best (lowest) NO ask on the orderbook [0, 1]. "
                        "Must be > 0.80 to qualify."
                    ),
                },
                "volume": {
                    "type": "number",
                    "description": (
                        "24-hour USDC volume on this market. Below "
                        "$10 the orderbook is too thin to trust."
                    ),
                },
                "days_to_expiry": {
                    "type": "number",
                    "description": (
                        "Days until market resolution. Sub-half-day "
                        "rejected (volatility); 60+ days rejected "
                        "(too much can change)."
                    ),
                },
                "portfolio_value": {
                    "type": "number",
                    "description": (
                        "Total Polymarket portfolio value in USDC. "
                        "Used for Kelly sizing — the suggested USDC "
                        "amount caps at 10% of this."
                    ),
                },
            },
            "required": [
                "yes_last_price",
                "lowest_no_ask",
                "volume",
                "days_to_expiry",
                "portfolio_value",
            ],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        try:
            candidate = score_safe_compounder(
                yes_last_price=float(params.get("yes_last_price", 0.0)),
                lowest_no_ask=float(params.get("lowest_no_ask", 0.0)),
                volume=float(params.get("volume", 0.0)),
                days_to_expiry=float(params.get("days_to_expiry", 0.0)),
                portfolio_value=float(params.get("portfolio_value", 0.0)),
            )
        except ValueError as e:
            return ToolResult(success=False, data={}, error=str(e))

        return ToolResult(
            success=True,
            data={
                "qualifies": candidate.qualifies,
                "estimated_no_prob": candidate.estimated_no_prob,
                "edge": candidate.edge,
                "suggested_limit_price": candidate.suggested_limit_price,
                "suggested_size_usdc": candidate.suggested_size_usdc,
                "rationale": candidate.rationale,
            },
        )
