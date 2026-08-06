"""Company posture (maturity × objective) — load/save, arbiter bias, spend."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.mind_arbiter import ArbiterWeights, Candidate, arbitrate, score_candidate
from core.posture import (
    INTENT_PRESETS,
    Posture,
    load_posture,
    merge_arbiter_weights,
    role_priority_weights,
    save_posture,
    source_multipliers,
    spend_allowed,
)
from tools.strategy._prompts import build_system_prompt


def _write_company(tmp: Path, slug: str, doc: dict) -> Path:
    p = tmp / "companies" / slug / "company.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return p


class TestPostureLoadSave:
    def test_defaults_when_missing(self, tmp_path: Path) -> None:
        p = load_posture(tmp_path, "missing")
        assert p.maturity == "scaling"
        assert p.objective == "balance"

    def test_falls_back_to_strategy_inputs_maturity(self, tmp_path: Path) -> None:
        _write_company(
            tmp_path,
            "co",
            {
                "name": "Co",
                "what_we_sell": "X",
                "strategy_inputs": {"maturity": "early"},
            },
        )
        p = load_posture(tmp_path, "co")
        assert p.maturity == "early"
        assert p.objective == "balance"

    def test_save_mirrors_maturity_into_strategy_inputs(self, tmp_path: Path) -> None:
        _write_company(tmp_path, "co", {"name": "Co", "what_we_sell": "X"})
        save_posture(tmp_path, "co", Posture("pre_revenue", "validate"))
        loaded = yaml.safe_load(
            (tmp_path / "companies" / "co" / "company.yaml").read_text()
        )
        assert loaded["posture"] == {"maturity": "pre_revenue", "objective": "validate"}
        assert loaded["strategy_inputs"]["maturity"] == "pre_revenue"
        assert load_posture(tmp_path, "co").label() == "pre_revenue/validate"

    def test_intent_presets(self) -> None:
        assert INTENT_PRESETS["startup_founder"] == ("pre_revenue", "validate")
        assert INTENT_PRESETS["profitability"][1] == "profit"


class TestArbiterPostureBias:
    def test_profit_penalizes_buildable_more_than_balance(self) -> None:
        build = Candidate(
            source="buildable_blocker",
            action_spec="build missing tool",
            expected_value=9.0,
            feasibility=0.6,
            cost=4.0,
            staleness_bonus=5.0,
            dedup_key="b1",
        )
        checkpoint = Candidate(
            source="workable_checkpoint",
            action_spec="advance ckpt",
            expected_value=7.0,
            feasibility=0.85,
            cost=2.0,
            dedup_key="c1",
        )
        base = ArbiterWeights()
        profit_w = merge_arbiter_weights(base, "profit")
        balance_scores = {
            c.source: score_candidate(
                c, base, source_multipliers=source_multipliers("balance") or None
            )
            for c in (build, checkpoint)
        }
        profit_scores = {
            c.source: score_candidate(
                c,
                profit_w,
                source_multipliers=source_multipliers("profit"),
            )
            for c in (build, checkpoint)
        }
        # Under profit, buildable should drop relative to checkpoint vs balance.
        bal_gap = (
            balance_scores["buildable_blocker"] - balance_scores["workable_checkpoint"]
        )
        prof_gap = (
            profit_scores["buildable_blocker"] - profit_scores["workable_checkpoint"]
        )
        assert prof_gap < bal_gap

    def test_validate_boosts_sales_role_over_marketing(self) -> None:
        sales = Candidate(
            source="role_neglect",
            action_spec="sales",
            expected_value=2.5,
            feasibility=0.7,
            staleness_bonus=6.0,
            dedup_key="role_switch:sales",
            metadata={"role_name": "sales"},
        )
        marketing = Candidate(
            source="role_neglect",
            action_spec="marketing",
            expected_value=2.5,
            feasibility=0.7,
            staleness_bonus=6.0,
            dedup_key="role_switch:marketing",
            metadata={"role_name": "marketing"},
        )
        weights = ArbiterWeights()
        scored = arbitrate(
            [marketing, sales],
            weights,
            top_k=2,
            role_priorities=role_priority_weights("validate"),
        )
        assert scored[0].candidate.metadata["role_name"] == "sales"

    def test_growth_role_priorities_favor_sales_marketing(self) -> None:
        prio = role_priority_weights("growth")
        assert prio["sales"] > prio["ops"]
        assert prio["marketing"] > prio["support"]


class TestSpendEnvelope:
    def test_validate_blocks_spend(self) -> None:
        ok, reason = spend_allowed(Posture("pre_revenue", "validate"))
        assert ok is False
        assert "validate" in reason

    def test_profit_blocks_when_burning(self) -> None:
        ok, _ = spend_allowed(
            Posture("scaling", "profit"), net_usd=-10.0, runway_weeks=1.0
        )
        assert ok is False

    def test_profit_allows_when_healthy(self) -> None:
        ok, _ = spend_allowed(
            Posture("scaling", "profit"), net_usd=50.0, runway_weeks=8.0
        )
        assert ok is True

    def test_balance_allows(self) -> None:
        ok, _ = spend_allowed(Posture("established", "balance"), net_usd=-5.0)
        assert ok is True


class TestStrategyPromptObjective:
    def test_validate_objective_in_prompt(self) -> None:
        p = build_system_prompt(maturity="pre_revenue", objective="validate")
        assert "OBJECTIVE - VALIDATE" in p
        assert "STAGE DISCIPLINE - PRE-REVENUE" in p

    def test_established_maturity(self) -> None:
        p = build_system_prompt(maturity="established", objective="balance")
        assert "STAGE DISCIPLINE - ESTABLISHED" in p
        assert "OBJECTIVE - BALANCE" in p

    def test_profit_objective(self) -> None:
        p = build_system_prompt(maturity="scaling", objective="profit")
        assert "OBJECTIVE - PROFIT" in p


@pytest.mark.asyncio
async def test_company_set_posture_tool(tmp_path: Path) -> None:
    from tools.companies.set_posture_tool import CompanySetPostureTool

    _write_company(tmp_path, "acme", {"name": "Acme", "what_we_sell": "Widgets"})
    tool = CompanySetPostureTool()
    tool._project_root = tmp_path
    r = await tool.execute({"slug": "acme", "intent": "startup_founder"})
    assert r.success is True
    assert r.data["posture"]["maturity"] == "pre_revenue"
    assert r.data["posture"]["objective"] == "validate"


def test_merge_carries_unnamed_weights_through() -> None:
    """Overrides must not reset weights they don't mention.

    Regression guard: an earlier version rebuilt ArbiterWeights from an
    enumerated field list, so any weight added later would silently snap back
    to its default — a wrong-but-plausible tuning value nobody would notice.
    """
    from dataclasses import fields

    from core.mind_arbiter import ArbiterWeights
    from core.posture import arbiter_weight_overrides, merge_arbiter_weights

    # A base deliberately far from defaults on every field.
    base = ArbiterWeights(**{f.name: 0.123 for f in fields(ArbiterWeights)})
    for objective in ("validate", "growth", "profit"):
        merged = merge_arbiter_weights(base, objective)
        overrides = arbiter_weight_overrides(objective)
        assert overrides, objective
        assert isinstance(merged, ArbiterWeights)
        for f in fields(ArbiterWeights):
            expected = overrides.get(f.name, 0.123)
            assert getattr(merged, f.name) == pytest.approx(expected), (
                f"{objective}/{f.name} was not carried through"
            )


def test_merge_is_identity_for_balance() -> None:
    from core.mind_arbiter import ArbiterWeights
    from core.posture import merge_arbiter_weights

    base = ArbiterWeights()
    assert merge_arbiter_weights(base, "balance") is base
    # Unknown objectives normalise to balance rather than exploding.
    assert merge_arbiter_weights(base, "nonsense") is base
