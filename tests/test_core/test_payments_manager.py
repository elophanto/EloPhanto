"""PaymentsManager tests — wallet lifecycle, balance, transfer, limits, validation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import PaymentsConfig
from core.database import Database
from core.payments.manager import PaymentsError, PaymentsManager


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def vault() -> MagicMock:
    v = MagicMock()
    v.get.return_value = None
    return v


@pytest.fixture
def config() -> PaymentsConfig:
    cfg = PaymentsConfig(enabled=True)
    cfg.crypto.enabled = True
    cfg.crypto.provider = "local"
    return cfg


@pytest.fixture
def manager(db: Database, config: PaymentsConfig, vault: MagicMock) -> PaymentsManager:
    return PaymentsManager(db=db, config=config, vault=vault)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInitialize:
    @pytest.mark.asyncio
    async def test_init_disabled(self, db: Database, vault: MagicMock) -> None:
        cfg = PaymentsConfig(enabled=True)
        cfg.crypto.enabled = False
        mgr = PaymentsManager(db=db, config=cfg, vault=vault)
        await mgr.initialize()
        assert mgr.wallet_address == ""

    @pytest.mark.asyncio
    async def test_init_no_vault(self, db: Database) -> None:
        cfg = PaymentsConfig(enabled=True)
        cfg.crypto.enabled = True
        mgr = PaymentsManager(db=db, config=cfg, vault=None)
        await mgr.initialize()
        assert mgr.wallet_address == ""

    @pytest.mark.asyncio
    async def test_reconnect_from_stored_address(
        self, db: Database, config: PaymentsConfig
    ) -> None:
        vault = MagicMock()
        vault.get.return_value = "0x" + "a" * 40
        mgr = PaymentsManager(db=db, config=config, vault=vault)
        await mgr.initialize()
        assert mgr.wallet_address == "0x" + "a" * 40

    @pytest.mark.asyncio
    async def test_auto_create_calls_create_wallet(self, manager: PaymentsManager) -> None:
        with patch.object(manager, "create_wallet", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = "0x" + "b" * 40
            await manager.initialize()
            mock_create.assert_called_once()


# ---------------------------------------------------------------------------
# Provider routing
# ---------------------------------------------------------------------------


class TestProviderRouting:
    @pytest.mark.asyncio
    async def test_local_provider_initialized(self, db: Database, vault: MagicMock) -> None:
        cfg = PaymentsConfig(enabled=True)
        cfg.crypto.enabled = True
        cfg.crypto.provider = "local"
        mgr = PaymentsManager(db=db, config=cfg, vault=vault)

        mock_instance = MagicMock()
        mock_instance.get_wallet_details.return_value = {
            "address": "0x" + "c" * 40,
        }
        # Patch where _init_local_provider imports LocalWalletProvider
        with patch(
            "core.payments.local_wallet.LocalWalletProvider",
            return_value=mock_instance,
        ):
            provider = await mgr._get_wallet_provider()
            assert provider is mock_instance

    @pytest.mark.asyncio
    async def test_cdp_provider_requires_credentials(self, db: Database, vault: MagicMock) -> None:
        cfg = PaymentsConfig(enabled=True)
        cfg.crypto.enabled = True
        cfg.crypto.provider = "agentkit"
        vault.get.return_value = None
        mgr = PaymentsManager(db=db, config=cfg, vault=vault)

        with pytest.raises(PaymentsError, match="CDP API credentials"):
            await mgr._get_wallet_provider()

    @pytest.mark.asyncio
    async def test_unknown_provider_raises(self, db: Database, vault: MagicMock) -> None:
        cfg = PaymentsConfig(enabled=True)
        cfg.crypto.enabled = True
        cfg.crypto.provider = "unknown_provider"
        mgr = PaymentsManager(db=db, config=cfg, vault=vault)

        with pytest.raises(PaymentsError, match="Unknown crypto provider"):
            await mgr._get_wallet_provider()

    @pytest.mark.asyncio
    async def test_cached_provider_returned(self, manager: PaymentsManager) -> None:
        mock_provider = MagicMock()
        manager._wallet_provider = mock_provider
        provider = await manager._get_wallet_provider()
        assert provider is mock_provider


# ---------------------------------------------------------------------------
# Address validation
# ---------------------------------------------------------------------------


class TestValidateAddress:
    def test_valid_evm_address(self, manager: PaymentsManager) -> None:
        assert manager.validate_address("0x" + "a" * 40, "base") is True
        assert manager.validate_address("0x" + "1234abcdef" * 4, "ethereum") is True

    def test_invalid_evm_address(self, manager: PaymentsManager) -> None:
        assert manager.validate_address("0x123", "base") is False
        assert manager.validate_address("not_an_address", "ethereum") is False
        assert manager.validate_address("", "base") is False

    def test_valid_solana_address(self, manager: PaymentsManager) -> None:
        solana_addr = "DRtXHDgC312wpNdNCSb8vCoXDcD4Vn73GUjCqhSiN3Sn"
        assert manager.validate_address(solana_addr, "solana") is True

    def test_invalid_solana_address(self, manager: PaymentsManager) -> None:
        assert manager.validate_address("0x" + "a" * 40, "solana") is False
        assert manager.validate_address("", "solana") is False

    def test_unknown_chain(self, manager: PaymentsManager) -> None:
        assert manager.validate_address("anything", "bitcoin") is False


# ---------------------------------------------------------------------------
# Approval tiers
# ---------------------------------------------------------------------------


class TestApprovalTier:
    def test_standard(self, manager: PaymentsManager) -> None:
        assert manager.get_approval_tier(5.0) == "standard"

    def test_always_ask(self, manager: PaymentsManager) -> None:
        assert manager.get_approval_tier(50.0) == "always_ask"

    def test_confirm(self, manager: PaymentsManager) -> None:
        assert manager.get_approval_tier(500.0) == "confirm"

    def test_cooldown(self, manager: PaymentsManager) -> None:
        assert manager.get_approval_tier(2000.0) == "cooldown"


# ---------------------------------------------------------------------------
# Transfer — limit enforcement
# ---------------------------------------------------------------------------


class TestTransfer:
    @pytest.mark.asyncio
    async def test_invalid_address_rejects(self, manager: PaymentsManager) -> None:
        with pytest.raises(PaymentsError, match="Invalid address"):
            await manager.transfer(to="not_valid", amount=10.0, token="USDC")

    @pytest.mark.asyncio
    async def test_exceeds_per_txn_limit(self, manager: PaymentsManager) -> None:
        with pytest.raises(PaymentsError, match="Spending limit"):
            await manager.transfer(to="0x" + "a" * 40, amount=200.0, token="USDC")

    @pytest.mark.asyncio
    async def test_transfer_success(self, manager: PaymentsManager, vault: MagicMock) -> None:
        # Mock the wallet provider directly
        mock_provider = MagicMock()
        mock_provider.transfer.return_value = "0xtxhash123"
        manager._wallet_provider = mock_provider

        result = await manager.transfer(to="0x" + "a" * 40, amount=10.0, token="USDC")
        assert result["success"] is True
        assert result["tx_hash"] == "0xtxhash123"
        assert result["amount"] == 10.0
        mock_provider.transfer.assert_called_once()


# ---------------------------------------------------------------------------
# Swap — limit enforcement + local provider rejection
# ---------------------------------------------------------------------------


class TestSwap:
    @pytest.mark.asyncio
    async def test_swap_rejected_with_local_provider(self, manager: PaymentsManager) -> None:
        """Local provider does not support swaps."""
        mock_provider = MagicMock()
        mock_provider.supports_swap.return_value = False
        manager._wallet_provider = mock_provider

        with pytest.raises(PaymentsError, match="not supported with the local wallet"):
            await manager.swap(from_token="ETH", to_token="USDC", amount=10.0)

    @pytest.mark.asyncio
    async def test_swap_allowed_with_cdp_provider(self, db: Database, vault: MagicMock) -> None:
        """CDP provider supports swaps — limit check proceeds."""
        cfg = PaymentsConfig(enabled=True)
        cfg.crypto.enabled = True
        cfg.crypto.provider = "agentkit"
        mgr = PaymentsManager(db=db, config=cfg, vault=vault)

        # Mock provider that supports swap but will hit spending limit
        mock_provider = MagicMock()
        mock_provider.supports_swap.return_value = True
        mgr._wallet_provider = mock_provider

        with pytest.raises(PaymentsError, match="Spending limit"):
            await mgr.swap(from_token="ETH", to_token="USDC", amount=200.0)

    @pytest.mark.asyncio
    async def test_exceeds_per_txn_limit(self, manager: PaymentsManager) -> None:
        """Swap spending limit check (provider that supports swaps)."""
        mock_provider = MagicMock()
        mock_provider.supports_swap.return_value = True
        manager._wallet_provider = mock_provider

        with pytest.raises(PaymentsError, match="Spending limit"):
            await manager.swap(from_token="ETH", to_token="USDC", amount=200.0)


# ---------------------------------------------------------------------------
# Swap price — local provider
# ---------------------------------------------------------------------------


class TestSwapPrice:
    @pytest.mark.asyncio
    async def test_swap_price_unavailable_local(self, manager: PaymentsManager) -> None:
        mock_provider = MagicMock()
        mock_provider.supports_swap.return_value = False
        manager._wallet_provider = mock_provider

        result = await manager.get_swap_price("ETH", "USDC", 1.0)
        assert "error" in result
        assert "local wallet" in result["error"]


# ---------------------------------------------------------------------------
# Wallet details
# ---------------------------------------------------------------------------


class TestWalletDetails:
    @pytest.mark.asyncio
    async def test_details_no_wallet(self, manager: PaymentsManager) -> None:
        details = await manager.get_wallet_details()
        assert details["address"] == ""
        assert details["chain"] == "base"
        assert details["daily_spent"] == 0.0
        assert details["monthly_spent"] == 0.0

    @pytest.mark.asyncio
    async def test_details_with_address(self, manager: PaymentsManager) -> None:
        manager._wallet_address = "0x" + "a" * 40
        # Without provider, balance will error but details still return
        details = await manager.get_wallet_details()
        assert details["address"] == "0x" + "a" * 40
        assert "balance_error" in details or "balance" in details
