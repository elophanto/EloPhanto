"""``polymarket_performance`` — agent reads its own track record.

The agent's scheduled tasks call this BEFORE deciding what to trade.
"How am I doing?" is the first question a competent trader asks; the
tool gives the answer back as a structured dict the LLM can reason over.

Returns realized P&L, win rate, open positions with cost basis,
failure-mode breakdown, and the top winning/losing positions in the
window. The agent can use this to:

  * notice a losing streak and back off
  * see how many orders are still hitting precision/allowance failures
    that need operator attention
  * size new positions based on current portfolio risk

SAFE permission level — read-only DB query, no I/O beyond the read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.polymarket_analytics import analyze_performance
from tools.base import BaseTool, PermissionLevel, ToolResult


class PolymarketPerformanceTool(BaseTool):
    """Read polynode-trading.db order_history and return a structured
    performance report for the requested window."""

    @property
    def group(self) -> str:
        return "polymarket"

    def __init__(self) -> None:
        # Injected at agent startup.
        self._polymarket_config: Any = None
        self._workspace: Path | None = None

    @property
    def name(self) -> str:
        return "polymarket_performance"

    @property
    def description(self) -> str:
        return (
            "Read your own Polymarket trade history and return a "
            "structured performance report. Use this BEFORE deciding "
            "what to trade — answer the 'how am I doing?' question. "
            "Returns realized P&L, win rate, open-position cost basis, "
            "failure-mode breakdown (precision rejections vs allowance "
            "vs other), and top winners/losers in the window. Default "
            "window is 30 days; pass `window_days: 7` for the recent "
            "week or `window_days: 0` for all-time."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "window_days": {
                    "type": "integer",
                    "description": (
                        "Lookback window in days. 0 or negative = "
                        "all-time. Default 30."
                    ),
                    "default": 30,
                },
                "top_n_positions": {
                    "type": "integer",
                    "description": (
                        "How many top winners + losers to surface in "
                        "the report. Default 5 each."
                    ),
                    "default": 5,
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        window_days_raw = int(params.get("window_days", 30))
        window_days = window_days_raw if window_days_raw > 0 else None
        top_n = max(1, int(params.get("top_n_positions", 5)))

        db_path = self._resolve_db_path()
        if db_path is None:
            return ToolResult(
                success=False,
                data={},
                error=(
                    "Could not resolve Polymarket trading DB path. "
                    "Set polymarket.trading_db_path in config.yaml or "
                    "ensure <agent.workspace>/data/polymarket/"
                    "polynode-trading.db exists."
                ),
            )

        try:
            report = analyze_performance(db_path, window_days=window_days)
        except FileNotFoundError as e:
            return ToolResult(success=False, data={}, error=str(e))

        # Closed positions sorted by realized P&L for the leaderboards.
        closed = [p for p in report.positions if not p.is_open]
        winners = sorted(closed, key=lambda p: p.realized_pnl, reverse=True)[:top_n]
        losers = sorted(closed, key=lambda p: p.realized_pnl)[:top_n]

        def _pos_to_dict(p: Any) -> dict[str, Any]:
            return {
                "token_id": p.token_id,
                "buy_count": p.buy_count,
                "sell_count": p.sell_count,
                "buy_size": round(p.buy_size, 4),
                "sell_size": round(p.sell_size, 4),
                "avg_buy_price": round(p.avg_buy_price, 4),
                "buy_cost_total": round(p.buy_cost_total, 2),
                "sell_proceeds_total": round(p.sell_proceeds_total, 2),
                "realized_pnl": round(p.realized_pnl, 2),
                "open_size": round(p.open_size, 4),
                "open_cost_basis": round(p.open_cost_basis, 2),
                "is_open": p.is_open,
            }

        return ToolResult(
            success=True,
            data={
                "window_label": report.window_label,
                "total_orders": report.total_orders,
                "submitted_orders": report.submitted_orders,
                "failed_orders": report.failed_orders,
                "submit_success_rate": round(report.submit_success_rate, 4),
                "total_buy_notional_usdc": round(report.total_buy_notional, 2),
                "total_sell_proceeds_usdc": round(report.total_sell_proceeds, 2),
                "total_realized_pnl_usdc": round(report.total_realized_pnl, 2),
                "total_open_cost_basis_usdc": round(report.total_open_cost_basis, 2),
                # Conservative net P&L: assumes every open position
                # resolves at zero. The operator-anchor number — see
                # docs/71-POLYMARKET-RISK.md and the CLI's leading row.
                "net_pnl_worst_case_usdc": round(report.net_pnl_worst_case, 2),
                "open_position_count": report.open_position_count,
                "closed_position_count": report.closed_position_count,
                "win_count": report.win_count,
                "loss_count": report.loss_count,
                "win_rate": round(report.win_rate, 4),
                "failures": {
                    "total_failed": report.failures.total_failed,
                    "precision": report.failures.precision,
                    "precision_pct": round(report.failures.precision_pct, 4),
                    "allowance": report.failures.allowance,
                    "allowance_pct": round(report.failures.allowance_pct, 4),
                    "other": report.failures.other,
                    "unknown": report.failures.unknown,
                    "sample_messages": report.failures.sample_messages,
                },
                "top_winners": [_pos_to_dict(p) for p in winners],
                "top_losers": [_pos_to_dict(p) for p in losers],
            },
        )

    def _resolve_db_path(self) -> Path | None:
        """Resolution order:
        1. polymarket.trading_db_path (operator-set absolute path).
        2. <agent.workspace>/data/polymarket/polynode-trading.db
           (default polynode location).
        Returns None when neither resolves to anything readable.
        """
        cfg_path = ""
        if self._polymarket_config is not None:
            cfg_path = getattr(self._polymarket_config, "trading_db_path", "") or ""
        if cfg_path:
            return Path(cfg_path).expanduser()
        if self._workspace is not None:
            default = self._workspace / "data" / "polymarket" / "polynode-trading.db"
            return default
        return None
