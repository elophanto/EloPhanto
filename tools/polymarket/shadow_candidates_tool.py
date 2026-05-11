"""``polymarket_shadow_candidates`` — pick markets worth shadow-predicting.

Shadow predictions are paper bets logged for calibration without any
capital at risk. The blocker for calibration in the live-only world is
sample size: real bets accrue slowly because the gate filters most
markets out, and resolution takes days-to-weeks. Shadows let the agent
log a probability estimate on *any* upcoming market and have it
auto-resolve via Gamma the moment the market closes — so calibration
n_resolved climbs in days instead of months.

This tool just lists candidates: upcoming markets in the next 0-14
days that the agent has not already logged a shadow for. The LLM
then forms its own probability via the usual research path and calls
``polymarket_log_prediction`` with ``live=false``.

SAFE — read-only against Gamma + our own audit table. No orders.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from tools.base import BaseTool, PermissionLevel, ToolResult, ToolTier

logger = logging.getLogger(__name__)

_GAMMA_URL = "https://gamma-api.polymarket.com"
_REQUEST_TIMEOUT_SECONDS = 10.0


class PolymarketShadowCandidatesTool(BaseTool):
    """List upcoming Polymarket markets not yet shadow-predicted."""

    @property
    def group(self) -> str:
        return "polymarket"

    def __init__(self) -> None:
        self._db: Any = None

    @property
    def name(self) -> str:
        return "polymarket_shadow_candidates"

    @property
    def description(self) -> str:
        return (
            "List upcoming Polymarket markets the agent has NOT yet "
            "shadow-predicted. Use this to drive the shadow-prediction "
            "loop: pick one, form a probability estimate via your usual "
            "research path, then call polymarket_log_prediction with "
            "live=false. Returns up to {limit} candidates with slug, "
            "question, end_date, current YES price, volume. Read-only."
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
                    "description": "Max candidates to return (default 10, max 50).",
                },
                "max_days_to_close": {
                    "type": "integer",
                    "description": (
                        "Only include markets closing within this many "
                        "days. Default 14. Shorter horizons resolve "
                        "faster and grow calibration data quickest."
                    ),
                },
                "min_volume": {
                    "type": "number",
                    "description": (
                        "Skip thin markets below this 24h volume in USD. "
                        "Default 1000. Thin markets resolve unpredictably."
                    ),
                },
            },
            "required": [],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._db is None:
            return ToolResult(success=False, error="db not injected")

        try:
            limit = int(params.get("limit", 10))
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(50, limit))

        try:
            max_days = int(params.get("max_days_to_close", 14))
        except (TypeError, ValueError):
            max_days = 14
        max_days = max(1, min(60, max_days))

        try:
            min_volume = float(params.get("min_volume", 1000.0))
        except (TypeError, ValueError):
            min_volume = 1000.0

        # Pull existing shadow slugs so we don't keep re-suggesting the
        # same market. Live predictions are NOT excluded — shadowing a
        # market we also bet on is fine and useful (separate kinds).
        existing_rows = await self._db.execute(
            "SELECT DISTINCT market_slug FROM polymarket_predictions "
            "WHERE kind = 'shadow' AND market_slug IS NOT NULL AND market_slug != ''"
        )
        already_shadowed = {r["market_slug"] for r in existing_rows}

        # Gamma /markets supports filtering by active/closed and order by
        # end_date asc. We fetch a few more than `limit` because we'll
        # filter post-hoc on volume + dedup.
        params_q = {
            "active": "true",
            "closed": "false",
            "order": "endDate",
            "ascending": "true",
            "limit": str(min(100, limit * 5)),
        }
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
                r = await client.get(
                    f"{_GAMMA_URL}/markets",
                    params=params_q,
                    headers={"Accept": "application/json"},
                )
                if r.status_code != 200:
                    return ToolResult(
                        success=False,
                        error=f"Gamma /markets returned {r.status_code}",
                    )
                data = r.json()
        except Exception as e:
            return ToolResult(success=False, error=f"Gamma fetch failed: {e}")

        markets = data if isinstance(data, list) else (data.get("markets") or [])

        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        horizon = now + timedelta(days=max_days)

        candidates: list[dict[str, Any]] = []
        for m in markets:
            slug = (m.get("slug") or "").strip()
            if not slug or slug in already_shadowed:
                continue

            end_iso = m.get("endDate") or m.get("end_date_iso")
            if not end_iso:
                continue
            try:
                end_dt = datetime.fromisoformat(str(end_iso).replace("Z", "+00:00"))
            except ValueError:
                continue
            if end_dt < now or end_dt > horizon:
                continue

            try:
                volume = float(m.get("volume24hr") or m.get("volume") or 0.0)
            except (TypeError, ValueError):
                volume = 0.0
            if volume < min_volume:
                continue

            raw_prices = m.get("outcomePrices")
            yes_price: float | None = None
            if isinstance(raw_prices, str):
                import json as _json

                try:
                    prices = _json.loads(raw_prices)
                except _json.JSONDecodeError:
                    prices = None
            else:
                prices = raw_prices
            if isinstance(prices, list) and prices:
                try:
                    yes_price = float(prices[0])
                except (TypeError, ValueError):
                    yes_price = None

            candidates.append(
                {
                    "slug": slug,
                    "question": m.get("question") or m.get("title") or slug,
                    "end_date": end_iso,
                    "yes_price": yes_price,
                    "volume24h": volume,
                }
            )
            if len(candidates) >= limit:
                break

        return ToolResult(
            success=True,
            data={
                "candidates": candidates,
                "n": len(candidates),
                "already_shadowed_count": len(already_shadowed),
            },
        )
