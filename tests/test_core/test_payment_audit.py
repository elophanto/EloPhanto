"""PaymentAuditor tests — record insertion, status updates, queries."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.database import Database
from core.payments.audit import PaymentAuditor


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def auditor(db: Database) -> PaymentAuditor:
    return PaymentAuditor(db)


# ---------------------------------------------------------------------------
# Record insertion
# ---------------------------------------------------------------------------


class TestLogRecord:
    @pytest.mark.asyncio
    async def test_insert_returns_row_id(self, auditor: PaymentAuditor) -> None:
        row_id = await auditor.log(
            tool_name="crypto_transfer",
            amount=10.0,
            currency="USDC",
            recipient="0x" + "a" * 40,
            payment_type="crypto",
            status="pending",
        )
        assert isinstance(row_id, int) and row_id > 0

    @pytest.mark.asyncio
    async def test_multiple_inserts_increment_id(self, auditor: PaymentAuditor) -> None:
        id1 = await auditor.log(
            tool_name="crypto_transfer",
            amount=5.0,
            currency="USDC",
            recipient="0x" + "b" * 40,
            payment_type="crypto",
        )
        id2 = await auditor.log(
            tool_name="crypto_swap",
            amount=20.0,
            currency="ETH",
            recipient="swap:ETH->USDC",
            payment_type="swap",
        )
        assert id2 > id1


# ---------------------------------------------------------------------------
# Status updates
# ---------------------------------------------------------------------------


class TestStatusUpdate:
    @pytest.mark.asyncio
    async def test_update_to_executed(self, auditor: PaymentAuditor) -> None:
        row_id = await auditor.log(
            tool_name="crypto_transfer",
            amount=10.0,
            currency="USDC",
            recipient="0x" + "c" * 40,
            payment_type="crypto",
            status="pending",
        )
        await auditor.update_status(row_id, "executed", transaction_ref="0xhash123")
        history = await auditor.get_history(limit=1)
        assert history[0]["status"] == "executed"
        assert history[0]["transaction_ref"] == "0xhash123"

    @pytest.mark.asyncio
    async def test_update_to_failed(self, auditor: PaymentAuditor) -> None:
        row_id = await auditor.log(
            tool_name="crypto_transfer",
            amount=10.0,
            currency="USDC",
            recipient="0x" + "d" * 40,
            payment_type="crypto",
            status="pending",
        )
        await auditor.update_status(row_id, "failed", error="Insufficient funds")
        history = await auditor.get_history(limit=1)
        assert history[0]["status"] == "failed"
        assert history[0]["error"] == "Insufficient funds"


# ---------------------------------------------------------------------------
# History queries
# ---------------------------------------------------------------------------


class TestHistory:
    @pytest.mark.asyncio
    async def test_get_history_empty(self, auditor: PaymentAuditor) -> None:
        result = await auditor.get_history()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_history_limit(self, auditor: PaymentAuditor) -> None:
        for i in range(5):
            await auditor.log(
                tool_name="crypto_transfer",
                amount=float(i + 1),
                currency="USDC",
                recipient=f"0x{'a' * 40}",
                payment_type="crypto",
                status="executed",
            )
        result = await auditor.get_history(limit=3)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_get_history_filter_by_status(self, auditor: PaymentAuditor) -> None:
        await auditor.log(
            tool_name="crypto_transfer",
            amount=10.0,
            currency="USDC",
            recipient="0x" + "a" * 40,
            payment_type="crypto",
            status="executed",
        )
        await auditor.log(
            tool_name="crypto_transfer",
            amount=5.0,
            currency="USDC",
            recipient="0x" + "b" * 40,
            payment_type="crypto",
            status="failed",
        )
        executed = await auditor.get_history(status="executed")
        assert len(executed) == 1
        assert executed[0]["amount"] == 10.0


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------


class TestTotals:
    @pytest.mark.asyncio
    async def test_daily_total_empty(self, auditor: PaymentAuditor) -> None:
        total = await auditor.get_daily_total()
        assert total == 0.0

    @pytest.mark.asyncio
    async def test_daily_total_sums_executed(self, auditor: PaymentAuditor) -> None:
        await auditor.log(
            tool_name="crypto_transfer",
            amount=10.0,
            currency="USDC",
            recipient="0x" + "a" * 40,
            payment_type="crypto",
            status="executed",
        )
        await auditor.log(
            tool_name="crypto_transfer",
            amount=25.0,
            currency="USDC",
            recipient="0x" + "b" * 40,
            payment_type="crypto",
            status="executed",
        )
        # Pending should not count
        await auditor.log(
            tool_name="crypto_transfer",
            amount=100.0,
            currency="USDC",
            recipient="0x" + "c" * 40,
            payment_type="crypto",
            status="pending",
        )
        total = await auditor.get_daily_total()
        assert total == 35.0

    @pytest.mark.asyncio
    async def test_monthly_total(self, auditor: PaymentAuditor) -> None:
        await auditor.log(
            tool_name="crypto_transfer",
            amount=50.0,
            currency="USDC",
            recipient="0x" + "a" * 40,
            payment_type="crypto",
            status="executed",
        )
        total = await auditor.get_monthly_total()
        assert total == 50.0

    @pytest.mark.asyncio
    async def test_recipient_daily_total(self, auditor: PaymentAuditor) -> None:
        recipient = "0x" + "a" * 40
        await auditor.log(
            tool_name="crypto_transfer",
            amount=10.0,
            currency="USDC",
            recipient=recipient,
            payment_type="crypto",
            status="executed",
        )
        await auditor.log(
            tool_name="crypto_transfer",
            amount=15.0,
            currency="USDC",
            recipient="0x" + "b" * 40,
            payment_type="crypto",
            status="executed",
        )
        total = await auditor.get_recipient_daily_total(recipient)
        assert total == 10.0

    @pytest.mark.asyncio
    async def test_hourly_count(self, auditor: PaymentAuditor) -> None:
        for _ in range(3):
            await auditor.log(
                tool_name="crypto_transfer",
                amount=1.0,
                currency="USDC",
                recipient="0x" + "a" * 40,
                payment_type="crypto",
                status="executed",
            )
        count = await auditor.get_hourly_count()
        assert count == 3

    @pytest.mark.asyncio
    async def test_has_recent_duplicate(self, auditor: PaymentAuditor) -> None:
        recipient = "0x" + "a" * 40
        await auditor.log(
            tool_name="crypto_transfer",
            amount=42.0,
            currency="USDC",
            recipient=recipient,
            payment_type="crypto",
            status="executed",
        )
        assert await auditor.has_recent_duplicate(42.0, recipient) is True
        assert await auditor.has_recent_duplicate(99.0, recipient) is False
