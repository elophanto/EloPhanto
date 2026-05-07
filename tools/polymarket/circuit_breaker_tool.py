"""``polymarket_circuit_breaker`` — drawdown check before opening positions.

The agent calls this with peak portfolio equity and current portfolio
equity. If the drawdown exceeds the configured threshold (default
20%), new entries are blocked while the breaker is active. Closing
existing positions stays allowed — this is the difference between
"had a bad week" and "blew up the account on tilt-trading."

Caller is responsible for tracking peak equity (typically rolling
30-day high). The tool does the math; persistence belongs to the
calling skill.

SAFE permission level — read-only decision.
"""

from __future__ import annotations

from typing import Any

from core.polymarket_engine import check_drawdown
from tools.base import BaseTool, PermissionLevel, ToolResult


class PolymarketCircuitBreakerTool(BaseTool):
    """Block new Polymarket entries when portfolio drawdown exceeds the
    configured threshold."""

    @property
    def group(self) -> str:
        return "polymarket"

    def __init__(self) -> None:
        self._polymarket_config: Any = None

    @property
    def name(self) -> str:
        return "polymarket_circuit_breaker"

    @property
    def description(self) -> str:
        return (
            "Drawdown circuit breaker for Polymarket. Pass peak "
            "portfolio equity (rolling 30-day high or operator-set) "
            "and current portfolio equity. Returns `paused: true` "
            "when drawdown exceeds the threshold (default 20%). "
            "When paused, do NOT open new positions — closing existing "
            "ones stays allowed. Pairs with `polymarket_pre_trade` as "
            "an outer gate before any new entry."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "peak_equity": {
                    "type": "number",
                    "description": (
                        "Highest portfolio value observed in the "
                        "lookback window. Operator decides the window — "
                        "typically 30 days. USD."
                    ),
                },
                "current_equity": {
                    "type": "number",
                    "description": "Current portfolio value, USD.",
                },
            },
            "required": ["peak_equity", "current_equity"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        peak = float(params.get("peak_equity", 0.0))
        current = float(params.get("current_equity", 0.0))
        pause_pct = 0.20
        if self._polymarket_config is not None:
            pause_pct = float(
                getattr(self._polymarket_config, "drawdown_pause_pct", pause_pct)
            )

        result = check_drawdown(peak, current, pause_pct=pause_pct)
        return ToolResult(
            success=True,
            data={
                "paused": result.paused,
                "drawdown_pct": result.drawdown_pct,
                "threshold_pct": result.threshold_pct,
                "reason": result.reason,
            },
        )
