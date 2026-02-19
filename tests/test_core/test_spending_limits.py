"""SpendingLimiter tests — per-txn, daily, monthly, rate, duplicate limits."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import PaymentApprovalConfig, PaymentLimitsConfig
from core.database import Database
from core.payments.audit import PaymentAuditor
from core.payments.limits import SpendingLimiter


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def auditor(db: Database) -> PaymentAuditor:
    return PaymentAuditor(db)


@pytest.fixture
def limiter(auditor: PaymentAuditor) -> SpendingLimiter:
    config = PaymentLimitsConfig(
        per_transaction=100.0,
        daily=500.0,
        monthly=5000.0,
        per_merchant_daily=200.0,
    )
    return SpendingLimiter(auditor, config)


# ---------------------------------------------------------------------------
# Per-transaction limit
# ---------------------------------------------------------------------------


class TestPerTransaction:
    @pytest.mark.asyncio
    async def test_within_limit(self, limiter: SpendingLimiter) -> None:
        check = await limiter.check(50.0, "USDC", "0x" + "a" * 40)
        assert check.allowed is True

    @pytest.mark.asyncio
    async def test_exceeds_limit(self, limiter: SpendingLimiter) -> None:
        check = await limiter.check(150.0, "USDC", "0x" + "a" * 40)
        assert check.allowed is False
        assert "per-transaction" in check.reason.lower()

    @pytest.mark.asyncio
    async def test_exact_limit(self, limiter: SpendingLimiter) -> None:
        check = await limiter.check(100.0, "USDC", "0x" + "a" * 40)
        assert check.allowed is True


# ---------------------------------------------------------------------------
# Daily rolling limit
# ---------------------------------------------------------------------------


class TestDailyLimit:
    @pytest.mark.asyncio
    async def test_exceeds_daily_with_history(
        self, limiter: SpendingLimiter, auditor: PaymentAuditor
    ) -> None:
        # Pre-load $450 of spending
        for _ in range(9):
            await auditor.log(
                tool_name="crypto_transfer",
                amount=50.0,
                currency="USDC",
                recipient="0x" + "a" * 40,
                payment_type="crypto",
                status="executed",
            )
        check = await limiter.check(60.0, "USDC", "0x" + "b" * 40)
        assert check.allowed is False
        assert "daily" in check.reason.lower()
        assert check.daily_spent == 450.0

    @pytest.mark.asyncio
    async def test_within_daily(self, limiter: SpendingLimiter, auditor: PaymentAuditor) -> None:
        await auditor.log(
            tool_name="crypto_transfer",
            amount=100.0,
            currency="USDC",
            recipient="0x" + "a" * 40,
            payment_type="crypto",
            status="executed",
        )
        check = await limiter.check(50.0, "USDC", "0x" + "b" * 40)
        assert check.allowed is True
        assert check.daily_spent == 100.0


# ---------------------------------------------------------------------------
# Monthly limit
# ---------------------------------------------------------------------------


class TestMonthlyLimit:
    @pytest.mark.asyncio
    async def test_exceeds_monthly(self, auditor: PaymentAuditor) -> None:
        # Use high daily limit so the monthly limit triggers first
        config = PaymentLimitsConfig(
            per_transaction=100.0,
            daily=50000.0,
            monthly=500.0,
            per_merchant_daily=50000.0,
        )
        limiter = SpendingLimiter(auditor, config)
        for _ in range(9):
            await auditor.log(
                tool_name="crypto_transfer",
                amount=50.0,
                currency="USDC",
                recipient="0x" + "a" * 40,
                payment_type="crypto",
                status="executed",
            )
        check = await limiter.check(60.0, "USDC", "0x" + "b" * 40)
        assert check.allowed is False
        assert "monthly" in check.reason.lower()


# ---------------------------------------------------------------------------
# Per-recipient daily limit
# ---------------------------------------------------------------------------


class TestPerRecipientLimit:
    @pytest.mark.asyncio
    async def test_exceeds_recipient_daily(
        self, limiter: SpendingLimiter, auditor: PaymentAuditor
    ) -> None:
        recipient = "0x" + "f" * 40
        for _ in range(4):
            await auditor.log(
                tool_name="crypto_transfer",
                amount=50.0,
                currency="USDC",
                recipient=recipient,
                payment_type="crypto",
                status="executed",
            )
        check = await limiter.check(10.0, "USDC", recipient)
        assert check.allowed is False
        assert "per-recipient" in check.reason.lower()


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(
        self, limiter: SpendingLimiter, auditor: PaymentAuditor
    ) -> None:
        # 10 transactions within the hour
        for i in range(10):
            await auditor.log(
                tool_name="crypto_transfer",
                amount=1.0,
                currency="USDC",
                recipient=f"0x{'0' * 39}{i}",
                payment_type="crypto",
                status="executed",
            )
        check = await limiter.check(1.0, "USDC", "0x" + "a" * 40)
        assert check.allowed is False
        assert "rate limit" in check.reason.lower()


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    @pytest.mark.asyncio
    async def test_duplicate_blocked(
        self, limiter: SpendingLimiter, auditor: PaymentAuditor
    ) -> None:
        recipient = "0x" + "e" * 40
        await auditor.log(
            tool_name="crypto_transfer",
            amount=42.0,
            currency="USDC",
            recipient=recipient,
            payment_type="crypto",
            status="executed",
        )
        check = await limiter.check(42.0, "USDC", recipient)
        assert check.allowed is False
        assert "duplicate" in check.reason.lower()


# ---------------------------------------------------------------------------
# Approval tier
# ---------------------------------------------------------------------------


class TestApprovalTier:
    def test_standard_tier(self) -> None:
        config = PaymentApprovalConfig()
        auditor_mock = PaymentAuditor.__new__(PaymentAuditor)
        limiter = SpendingLimiter(auditor_mock, config)
        assert limiter.get_approval_tier(5.0) == "standard"

    def test_always_ask_tier(self) -> None:
        config = PaymentApprovalConfig()
        auditor_mock = PaymentAuditor.__new__(PaymentAuditor)
        limiter = SpendingLimiter(auditor_mock, config)
        assert limiter.get_approval_tier(50.0) == "always_ask"

    def test_confirm_tier(self) -> None:
        config = PaymentApprovalConfig()
        auditor_mock = PaymentAuditor.__new__(PaymentAuditor)
        limiter = SpendingLimiter(auditor_mock, config)
        assert limiter.get_approval_tier(500.0) == "confirm"

    def test_cooldown_tier(self) -> None:
        config = PaymentApprovalConfig()
        auditor_mock = PaymentAuditor.__new__(PaymentAuditor)
        limiter = SpendingLimiter(auditor_mock, config)
        assert limiter.get_approval_tier(2000.0) == "cooldown"
