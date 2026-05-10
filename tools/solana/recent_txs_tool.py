"""``solana_recent_txs`` — last N parsed transactions for a wallet.

Uses Helius Enhanced Transactions API to return human-readable tx
data (transfer amounts, swap legs, NFT mints, etc.) instead of raw
instructions. Default limit 10. SAFE — read-only.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult
from tools.solana._client import HeliusClient, HeliusError


class SolanaRecentTxsTool(BaseTool):
    """Recent parsed transactions for a Solana wallet."""

    @property
    def group(self) -> str:
        return "solana"

    def __init__(self) -> None:
        self._vault: Any = None

    @property
    def name(self) -> str:
        return "solana_recent_txs"

    @property
    def description(self) -> str:
        return (
            "Return recent parsed transactions for a Solana wallet "
            "(default the agent's own). Uses Helius Enhanced "
            "Transactions API so the result is human-readable: "
            "transfer amounts, swap legs, NFT mints, etc. Returns "
            "{address, count, transactions: [{signature, type, "
            "description, fee, timestamp, source}]}. Use this for "
            "wallet activity audits and the daily review."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": (
                        "Solana wallet address. Omit to use the " "agent's own wallet."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 10, max 100).",
                },
            },
            "required": [],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        address = (params.get("address") or "").strip()
        if not address:
            if not self._vault:
                return ToolResult(success=False, error="vault not available")
            address = self._vault.get("solana_wallet_address") or ""
            if not address:
                return ToolResult(
                    success=False,
                    error=(
                        "no address given and solana_wallet_address " "not set in vault"
                    ),
                )

        try:
            limit = max(1, min(100, int(params.get("limit", 10))))
        except (TypeError, ValueError):
            limit = 10

        client = HeliusClient(self._vault)
        try:
            sigs = await client.get_signatures(address, limit=limit)
            sig_strs = [s["signature"] for s in sigs if "signature" in s]
            parsed = await client.parsed_transactions(sig_strs)
        except HeliusError as e:
            return ToolResult(success=False, error=str(e))

        rows: list[dict[str, Any]] = []
        for tx in parsed:
            rows.append(
                {
                    "signature": tx.get("signature", ""),
                    "type": tx.get("type", ""),
                    "description": tx.get("description", "")[:300],
                    "fee": tx.get("fee", 0),
                    "timestamp": tx.get("timestamp", 0),
                    "source": tx.get("source", ""),
                }
            )

        return ToolResult(
            success=True,
            data={
                "address": address,
                "count": len(rows),
                "transactions": rows,
            },
        )
