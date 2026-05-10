"""Thin async client for Helius RPC + DAS endpoints.

Single httpx.AsyncClient per call to keep the surface trivially mockable
in tests. The vault key is ``helius_api_key``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_RPC_URL = "https://mainnet.helius-rpc.com"
_API_BASE = "https://api.helius.xyz"
_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
_DEFAULT_TIMEOUT = 15.0


class HeliusError(Exception):
    """Raised on any Helius API failure (network, HTTP, RPC error code)."""


class HeliusClient:
    """Stateless Helius wrapper. Vault is consulted on each call so a
    rotated key is picked up without restart."""

    def __init__(self, vault: Any) -> None:
        self._vault = vault

    def _api_key(self) -> str:
        if not self._vault:
            raise HeliusError("vault not configured")
        key = self._vault.get("helius_api_key")
        if not key:
            raise HeliusError(
                "helius_api_key not found in vault. "
                "Run: vault_set helius_api_key=<key>"
            )
        return key

    async def rpc(self, method: str, params: list[Any]) -> Any:
        """Make a JSON-RPC call against Helius's mainnet endpoint."""
        api_key = self._api_key()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as c:
            r = await c.post(f"{_RPC_URL}/?api-key={api_key}", json=payload)
            if r.status_code != 200:
                raise HeliusError(f"rpc {method} HTTP {r.status_code}: {r.text[:200]}")
            data = r.json()
            if "error" in data:
                raise HeliusError(f"rpc {method} error: {data['error']}")
            return data.get("result")

    async def das_get_asset(self, mint: str) -> dict[str, Any]:
        """Fetch token/NFT metadata via the Digital Asset Standard API."""
        result = await self.rpc("getAsset", [mint])
        if not isinstance(result, dict):
            raise HeliusError(f"getAsset returned non-dict: {type(result).__name__}")
        return result

    async def get_balance(self, address: str) -> int:
        """Native SOL balance in lamports."""
        result = await self.rpc("getBalance", [address])
        if isinstance(result, dict) and "value" in result:
            return int(result["value"])
        raise HeliusError(f"getBalance returned unexpected shape: {result!r}")

    async def get_token_accounts(self, owner: str) -> list[dict[str, Any]]:
        """All SPL token accounts owned by a wallet."""
        result = await self.rpc(
            "getTokenAccountsByOwner",
            [
                owner,
                {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                {"encoding": "jsonParsed"},
            ],
        )
        if isinstance(result, dict) and "value" in result:
            return list(result["value"])
        raise HeliusError(
            f"getTokenAccountsByOwner returned unexpected shape: {result!r}"
        )

    async def get_token_largest_accounts(self, mint: str) -> list[dict[str, Any]]:
        """Top 20 holder accounts for a mint, by amount."""
        result = await self.rpc("getTokenLargestAccounts", [mint])
        if isinstance(result, dict) and "value" in result:
            return list(result["value"])
        raise HeliusError(
            f"getTokenLargestAccounts returned unexpected shape: {result!r}"
        )

    async def get_token_supply(self, mint: str) -> dict[str, Any]:
        """Total supply, decimals."""
        result = await self.rpc("getTokenSupply", [mint])
        if isinstance(result, dict) and "value" in result:
            return dict(result["value"])
        raise HeliusError(f"getTokenSupply returned unexpected shape: {result!r}")

    async def get_signatures(
        self, address: str, limit: int = 25
    ) -> list[dict[str, Any]]:
        """Recent confirmed signatures for a wallet."""
        result = await self.rpc("getSignaturesForAddress", [address, {"limit": limit}])
        if isinstance(result, list):
            return result
        raise HeliusError(
            f"getSignaturesForAddress returned unexpected shape: {result!r}"
        )

    async def parsed_transactions(self, signatures: list[str]) -> list[dict[str, Any]]:
        """Helius Enhanced Transactions: human-parsed tx data."""
        if not signatures:
            return []
        api_key = self._api_key()
        payload = {"transactions": signatures}
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as c:
            r = await c.post(
                f"{_API_BASE}/v0/transactions/?api-key={api_key}",
                json=payload,
            )
            if r.status_code != 200:
                raise HeliusError(
                    f"parsed_transactions HTTP {r.status_code}: {r.text[:200]}"
                )
            data = r.json()
            if isinstance(data, list):
                return data
            raise HeliusError(
                f"parsed_transactions returned non-list: {type(data).__name__}"
            )


def lamports_to_sol(lamports: int) -> float:
    """1 SOL = 10^9 lamports."""
    return lamports / 1_000_000_000


USDC_MINT = _USDC_MINT
