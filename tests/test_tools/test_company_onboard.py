"""``company_onboard`` end-to-end tool tests (ABE Phase 8.5).

Locks in the orchestration: company_create + persist context +
write product YAML + optional seed goal, all under a single
MODERATE approval. The gap review (2026-05-26) flagged that
forcing the LLM to chain those four calls correctly was the main
reason 'I have a business on X, drive it' didn't work end-to-end.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.company import (
    CompanyManager,
    read_persisted_current_company,
    set_current_company,
)
from core.config import GoalsConfig
from core.database import Database
from core.goal_manager import GoalManager
from core.product import load_product
from tools.companies.onboard_tool import CompanyOnboardTool


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()
    return db


@pytest.fixture
async def company_mgr(db: Database, tmp_path) -> CompanyManager:
    return CompanyManager(db=db, project_root=tmp_path)


@pytest.fixture
async def goal_mgr(db: Database) -> GoalManager:
    return GoalManager(db=db, router=MagicMock(), config=GoalsConfig())


@pytest.fixture
def tool(
    db: Database,
    tmp_path,
    company_mgr: CompanyManager,
    goal_mgr: GoalManager,
) -> CompanyOnboardTool:
    t = CompanyOnboardTool()
    t._db = db
    t._project_root = tmp_path
    t._company_manager = company_mgr
    t._goal_manager = goal_mgr
    return t


@pytest.fixture(autouse=True)
def reset_sidecar_after_test(tmp_path, monkeypatch):
    """Each test runs with an isolated sidecar so persistence
    doesn't leak across tests / into the operator's real home dir."""
    sidecar = tmp_path / ".elophanto-test" / "current_company"
    monkeypatch.setattr("core.company._CURRENT_COMPANY_FILE", sidecar)
    yield
    # Reset contextvar back to default at end of every test
    try:
        set_current_company("elophanto-self")
    except Exception:
        pass


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_onboard_creates_and_persists_and_writes_yaml(
        self, tool: CompanyOnboardTool, tmp_path
    ) -> None:
        result = await tool.execute(
            {
                "slug": "acme-inc",
                "name": "Acme Inc",
                "what_we_sell": (
                    "Boutique automations for indie operators — "
                    "we ship agent-built lead-gen pipelines per "
                    "engagement."
                ),
                "price": {"amount": 100, "currency": "USD", "model": "hourly"},
                "kpis": [{"type": "pipeline_advance", "target_weekly": 5}],
            }
        )
        assert result.success is True
        assert result.data["slug"] == "acme-inc"
        assert result.data["active_session_persisted"] is True

        # YAML landed at the canonical path with the right fields
        product = load_product(tmp_path, "acme-inc")
        assert product is not None
        assert "Boutique automations" in product.what_we_sell
        assert product.price == {
            "amount": 100,
            "currency": "USD",
            "model": "hourly",
        }
        # Sidecar was written (mind will inherit on next cycle)
        assert read_persisted_current_company() == "acme-inc"

    @pytest.mark.asyncio
    async def test_seed_goal_creates_goal_row(
        self,
        tool: CompanyOnboardTool,
        goal_mgr: GoalManager,
    ) -> None:
        result = await tool.execute(
            {
                "slug": "acme-inc",
                "what_we_sell": "Real product for real customers.",
                "seed_goal": (
                    "Research 20 qualified prospects for acme-inc and "
                    "capture them in the CRM."
                ),
            }
        )
        assert result.success is True
        gid = result.data["seed_goal_id"]
        assert gid is not None
        goal = await goal_mgr.get_goal(gid)
        assert goal is not None
        assert "acme-inc" in goal.goal

    @pytest.mark.asyncio
    async def test_no_seed_goal_returns_none(self, tool: CompanyOnboardTool) -> None:
        result = await tool.execute(
            {"slug": "acme", "what_we_sell": "Concrete deliverable for clients."}
        )
        assert result.success
        assert result.data["seed_goal_id"] is None


class TestValidation:
    @pytest.mark.asyncio
    async def test_missing_slug(self, tool: CompanyOnboardTool) -> None:
        result = await tool.execute({"what_we_sell": "x"})
        assert not result.success
        assert "slug" in result.error

    @pytest.mark.asyncio
    async def test_missing_what_we_sell(self, tool: CompanyOnboardTool) -> None:
        result = await tool.execute({"slug": "acme"})
        assert not result.success
        assert "what_we_sell" in result.error

    @pytest.mark.asyncio
    async def test_navel_gazing_what_we_sell_rejected(
        self, tool: CompanyOnboardTool
    ) -> None:
        # The shared consumer filter must apply here too — same
        # protection as company_set_product and the dream lens
        # rewrite. Agent can't bypass the banlist via the onboard
        # tool.
        result = await tool.execute(
            {
                "slug": "narcissist-co",
                "what_we_sell": "A framework for documenting self-perception.",
            }
        )
        assert not result.success
        assert "consumer filter" in result.error
        # And nothing was created — the early bail must precede
        # the create/persist/write side effects.
        assert load_product(tool._project_root, "narcissist-co") is None

    @pytest.mark.asyncio
    async def test_uninitialized_tool_fails(self) -> None:
        t = CompanyOnboardTool()  # no deps wired
        result = await t.execute({"slug": "x", "what_we_sell": "real product"})
        assert not result.success
        assert "not initialized" in result.error

    @pytest.mark.asyncio
    async def test_duplicate_slug_fails(
        self, tool: CompanyOnboardTool, company_mgr: CompanyManager
    ) -> None:
        await company_mgr.create("dup", "Dup Co")
        result = await tool.execute({"slug": "dup", "what_we_sell": "real deliverable"})
        assert not result.success
        assert "company_create failed" in result.error
