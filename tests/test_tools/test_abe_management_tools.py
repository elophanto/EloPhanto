"""ABE chat-callable management tools (Phase 8).

Locks in: 11 ABE tools (1 from Phase 7 + 10 from Phase 8) round-trip
the same way the CLI does. Validates session-only vs persist semantics
on company_use and role_use.
"""

from __future__ import annotations

import pytest

from core.company import (
    CompanyManager,
    current_company_id,
    reset_current_company,
    set_current_company,
)
from core.database import Database
from core.ledger import LedgerEntry, ResourceLedger
from core.role import RoleManager
from core.role_context import current_role, reset_current_role, set_current_role
from tools.companies.management_tools import (
    CompanyCreateTool,
    CompanyListTool,
    CompanyPauseTool,
    CompanyReportTool,
    CompanyResumeTool,
    CompanyUseTool,
)
from tools.roles.management_tools import (
    RoleListTool,
    RoleShowTool,
    RoleSyncTool,
    RoleUseTool,
)


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()
    return db


@pytest.fixture
async def company_mgr(db: Database, tmp_path) -> CompanyManager:
    return CompanyManager(db=db, project_root=tmp_path)


@pytest.fixture
async def role_mgr(db: Database, tmp_path) -> RoleManager:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    return RoleManager(db=db, roles_dir=roles_dir)


def _company_tool(cls, db, project_root, company_mgr):
    t = cls()
    t._db = db
    t._project_root = project_root
    t._company_manager = company_mgr
    return t


def _role_tool(cls, role_mgr):
    t = cls()
    t._role_manager = role_mgr
    return t


# ── Company management ────────────────────────────────────────────────


class TestCompanyList:
    @pytest.mark.asyncio
    async def test_lists_default_seed(self, db, tmp_path, company_mgr) -> None:
        tool = _company_tool(CompanyListTool, db, tmp_path, company_mgr)
        result = await tool.execute({})
        assert result.success
        slugs = [c["slug"] for c in result.data["companies"]]
        assert "elophanto-self" in slugs

    @pytest.mark.asyncio
    async def test_active_marker_follows_contextvar(
        self, db, tmp_path, company_mgr
    ) -> None:
        await company_mgr.create("acme-inc", "Acme")
        tool = _company_tool(CompanyListTool, db, tmp_path, company_mgr)
        token = set_current_company("acme-inc")
        try:
            result = await tool.execute({})
        finally:
            reset_current_company(token)
        active = [c for c in result.data["companies"] if c["active_session"]]
        assert len(active) == 1
        assert active[0]["slug"] == "acme-inc"

    @pytest.mark.asyncio
    async def test_uninitialized_fails(self) -> None:
        tool = CompanyListTool()
        result = await tool.execute({})
        assert not result.success
        assert "not initialized" in result.error


class TestCompanyReport:
    @pytest.mark.asyncio
    async def test_returns_headline_for_active(self, db, tmp_path, company_mgr) -> None:
        tool = _company_tool(CompanyReportTool, db, tmp_path, company_mgr)
        # Seed a ledger event so the headline isn't all zeros
        ledger = ResourceLedger(db)
        await ledger.write(
            LedgerEntry(
                company_id="elophanto-self",
                direction="out",
                type="usd",
                amount=1.23,
                unit="usd",
            )
        )
        result = await tool.execute({})
        assert result.success
        assert result.data["slug"] == "elophanto-self"
        assert result.data["headline"]["spend_usd"] == pytest.approx(1.23)
        assert result.data["product_defined"] is False  # no yaml in tmp

    @pytest.mark.asyncio
    async def test_unknown_slug_fails(self, db, tmp_path, company_mgr) -> None:
        tool = _company_tool(CompanyReportTool, db, tmp_path, company_mgr)
        result = await tool.execute({"slug": "nope"})
        assert not result.success
        assert "nope" in result.error


class TestCompanyCreate:
    @pytest.mark.asyncio
    async def test_creates_with_slug_only(self, db, tmp_path, company_mgr) -> None:
        tool = _company_tool(CompanyCreateTool, db, tmp_path, company_mgr)
        result = await tool.execute({"slug": "new-co"})
        assert result.success
        assert result.data["slug"] == "new-co"
        # Data dir was materialized
        assert (tmp_path / "data" / "companies" / "new-co").is_dir()

    @pytest.mark.asyncio
    async def test_duplicate_fails(self, db, tmp_path, company_mgr) -> None:
        tool = _company_tool(CompanyCreateTool, db, tmp_path, company_mgr)
        await tool.execute({"slug": "dup"})
        result = await tool.execute({"slug": "dup"})
        assert not result.success
        assert "already exists" in result.error

    @pytest.mark.asyncio
    async def test_empty_slug_fails(self, db, tmp_path, company_mgr) -> None:
        tool = _company_tool(CompanyCreateTool, db, tmp_path, company_mgr)
        result = await tool.execute({"slug": ""})
        assert not result.success


