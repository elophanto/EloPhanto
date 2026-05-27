"""company_archive + company_purge tools (Phase 5 board view follow-on).

The board view exposed an obvious operator gap — they could see a
company they wanted to remove but there was no tool path. These two
tools close that gap with the right safety semantics: archive is
soft + reversible (DESTRUCTIVE permission), purge is hard + cascade
(CRITICAL permission + explicit confirm flag + refuses elophanto-self).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.company import CompanyManager
from core.database import Database
from tools.base import PermissionLevel
from tools.companies.management_tools import (
    CompanyArchiveTool,
    CompanyPurgeTool,
)


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()
    return db


@pytest.fixture
async def company_mgr(db: Database, tmp_path) -> CompanyManager:
    mgr = CompanyManager(db=db, project_root=tmp_path)
    await mgr.create("acme-inc", "Acme Inc")
    return mgr


def _make_archive(
    db: Database, mgr: CompanyManager, tmp_path: Path
) -> CompanyArchiveTool:
    t = CompanyArchiveTool()
    t._db = db
    t._company_manager = mgr
    t._project_root = tmp_path
    return t


def _make_purge(db: Database, mgr: CompanyManager, tmp_path: Path) -> CompanyPurgeTool:
    t = CompanyPurgeTool()
    t._db = db
    t._company_manager = mgr
    t._project_root = tmp_path
    return t


class TestCompanyArchive:
    @pytest.mark.asyncio
    async def test_flips_status_to_archived(
        self, db: Database, company_mgr: CompanyManager, tmp_path: Path
    ) -> None:
        tool = _make_archive(db, company_mgr, tmp_path)
        r = await tool.execute({"slug": "acme-inc"})
        assert r.success is True
        assert r.data["status"] == "archived"
        company = await company_mgr.get("acme-inc")
        assert company is not None
        assert company.status == "archived"

    @pytest.mark.asyncio
    async def test_refuses_elophanto_self(
        self, db: Database, company_mgr: CompanyManager, tmp_path: Path
    ) -> None:
        tool = _make_archive(db, company_mgr, tmp_path)
        r = await tool.execute({"slug": "elophanto-self"})
        assert r.success is False
        assert "elophanto-self" in (r.error or "")

    @pytest.mark.asyncio
    async def test_unknown_slug(
        self, db: Database, company_mgr: CompanyManager, tmp_path: Path
    ) -> None:
        tool = _make_archive(db, company_mgr, tmp_path)
        r = await tool.execute({"slug": "ghost"})
        assert r.success is False

    @pytest.mark.asyncio
    async def test_permission_destructive(self) -> None:
        assert CompanyArchiveTool().permission_level == PermissionLevel.DESTRUCTIVE


class TestCompanyPurge:
    @pytest.mark.asyncio
    async def test_requires_confirm_flag(
        self, db: Database, company_mgr: CompanyManager, tmp_path: Path
    ) -> None:
        tool = _make_purge(db, company_mgr, tmp_path)
        r = await tool.execute({"slug": "acme-inc", "confirm": False})
        assert r.success is False
        assert "confirm" in (r.error or "").lower()
        # Company still exists
        assert (await company_mgr.get("acme-inc")) is not None

    @pytest.mark.asyncio
    async def test_refuses_elophanto_self(
        self, db: Database, company_mgr: CompanyManager, tmp_path: Path
    ) -> None:
        tool = _make_purge(db, company_mgr, tmp_path)
        r = await tool.execute({"slug": "elophanto-self", "confirm": True})
        assert r.success is False
        assert "elophanto-self" in (r.error or "")

    @pytest.mark.asyncio
    async def test_unknown_slug(
        self, db: Database, company_mgr: CompanyManager, tmp_path: Path
    ) -> None:
        tool = _make_purge(db, company_mgr, tmp_path)
        r = await tool.execute({"slug": "ghost", "confirm": True})
        assert r.success is False

    @pytest.mark.asyncio
    async def test_hard_delete_with_cascade(
        self, db: Database, company_mgr: CompanyManager, tmp_path: Path
    ) -> None:
        # Seed dependent rows under acme-inc
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        await db.execute_insert(
            "INSERT INTO goals (goal_id, goal, status, attempts, max_attempts, "
            "llm_calls_used, cost_usd, created_at, updated_at, company_id) "
            "VALUES (?, ?, 'planning', 0, 3, 0, 0.0, ?, ?, 'acme-inc')",
            ("g1", "x", now, now),
        )
        await db.execute_insert(
            "INSERT INTO resource_ledger "
            "(company_id, type, amount, direction, unit, source_table, "
            "source_id, note, ts) "
            "VALUES ('acme-inc', 'usd', 5.0, 'in', 'usd', 't', 1, '', ?)",
            (now,),
        )
        # Seed filesystem artifacts
        (tmp_path / "companies" / "acme-inc").mkdir(parents=True, exist_ok=True)
        (tmp_path / "companies" / "acme-inc" / "company.yaml").write_text(
            "name: Acme\n"
        )
        (tmp_path / "data" / "companies" / "acme-inc").mkdir(
            parents=True, exist_ok=True
        )
        (tmp_path / "data" / "companies" / "acme-inc" / "voice.yaml").write_text(
            "banned_phrases: [x]\n"
        )

        tool = _make_purge(db, company_mgr, tmp_path)
        r = await tool.execute({"slug": "acme-inc", "confirm": True})
        assert r.success is True, r.error
        # Company gone from DB
        assert (await company_mgr.get("acme-inc")) is None
        # Cascade through dependent rows
        rows = await db.execute(
            "SELECT COUNT(*) AS n FROM goals WHERE company_id = 'acme-inc'"
        )
        assert rows[0]["n"] == 0
        rows = await db.execute(
            "SELECT COUNT(*) AS n FROM resource_ledger WHERE company_id = 'acme-inc'"
        )
        assert rows[0]["n"] == 0
        # Cascade counts surfaced in response
        assert r.data["deleted_rows"]["goals"] == 1
        assert r.data["deleted_rows"]["resource_ledger"] == 1
        # Filesystem cleaned
        assert not (tmp_path / "companies" / "acme-inc").exists()
        assert not (tmp_path / "data" / "companies" / "acme-inc").exists()
        assert len(r.data["fs_removed"]) == 2

    @pytest.mark.asyncio
    async def test_permission_critical(self) -> None:
        assert CompanyPurgeTool().permission_level == PermissionLevel.CRITICAL

    @pytest.mark.asyncio
    async def test_unknown_table_tolerated(
        self, db: Database, company_mgr: CompanyManager, tmp_path: Path
    ) -> None:
        """If a table in the cascade list doesn't exist on this schema
        (older install), purge should skip it cleanly rather than abort.
        The companies row itself must still get deleted."""
        # All cascade tables exist on a freshly-initialized DB, so this
        # is essentially a smoke test that the try/except boundary
        # works — but it confirms the deleted_rows dict is well-formed
        # (every table key present, even if 0).
        tool = _make_purge(db, company_mgr, tmp_path)
        r = await tool.execute({"slug": "acme-inc", "confirm": True})
        assert r.success is True
        for table in (
            "resource_ledger",
            "goals",
            "missions",
            "scheduled_tasks",
            "prospects",
        ):
            assert table in r.data["deleted_rows"]
