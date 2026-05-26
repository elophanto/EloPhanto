"""Phase 11 wiring into the autonomous mind.

Locks in:
- from_unplanned_companies: surfaces productized companies without
  active strategy, skips planned ones, caps at 3, degrades gracefully
- from_blocked_strategy_days: requires age > 3d, unresolved blockers
- from_buildable_blockers: only fires for resolution=build with
  build_method set; one candidate per applicable blocker
- collect_all registers all three
- CandidateContext exposes strategy_manager
"""

from __future__ import annotations

import pytest

from core.company import CompanyManager
from core.database import Database
from core.mind_candidates import (
    CandidateContext,
    collect_all,
    from_blocked_strategy_days,
    from_buildable_blockers,
    from_unplanned_companies,
)
from core.strategy import Blocker, StrategyManager, save_blockers


def _write_product_yaml(tmp_path, slug: str) -> None:
    p = tmp_path / "companies" / slug / "company.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "name: " + slug + "\nwhat_we_sell: Real concrete deliverable for clients.\n",
        encoding="utf-8",
    )


def _seed_active_strategy(tmp_path, slug: str, name: str = "v1") -> None:
    mgr = StrategyManager(tmp_path)
    prop = mgr.write_proposal(slug, {"strategyName": name, "tactics": []})
    mgr.promote_proposal(slug, prop)


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()
    return db


# ── from_unplanned_companies ────────────────────────────────────────


