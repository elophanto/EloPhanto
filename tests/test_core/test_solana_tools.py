"""Solana on-chain read tool tests.

Mocks HeliusClient at the tool boundary so no network calls happen.
Pins the vault-default-address path, the parsing of common shapes,
and the failure paths for missing keys / RPC errors.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tools.solana._client import HeliusError, lamports_to_sol
from tools.solana.balance_tool import SolanaBalanceTool
from tools.solana.holders_tool import SolanaTokenHoldersTool
from tools.solana.recent_txs_tool import SolanaRecentTxsTool
from tools.solana.token_info_tool import SolanaTokenInfoTool


class FakeVault:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    def get(self, key: str) -> str:
        return self._store.get(key, "")


# ---------------------------------------------------------------------------
# _client helpers
# ---------------------------------------------------------------------------


def test_lamports_to_sol() -> None:
    assert lamports_to_sol(0) == 0.0
    assert lamports_to_sol(1_000_000_000) == 1.0
    assert lamports_to_sol(500_000_000) == 0.5


# ---------------------------------------------------------------------------
# solana_balance
# ---------------------------------------------------------------------------


class TestSolanaBalanceTool:
    @pytest.mark.asyncio
    async def test_uses_vault_default_address(self) -> None:
        tool = SolanaBalanceTool()
        tool._vault = FakeVault(
            {"helius_api_key": "k", "solana_wallet_address": "AGENTWALLET"}
        )

        with (
            patch(
                "tools.solana.balance_tool.HeliusClient.get_balance",
                new=AsyncMock(return_value=1_500_000_000),
            ),
            patch(
                "tools.solana.balance_tool.HeliusClient.get_token_accounts",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await tool.execute({})
        assert result.success
        assert result.data["address"] == "AGENTWALLET"
        assert result.data["sol"] == 1.5
        assert result.data["usdc"] == 0.0
        assert result.data["tokens"] == []

    @pytest.mark.asyncio
    async def test_explicit_address_wins_over_vault(self) -> None:
        tool = SolanaBalanceTool()
        tool._vault = FakeVault(
            {"helius_api_key": "k", "solana_wallet_address": "AGENT"}
        )
        with (
            patch(
                "tools.solana.balance_tool.HeliusClient.get_balance",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "tools.solana.balance_tool.HeliusClient.get_token_accounts",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await tool.execute({"address": "OTHER"})
        assert result.success
        assert result.data["address"] == "OTHER"

    @pytest.mark.asyncio
    async def test_picks_usdc_balance_out(self) -> None:
        tool = SolanaBalanceTool()
        tool._vault = FakeVault(
            {"helius_api_key": "k", "solana_wallet_address": "AGENT"}
        )
        accounts = [
            {
                "account": {
                    "data": {
                        "parsed": {
                            "info": {
                                "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                                "tokenAmount": {
                                    "uiAmount": 285.5,
                                    "decimals": 6,
                                },
                            }
                        }
                    }
                }
            },
            {
                "account": {
                    "data": {
                        "parsed": {
                            "info": {
                                "mint": "OTHER_MINT",
                                "tokenAmount": {"uiAmount": 1000.0, "decimals": 9},
                            }
                        }
                    }
                }
            },
            {  # zero-amount account is filtered
                "account": {
                    "data": {
                        "parsed": {
                            "info": {
                                "mint": "EMPTY",
                                "tokenAmount": {"uiAmount": 0, "decimals": 9},
                            }
                        }
                    }
                }
            },
        ]
        with (
            patch(
                "tools.solana.balance_tool.HeliusClient.get_balance",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "tools.solana.balance_tool.HeliusClient.get_token_accounts",
                new=AsyncMock(return_value=accounts),
            ),
        ):
            result = await tool.execute({})
        assert result.success
        assert result.data["usdc"] == 285.5
        mints = [t["mint"] for t in result.data["tokens"]]
        assert "EMPTY" not in mints
        assert len(result.data["tokens"]) == 2

    @pytest.mark.asyncio
    async def test_no_address_anywhere_errors_cleanly(self) -> None:
        tool = SolanaBalanceTool()
        tool._vault = FakeVault({"helius_api_key": "k"})
        result = await tool.execute({})
        assert not result.success
        assert "solana_wallet_address" in (result.error or "")

    @pytest.mark.asyncio
    async def test_helius_error_surfaces_cleanly(self) -> None:
        tool = SolanaBalanceTool()
        tool._vault = FakeVault({"helius_api_key": "k", "solana_wallet_address": "X"})
        with patch(
            "tools.solana.balance_tool.HeliusClient.get_balance",
            new=AsyncMock(side_effect=HeliusError("rpc 500")),
        ):
            result = await tool.execute({})
        assert not result.success
        assert "rpc 500" in (result.error or "")


# ---------------------------------------------------------------------------
# solana_token_holders
# ---------------------------------------------------------------------------


class TestSolanaTokenHoldersTool:
    @pytest.mark.asyncio
    async def test_top10_concentration_computed(self) -> None:
        tool = SolanaTokenHoldersTool()
        tool._vault = FakeVault({"helius_api_key": "k"})
        # Supply 1000, top 10 hold 600 → 60% concentration.
        accounts = [{"address": f"A{i}", "uiAmount": 60.0} for i in range(15)]
        with (
            patch(
                "tools.solana.holders_tool.HeliusClient.get_token_supply",
                new=AsyncMock(return_value={"uiAmountString": "1000.0", "decimals": 6}),
            ),
            patch(
                "tools.solana.holders_tool.HeliusClient.get_token_largest_accounts",
                new=AsyncMock(return_value=accounts),
            ),
        ):
            result = await tool.execute({"mint": "MINT"})
        assert result.success
        assert result.data["supply"] == 1000.0
        assert result.data["top10_concentration_pct"] == 60.0
        assert len(result.data["top_holders"]) == 15

    @pytest.mark.asyncio
    async def test_zero_supply_doesnt_crash(self) -> None:
        tool = SolanaTokenHoldersTool()
        tool._vault = FakeVault({"helius_api_key": "k"})
        with (
            patch(
                "tools.solana.holders_tool.HeliusClient.get_token_supply",
                new=AsyncMock(return_value={"uiAmountString": "0", "decimals": 6}),
            ),
            patch(
                "tools.solana.holders_tool.HeliusClient.get_token_largest_accounts",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await tool.execute({"mint": "MINT"})
        assert result.success
        assert result.data["top10_concentration_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_missing_mint_errors(self) -> None:
        tool = SolanaTokenHoldersTool()
        result = await tool.execute({})
        assert not result.success


# ---------------------------------------------------------------------------
# solana_recent_txs
# ---------------------------------------------------------------------------


class TestSolanaRecentTxsTool:
    @pytest.mark.asyncio
    async def test_clamps_limit(self) -> None:
        tool = SolanaRecentTxsTool()
        tool._vault = FakeVault({"helius_api_key": "k", "solana_wallet_address": "X"})
        captured: dict[str, Any] = {}

        async def fake_get_signatures(
            self: Any, addr: str, limit: int = 25
        ) -> list[dict[str, Any]]:
            captured["limit"] = limit
            return []

        async def fake_parsed(self: Any, signatures: list[str]) -> list[dict[str, Any]]:
            return []

        with (
            patch(
                "tools.solana.recent_txs_tool.HeliusClient.get_signatures",
                new=fake_get_signatures,
            ),
            patch(
                "tools.solana.recent_txs_tool.HeliusClient.parsed_transactions",
                new=fake_parsed,
            ),
        ):
            await tool.execute({"limit": 9999})
            assert captured["limit"] == 100
            await tool.execute({"limit": -5})
            assert captured["limit"] == 1

    @pytest.mark.asyncio
    async def test_shape_of_returned_rows(self) -> None:
        tool = SolanaRecentTxsTool()
        tool._vault = FakeVault({"helius_api_key": "k", "solana_wallet_address": "X"})
        with (
            patch(
                "tools.solana.recent_txs_tool.HeliusClient.get_signatures",
                new=AsyncMock(return_value=[{"signature": "sig1"}]),
            ),
            patch(
                "tools.solana.recent_txs_tool.HeliusClient.parsed_transactions",
                new=AsyncMock(
                    return_value=[
                        {
                            "signature": "sig1",
                            "type": "TRANSFER",
                            "description": "Wallet X transferred 1 SOL to Y",
                            "fee": 5000,
                            "timestamp": 1_700_000_000,
                            "source": "SYSTEM_PROGRAM",
                        }
                    ]
                ),
            ),
        ):
            result = await tool.execute({"limit": 5})
        assert result.success
        assert result.data["count"] == 1
        row = result.data["transactions"][0]
        assert row["signature"] == "sig1"
        assert row["type"] == "TRANSFER"


# ---------------------------------------------------------------------------
# solana_token_info
# ---------------------------------------------------------------------------


class TestSolanaTokenInfoTool:
    @pytest.mark.asyncio
    async def test_extracts_metadata_shape(self) -> None:
        tool = SolanaTokenInfoTool()
        tool._vault = FakeVault({"helius_api_key": "k"})
        asset = {
            "content": {
                "metadata": {
                    "name": "ELO",
                    "symbol": "ELO",
                    "description": "EloPhanto agent native currency",
                },
                "links": {"image": "https://example/image.png"},
            },
            "authorities": [{"address": "AUTH1"}, {"address": "AUTH2"}],
        }
        with (
            patch(
                "tools.solana.token_info_tool.HeliusClient.das_get_asset",
                new=AsyncMock(return_value=asset),
            ),
            patch(
                "tools.solana.token_info_tool.HeliusClient.get_token_supply",
                new=AsyncMock(
                    return_value={
                        "uiAmountString": "1000000000.0",
                        "decimals": 6,
                    }
                ),
            ),
        ):
            result = await tool.execute({"mint": "MINT"})
        assert result.success
        assert result.data["name"] == "ELO"
        assert result.data["symbol"] == "ELO"
        assert result.data["supply"] == 1_000_000_000.0
        assert result.data["decimals"] == 6
        assert result.data["authorities"] == ["AUTH1", "AUTH2"]
