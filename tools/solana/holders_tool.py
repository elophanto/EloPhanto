"""``solana_token_holders`` — top holders + concentration for a mint.

Use this for the daily review's "how is our coin doing?" angle:
top-N holder concentration is a signal for both legitimacy
(too-concentrated → red flag) and growth (more wallets above a
threshold over time).

SAFE — read-only.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult
from tools.solana._client import HeliusClient, HeliusError


class SolanaTokenHoldersTool(BaseTool):
    """Top-20 holders for a Solana SPL token mint."""

    @property
    def group(self) -> str:
        return "solana"

    def __init__(self) -> None:
        self._vault: Any = None

    @property
    def name(self) -> str:
        return "solana_token_holders"

    @property
    def description(self) -> str:
        return (
            "List the top 20 holder accounts for a Solana SPL mint, with "
            "amounts and concentration percentages. Returns "
            "{mint, supply, decimals, top_holders: [{rank, address, "
            "amount, pct_of_supply}], top10_concentration_pct}. "
            "High top-10 concentration (>50%) is a red flag for "
            "manipulation; growing holder count over time is a "
            "growth signal."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mint": {
                    "type": "string",
                    "description": "SPL token mint address (base58).",
                },
            },
            "required": ["mint"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        mint = (params.get("mint") or "").strip()
        if not mint:
            return ToolResult(success=False, error="mint is required")

        client = HeliusClient(self._vault)
        try:
            supply_info = await client.get_token_supply(mint)
            largest = await client.get_token_largest_accounts(mint)
        except HeliusError as e:
            return ToolResult(success=False, error=str(e))

        try:
            decimals = int(supply_info.get("decimals", 0))
            supply = float(supply_info.get("uiAmountString") or 0.0)
        except (TypeError, ValueError):
            return ToolResult(
                success=False, error=f"unexpected supply payload: {supply_info!r}"
            )

        top_holders: list[dict[str, Any]] = []
        top10_amount = 0.0
        for i, h in enumerate(largest[:20], start=1):
            try:
                addr = h["address"]
                amount = float(h.get("uiAmount") or 0.0)
            except (KeyError, TypeError, ValueError):
                continue
            pct = (amount / supply * 100.0) if supply > 0 else 0.0
            top_holders.append(
                {
                    "rank": i,
                    "address": addr,
                    "amount": amount,
                    "pct_of_supply": round(pct, 4),
                }
            )
            if i <= 10:
                top10_amount += amount

        top10_pct = (top10_amount / supply * 100.0) if supply > 0 else 0.0

        return ToolResult(
            success=True,
            data={
                "mint": mint,
                "supply": supply,
                "decimals": decimals,
                "top_holders": top_holders,
                "top10_concentration_pct": round(top10_pct, 4),
            },
        )
