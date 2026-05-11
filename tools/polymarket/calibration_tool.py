"""``polymarket_calibration`` — produce the calibration audit report.

Reads ``polymarket_predictions``, joins with the eventual outcomes
(set by ``polymarket_resolve_pending``), and produces:

- **By stated probability** — bucket predictions by their stated
  win probability (the LLM's ``llm_prob`` re-framed to the side we
  took) and report realized win rate per bucket. The ideal calibrated
  bot has ``realized_win_rate ≈ avg_claimed`` per bucket.
- **By entry price** — bucket by the implied market probability of
  the side we took (1 - entry_price for NO, entry_price for YES).
  This is the chart in the Polymarket Quantitative Trading Framework
  image: dots near the diagonal = market is calibrated; dots above =
  we found edge; dots below = we paid the spread for nothing.
- **By confidence band** — high/medium/low bucket realized stats so
  we can tell if the band labels actually mean what they claim.
- **Brier score** — overall probabilistic accuracy. <0.25 means the
  bot is at least better than always claiming 50%.
- **Maker fill rate** — fraction of post-only orders that filled
  before resolution.

SAFE — pure read on our own audit table, no network.
"""

from __future__ import annotations

from typing import Any

from core.polymarket_calibration import (
    ResolvedPrediction,
    build_report,
    to_winner_perspective,
)
from tools.base import BaseTool, PermissionLevel, ToolResult, ToolTier


class PolymarketCalibrationTool(BaseTool):
    """Calibration audit over the predictions audit table."""

    @property
    def group(self) -> str:
        return "polymarket"

    def __init__(self) -> None:
        self._db: Any = None

    @property
    def name(self) -> str:
        return "polymarket_calibration"

    @property
    def description(self) -> str:
        return (
            "Calibration audit over logged Polymarket predictions. "
            "Buckets resolved predictions by stated probability AND by "
            "entry price; reports realized win rate per bucket, Brier "
            "score, per-confidence-band stats, and maker fill rate. "
            "Use this to answer: (1) when the LLM says 70%, does it "
            "actually win 70%? (2) do markets we entered at $0.40 pay "
            "out 40% of the time? (3) is our high-confidence band "
            "actually high-confidence? Read-only."
        )

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def tier(self) -> ToolTier:
        return ToolTier.PROFILE

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "since": {
                    "type": "string",
                    "description": (
                        "ISO timestamp lower bound. Only predictions "
                        "with created_at >= since are included. "
                        "Default: include all."
                    ),
                },
                "bucket_width": {
                    "type": "number",
                    "description": "Bucket width in [0, 1]. Default 0.10 (10% buckets).",
                },
                "kind": {
                    "type": "string",
                    "enum": ["live", "shadow", "all"],
                    "description": (
                        "Filter predictions by kind. 'live' = real bets "
                        "only, 'shadow' = paper bets only, 'all' "
                        "(default) = both, with per-kind breakdown in "
                        "the report's by_kind field. Use 'live' before "
                        "making claims about real edge."
                    ),
                },
            },
            "required": [],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._db is None:
            return ToolResult(success=False, error="db not injected")

        try:
            bucket_width = float(params.get("bucket_width", 0.10))
        except (TypeError, ValueError):
            bucket_width = 0.10
        if not 0 < bucket_width <= 1:
            return ToolResult(
                success=False,
                error=f"bucket_width must be in (0, 1], got {bucket_width}",
            )

        since = (params.get("since") or "").strip()
        kind_filter = (params.get("kind") or "all").lower()
        if kind_filter not in ("live", "shadow", "all"):
            kind_filter = "all"

        # Resolved predictions for the report's main body.
        where = ["resolved_at IS NOT NULL"]
        args: list[Any] = []
        if since:
            where.append("created_at >= ?")
            args.append(since)
        if kind_filter != "all":
            where.append("kind = ?")
            args.append(kind_filter)
        sql = (
            "SELECT side, entry_price, llm_prob, settle_price, "
            "confidence_band, order_type, kind "
            "FROM polymarket_predictions WHERE "
            + " AND ".join(where)
            + " ORDER BY created_at"
        )
        resolved_rows = (
            await self._db.execute(sql, tuple(args))
            if args
            else await self._db.execute(sql)
        )

        resolved: list[ResolvedPrediction] = []
        for r in resolved_rows:
            try:
                claimed, implied, won = to_winner_perspective(
                    side=r["side"],
                    entry_price=float(r["entry_price"]),
                    llm_prob=float(r["llm_prob"]),
                    settle_price=float(r["settle_price"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            resolved.append(
                ResolvedPrediction(
                    claimed_prob=claimed,
                    entry_price_implied=implied,
                    won=won,
                    confidence_band=(r["confidence_band"] or "medium").lower(),
                    order_type=(r["order_type"] or "GTC"),
                    filled=True,  # by definition, resolved predictions filled
                    kind=(r["kind"] or "live"),
                )
            )

        # Maker fill rate: count post-only orders placed (any time) vs filled.
        # An order "filled" if we have a corresponding row that resolved
        # — for now we approximate by "the prediction has settle_price".
        # The polynode-trading.db side has the authoritative fill flag,
        # but JOINing across DBs is out of scope for v1 — this is a good
        # proxy because unfilled post-only orders never see a resolution.
        if since:
            placed_rows = await self._db.execute(
                """SELECT COUNT(*) AS n
                   FROM polymarket_predictions
                   WHERE order_type LIKE '%post%' AND created_at >= ?""",
                (since,),
            )
            filled_rows = await self._db.execute(
                """SELECT COUNT(*) AS n
                   FROM polymarket_predictions
                   WHERE order_type LIKE '%post%'
                     AND resolved_at IS NOT NULL
                     AND created_at >= ?""",
                (since,),
            )
        else:
            placed_rows = await self._db.execute(
                """SELECT COUNT(*) AS n
                   FROM polymarket_predictions
                   WHERE order_type LIKE '%post%'"""
            )
            filled_rows = await self._db.execute(
                """SELECT COUNT(*) AS n
                   FROM polymarket_predictions
                   WHERE order_type LIKE '%post%' AND resolved_at IS NOT NULL"""
            )
        placed = placed_rows[0]["n"] if placed_rows else 0
        filled = filled_rows[0]["n"] if filled_rows else 0

        report = build_report(
            resolved,
            bucket_width=bucket_width,
            placed_post_only=placed,
            filled_post_only=filled,
        )

        return ToolResult(success=True, data=report.to_dict())
