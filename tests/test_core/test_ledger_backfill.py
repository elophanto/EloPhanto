"""Ledger backfill — one-shot import of historical rows.

Locks in: idempotency, attribution to default company when source rows
have no company_id, and the per-source row counts surface correctly in
the BackfillReport.
"""

from __future__ import annotations

import pytest

from core.database import Database
from core.ledger_backfill import backfill_ledger


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()
    return db


async def _seed_history(db: Database) -> None:
    """Insert one row in each source table — directly into the DB,
    bypassing the live writer paths so we can simulate pre-Phase-1
    history (no ledger rows created)."""
    await db.execute_insert(
        "INSERT INTO llm_usage "
        "(model, provider, input_tokens, output_tokens, cost_usd, "
        "task_type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("opus-4", "anthropic", 1000, 500, 0.05, "general", "2026-05-20"),
    )
    await db.execute_insert(
        "INSERT INTO payment_audit "
        "(timestamp, tool_name, amount, currency, recipient, payment_type, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-20", "wallet_transfer", 25.0, "USD", "0xabc", "outbound", "executed"),
    )
    await db.execute_insert(
        "INSERT INTO email_log "
        "(timestamp, tool_name, inbox_id, direction, recipient, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("2026-05-20", "email_send", "inbox-1", "outbound", "x@y.com", "sent"),
    )
    # And an inbound row that should NOT count as a touch
    await db.execute_insert(
        "INSERT INTO email_log "
        "(timestamp, tool_name, inbox_id, direction, status) "
        "VALUES (?, ?, ?, ?, ?)",
        ("2026-05-20", "email_inbox", "inbox-1", "inbound", "received"),
    )


class TestBackfill:
    @pytest.mark.asyncio
    async def test_backfill_counts(self, db: Database) -> None:
        await _seed_history(db)
        report = await backfill_ledger(db)
        # 1 llm_usage row → 2 ledger rows (tokens + usd)
        assert report.llm_tokens_added == 1
        assert report.llm_usd_added == 1
        assert report.payment_added == 1
        # outbound only — the inbound row must be ignored
        assert report.email_added == 1
        assert report.total == 4

    @pytest.mark.asyncio
    async def test_backfill_attributes_to_default_company(self, db: Database) -> None:
        await _seed_history(db)
        await backfill_ledger(db)
        rows = await db.execute("SELECT DISTINCT company_id FROM resource_ledger")
        assert len(rows) == 1
        assert rows[0]["company_id"] == "elophanto-self"

    @pytest.mark.asyncio
    async def test_backfill_is_idempotent(self, db: Database) -> None:
        await _seed_history(db)
        first = await backfill_ledger(db)
        assert first.total == 4
        second = await backfill_ledger(db)
        # All source_ids already present → 0 new rows
        assert second.total == 0
        # Ledger row count unchanged
        rows = await db.execute("SELECT COUNT(*) AS c FROM resource_ledger")
        assert rows[0]["c"] == 4

    @pytest.mark.asyncio
    async def test_backfill_amounts_match_source(self, db: Database) -> None:
        await _seed_history(db)
        await backfill_ledger(db)
        # llm_usage cost should appear as a usd row
        usd_rows = await db.execute(
            "SELECT amount FROM resource_ledger "
            "WHERE source_table = 'llm_usage' AND type = 'usd'"
        )
        assert usd_rows[0]["amount"] == pytest.approx(0.05)
        # llm_usage tokens row sums input + output
        tok_rows = await db.execute(
            "SELECT amount FROM resource_ledger "
            "WHERE source_table = 'llm_usage' AND type = 'tokens'"
        )
        assert tok_rows[0]["amount"] == 1500.0
        # payment_audit row
        pay_rows = await db.execute(
            "SELECT amount, direction FROM resource_ledger "
            "WHERE source_table = 'payment_audit'"
        )
        assert pay_rows[0]["amount"] == 25.0
        assert pay_rows[0]["direction"] == "out"
        # email touch counts as 1
        email_rows = await db.execute(
            "SELECT amount FROM resource_ledger " "WHERE source_table = 'email_log'"
        )
        assert email_rows[0]["amount"] == 1.0

    @pytest.mark.asyncio
    async def test_backfill_empty_db_is_noop(self, db: Database) -> None:
        report = await backfill_ledger(db)
        assert report.total == 0
