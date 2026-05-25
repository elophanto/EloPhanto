"""Product loader + arbiter KPI-gap (ABE framework Phase 4).

Locks in the Phase 4 contract from docs/76-ABE-FRAMEWORK.md:
- load_product returns None for missing file, empty what_we_sell,
  malformed YAML, or non-mapping top-level (navel-gazing guard).
- Arbiter kpi_gap term adds to score linearly with the weight.
- Legacy Candidate (no kpi_gap field) scores identically pre/post.
- from_role_neglect populates kpi_gap from ledger sums vs role.kpi.
- Dream-phase context includes / omits PRODUCT block correctly.
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.company import (
    reset_current_company,
    set_current_company,
)
from core.database import Database
from core.ledger import LedgerEntry, ResourceLedger
from core.mind_arbiter import ArbiterWeights, Candidate, score_candidate
from core.mind_candidates import CandidateContext, from_role_neglect
from core.product import Product, load_product
from core.role import RoleManager


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()
    return db


@pytest.fixture
async def role_mgr(db: Database, tmp_path) -> RoleManager:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    return RoleManager(db=db, roles_dir=roles_dir)


def _write_product_yaml(root: Path, company_id: str, body: str) -> Path:
    """Write companies/<slug>/company.yaml under a project root."""
    target = root / "companies" / company_id / "company.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(body), encoding="utf-8")
    return target


class TestProductLoader:
    def test_missing_file_returns_none(self, tmp_path) -> None:
        assert load_product(tmp_path, "anybody") is None

    def test_empty_what_we_sell_returns_none(self, tmp_path) -> None:
        _write_product_yaml(
            tmp_path,
            "acme",
            """
            name: Acme
            what_we_sell: ""
            """,
        )
        # Empty `what_we_sell` is the navel-gazing guard. Returns None
        # even though the file exists.
        assert load_product(tmp_path, "acme") is None

    def test_whitespace_only_what_we_sell_returns_none(self, tmp_path) -> None:
        _write_product_yaml(
            tmp_path,
            "acme",
            """
            name: Acme
            what_we_sell: "   \n   "
            """,
        )
        assert load_product(tmp_path, "acme") is None

    def test_happy_path_roundtrip(self, tmp_path) -> None:
        _write_product_yaml(
            tmp_path,
            "acme",
            """
            name: Acme Inc
            what_we_sell: Boutique automations for indie operators.
            price:
              amount: 100
              currency: USD
              model: hourly
            fulfillment: |
              Operator builds + ships.
            channels: [cli, telegram]
            wallet:
              chain: solana
              address: ""
            kpis:
              - type: pipeline_advance
                target_weekly: 5
              - type: email_sent
                target_weekly: 20
            """,
        )
        p = load_product(tmp_path, "acme")
        assert isinstance(p, Product)
        assert p.name == "Acme Inc"
        assert "Boutique automations" in p.what_we_sell
        assert p.price == {"amount": 100, "currency": "USD", "model": "hourly"}
        assert "Operator builds" in p.fulfillment
        assert p.channels == ["cli", "telegram"]
        assert p.wallet == {"chain": "solana", "address": ""}
        assert len(p.kpis) == 2
        assert p.kpis[0]["type"] == "pipeline_advance"
        assert p.kpis[0]["target_weekly"] == 5

    def test_malformed_yaml_returns_none(self, tmp_path) -> None:
        target = tmp_path / "companies" / "broken" / "company.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("not: valid: yaml: at: all:\n  :::\n", encoding="utf-8")
        assert load_product(tmp_path, "broken") is None

    def test_non_mapping_returns_none(self, tmp_path) -> None:
        _write_product_yaml(
            tmp_path,
            "list_only",
            """
            - just
            - a
            - list
            """,
        )
        assert load_product(tmp_path, "list_only") is None


class TestArbiterKpiGapTerm:
    def test_kpi_gap_adds_to_score(self) -> None:
        weights = ArbiterWeights()  # defaults; kpi_gap_weight = 0.4
        base = Candidate(source="t", action_spec="x", kpi_gap=0.0)
        gapped = Candidate(source="t", action_spec="x", kpi_gap=1.0)

        s_base = score_candidate(base, weights)
        s_gapped = score_candidate(gapped, weights)
        # kpi_gap=1.0 → +4.0 raw points (0.4 weight × 10 multiplier)
        assert s_gapped - s_base == pytest.approx(4.0)

    def test_kpi_gap_weight_tunable(self) -> None:
        weights_off = ArbiterWeights(kpi_gap_weight=0.0)
        weights_on = ArbiterWeights(kpi_gap_weight=1.0)
        c = Candidate(source="t", action_spec="x", kpi_gap=0.5)
        # 0 weight = no contribution; 1.0 weight × 0.5 gap × 10 = +5
        assert score_candidate(c, weights_off) == pytest.approx(
            score_candidate(Candidate(source="t", action_spec="x"), weights_off)
        )
        diff = score_candidate(c, weights_on) - score_candidate(
            Candidate(source="t", action_spec="x"), weights_on
        )
        assert diff == pytest.approx(5.0)

    def test_legacy_candidate_default_zero(self) -> None:
        # A Candidate constructed without specifying kpi_gap should
        # behave like every existing pre-Phase-4 candidate (no boost,
        # no crash, no contribution to score).
        c = Candidate(source="t", action_spec="x")
        assert c.kpi_gap == 0.0
        weights = ArbiterWeights()
        # Equal to a candidate that explicitly set kpi_gap=0.0
        c2 = Candidate(source="t", action_spec="x", kpi_gap=0.0)
        assert score_candidate(c, weights) == score_candidate(c2, weights)

    def test_from_config_dict_accepts_kpi_gap_weight(self) -> None:
        w = ArbiterWeights.from_config_dict({"kpi_gap_weight": 0.7})
        assert w.kpi_gap_weight == 0.7

    def test_from_config_dict_ignores_missing(self) -> None:
        w = ArbiterWeights.from_config_dict({"value": 2.0})
        assert w.value == 2.0
        assert w.kpi_gap_weight == 0.4  # default


class TestFromRoleNeglectKpiGap:
    @pytest.mark.asyncio
    async def test_populates_gap_from_ledger(
        self, db: Database, role_mgr: RoleManager
    ) -> None:
        # Sales role wants 10 pipeline_advances/week; ledger has 3.
        # Gap = (10-3)/10 = 0.7.
        await role_mgr.upsert(
            name="sales",
            description="Pipeline",
            kpi={"pipeline_advance": 10.0},
        )
        ledger = ResourceLedger(db)
        for _ in range(3):
            await ledger.write(
                LedgerEntry(
                    company_id="elophanto-self",
                    direction="in",
                    type="pipeline_advance",
                    amount=1.0,
                    unit="count",
                )
            )

        ctx = CandidateContext(role_manager=role_mgr)
        candidates = await from_role_neglect(ctx)
        sales_cand = next(
            c for c in candidates if c.metadata.get("role_name") == "sales"
        )
        assert sales_cand.kpi_gap == pytest.approx(0.7)

    @pytest.mark.asyncio
    async def test_no_kpi_means_zero_gap(
        self, db: Database, role_mgr: RoleManager
    ) -> None:
        await role_mgr.upsert(name="ceo", description="Default", kpi={})
        ctx = CandidateContext(role_manager=role_mgr)
        candidates = await from_role_neglect(ctx)
        ceo_cand = next(c for c in candidates if c.metadata.get("role_name") == "ceo")
        assert ceo_cand.kpi_gap == 0.0

    @pytest.mark.asyncio
    async def test_gap_capped_at_one(self, db: Database, role_mgr: RoleManager) -> None:
        await role_mgr.upsert(
            name="sales",
            kpi={"pipeline_advance": 10.0},
        )
        # No ledger entries — gap = (10-0)/10 = 1.0
        ctx = CandidateContext(role_manager=role_mgr)
        candidates = await from_role_neglect(ctx)
        sales = next(c for c in candidates if c.metadata.get("role_name") == "sales")
        assert sales.kpi_gap == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_gap_excludes_rows_older_than_7d(
        self, db: Database, role_mgr: RoleManager
    ) -> None:
        await role_mgr.upsert(
            name="sales",
            kpi={"pipeline_advance": 10.0},
        )
        # Insert an old ledger row directly (8 days ago) — should NOT
        # count toward the past-7d window the gap calc uses.
        old_ts = (datetime.now(UTC) - timedelta(days=8)).isoformat()
        await db.execute_insert(
            "INSERT INTO resource_ledger "
            "(company_id, ts, direction, type, amount, unit) "
            "VALUES ('elophanto-self', ?, 'in', 'pipeline_advance', 5.0, 'count')",
            (old_ts,),
        )
        ctx = CandidateContext(role_manager=role_mgr)
        candidates = await from_role_neglect(ctx)
        sales = next(c for c in candidates if c.metadata.get("role_name") == "sales")
        # Old row shouldn't reduce the gap from 1.0
        assert sales.kpi_gap == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_gap_respects_active_company(
        self, db: Database, role_mgr: RoleManager
    ) -> None:
        await role_mgr.upsert(
            name="sales",
            kpi={"pipeline_advance": 5.0},
        )
        # 3 advances under acme-inc, none under elophanto-self
        ledger = ResourceLedger(db)
        for _ in range(3):
            await ledger.write(
                LedgerEntry(
                    company_id="acme-inc",
                    direction="in",
                    type="pipeline_advance",
                    amount=1.0,
                    unit="count",
                )
            )

        # Under elophanto-self (the default), gap is full (no progress)
        ctx = CandidateContext(role_manager=role_mgr)
        candidates = await from_role_neglect(ctx)
        sales = next(c for c in candidates if c.metadata.get("role_name") == "sales")
        assert sales.kpi_gap == pytest.approx(1.0)

        # Switching to acme-inc, gap reflects the 3 advances
        token = set_current_company("acme-inc")
        try:
            ctx2 = CandidateContext(role_manager=role_mgr)
            candidates2 = await from_role_neglect(ctx2)
        finally:
            reset_current_company(token)
        sales2 = next(c for c in candidates2 if c.metadata.get("role_name") == "sales")
        assert sales2.kpi_gap == pytest.approx(0.4)  # (5-3)/5


class TestDreamContextProduct:
    """Smoke tests at the loader level. End-to-end dream-context
    assembly involves enough other manager wiring that a behavioural
    test is heavier than warranted for Phase 4 — the load_product
    contract above is what actually controls whether the block fires.
    """

    def test_loader_invoked_for_active_company(self, tmp_path) -> None:
        _write_product_yaml(
            tmp_path,
            "elophanto-self",
            """
            name: Default
            what_we_sell: Things and stuff.
            """,
        )
        # Confirms the convention path lookup works with the loader.
        p = load_product(tmp_path, "elophanto-self")
        assert p is not None
        assert "Things and stuff" in p.what_we_sell

    def test_loader_returns_none_for_unproductized_company(self, tmp_path) -> None:
        # No yaml at all → loader silently returns None and the dream
        # phase will skip the PRODUCT block.
        assert load_product(tmp_path, "ghost-co") is None