class TestCompanyUse:
    @pytest.mark.asyncio
    async def test_session_only_default(self, db, tmp_path, company_mgr) -> None:
        await company_mgr.create("acme-inc", "Acme")
        tool = _company_tool(CompanyUseTool, db, tmp_path, company_mgr)
        # Reset to known default
        token = set_current_company("elophanto-self")
        try:
            result = await tool.execute({"slug": "acme-inc"})
            assert result.success
            assert result.data["scope"] == "session-only"
            assert result.data["persisted_to_sidecar"] is False
            # Contextvar updated
            assert current_company_id() == "acme-inc"
        finally:
            reset_current_company(token)

    @pytest.mark.asyncio
    async def test_unknown_slug_fails(self, db, tmp_path, company_mgr) -> None:
        tool = _company_tool(CompanyUseTool, db, tmp_path, company_mgr)
        result = await tool.execute({"slug": "no-such"})
        assert not result.success


class TestCompanyPauseResume:
    @pytest.mark.asyncio
    async def test_pause_then_resume(self, db, tmp_path, company_mgr) -> None:
        await company_mgr.create("acme-inc", "Acme")
        pause = _company_tool(CompanyPauseTool, db, tmp_path, company_mgr)
        resume = _company_tool(CompanyResumeTool, db, tmp_path, company_mgr)

        result = await pause.execute({"slug": "acme-inc"})
        assert result.success
        c = await company_mgr.get("acme-inc")
        assert c.status == "paused"

        result = await resume.execute({"slug": "acme-inc"})
        assert result.success
        c = await company_mgr.get("acme-inc")
        assert c.status == "active"


# ── Role management ──────────────────────────────────────────────────


class TestRoleList:
    @pytest.mark.asyncio
    async def test_lists_synced_roles(self, role_mgr) -> None:
        await role_mgr.upsert(
            name="sales", description="Pipeline", allowed_tools=["email_send"]
        )
        await role_mgr.upsert(name="ceo", description="Default")
        tool = _role_tool(RoleListTool, role_mgr)
        result = await tool.execute({})
        assert result.success
        names = {r["name"] for r in result.data["roles"]}
        assert names == {"sales", "ceo"}

    @pytest.mark.asyncio
    async def test_active_marker(self, role_mgr) -> None:
        await role_mgr.upsert(name="sales", description="")
        tool = _role_tool(RoleListTool, role_mgr)
        token = set_current_role("sales")
        try:
            result = await tool.execute({})
        finally:
            reset_current_role(token)
        active = [r for r in result.data["roles"] if r["active_session"]]
        assert len(active) == 1
        assert active[0]["name"] == "sales"


class TestRoleShow:
    @pytest.mark.asyncio
    async def test_returns_full_role(self, role_mgr) -> None:
        await role_mgr.upsert(
            name="sales",
            description="Pipeline",
            prompt_overlay="You are SALES.",
            allowed_tools=["email_send", "prospect_search"],
            kpi={"email_sent": 20.0},
        )
        tool = _role_tool(RoleShowTool, role_mgr)
        result = await tool.execute({"name": "sales"})
        assert result.success
        assert result.data["prompt_overlay"] == "You are SALES."
        assert result.data["allowed_tools"] == ["email_send", "prospect_search"]
        assert result.data["kpi"] == {"email_sent": 20.0}

    @pytest.mark.asyncio
    async def test_unknown_role_fails(self, role_mgr) -> None:
        tool = _role_tool(RoleShowTool, role_mgr)
        result = await tool.execute({"name": "no-such"})
        assert not result.success


class TestRoleUse:
    @pytest.mark.asyncio
    async def test_switch_session_only(self, role_mgr) -> None:
        await role_mgr.upsert(name="sales", description="")
        tool = _role_tool(RoleUseTool, role_mgr)
        token = set_current_role(None)
        try:
            result = await tool.execute({"name": "sales"})
            assert result.success
            assert result.data["scope"] == "session-only"
            assert current_role() == "sales"
        finally:
            reset_current_role(token)

    @pytest.mark.asyncio
    async def test_clear_via_empty(self, role_mgr) -> None:
        await role_mgr.upsert(name="sales", description="")
        tool = _role_tool(RoleUseTool, role_mgr)
        token = set_current_role("sales")
        try:
            result = await tool.execute({"name": ""})
            assert result.success
            assert result.data["active_session"] is None
            assert current_role() is None
        finally:
            reset_current_role(token)

    @pytest.mark.asyncio
    async def test_unknown_role_fails(self, role_mgr) -> None:
        tool = _role_tool(RoleUseTool, role_mgr)
        result = await tool.execute({"name": "no-such"})
        assert not result.success


class TestRoleSync:
    @pytest.mark.asyncio
    async def test_syncs_from_disk(self, db, tmp_path) -> None:
        import yaml as _yaml

        roles_dir = tmp_path / "roles"
        roles_dir.mkdir()
        (roles_dir / "support.yaml").write_text(
            _yaml.safe_dump({"name": "support", "description": "Triage"}),
            encoding="utf-8",
        )
        mgr = RoleManager(db=db, roles_dir=roles_dir)
        tool = _role_tool(RoleSyncTool, mgr)
        result = await tool.execute({})
        assert result.success
        assert result.data["synced"] == 1
        role = await mgr.get("support")
        assert role is not None
