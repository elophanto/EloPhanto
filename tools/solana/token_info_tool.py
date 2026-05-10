"""``solana_token_info`` — supply + metadata for a Solana SPL mint.

Combines getTokenSupply (RPC) with the DAS getAsset call so the agent
can ask "what do we know about this mint?" in one shot. SAFE.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult
from tools.solana._client import HeliusClient, HeliusError


class SolanaTokenInfoTool(BaseTool):
    """Supply + metadata for a Solana SPL token mint."""

    @property
    def group(self) -> str:
        return "solana"

    def __init__(self) -> None:
        self._vault: Any = None

    @property
    def name(self) -> str:
        return "solana_token_info"

    @property
    def description(self) -> str:
        return (
            "Read on-chain metadata + supply for a Solana SPL mint via "
            "Helius DAS API. Returns {mint, supply, decimals, name, "
            "symbol, image, description, authorities}. Use this to "
            "ground the daily review with real on-chain stats for the "
            "agent's own coin (or any other mint of interest)."
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
            asset = await client.das_get_asset(mint)
            supply_info = await client.get_token_supply(mint)
        except HeliusError as e:
            return ToolResult(success=False, error=str(e))

        # DAS shape — content.metadata for name/symbol, content.links for image.
        content = asset.get("content") or {}
        meta = content.get("metadata") or {}
        links = content.get("links") or {}
        authorities = [a.get("address") for a in (asset.get("authorities") or [])]

        try:
            decimals = int(supply_info.get("decimals", 0))
            supply = float(supply_info.get("uiAmountString") or 0.0)
        except (TypeError, ValueError):
            decimals = 0
            supply = 0.0

        return ToolResult(
            success=True,
            data={
                "mint": mint,
                "supply": supply,
                "decimals": decimals,
                "name": meta.get("name", ""),
                "symbol": meta.get("symbol", ""),
                "description": meta.get("description", "")[:500],
                "image": links.get("image", ""),
                "authorities": authorities,
            },
        )
