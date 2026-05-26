"""Prospect tools → resource_ledger mirror (ABE framework Phase 3).

Locks in the Phase 3 contract from docs/76-ABE-FRAMEWORK.md:
- prospect_outreach writes a `pipeline_advance` ledger row for
  positive status transitions (evaluated, outreach_sent, replied,
  converted) and NOT for negative ones (rejected, expired).
- prospect_evaluate writes a `pipeline_advance` ledger row only
  for the 'pursue' decision.
- Ledger events attribute to the prospect's own company (its funnel),
  not the operator's currently-active company.
- prospect_search threads company_id from the active contextvar so
  prospects discovered under a non-default company stay attributed.
- Pipeline-advance sums roll up correctly via ResourceLedger.sum.
"""

from __future__ import annotations

import pytest

from core.company import (
    reset_current_company,
    set_current_company,
)
from core.database import Database
from core.ledger import ResourceLedger
from tools.prospecting.evaluate_tool import ProspectEvaluateTool
from tools.prospecting.outreach_tool import ProspectOutreachTool
from tools.prospecting.search_tool import ProspectSearchTool


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()
    return db


async def _seed_prospect(
    db: Database,
    prospect_id: str = "p_test_1",
    company_id: str = "elophanto-self",
    status: str = "new",
) -> str:
    """Insert a prospect row directly (bypassing tools) for tests
    that need a prospect to operate on.

    ABE Phase 9 compat: also INSERT the company row in `operating`
    trust state when it's not `elophanto-self`. Without this the
    Phase 9 trust gate refuses outreach (company defaults to
    `learning` when missing, which is the right production
    behavior — but these Phase 3 tests need the outreach path
    open). Using `INSERT OR IGNORE` keeps the call idempotent
    across tests that share `acme-inc`.
    """
    if company_id != "elophanto-self":
        await db.execute_insert(
            "INSERT OR IGNORE INTO companies "
            "(id, name, status, trust_state, created_at, updated_at) "
            "VALUES (?, ?, 'active', 'operating', '2026-05-25', '2026-05-25')",
            (company_id, company_id),
        )
    await db.execute_insert(
        "INSERT INTO prospects "
        "(prospect_id, source, platform, title, status, discovered_at, "
        "company_id) "
        "VALUES (?, 'freelance', 'test', 'Test gig', ?, '2026-05-25', ?)",
        (prospect_id, status, company_id),
    )
    return prospect_id


class TestOutreachLedgerMirror:
    @pytest.mark.asyncio
    async def test_email_sent_writes_pipeline_advance(self, db: Database) -> None:
        prospect_id = await _seed_prospect(db)
        tool = ProspectOutreachTool()
        tool._db = db

        result = await tool.execute(
            {"prospect_id": prospect_id, "action": "email_sent"}
        )
        assert result.success is True

        ledger = ResourceLedger(db)
        rows = await db.execute(
            "SELECT type, amount, direction, company_id, source_table "
            "FROM resource_ledger WHERE type = 'pipeline_advance'"
        )
        assert len(rows) == 1
        assert rows[0]["amount"] == 1.0
        assert rows[0]["direction"] == "in"
        assert rows[0]["source_table"] == "outreach_log"
        assert rows[0]["company_id"] == "elophanto-self"
        assert (
            await ledger.sum("elophanto-self", type="pipeline_advance", direction="in")
            == 1.0
        )

    @pytest.mark.asyncio
    async def test_reply_received_writes_pipeline_advance(self, db: Database) -> None:
        prospect_id = await _seed_prospect(db)
        tool = ProspectOutreachTool()
        tool._db = db

        await tool.execute({"prospect_id": prospect_id, "action": "reply_received"})

        rows = await db.execute(
            "SELECT type, note FROM resource_ledger WHERE type = 'pipeline_advance'"
        )
        assert len(rows) == 1
        assert "replied" in rows[0]["note"]

    @pytest.mark.asyncio
    async def test_rejected_does_not_write_ledger(self, db: Database) -> None:
        prospect_id = await _seed_prospect(db)
        tool = ProspectOutreachTool()
        tool._db = db

        await tool.execute(
            {
                "prospect_id": prospect_id,
                "action": "note",
                "new_status": "rejected",
            }
        )

        # outreach_log row written, but no pipeline_advance ledger event
        log_rows = await db.execute("SELECT COUNT(*) AS n FROM outreach_log")
        assert log_rows[0]["n"] == 1
        ledger_rows = await db.execute(
            "SELECT COUNT(*) AS n FROM resource_ledger "
            "WHERE type = 'pipeline_advance'"
        )
        assert ledger_rows[0]["n"] == 0

    @pytest.mark.asyncio
    async def test_attributes_to_prospect_company_not_active(
        self, db: Database
    ) -> None:
        # Prospect owned by acme-inc; operator currently has elophanto-self
        # active. The pipeline_advance event must attribute to acme-inc
        # (the funnel that advanced), NOT to the operator's active company.
        await _seed_prospect(db, prospect_id="p_acme", company_id="acme-inc")
        tool = ProspectOutreachTool()
        tool._db = db

        token = set_current_company("elophanto-self")
        try:
            await tool.execute({"prospect_id": "p_acme", "action": "email_sent"})
        finally:
            reset_current_company(token)

        rows = await db.execute(
            "SELECT company_id FROM resource_ledger WHERE type = 'pipeline_advance'"
        )
        assert rows[0]["company_id"] == "acme-inc"
        # outreach_log row should also follow the prospect, not the active company
        log_rows = await db.execute(
            "SELECT company_id FROM outreach_log WHERE prospect_id = 'p_acme'"
        )
        assert log_rows[0]["company_id"] == "acme-inc"


