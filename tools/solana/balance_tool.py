"""``solana_balance`` — fetch SOL + SPL token balances for a wallet.

Defaults to the agent's own wallet address (vault key
``solana_wallet_address``) so the daily review can ask
"how much is in our treasury?" without specifying anything.

SAFE — read-only RPC.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult
from tools.solana._client import (
    USDC_MINT,
    HeliusClient,
    HeliusError,
    lamports_to_sol,
)


class SolanaBalanceTool(BaseTool):
    """Read SOL + SPL token balances for a Solana wallet."""

    @property
    def group(self) -> str:
        return "solana"

    def __init__(self) -> None:
        self._vault: Any = None

    @property
    def name(self) -> str:
        return "solana_balance"

    @property
    def description(self) -> str:
        return (
            "Read SOL + SPL token balances for a Solana wallet via "
            "Helius. If `address` is omitted, defaults to the agent's "
            "own wallet (vault key `solana_wallet_address`). Returns "
            "{address, sol, usdc, tokens: [{mint, amount, decimals}]}. "
            "Read-only — use this for treasury awareness, daily review, "
            "and balance checks before considering a transfer."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": (
                        "Solana wallet address (base58). "
                        "Omit to use the agent's own wallet."
                    ),
                },
            },
            "required": [],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        address = params.get("address", "").strip()
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

        client = HeliusClient(self._vault)
        try:
            lamports = await client.get_balance(address)
            accounts = await client.get_token_accounts(address)
        except HeliusError as e:
            return ToolResult(success=False, error=str(e))

        tokens: list[dict[str, Any]] = []
        usdc_amount = 0.0
        for acct in accounts:
            try:
                info = acct["account"]["data"]["parsed"]["info"]
                mint = info["mint"]
                ta = info["tokenAmount"]
                amount = float(ta["uiAmount"] or 0.0)
                decimals = int(ta["decimals"])
            except (KeyError, TypeError, ValueError):
                continue
            if amount == 0.0:
                continue
            tokens.append({"mint": mint, "amount": amount, "decimals": decimals})
            if mint == USDC_MINT:
                usdc_amount = amount

        return ToolResult(
            success=True,
            data={
                "address": address,
                "sol": round(lamports_to_sol(lamports), 9),
                "usdc": usdc_amount,
                "tokens": tokens,
            },
        )