class TestUnplannedCompanies:
    @pytest.mark.asyncio
    async def test_yields_for_productized_without_strategy(
        self, db: Database, tmp_path
    ) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        await mgr.create("alphascala", "AlphaScala")
        _write_product_yaml(tmp_path, "alphascala")
        ctx = CandidateContext(
            company_manager=mgr,
            project_root=tmp_path,
            strategy_manager=StrategyManager(tmp_path),
        )
        out = await from_unplanned_companies(ctx)
        slugs = {c.metadata["company_id"] for c in out}
        assert "alphascala" in slugs

    @pytest.mark.asyncio
    async def test_skips_when_strategy_active(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        await mgr.create("co", "Co")
        _write_product_yaml(tmp_path, "co")
        _seed_active_strategy(tmp_path, "co")
        ctx = CandidateContext(
            company_manager=mgr,
            project_root=tmp_path,
            strategy_manager=StrategyManager(tmp_path),
        )
        out = await from_unplanned_companies(ctx)
        assert all(c.metadata["company_id"] != "co" for c in out)

    @pytest.mark.asyncio
    async def test_skips_unproductized(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        await mgr.create("co", "Co")
        # No company.yaml seeded — unproductized
        ctx = CandidateContext(
            company_manager=mgr,
            project_root=tmp_path,
            strategy_manager=StrategyManager(tmp_path),
        )
        out = await from_unplanned_companies(ctx)
        assert all(c.metadata["company_id"] != "co" for c in out)

    @pytest.mark.asyncio
    async def test_empty_without_strategy_manager(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        ctx = CandidateContext(
            company_manager=mgr, project_root=tmp_path, strategy_manager=None
        )
        assert await from_unplanned_companies(ctx) == []

    @pytest.mark.asyncio
    async def test_caps_at_three(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        for i in range(5):
            slug = f"co-{i}"
            await mgr.create(slug, slug)
            _write_product_yaml(tmp_path, slug)
        ctx = CandidateContext(
            company_manager=mgr,
            project_root=tmp_path,
            strategy_manager=StrategyManager(tmp_path),
        )
        out = await from_unplanned_companies(ctx)
        assert len(out) <= 3


# ── from_blocked_strategy_days ──────────────────────────────────────


class TestBlockedStrategyDays:
    @pytest.mark.asyncio
    async def test_skips_recent_strategy(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        await mgr.create("co", "Co")
        _seed_active_strategy(tmp_path, "co")
        # Recently active — no blockers yet
        save_blockers(
            tmp_path,
            "co",
            [Blocker(id="b1", type="missing_tool", description="x")],
        )
        ctx = CandidateContext(
            company_manager=mgr,
            project_root=tmp_path,
            strategy_manager=StrategyManager(tmp_path),
        )
        out = await from_blocked_strategy_days(ctx)
        # Strategy is fresh; should NOT fire (age < 3d)
        assert all(c.metadata["company_id"] != "co" for c in out)

    @pytest.mark.asyncio
    async def test_skips_when_no_blockers(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        await mgr.create("co", "Co")
        _seed_active_strategy(tmp_path, "co")
        ctx = CandidateContext(
            company_manager=mgr,
            project_root=tmp_path,
            strategy_manager=StrategyManager(tmp_path),
        )
        out = await from_blocked_strategy_days(ctx)
        assert out == []


# ── from_buildable_blockers ─────────────────────────────────────────


class TestBuildableBlockers:
    @pytest.mark.asyncio
    async def test_fires_for_build_proposals(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        await mgr.create("co", "Co")
        _seed_active_strategy(tmp_path, "co")
        save_blockers(
            tmp_path,
            "co",
            [
                Blocker(
                    id="b1",
                    type="missing_tool",
                    description="LinkedIn poster",
                    affected_tactics=["t5"],
                    resolution_proposal="build",
                    build_method="self_create_plugin",
                    build_hint="Selenium",
                ),
                Blocker(
                    id="b2",
                    type="missing_vault_credential",
                    description="SMTP",
                    resolution_proposal="ask",  # excluded
                ),
            ],
        )
        ctx = CandidateContext(
            company_manager=mgr,
            project_root=tmp_path,
            strategy_manager=StrategyManager(tmp_path),
        )
        out = await from_buildable_blockers(ctx)
        assert len(out) == 1
        assert out[0].metadata["blocker_id"] == "b1"
        assert out[0].metadata["build_method"] == "self_create_plugin"
        assert "self_create_plugin" in out[0].action_spec

    @pytest.mark.asyncio
    async def test_skips_resolved(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        await mgr.create("co", "Co")
        _seed_active_strategy(tmp_path, "co")
        b = Blocker(
            id="b1",
            type="missing_tool",
            description="x",
            resolution_proposal="build",
            build_method="self_create_plugin",
        )
        b.resolved_at = "2026-05-26T10:00:00+00:00"
        save_blockers(tmp_path, "co", [b])
        ctx = CandidateContext(
            company_manager=mgr,
            project_root=tmp_path,
            strategy_manager=StrategyManager(tmp_path),
        )
        out = await from_buildable_blockers(ctx)
        assert out == []

    @pytest.mark.asyncio
    async def test_empty_without_strategy_manager(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        ctx = CandidateContext(
            company_manager=mgr, project_root=tmp_path, strategy_manager=None
        )
        assert await from_buildable_blockers(ctx) == []


# ── collect_all registration ────────────────────────────────────────


class TestCollectAll:
    @pytest.mark.asyncio
    async def test_includes_unplanned(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        await mgr.create("co", "Co")
        _write_product_yaml(tmp_path, "co")
        ctx = CandidateContext(
            company_manager=mgr,
            project_root=tmp_path,
            strategy_manager=StrategyManager(tmp_path),
        )
        out = await collect_all(ctx)
        sources = {c.source for c in out}
        assert "unplanned_company" in sources

    @pytest.mark.asyncio
    async def test_includes_buildable(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        await mgr.create("co", "Co")
        _seed_active_strategy(tmp_path, "co")
        save_blockers(
            tmp_path,
            "co",
            [
                Blocker(
                    id="b1",
                    type="missing_tool",
                    description="x",
                    resolution_proposal="build",
                    build_method="self_create_plugin",
                )
            ],
        )
        ctx = CandidateContext(
            company_manager=mgr,
            project_root=tmp_path,
            strategy_manager=StrategyManager(tmp_path),
        )
        out = await collect_all(ctx)
        assert "buildable_blocker" in {c.source for c in out}
