"""Resource ledger + cross-table mirrors (ABE framework Phase 1).

Locks in the Phase 1 contract from docs/76-ABE-FRAMEWORK.md:
- ResourceLedger.write/sum/recent round-trip correctly.
- CostTracker.flush mirrors each llm_usage row as paired tokens+usd
  ledger entries attributed to the active company.
- email_send mirrors as a single 'email_sent' ledger event when the
  send succeeded; failed sends still log to email_log but don't count
  as a touch.
"""

from __future__ import annotations

import pytest

from core.company import (
    DEFAULT_COMPANY_ID,
    current_company_id,
    reset_current_company,
    set_current_company,
)
from core.database import Database
from core.ledger import LedgerEntry, ResourceLedger
from core.router import CostTracker


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()
    return db


class TestLedger:
    @pytest.mark.asyncio
    async def test_write_and_sum(self, db: Database) -> None:
        ledger = ResourceLedger(db)
        await ledger.write(
            LedgerEntry(
                company_id=DEFAULT_COMPANY_ID,
                direction="in",
                type="usd",
                amount=100.0,
                unit="usd",
            )
        )
        await ledger.write(
            LedgerEntry(
                company_id=DEFAULT_COMPANY_ID,
                direction="out",
                type="usd",
                amount=5.0,
                unit="usd",
            )
        )
        await ledger.write(
            LedgerEntry(
                company_id=DEFAULT_COMPANY_ID,
                direction="out",
                type="tokens",
                amount=1500.0,
                unit="tok",
            )
        )

        # Sum by direction
        revenue = await ledger.sum(DEFAULT_COMPANY_ID, type="usd", direction="in")
        spend = await ledger.sum(DEFAULT_COMPANY_ID, type="usd", direction="out")
        assert revenue == 100.0
        assert spend == 5.0

        # Sum by type only — both directions roll up
        all_usd = await ledger.sum(DEFAULT_COMPANY_ID, type="usd")
        assert all_usd == 105.0

        # Different company → 0
        zero = await ledger.sum("acme-inc", type="usd")
        assert zero == 0.0

    @pytest.mark.asyncio
    async def test_recent_orders_newest_first(self, db: Database) -> None:
        ledger = ResourceLedger(db)
        for i in range(5):
            await ledger.write(
                LedgerEntry(
                    company_id=DEFAULT_COMPANY_ID,
                    direction="out",
                    type="tokens",
                    amount=float(i),
                    unit="tok",
                    note=f"call-{i}",
                )
            )
        rows = await ledger.recent(DEFAULT_COMPANY_ID, limit=3)
        assert len(rows) == 3
        # Newest first → highest i
        assert rows[0]["note"] == "call-4"
        assert rows[2]["note"] == "call-2"

    @pytest.mark.asyncio
    async def test_invalid_direction_raises(self, db: Database) -> None:
        ledger = ResourceLedger(db)
        with pytest.raises(ValueError, match="direction"):
            await ledger.write(
                LedgerEntry(
                    company_id=DEFAULT_COMPANY_ID,
                    direction="sideways",
                    type="usd",
                    amount=1.0,
                    unit="usd",
                )
            )


class TestLLMUsageMirror:
    @pytest.mark.asyncio
    async def test_flush_mirrors_tokens_and_usd(self, db: Database) -> None:
        # Make sure the contextvar is at default for this test
        token = set_current_company(DEFAULT_COMPANY_ID)
        try:
            tracker = CostTracker()
            tracker.record(
                cost=0.0025,
                input_tokens=800,
                output_tokens=200,
                provider="anthropic",
                model="claude-opus-4-7",
                task_type="general",
            )
            await tracker.flush(db)

            # llm_usage got one row
            usage_rows = await db.execute(
                "SELECT id, cost_usd, company_id FROM llm_usage"
            )
            assert len(usage_rows) == 1
            assert usage_rows[0]["company_id"] == DEFAULT_COMPANY_ID
            usage_id = usage_rows[0]["id"]

            # Ledger got TWO rows: tokens + usd
            ledger_rows = await db.execute(
                "SELECT type, amount, direction, source_table, source_id "
                "FROM resource_ledger ORDER BY type"
            )
            assert len(ledger_rows) == 2
            tokens_row, usd_row = ledger_rows
            assert tokens_row["type"] == "tokens"
            assert tokens_row["amount"] == 1000.0  # 800 + 200
            assert tokens_row["direction"] == "out"
            assert tokens_row["source_table"] == "llm_usage"
            assert tokens_row["source_id"] == usage_id
            assert usd_row["type"] == "usd"
            assert usd_row["amount"] == pytest.approx(0.0025)
        finally:
            reset_current_company(token)

    @pytest.mark.asyncio
    async def test_flush_respects_active_company(self, db: Database) -> None:
        # Create a non-default company then activate it
        await db.execute_insert(
            "INSERT INTO companies (id, name, status, created_at, updated_at) "
            "VALUES ('acme-inc', 'Acme', 'active', '2026-05-25', '2026-05-25')",
        )
        token = set_current_company("acme-inc")
        try:
            assert current_company_id() == "acme-inc"
            tracker = CostTracker()
            tracker.record(
                cost=0.01,
                input_tokens=100,
                output_tokens=100,
                provider="openrouter",
                model="x/y",
                task_type="t",
            )
            await tracker.flush(db)

            usage = await db.execute(
                "SELECT company_id FROM llm_usage WHERE provider = 'openrouter'"
            )
            assert usage[0]["company_id"] == "acme-inc"
            ledger = await db.execute(
                "SELECT company_id FROM resource_ledger WHERE type = 'usd'"
            )
            assert all(r["company_id"] == "acme-inc" for r in ledger)
        finally:
            reset_current_company(token)


class TestEmailMirror:
    @pytest.mark.asyncio
    async def test_outbound_email_mirrors_as_touch(self, db: Database) -> None:
        from tools.email._log import mirror_email_to_ledger

        # Insert an email_log row manually (simulating what send_tool does)
        email_id = await db.execute_insert(
            "INSERT INTO email_log "
            "(timestamp, tool_name, inbox_id, direction, recipient, "
            "subject, message_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-05-25T10:00:00",
                "email_send",
                "inbox-1",
                "outbound",
                "petr@example.com",
                "Hello",
                "msg-1",
                "sent",
            ),
        )

        await mirror_email_to_ledger(
            db,
            email_log_id=email_id,
            direction="outbound",
            tool_name="email_send",
            recipient="petr@example.com",
        )

        rows = await db.execute(
            "SELECT type, amount, source_table, source_id "
            "FROM resource_ledger WHERE type = 'email_sent'"
        )
        assert len(rows) == 1
        assert rows[0]["amount"] == 1.0
        assert rows[0]["source_table"] == "email_log"
        assert rows[0]["source_id"] == email_id

    @pytest.mark.asyncio
    async def test_non_outbound_does_not_mirror(self, db: Database) -> None:
        from tools.email._log import mirror_email_to_ledger

        await mirror_email_to_ledger(
            db,
            email_log_id=999,
            direction="inbound",  # incoming → not a touch
            tool_name="email_inbox",
        )
        await mirror_email_to_ledger(
            db,
            email_log_id=999,
            direction="system",  # admin → not a touch
            tool_name="email_create_inbox",
        )
        rows = await db.execute(
            "SELECT COUNT(*) AS c FROM resource_ledger WHERE type = 'email_sent'"
        )
        assert rows[0]["c"] == 0
