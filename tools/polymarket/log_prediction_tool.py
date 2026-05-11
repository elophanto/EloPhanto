"""``polymarket_log_prediction`` — record the bot's stated probability
for a market BEFORE placing the order.

This is the calibration audit's input feed. Without it, we'd never be
able to answer "when the LLM said 70%, did it actually win 70%?" —
the on-chain order_history only knows the price we paid, not what we
*believed*.

Skill should call this immediately after pre_trade_gate passes and
before create_and_post_order. The tool returns the row id so the same
prediction can later be linked to its filled order_id if needed.

SAFE — pure write to a local audit table. No network, no order
placement.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult, ToolTier


class PolymarketLogPredictionTool(BaseTool):
    """Log a prediction-with-probability before placing the order."""

    @property
    def group(self) -> str:
        return "polymarket"

    def __init__(self) -> None:
        self._db: Any = None

    @property
    def name(self) -> str:
        return "polymarket_log_prediction"

    @property
    def description(self) -> str:
        return (
            "Log the bot's stated probability for a Polymarket market "
            "BEFORE placing the order. Required input for the "
            "calibration audit (use polymarket_calibration to read "
            "back). Pass the same llm_prob you fed to "
            "polymarket_pre_trade. Returns {prediction_id} on success."
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
                "token_id": {
                    "type": "string",
                    "description": "CTF token id we're betting on (the YES or NO token).",
                },
                "side": {
                    "type": "string",
                    "enum": ["YES", "NO"],
                    "description": "Which side this prediction takes.",
                },
                "entry_price": {
                    "type": "number",
                    "description": (
                        "Price you pay for one share, 0–1. The implied "
                        "market probability of the side you're taking."
                    ),
                },
                "size": {
                    "type": "number",
                    "description": "Number of shares (intended position size).",
                },
                "llm_prob": {
                    "type": "number",
                    "description": (
                        "LLM's probability that YES wins (NOT the side "
                        "you're taking — always YES-frame, 0–1). The "
                        "calibration tool re-frames internally."
                    ),
                },
                "confidence_band": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": (
                        "Confidence band used by the edge filter "
                        "(matches polymarket_pre_trade input)."
                    ),
                },
                "kelly_fraction": {
                    "type": "number",
                    "description": ("Kelly fraction used for sizing (optional)."),
                },
                "order_type": {
                    "type": "string",
                    "description": (
                        "GTC / GTD / FOK / FAK / post-only — used "
                        "later to compute maker fill rate."
                    ),
                },
                "market_slug": {
                    "type": "string",
                    "description": ("Polymarket event slug (for resolution lookup)."),
                },
                "rationale": {
                    "type": "string",
                    "description": "One-line LLM rationale (for audit).",
                },
                "live": {
                    "type": "boolean",
                    "description": (
                        "True (default) = real bet with capital at risk. "
                        "False = SHADOW prediction (paper bet for "
                        "calibration data — no order placed, just "
                        "logging your probability estimate to be resolved "
                        "later via Gamma API). Shadow predictions let "
                        "calibration accumulate in days instead of months "
                        "and carry zero financial risk. Used by the "
                        "shadow-prediction cron loop. See SKILL §8c."
                    ),
                },
            },
            "required": [
                "token_id",
                "side",
                "entry_price",
                "llm_prob",
            ],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._db is None:
            return ToolResult(success=False, error="db not injected")

        side = (params.get("side") or "").upper()
        if side not in ("YES", "NO"):
            return ToolResult(
                success=False, error=f"side must be YES or NO, got {side!r}"
            )

        # Shadow predictions don't need size (no real bet placed) and
        # default to 0. Live predictions still require it via the
        # warning path below.
        live = bool(params.get("live", True))
        kind = "live" if live else "shadow"
        try:
            entry_price = float(params["entry_price"])
            size = float(params.get("size") or 0.0)
            llm_prob = float(params["llm_prob"])
        except (KeyError, TypeError, ValueError) as e:
            return ToolResult(success=False, error=f"bad numeric input: {e}")

        if not 0 <= entry_price <= 1:
            return ToolResult(
                success=False,
                error=f"entry_price must be in [0, 1], got {entry_price}",
            )
        if not 0 <= llm_prob <= 1:
            return ToolResult(
                success=False, error=f"llm_prob must be in [0, 1], got {llm_prob}"
            )

        confidence_band = (params.get("confidence_band") or "medium").lower()
        if confidence_band not in ("high", "medium", "low"):
            confidence_band = "medium"

        kelly_fraction = params.get("kelly_fraction")
        if kelly_fraction is not None:
            try:
                kelly_fraction = float(kelly_fraction)
            except (TypeError, ValueError):
                kelly_fraction = None

        # Sanity warning: LIVE prediction with a non-trivial size but
        # no Kelly fraction. The calibration audit later can't assess
        # "was my sizing strategy good?" without the kelly_fraction at
        # entry — that whole dimension goes dead. Shadow predictions
        # skip this check because they don't represent capital at risk.
        warning: str | None = None
        if live and size >= 1.0 and (kelly_fraction is None or kelly_fraction == 0.0):
            warning = (
                "kelly_fraction missing or zero on a non-trivial size — "
                "calibration audit won't be able to assess sizing strategy "
                "for this trade later. Call polymarket_safe_compounder "
                "BEFORE log_prediction and thread its returned kelly_fraction "
                "in. See SKILL.md §8a."
            )

        now = datetime.now(UTC).isoformat()
        row_id = await self._db.execute_insert(
            """INSERT INTO polymarket_predictions
               (market_slug, token_id, side, entry_price, size, llm_prob,
                confidence_band, kelly_fraction, order_type, rationale,
                created_at, kind)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(params.get("market_slug") or ""),
                str(params["token_id"]),
                side,
                entry_price,
                size,
                llm_prob,
                confidence_band,
                kelly_fraction,
                str(params.get("order_type") or "GTC"),
                str(params.get("rationale") or "")[:500],
                now,
                kind,
            ),
        )

        data: dict[str, Any] = {
            "prediction_id": row_id,
            "logged_at": now,
            "side": side,
            "entry_price": entry_price,
            "llm_prob": llm_prob,
            "kind": kind,
        }
        if warning:
            data["warning"] = warning
        return ToolResult(success=True, data=data)
