"""``polymarket_pre_trade`` — single mandatory gate before any place_order.

The agent calls this with: the LLM's estimated probability, the
market's current YES price, the LLM's self-reported confidence, plus
the market's tags + title. The tool returns a structured decision —
allow or block — plus the stop-loss / take-profit levels the caller
must place alongside the entry order on a successful pass.

This replaces the historical pattern of "the LLM had an opinion → run
``shell_execute`` with py-clob-client → place an order." The live
trade history showed that pattern losing money: avg BUY at $0.599,
SELL avg $0.864 (only winners get sold), no exits on losers, no edge
measurement, sports markets included. See zostaff/poly-trading-bot for
the borrowed risk-management beats and ``core/polymarket_engine.py``
for the math.

SAFE permission level — pure decision tool, no I/O. Pair with the
existing skill flow for the actual ``py-clob-client`` order placement.
"""

from __future__ import annotations

from typing import Any

from core.polymarket_engine import evaluate_pre_trade
from tools.base import BaseTool, PermissionLevel, ToolResult


class PolymarketPreTradeTool(BaseTool):
    """Pre-trade decision gate. Edge filter + skip-tag + stop-loss in one
    call so the agent has a single canonical place to ask 'should this
    trade ship?'."""

    @property
    def group(self) -> str:
        return "polymarket"

    def __init__(self) -> None:
        # Injected at agent startup — see Agent._inject_polymarket_deps.
        self._polymarket_config: Any = None

    @property
    def name(self) -> str:
        return "polymarket_pre_trade"

    @property
    def description(self) -> str:
        return (
            "Mandatory pre-trade decision gate for Polymarket orders. "
            "Combines edge filter (block trades where LLM probability "
            "is too close to market price), skip-tag filter (block "
            "sports / entertainment / awards markets — pure noise for "
            "LLM directional bets), and stop-loss/take-profit "
            "calculation. Call this BEFORE any place_order via "
            "py-clob-client. If `allow_trade` is true, place the "
            "entry AND immediately place companion limit orders at "
            "`stop_loss_price` and `take_profit_price`. If false, do "
            "not trade — `blockers` lists why."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "llm_prob": {
                    "type": "number",
                    "description": (
                        "LLM-estimated probability of YES outcome [0, 1]. "
                        "Inputs out of range are clamped, not rejected."
                    ),
                },
                "market_price": {
                    "type": "number",
                    "description": (
                        "Current YES price on the orderbook [0, 1]. "
                        "Use the lowest YES ask if buying YES, highest "
                        "YES bid if selling YES."
                    ),
                },
                "confidence": {
                    "type": "number",
                    "description": (
                        "LLM self-reported confidence [0, 1]. "
                        "Drives confidence-asymmetric edge thresholds — "
                        "uncertain bets need a bigger edge."
                    ),
                },
                "market_tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Polymarket parent-event tag slugs (e.g. "
                        "['sports', 'nfl']). Compared case-insensitively "
                        "against the skip list."
                    ),
                },
                "market_title": {
                    "type": "string",
                    "description": (
                        "Market question text. Substring-matched against "
                        "title-phrase blocklist (mention/say/wear/etc)."
                    ),
                },
            },
            "required": ["llm_prob", "market_price", "confidence"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        llm_prob = float(params.get("llm_prob", 0.0))
        market_price = float(params.get("market_price", 0.0))
        confidence = float(params.get("confidence", 0.0))
        market_tags = params.get("market_tags") or []
        market_title = str(params.get("market_title", ""))

        decision = evaluate_pre_trade(
            llm_prob=llm_prob,
            market_price=market_price,
            confidence=confidence,
            market_tags=market_tags,
            market_title=market_title,
            config=self._polymarket_config,
        )

        data: dict[str, Any] = {
            "allow_trade": decision.allow_trade,
            "blockers": decision.blockers,
            "edge": {
                "passes": decision.edge.passes,
                "edge": decision.edge.edge,
                "edge_abs": decision.edge.edge_abs,
                "threshold_used": decision.edge.threshold_used,
                "band": decision.edge.band,
                "side": decision.edge.side,
                "reason": decision.edge.reason,
            },
            "skip_tag": {
                "skip": decision.skip.skip,
                "reason": decision.skip.reason,
            },
        }
        if decision.stop_loss is not None:
            data["stop_loss"] = {
                "entry_price": decision.stop_loss.entry_price,
                "side": decision.stop_loss.side,
                "stop_loss_price": decision.stop_loss.stop_loss_price,
                "take_profit_price": decision.stop_loss.take_profit_price,
                "stop_loss_pct": decision.stop_loss.stop_loss_pct,
                "take_profit_pct": decision.stop_loss.take_profit_pct,
                "rationale": decision.stop_loss.rationale,
            }
        else:
            data["stop_loss"] = None

        return ToolResult(success=True, data=data)
