"""Payment tool tests — interface compliance and execution paths."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tools.base import PermissionLevel
from tools.payments.balance_tool import PaymentBalanceTool
from tools.payments.history_tool import PaymentHistoryTool
from tools.payments.preview_tool import PaymentPreviewTool
from tools.payments.swap_tool import CryptoSwapTool
from tools.payments.transfer_tool import CryptoTransferTool
from tools.payments.validate_tool import PaymentValidateTool
from tools.payments.wallet_status_tool import WalletStatusTool

ALL_TOOL_CLASSES = [
    WalletStatusTool,
    PaymentBalanceTool,
    PaymentValidateTool,
    PaymentPreviewTool,
    CryptoTransferTool,
    CryptoSwapTool,
    PaymentHistoryTool,
]


def _mock_payments_manager() -> AsyncMock:
    mgr = AsyncMock()
    mgr.chain = "base"
    mgr.wallet_address = "0x" + "a" * 40
    mgr.get_wallet_details.return_value = {
        "address": "0x" + "a" * 40,
        "chain": "base",
        "balance": {"token": "USDC", "amount": "100.0"},
        "daily_spent": 50.0,
        "monthly_spent": 200.0,
        "daily_limit": 500.0,
        "monthly_limit": 5000.0,
    }
    mgr.get_balance.return_value = {"token": "USDC", "amount": "100.0", "chain": "base"}
    mgr.validate_address = MagicMock(return_value=True)
    mgr.get_approval_tier = MagicMock(return_value="standard")
    mgr.transfer.return_value = {
        "success": True,
        "tx_hash": "0xtxhash",
        "amount": 10.0,
        "token": "USDC",
        "to": "0x" + "b" * 40,
        "chain": "base",
    }
    mgr.swap.return_value = {
        "success": True,
        "tx_hash": "0xswaphash",
        "from_token": "ETH",
        "to_token": "USDC",
        "amount": 0.1,
        "chain": "base",
    }
    mgr.get_swap_price.return_value = {
        "from_token": "ETH",
        "to_token": "USDC",
        "amount": 0.1,
        "quote": "250.0",
        "chain": "base",
    }

    # Auditor for history tool
    auditor = AsyncMock()
    auditor.get_history.return_value = [
        {"id": 1, "amount": 10.0, "status": "executed"},
    ]
    auditor.get_daily_total.return_value = 50.0
    auditor.get_monthly_total.return_value = 200.0
    mgr.auditor = auditor

    # Limiter for preview tool
    from core.payments.limits import SpendingCheck

    limiter = AsyncMock()
    limiter.check.return_value = SpendingCheck(allowed=True, daily_spent=50.0, monthly_spent=200.0)
    mgr.limiter = limiter

    # Config for preview/history
    class _FakeLimitsConfig:
        daily = 500.0
        monthly = 5000.0

    mgr._config = AsyncMock()
    mgr._config.limits = _FakeLimitsConfig()

    return mgr


# ---------------------------------------------------------------------------
# Interface compliance — all 7 tools
# ---------------------------------------------------------------------------


class TestToolInterface:
    @pytest.mark.parametrize("tool_cls", ALL_TOOL_CLASSES)
    def test_has_required_properties(self, tool_cls: type) -> None:
        t = tool_cls()
        assert isinstance(t.name, str) and len(t.name) > 0
        assert isinstance(t.description, str) and len(t.description) > 10
        assert t.input_schema["type"] == "object"
        assert isinstance(t.permission_level, PermissionLevel)

    @pytest.mark.parametrize("tool_cls", ALL_TOOL_CLASSES)
    def test_llm_schema_format(self, tool_cls: type) -> None:
        t = tool_cls()
        schema = t.to_llm_schema()
        assert schema["type"] == "function"
        assert "function" in schema
        assert "name" in schema["function"]
        assert "parameters" in schema["function"]

    def test_permission_levels(self) -> None:
        assert WalletStatusTool().permission_level == PermissionLevel.SAFE
        assert PaymentBalanceTool().permission_level == PermissionLevel.SAFE
        assert PaymentValidateTool().permission_level == PermissionLevel.SAFE
        assert PaymentPreviewTool().permission_level == PermissionLevel.SAFE
        assert CryptoTransferTool().permission_level == PermissionLevel.CRITICAL
        assert CryptoSwapTool().permission_level == PermissionLevel.CRITICAL
        assert PaymentHistoryTool().permission_level == PermissionLevel.SAFE

    def test_tool_names(self) -> None:
        expected = {
            "wallet_status",
            "payment_balance",
            "payment_validate",
            "payment_preview",
            "crypto_transfer",
            "crypto_swap",
            "payment_history",
        }
        actual = {cls().name for cls in ALL_TOOL_CLASSES}
        assert actual == expected


# ---------------------------------------------------------------------------
# Not-initialized errors — all tools
# ---------------------------------------------------------------------------


class TestNotInitialized:
    @pytest.mark.asyncio
    async def test_wallet_status(self) -> None:
        result = await WalletStatusTool().execute({})
        assert not result.success
        assert "not initialized" in result.error.lower()

    @pytest.mark.asyncio
    async def test_payment_balance(self) -> None:
        result = await PaymentBalanceTool().execute({})
        assert not result.success
        assert "not initialized" in result.error.lower()

    @pytest.mark.asyncio
    async def test_payment_validate(self) -> None:
        result = await PaymentValidateTool().execute({"address": "0x" + "a" * 40})
        assert not result.success
        assert "not initialized" in result.error.lower()

    @pytest.mark.asyncio
    async def test_payment_preview(self) -> None:
        result = await PaymentPreviewTool().execute({"amount": 10.0})
        assert not result.success
        assert "not initialized" in result.error.lower()

    @pytest.mark.asyncio
    async def test_crypto_transfer(self) -> None:
        result = await CryptoTransferTool().execute(
            {"to": "0x" + "a" * 40, "amount": 10.0, "token": "USDC"}
        )
        assert not result.success
        assert "not initialized" in result.error.lower()

    @pytest.mark.asyncio
    async def test_crypto_swap(self) -> None:
        result = await CryptoSwapTool().execute(
            {"from_token": "ETH", "to_token": "USDC", "amount": 0.1}
        )
        assert not result.success
        assert "not initialized" in result.error.lower()

    @pytest.mark.asyncio
    async def test_payment_history(self) -> None:
        result = await PaymentHistoryTool().execute({})
        assert not result.success
        assert "not initialized" in result.error.lower()


# ---------------------------------------------------------------------------
# WalletStatusTool execution
# ---------------------------------------------------------------------------


class TestWalletStatusExecution:
    @pytest.mark.asyncio
    async def test_returns_details(self) -> None:
        t = WalletStatusTool()
        t._payments_manager = _mock_payments_manager()
        result = await t.execute({})
        assert result.success
        assert result.data["address"] == "0x" + "a" * 40
        assert result.data["chain"] == "base"


# ---------------------------------------------------------------------------
# PaymentBalanceTool execution
# ---------------------------------------------------------------------------


class TestPaymentBalanceExecution:
    @pytest.mark.asyncio
    async def test_default_token(self) -> None:
        t = PaymentBalanceTool()
        t._payments_manager = _mock_payments_manager()
        result = await t.execute({})
        assert result.success
        assert result.data["token"] == "USDC"

    @pytest.mark.asyncio
    async def test_specific_token(self) -> None:
        t = PaymentBalanceTool()
        mgr = _mock_payments_manager()
        mgr.get_balance.return_value = {"token": "ETH", "amount": "1.5", "chain": "base"}
        t._payments_manager = mgr
        result = await t.execute({"token": "ETH"})
        assert result.success
        mgr.get_balance.assert_called_with("ETH")


# ---------------------------------------------------------------------------
# PaymentValidateTool execution
# ---------------------------------------------------------------------------


class TestPaymentValidateExecution:
    @pytest.mark.asyncio
    async def test_valid_address(self) -> None:
        t = PaymentValidateTool()
        t._payments_manager = _mock_payments_manager()
        result = await t.execute({"address": "0x" + "a" * 40})
        assert result.success
        assert result.data["valid"] is True

    @pytest.mark.asyncio
    async def test_invalid_address(self) -> None:
        t = PaymentValidateTool()
        mgr = _mock_payments_manager()
        mgr.validate_address = MagicMock(return_value=False)
        t._payments_manager = mgr
        result = await t.execute({"address": "invalid"})
        assert result.success
        assert result.data["valid"] is False


# ---------------------------------------------------------------------------
# CryptoTransferTool execution
# ---------------------------------------------------------------------------


class TestCryptoTransferExecution:
    @pytest.mark.asyncio
    async def test_successful_transfer(self) -> None:
        t = CryptoTransferTool()
        t._payments_manager = _mock_payments_manager()
        result = await t.execute({"to": "0x" + "b" * 40, "amount": 10.0, "token": "USDC"})
        assert result.success
        assert result.data["tx_hash"] == "0xtxhash"

    @pytest.mark.asyncio
    async def test_transfer_error(self) -> None:
        t = CryptoTransferTool()
        mgr = _mock_payments_manager()
        mgr.transfer.side_effect = Exception("Insufficient funds")
        t._payments_manager = mgr
        result = await t.execute({"to": "0x" + "b" * 40, "amount": 10.0, "token": "USDC"})
        assert not result.success
        assert "Insufficient funds" in result.error


# ---------------------------------------------------------------------------
# CryptoSwapTool execution
# ---------------------------------------------------------------------------


class TestCryptoSwapExecution:
    @pytest.mark.asyncio
    async def test_successful_swap(self) -> None:
        t = CryptoSwapTool()
        t._payments_manager = _mock_payments_manager()
        result = await t.execute({"from_token": "ETH", "to_token": "USDC", "amount": 0.1})
        assert result.success
        assert result.data["tx_hash"] == "0xswaphash"

    @pytest.mark.asyncio
    async def test_swap_error(self) -> None:
        t = CryptoSwapTool()
        mgr = _mock_payments_manager()
        mgr.swap.side_effect = Exception("Slippage too high")
        t._payments_manager = mgr
        result = await t.execute({"from_token": "ETH", "to_token": "USDC", "amount": 0.1})
        assert not result.success
        assert "Slippage" in result.error


# ---------------------------------------------------------------------------
# PaymentHistoryTool execution
# ---------------------------------------------------------------------------


class TestPaymentHistoryExecution:
    @pytest.mark.asyncio
    async def test_history_list(self) -> None:
        t = PaymentHistoryTool()
        t._payments_manager = _mock_payments_manager()
        result = await t.execute({})
        assert result.success
        assert result.data["count"] == 1
        assert len(result.data["transactions"]) == 1

    @pytest.mark.asyncio
    async def test_history_summary(self) -> None:
        t = PaymentHistoryTool()
        t._payments_manager = _mock_payments_manager()
        result = await t.execute({"summary": True})
        assert result.success
        assert result.data["daily_spent"] == 50.0
        assert result.data["monthly_spent"] == 200.0

    @pytest.mark.asyncio
    async def test_history_with_status_filter(self) -> None:
        t = PaymentHistoryTool()
        mgr = _mock_payments_manager()
        t._payments_manager = mgr
        await t.execute({"status": "failed", "limit": 5})
        mgr.auditor.get_history.assert_called_with(limit=5, status="failed")


# ---------------------------------------------------------------------------
# PaymentPreviewTool execution
# ---------------------------------------------------------------------------


class TestPaymentPreviewExecution:
    @pytest.mark.asyncio
    async def test_transfer_preview(self) -> None:
        t = PaymentPreviewTool()
        t._payments_manager = _mock_payments_manager()
        result = await t.execute({"amount": 50.0, "to": "0x" + "a" * 40})
        assert result.success
        assert result.data["action"] == "transfer"
        assert "limits" in result.data
        assert "approval_tier" in result.data

    @pytest.mark.asyncio
    async def test_swap_preview(self) -> None:
        t = PaymentPreviewTool()
        t._payments_manager = _mock_payments_manager()
        result = await t.execute(
            {"action": "swap", "from_token": "ETH", "to_token": "USDC", "amount": 0.1}
        )
        assert result.success
        assert result.data["action"] == "swap"
        assert "quote" in result.data
