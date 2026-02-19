"""LocalWalletProvider tests — account lifecycle, balance, transfers."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_vault(stored_key: str | None = None) -> MagicMock:
    """Create a mock vault, optionally with a stored private key."""
    v = MagicMock()
    v.get.side_effect = lambda k: {
        "local_wallet_private_key": stored_key,
    }.get(k)
    return v


def _rpc_response(result: str) -> MagicMock:
    """Create a mock urllib response for a JSON-RPC result."""
    resp = MagicMock()
    resp.read.return_value = json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _rpc_responses(*results: str):
    """Return a side_effect function that yields sequential RPC responses."""
    call_count = [0]

    def side_effect(*args, **kwargs):
        resp = _rpc_response(results[call_count[0]])
        call_count[0] += 1
        return resp

    return side_effect


# ---------------------------------------------------------------------------
# Account lifecycle
# ---------------------------------------------------------------------------


class TestAccountLifecycle:
    @patch("core.payments.local_wallet.urllib.request.urlopen")
    def test_creates_new_account_when_vault_empty(self, _mock_urlopen: MagicMock) -> None:
        """New account generated and stored when vault has no key."""
        from core.payments.local_wallet import LocalWalletProvider

        vault = _mock_vault(stored_key=None)
        provider = LocalWalletProvider(vault=vault, chain="base")

        # Should have called vault.set for private key and address
        set_calls = {c[0][0]: c[0][1] for c in vault.set.call_args_list}
        assert "local_wallet_private_key" in set_calls
        assert "crypto_wallet_address" in set_calls
        assert provider.get_address().startswith("0x")
        assert len(provider.get_address()) == 42

    @patch("core.payments.local_wallet.urllib.request.urlopen")
    def test_loads_existing_account_from_vault(self, _mock_urlopen: MagicMock) -> None:
        """When vault has a key, the same address is loaded."""
        from eth_account import Account

        from core.payments.local_wallet import LocalWalletProvider

        acct = Account.create()
        vault = _mock_vault(stored_key=acct.key.hex())
        provider = LocalWalletProvider(vault=vault, chain="base")

        assert provider.get_address() == acct.address
        # Should NOT call vault.set (no new key generated)
        vault.set.assert_not_called()


# ---------------------------------------------------------------------------
# Wallet details
# ---------------------------------------------------------------------------


class TestWalletDetails:
    @patch("core.payments.local_wallet.urllib.request.urlopen")
    def test_get_wallet_details_shape(self, _mock_urlopen: MagicMock) -> None:
        from core.payments.local_wallet import LocalWalletProvider

        vault = _mock_vault()
        provider = LocalWalletProvider(vault=vault, chain="base")
        details = provider.get_wallet_details()

        assert "address" in details
        assert details["chain"] == "base"
        assert details["provider"] == "local"

    @patch("core.payments.local_wallet.urllib.request.urlopen")
    def test_get_address_matches_details(self, _mock_urlopen: MagicMock) -> None:
        from core.payments.local_wallet import LocalWalletProvider

        vault = _mock_vault()
        provider = LocalWalletProvider(vault=vault, chain="base")
        assert provider.get_address() == provider.get_wallet_details()["address"]


# ---------------------------------------------------------------------------
# Swap support
# ---------------------------------------------------------------------------


class TestSwapSupport:
    @patch("core.payments.local_wallet.urllib.request.urlopen")
    def test_supports_swap_returns_false(self, _mock_urlopen: MagicMock) -> None:
        from core.payments.local_wallet import LocalWalletProvider

        vault = _mock_vault()
        provider = LocalWalletProvider(vault=vault, chain="base")
        assert provider.supports_swap() is False


# ---------------------------------------------------------------------------
# Get balance
# ---------------------------------------------------------------------------


class TestGetBalance:
    @patch("core.payments.local_wallet.urllib.request.urlopen")
    def test_get_balance_parses_wei(self, mock_urlopen: MagicMock) -> None:
        """Parses hex wei from eth_getBalance into decimal ETH."""
        from core.payments.local_wallet import LocalWalletProvider

        vault = _mock_vault()
        provider = LocalWalletProvider(vault=vault, chain="base")

        # 1 ETH = 10^18 wei = 0xDE0B6B3A7640000
        mock_urlopen.return_value = _rpc_response("0xDE0B6B3A7640000")
        balance = provider.get_balance()
        assert float(balance) == 1.0

    @patch("core.payments.local_wallet.urllib.request.urlopen")
    def test_get_balance_zero(self, mock_urlopen: MagicMock) -> None:
        from core.payments.local_wallet import LocalWalletProvider

        vault = _mock_vault()
        provider = LocalWalletProvider(vault=vault, chain="base")

        mock_urlopen.return_value = _rpc_response("0x0")
        balance = provider.get_balance()
        assert float(balance) == 0.0

    @patch("core.payments.local_wallet.urllib.request.urlopen")
    def test_get_erc20_balance(self, mock_urlopen: MagicMock) -> None:
        """Parses ERC-20 balance with correct decimals (USDC = 6)."""
        from core.payments.local_wallet import LocalWalletProvider

        vault = _mock_vault()
        provider = LocalWalletProvider(vault=vault, chain="base")

        # 100 USDC = 100 * 10^6 = 100000000 = 0x5F5E100
        mock_urlopen.return_value = _rpc_response(
            "0x0000000000000000000000000000000000000000000000000000000005F5E100"
        )
        usdc_addr = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
        balance = provider.get_erc20_balance(usdc_addr)
        assert float(balance) == 100.0


# ---------------------------------------------------------------------------
# Native transfer
# ---------------------------------------------------------------------------


class TestNativeTransfer:
    @patch("core.payments.local_wallet.urllib.request.urlopen")
    def test_native_transfer_returns_tx_hash(self, mock_urlopen: MagicMock) -> None:
        """Signs and sends native ETH transfer, returns tx hash."""
        from core.payments.local_wallet import LocalWalletProvider

        vault = _mock_vault()
        provider = LocalWalletProvider(vault=vault, chain="base")

        tx_hash = "0x" + "ab" * 32
        # Sequential RPC calls: eth_getTransactionCount, eth_gasPrice, eth_sendRawTransaction
        mock_urlopen.side_effect = _rpc_responses("0x5", "0x3B9ACA00", tx_hash)

        result = provider.native_transfer(to="0x" + "a" * 40, amount="0.001")
        assert result == tx_hash
        assert mock_urlopen.call_count == 3


# ---------------------------------------------------------------------------
# ERC-20 transfer
# ---------------------------------------------------------------------------


class TestERC20Transfer:
    @patch("core.payments.local_wallet.urllib.request.urlopen")
    def test_erc20_transfer_returns_tx_hash(self, mock_urlopen: MagicMock) -> None:
        """Signs and sends ERC-20 transfer, returns tx hash."""
        from core.payments.local_wallet import LocalWalletProvider

        vault = _mock_vault()
        provider = LocalWalletProvider(vault=vault, chain="base")

        tx_hash = "0x" + "cd" * 32
        # Sequential: nonce, gasPrice, estimateGas, sendRawTransaction
        mock_urlopen.side_effect = _rpc_responses("0x5", "0x3B9ACA00", "0x15F90", tx_hash)

        result = provider.transfer(to="0x" + "b" * 40, amount="50.0", token="USDC")
        assert result == tx_hash
        assert mock_urlopen.call_count == 4


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------


class TestTokenResolution:
    @patch("core.payments.local_wallet.urllib.request.urlopen")
    def test_known_token_resolves(self, _mock_urlopen: MagicMock) -> None:
        from core.payments.local_wallet import LocalWalletProvider

        vault = _mock_vault()
        provider = LocalWalletProvider(vault=vault, chain="base")
        addr = provider._get_token_address("USDC")
        assert addr.startswith("0x")

    @patch("core.payments.local_wallet.urllib.request.urlopen")
    def test_unknown_token_raises(self, _mock_urlopen: MagicMock) -> None:
        from core.payments.local_wallet import LocalWalletProvider

        vault = _mock_vault()
        provider = LocalWalletProvider(vault=vault, chain="base")
        with pytest.raises(ValueError, match="Unknown token"):
            provider._get_token_address("SHIBA")


# ---------------------------------------------------------------------------
# ABI encoding
# ---------------------------------------------------------------------------


class TestABIEncoding:
    @patch("core.payments.local_wallet.urllib.request.urlopen")
    def test_encode_address(self, _mock_urlopen: MagicMock) -> None:
        from core.payments.local_wallet import LocalWalletProvider

        result = LocalWalletProvider._encode_address("0x" + "a" * 40)
        assert len(result) == 64
        assert result == "0" * 24 + "a" * 40

    @patch("core.payments.local_wallet.urllib.request.urlopen")
    def test_encode_uint256(self, _mock_urlopen: MagicMock) -> None:
        from core.payments.local_wallet import LocalWalletProvider

        result = LocalWalletProvider._encode_uint256(100000000)  # 100 USDC
        assert len(result) == 64
        assert result == "0" * 56 + "05f5e100"


# ---------------------------------------------------------------------------
# RPC error handling
# ---------------------------------------------------------------------------


class TestRPCErrors:
    @patch("core.payments.local_wallet.urllib.request.urlopen")
    def test_rpc_error_raises(self, mock_urlopen: MagicMock) -> None:
        from core.payments.local_wallet import LocalWalletProvider

        vault = _mock_vault()
        provider = LocalWalletProvider(vault=vault, chain="base")

        resp = MagicMock()
        resp.read.return_value = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "insufficient funds"}}
        ).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        with pytest.raises(RuntimeError, match="insufficient funds"):
            provider.get_balance()


# ---------------------------------------------------------------------------
# Chain config
# ---------------------------------------------------------------------------


class TestChainConfig:
    @patch("core.payments.local_wallet.urllib.request.urlopen")
    def test_base_chain_defaults(self, _mock_urlopen: MagicMock) -> None:
        from core.payments.local_wallet import LocalWalletProvider

        vault = _mock_vault()
        provider = LocalWalletProvider(vault=vault, chain="base")
        assert provider._chain_id == 8453
        assert "mainnet.base.org" in provider._rpc_url

    @patch("core.payments.local_wallet.urllib.request.urlopen")
    def test_custom_rpc_url(self, _mock_urlopen: MagicMock) -> None:
        from core.payments.local_wallet import LocalWalletProvider

        vault = _mock_vault()
        provider = LocalWalletProvider(
            vault=vault, chain="base", rpc_url="https://my-rpc.example.com"
        )
        assert provider._rpc_url == "https://my-rpc.example.com"

    @patch("core.payments.local_wallet.urllib.request.urlopen")
    def test_base_sepolia(self, _mock_urlopen: MagicMock) -> None:
        from core.payments.local_wallet import LocalWalletProvider

        vault = _mock_vault()
        provider = LocalWalletProvider(vault=vault, chain="base-sepolia")
        assert provider._chain_id == 84532
        assert "sepolia.base.org" in provider._rpc_url
