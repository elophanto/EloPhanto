"""Company scope + persistence (ABE framework Phase 1).

Locks in the Phase 1 contract from docs/76-ABE-FRAMEWORK.md:
- Fresh DB has exactly one company row: 'elophanto-self'.
- New columns on existing tables default to 'elophanto-self', so old
  rows attribute automatically with no backfill UPDATE.
- _init_sync is idempotent: re-running it does not raise.
- CompanyManager.create / get / list round-trip cleanly.
- contextvar defaults to 'elophanto-self' when nothing has set it.
"""

from __future__ import annotations

import pytest

from core.company import (
    CompanyManager,
    current_company_id,
    set_current_company,
)
from core.database import Database


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()
    return db


@pytest.fixture
async def mgr(db: Database) -> CompanyManager:
    return CompanyManager(db)


class TestSeedAndMigration:
    @pytest.mark.asyncio
    async def test_default_company_seeded_on_init(self, mgr: CompanyManager) -> None:
        rows = await mgr.list()
        assert len(rows) == 1
        assert rows[0].id == "elophanto-self"
        assert rows[0].status == "active"

    @pytest.mark.asyncio
    async def test_existing_rows_attribute_to_self(self, db: Database) -> None:
        # Insert into llm_usage WITHOUT specifying company_id —
        # the DEFAULT 'elophanto-self' on the column should apply.
        await db.execute_insert(
            "INSERT INTO llm_usage "
            "(model, provider, input_tokens, output_tokens, cost_usd, "
            "task_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test-model", "test", 100, 50, 0.001, "test", "2026-05-25"),
        )
        rows = await db.execute(
            "SELECT company_id FROM llm_usage WHERE model = 'test-model'"
        )
        assert len(rows) == 1
        assert rows[0]["company_id"] == "elophanto-self"

    @pytest.mark.asyncio
    async def test_migration_idempotent(self, db: Database) -> None:
        # Re-running _init_sync must not raise (duplicate-column ALTERs
        # are silently swallowed in the existing migration loop).
        db._init_sync()
        # Still exactly one default company (INSERT OR IGNORE).
        rows = await db.execute("SELECT COUNT(*) AS c FROM companies")
        assert rows[0]["c"] == 1


class TestCRUD:
    @pytest.mark.asyncio
    async def test_create_and_list(self, mgr: CompanyManager) -> None:
        created = await mgr.create("acme-inc", "Acme, Inc.")
        assert created.id == "acme-inc"
        assert created.name == "Acme, Inc."
        assert created.status == "active"

        rows = await mgr.list()
        slugs = [r.id for r in rows]
        assert "elophanto-self" in slugs
        assert "acme-inc" in slugs

    @pytest.mark.asyncio
    async def test_create_rejects_duplicate(self, mgr: CompanyManager) -> None:
        await mgr.create("dup", "Dup Co")
        with pytest.raises(ValueError, match="already exists"):
            await mgr.create("dup", "Other")

    @pytest.mark.asyncio
    async def test_create_rejects_empty_slug(self, mgr: CompanyManager) -> None:
        with pytest.raises(ValueError, match="empty"):
            await mgr.create("", "X")

    @pytest.mark.asyncio
    async def test_set_status(self, mgr: CompanyManager) -> None:
        await mgr.create("temp", "Temp")
        await mgr.set_status("temp", "paused")
        company = await mgr.get("temp")
        assert company is not None
        assert company.status == "paused"


class TestContextVar:
    def test_default_is_elophanto_self(self) -> None:
        # In a fresh sub-context, the default applies. We use a
        # contextvars.copy_context() so this assertion isn't polluted
        # by other tests that may have called set_current_company.
        import contextvars

        def _check() -> str:
            return current_company_id()

        ctx = contextvars.copy_context()
        # Reset to default by setting then resetting
        token = set_current_company("elophanto-self")
        try:
            assert ctx.run(_check) == "elophanto-self"
        finally:
            from core.company import reset_current_company

            reset_current_company(token)

    def test_set_and_read(self) -> None:
        from core.company import reset_current_company

        token = set_current_company("acme-inc")
        try:
            assert current_company_id() == "acme-inc"
        finally:
            reset_current_company(token)
