"""``polymarket_mark_to_market`` — price every open position at the
current best bid.

The conservative ``polymarket_performance`` worst-case treats every
open position as worth $0. Reality lives between that and cost basis:
each token has a current best bid on the book, and that's what the
position would actually recover on a market sell.

This tool fetches live bids from Polymarket's public CLOB API for
every open position, returns per-position recovery estimates, and
rolls up the true unrealized P&L. Use it to:

  * decide which open positions to cut now (cheap recovery vs.
    holding to resolution)
  * see the real bot P&L instead of "everything to zero"
  * notice positions with no bids — those are effectively dead

SAFE permission level — read-only HTTP + DB read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.polymarket_analytics import (
    analyze_performance,
    fetch_best_bid_via_clob,
    mark_open_positions_to_market,
)
from tools.base import BaseTool, PermissionLevel, ToolResult


class PolymarketMarkToMarketTool(BaseTool):
    """Fetch live best bids for every open Polymarket position and
    return enriched recovery estimates."""

    @property
    def group(self) -> str:
        return "polymarket"

    def __init__(self) -> None:
        self._polymarket_config: Any = None
        self._workspace: Path | None = None

    @property
    def name(self) -> str:
        return "polymarket_mark_to_market"

    @property
    def description(self) -> str:
        return (
            "Mark every open Polymarket position to current market — "
            "fetches the best bid from the CLOB orderbook for each "
            "open token_id and returns per-position recovery estimates "
            "plus a rolled-up true unrealized P&L. Use this when "
            "deciding which open positions to cut (cheap recovery now "
            "vs. holding to resolution) or to see real bot P&L instead "
            "of the 'open positions = $0' worst case. Read-only HTTP "
            "to clob.polymarket.com — no orders placed."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "max_positions": {
                    "type": "integer",
                    "description": (
                        "Cap how many open positions to query. Defaults "
                        "to all of them. Bound to keep token cost / HTTP "
                        "load predictable when there are many opens."
                    ),
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        max_positions = params.get("max_positions")
        try:
            max_positions = int(max_positions) if max_positions else None
        except (TypeError, ValueError):
            max_positions = None

        db_path = self._resolve_db_path()
        if db_path is None or not db_path.exists():
            return ToolResult(
                success=False,
                data={},
                error=(
                    "Polymarket trading DB not found. Set "
                    "polymarket.trading_db_path or ensure "
                    "<workspace>/data/polymarket/polynode-trading.db "
                    "exists."
                ),
            )

        report = analyze_performance(db_path, window_days=None)
        open_positions = [p for p in report.positions if p.is_open]
        if max_positions is not None:
            # Highest cost basis first — operator usually cares about
            # the biggest exposures.
            open_positions = sorted(
                open_positions, key=lambda p: p.open_cost_basis, reverse=True
            )[:max_positions]

        summary = mark_open_positions_to_market(
            open_positions, fetch_bid=fetch_best_bid_via_clob
        )

        return ToolResult(
            success=True,
            data={
                "open_position_count": len(summary.positions),
                "total_cost_basis_usdc": summary.total_cost_basis,
                "total_market_value_usdc": summary.total_market_value,
                "total_unrealized_pnl_usdc": summary.total_unrealized_pnl,
                "liveness_pct": round(summary.liveness_pct, 4),
                "no_bids_count": summary.no_bids_count,
                "fetch_failed_count": summary.fetch_failed_count,
                # True net P&L: realized + (live unrealized) — the
                # operator-anchor number AFTER mark-to-market replaces
                # the pessimistic "open=0" worst case.
                "net_pnl_marked_usdc": round(
                    report.total_realized_pnl + summary.total_unrealized_pnl, 2
                ),
                "realized_pnl_usdc": round(report.total_realized_pnl, 2),
                "positions": [
                    {
                        "token_id": p.token_id,
                        "open_size": round(p.open_size, 4),
                        "avg_buy_price": round(p.avg_buy_price, 4),
                        "cost_basis": round(p.cost_basis, 2),
                        "current_bid": p.current_bid,
                        "market_value": p.market_value,
                        "unrealized_pnl": p.unrealized_pnl,
                        "note": p.note,
                    }
                    for p in summary.positions
                ],
            },
        )

    def _resolve_db_path(self) -> Path | None:
        cfg_path = ""
        if self._polymarket_config is not None:
            cfg_path = getattr(self._polymarket_config, "trading_db_path", "") or ""
        if cfg_path:
            return Path(cfg_path).expanduser()
        if self._workspace is not None:
            return self._workspace / "data" / "polymarket" / "polynode-trading.db"
        return None