class TestSearchCompanyAttribution:
    @pytest.mark.asyncio
    async def test_search_writes_with_active_company_id(self, db: Database) -> None:
        tool = ProspectSearchTool()
        tool._db = db

        token = set_current_company("acme-inc")
        try:
            await tool.execute(
                {
                    "prospects": [
                        {
                            "title": "Build landing page",
                            "source": "freelance",
                            "platform": "upwork",
                            "url": "https://example.com/job/1",
                        }
                    ]
                }
            )
        finally:
            reset_current_company(token)

        rows = await db.execute("SELECT company_id FROM prospects")
        assert rows[0]["company_id"] == "acme-inc"


class TestEvaluateLedgerMirror:
    @pytest.mark.asyncio
    async def test_pursue_writes_pipeline_advance(self, db: Database) -> None:
        prospect_id = await _seed_prospect(db, status="new")
        tool = ProspectEvaluateTool()
        tool._db = db

        await tool.execute(
            {
                "prospect_id": prospect_id,
                "decision": "pursue",
                "match_score": 0.9,
                "match_reasoning": "Strong fit",
            }
        )

        rows = await db.execute(
            "SELECT amount, source_table, note FROM resource_ledger "
            "WHERE type = 'pipeline_advance'"
        )
        assert len(rows) == 1
        assert rows[0]["source_table"] == "prospects"
        assert "evaluated" in rows[0]["note"]

    @pytest.mark.asyncio
    async def test_skip_does_not_write_ledger(self, db: Database) -> None:
        prospect_id = await _seed_prospect(db, status="new")
        tool = ProspectEvaluateTool()
        tool._db = db

        await tool.execute(
            {
                "prospect_id": prospect_id,
                "decision": "skip",
                "match_score": 0.1,
                "match_reasoning": "Wrong domain",
            }
        )

        ledger_rows = await db.execute(
            "SELECT COUNT(*) AS n FROM resource_ledger "
            "WHERE type = 'pipeline_advance'"
        )
        assert ledger_rows[0]["n"] == 0


class TestPipelineSum:
    @pytest.mark.asyncio
    async def test_multiple_advances_sum_correctly(self, db: Database) -> None:
        # Three positive transitions + one negative on three prospects;
        # ResourceLedger.sum should return 3.0.
        await _seed_prospect(db, "p_a")
        await _seed_prospect(db, "p_b")
        await _seed_prospect(db, "p_c")
        tool = ProspectOutreachTool()
        tool._db = db

        await tool.execute({"prospect_id": "p_a", "action": "email_sent"})
        await tool.execute({"prospect_id": "p_b", "action": "email_sent"})
        await tool.execute({"prospect_id": "p_c", "action": "reply_received"})
        # Negative — should not count
        await tool.execute(
            {"prospect_id": "p_a", "action": "note", "new_status": "rejected"}
        )

        ledger = ResourceLedger(db)
        total = await ledger.sum(
            "elophanto-self", type="pipeline_advance", direction="in"
        )
        assert total == 3.0
