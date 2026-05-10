"""``polymarket_resolve_pending`` — fetch resolution outcomes for
unresolved predictions and update the calibration table.

Reads ``polymarket_predictions`` rows where ``resolved_at IS NULL``,
batches them by market_slug, hits Polymarket's Gamma API
(``/events/<slug>``) to read the ``resolved`` flag and outcome prices
per outcome token, then writes ``resolved_at`` + ``settle_price`` +
``outcome`` + ``realized_pnl`` back.

SAFE — read-only against the agent's own audit table + a single
unauthenticated GET per unique market_slug. No order placement, no
on-chain transactions.

Run periodically from a scheduled task (cron 0 */6 * * * is plenty —
Polymarket markets resolve on weekly-to-monthly cadence). The
calibration tool is the consumer.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from tools.base import BaseTool, PermissionLevel, ToolResult, ToolTier

logger = logging.getLogger(__name__)

_GAMMA_URL = "https://gamma-api.polymarket.com"
_REQUEST_TIMEOUT_SECONDS = 10.0


def _compute_realized_pnl(
    side: str, entry_price: float, size: float, settle_price: float
) -> float:
    """Polymarket settles to 0 or 1. PnL on a single share:

    - YES side, settle=1: payout 1, cost ``entry_price`` → +(1 - entry)
    - YES side, settle=0: payout 0, cost ``entry_price`` → -entry
    - NO side, settle=0: payout 1, cost ``(1 - entry_price)`` → +entry
    - NO side, settle=1: payout 0, cost ``(1 - entry_price)`` → -(1 - entry)

    The NO side's cost basis is ``1 - entry_price`` because that's what
    you actually pay for the NO token at the implied YES price.
    """
    side_u = side.upper()
    if side_u == "YES":
        per_share = settle_price - entry_price
    else:
        per_share = (1.0 - settle_price) - (1.0 - entry_price)
    return per_share * size


def _classify_outcome(side: str, settle_price: float) -> str:
    """Resolves to WIN / LOSS / PUSH. PUSH only when settle_price
    is exactly 0.5 (rare, only on cancelled markets)."""
    if abs(settle_price - 0.5) < 1e-6:
        return "PUSH"
    side_u = side.upper()
    if side_u == "YES":
        return "WIN" if settle_price > 0.5 else "LOSS"
    return "WIN" if settle_price < 0.5 else "LOSS"


async def _fetch_resolution_for_slug(slug: str) -> dict | None:
    """Hit Gamma API for a single market. Returns
    ``{resolved: bool, settle_price_yes: float | None}`` or None on
    any failure (network, parse, market not found)."""
    if not slug:
        return None
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            r = await client.get(
                f"{_GAMMA_URL}/events/slug/{slug}",
                headers={"Accept": "application/json"},
            )
            if r.status_code != 200:
                return None
            data = r.json()
    except Exception as e:
        logger.debug("Gamma fetch failed for %s: %s", slug, e)
        return None

    # Polymarket events have a list of markets; for binary YES/NO
    # markets the YES outcome's `outcomePrices[0]` settles to 1 on
    # resolve. Multi-outcome events are handled by reading the matching
    # outcome via the ``outcomes`` array.
    markets = data.get("markets") or [data] if isinstance(data, dict) else []
    if not markets:
        return None
    market = markets[0]
    closed = bool(market.get("closed"))
    if not closed:
        return {"resolved": False, "settle_price_yes": None}

    # outcomePrices is a JSON-encoded list of strings (per Polymarket convention).
    raw_prices = market.get("outcomePrices")
    if isinstance(raw_prices, str):
        import json as _json

        try:
            prices = _json.loads(raw_prices)
        except _json.JSONDecodeError:
            return None
    else:
        prices = raw_prices
    if not isinstance(prices, list) or not prices:
        return None
    try:
        settle_yes = float(prices[0])
    except (TypeError, ValueError):
        return None
    return {"resolved": True, "settle_price_yes": settle_yes}


class PolymarketResolvePendingTool(BaseTool):
    """Fetch resolutions for unresolved predictions and update the audit table."""

    @property
    def group(self) -> str:
        return "polymarket"

    def __init__(self) -> None:
        self._db: Any = None

    @property
    def name(self) -> str:
        return "polymarket_resolve_pending"

    @property
    def description(self) -> str:
        return (
            "Fetch resolution outcomes from Polymarket's Gamma API for "
            "all logged predictions where resolved_at IS NULL. Updates "
            "settle_price, outcome (WIN/LOSS/PUSH), realized_pnl, and "
            "resolved_at. Returns {checked, resolved, still_pending, "
            "skipped_no_slug, errors}. Run on a 6h schedule. Read-only "
            "against Polymarket; only writes to our own audit table."
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
                "limit": {
                    "type": "integer",
                    "description": (
                        "Max predictions to check this run (default 200). "
                        "Caps API calls."
                    ),
                },
            },
            "required": [],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._db is None:
            return ToolResult(success=False, error="db not injected")

        try:
            limit = int(params.get("limit", 200))
        except (TypeError, ValueError):
            limit = 200
        limit = max(1, min(1000, limit))

        rows = await self._db.execute(
            """SELECT id, market_slug, token_id, side, entry_price, size
               FROM polymarket_predictions
               WHERE resolved_at IS NULL
               ORDER BY created_at
               LIMIT ?""",
            (limit,),
        )

        checked = len(rows)
        resolved = 0
        still_pending = 0
        skipped_no_slug = 0
        errors = 0

        # Cache per-slug results so duplicate predictions on the same
        # market only hit Gamma once.
        slug_cache: dict[str, dict | None] = {}

        for row in rows:
            slug = (row["market_slug"] or "").strip()
            if not slug:
                skipped_no_slug += 1
                continue
            if slug not in slug_cache:
                slug_cache[slug] = await _fetch_resolution_for_slug(slug)
            data = slug_cache[slug]
            if data is None:
                errors += 1
                continue
            if not data["resolved"]:
                still_pending += 1
                continue
            settle_yes = data["settle_price_yes"]
            if settle_yes is None:
                errors += 1
                continue
            outcome = _classify_outcome(row["side"], settle_yes)
            pnl = _compute_realized_pnl(
                row["side"], float(row["entry_price"]), float(row["size"]), settle_yes
            )
            now = datetime.now(UTC).isoformat()
            await self._db.execute_insert(
                """UPDATE polymarket_predictions
                   SET resolved_at = ?,
                       settle_price = ?,
                       outcome = ?,
                       realized_pnl = ?
                   WHERE id = ?""",
                (now, settle_yes, outcome, pnl, row["id"]),
            )
            resolved += 1

        return ToolResult(
            success=True,
            data={
                "checked": checked,
                "resolved": resolved,
                "still_pending": still_pending,
                "skipped_no_slug": skipped_no_slug,
                "errors": errors,
                "unique_markets_queried": len(slug_cache),
            },
        )
