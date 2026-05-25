"""``company_set_product`` tool (ABE framework Phase 7).

Locks in the Phase 7 contract from docs/76-ABE-FRAMEWORK.md:
- Writes companies/<slug>/company.yaml when slug exists + content valid
- Refuses to write for unknown slugs (operator controls company creation)
- Refuses empty what_we_sell (navel-gazing guard)
- Refuses banned navel-gazing fragments in what_we_sell
- Overwrites existing yaml on second call
- Round-trips through load_product
- from_unproductized_companies yields per-missing candidates
"""

from __future__ import annotations

import pytest

from core.company import CompanyManager
from core.database import Database
from core.mind_candidates import CandidateContext, from_unproductized_companies
from core.product import load_product
from tools.companies.set_product_tool import CompanySetProductTool


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()
    return db


@pytest.fixture
async def company_mgr(db: Database, tmp_path) -> CompanyManager:
    mgr = CompanyManager(db=db, project_root=tmp_path)
    # Seed a known company so the tool's slug-exists check passes.
    await mgr.create("acme-inc", "Acme Inc")
    return mgr


@pytest.fixture
def tool(db: Database, tmp_path) -> CompanySetProductTool:
    t = CompanySetProductTool()
    t._db = db
    t._project_root = tmp_path
    return t


class TestSetProductWrites:
    @pytest.mark.asyncio
    async def test_writes_yaml_for_existing_slug(
        self,
        tool: CompanySetProductTool,
        company_mgr: CompanyManager,
        tmp_path,
    ) -> None:
        result = await tool.execute(
            {
                "slug": "acme-inc",
                "what_we_sell": "Boutique automations for indie operators.",
                "price": {"amount": 100, "currency": "USD", "model": "hourly"},
                "kpis": [{"type": "pipeline_advance", "target_weekly": 5}],
            }
        )
        assert result.success is True
        target = tmp_path / "companies" / "acme-inc" / "company.yaml"
        assert target.is_file()

        loaded = load_product(tmp_path, "acme-inc")
        assert loaded is not None
        assert "Boutique automations" in loaded.what_we_sell
        assert loaded.price == {"amount": 100, "currency": "USD", "model": "hourly"}
        assert len(loaded.kpis) == 1

    @pytest.mark.asyncio
    async def test_overwrites_existing(
        self,
        tool: CompanySetProductTool,
        company_mgr: CompanyManager,
        tmp_path,
    ) -> None:
        await tool.execute({"slug": "acme-inc", "what_we_sell": "First version"})
        await tool.execute({"slug": "acme-inc", "what_we_sell": "Replacement version"})
        loaded = load_product(tmp_path, "acme-inc")
        assert loaded is not None
        assert loaded.what_we_sell == "Replacement version"


class TestSetProductValidation:
    @pytest.mark.asyncio
    async def test_refuses_unknown_slug(
        self,
        tool: CompanySetProductTool,
        company_mgr: CompanyManager,
        tmp_path,
    ) -> None:
        result = await tool.execute(
            {"slug": "no-such-co", "what_we_sell": "Real product."}
        )
        assert result.success is False
        assert result.error is not None
        assert "does not exist" in result.error
        # File should NOT have been written
        assert not (tmp_path / "companies" / "no-such-co").exists()

    @pytest.mark.asyncio
    async def test_refuses_empty_what_we_sell(
        self,
        tool: CompanySetProductTool,
        company_mgr: CompanyManager,
    ) -> None:
        result = await tool.execute({"slug": "acme-inc", "what_we_sell": ""})
        assert result.success is False
        assert result.error is not None
        assert "required" in result.error or "empty" in result.error

    @pytest.mark.asyncio
    async def test_refuses_banned_fragment(
        self,
        tool: CompanySetProductTool,
        company_mgr: CompanyManager,
    ) -> None:
        # 'evidence garden' is on the banlist
        result = await tool.execute(
            {
                "slug": "acme-inc",
                "what_we_sell": "An evidence garden for self-perception.",
            }
        )
        assert result.success is False
        assert result.error is not None
        assert "consumer filter" in result.error

    @pytest.mark.asyncio
    async def test_uninitialized_tool_fails(self, tmp_path) -> None:
        t = CompanySetProductTool()
        # no db, no project_root
        result = await t.execute({"slug": "acme-inc", "what_we_sell": "x"})
        assert result.success is False
        assert result.error is not None
        assert "not initialized" in result.error


class TestUnproductizedCandidateSource:
    @pytest.mark.asyncio
    async def test_yields_one_per_missing_product(
        self,
        db: Database,
        tmp_path,
    ) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        # 3 companies; 1 will get a product, the other 2 won't.
        await mgr.create("with-product", "With Product")
        await mgr.create("missing-a", "Missing A")
        await mgr.create("missing-b", "Missing B")

        # Seed a product yaml for one company
        target = tmp_path / "companies" / "with-product" / "company.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "name: With Product\nwhat_we_sell: Real thing.\n", encoding="utf-8"
        )

        ctx = CandidateContext(
            company_manager=mgr,
            project_root=tmp_path,
        )
        candidates = await from_unproductized_companies(ctx)
        slugs = {c.metadata["company_id"] for c in candidates}
        # elophanto-self default seed also exists (from db.initialize) +
        # the two unseeded companies, but with-product is excluded.
        assert "with-product" not in slugs
        assert "missing-a" in slugs
        assert "missing-b" in slugs

    @pytest.mark.asyncio
    async def test_returns_empty_without_manager(self) -> None:
        ctx = CandidateContext()  # no company_manager, no project_root
        assert await from_unproductized_companies(ctx) == []

    @pytest.mark.asyncio
    async def test_returns_empty_without_project_root(self, db: Database) -> None:
        mgr = CompanyManager(db=db)  # no project_root
        ctx = CandidateContext(company_manager=mgr)
        assert await from_unproductized_companies(ctx) == []

    @pytest.mark.asyncio
    async def test_caps_at_three(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        # Create 5 unproductized companies (plus the default seed = 6).
        for i in range(5):
            await mgr.create(f"co-{i}", f"Co {i}")
        ctx = CandidateContext(company_manager=mgr, project_root=tmp_path)
        candidates = await from_unproductized_companies(ctx)
        assert len(candidates) == 3
