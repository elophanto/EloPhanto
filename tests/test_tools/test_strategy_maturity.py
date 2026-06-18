"""Founder-doctrine Stage 0 (P0-5) — strategy `maturity` gates channel
breadth in build_system_prompt, and company_set_strategy_inputs persists it.

See tmp/founder-vs-elophanto-audit-2026-06-18.md Phase 6 (§6.10/§6.11).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.companies.set_strategy_inputs_tool import CompanySetStrategyInputsTool
from tools.strategy._prompts import build_system_prompt

_MULTI_SURFACE = "address every distinct surface"
_PRE = "STAGE DISCIPLINE - PRE-REVENUE"
_EARLY = "STAGE DISCIPLINE - EARLY"


class TestMaturityBranch:
    def test_pre_revenue_forces_one_channel_no_multisurface(self) -> None:
        p = build_system_prompt(maturity="pre_revenue")
        assert _PRE in p
        assert "exactly ONE primary acquisition channel" in p
        # The multi-surface mandate must NOT appear pre-revenue.
        assert _MULTI_SURFACE not in p

    def test_early_allows_capped_second_channel(self) -> None:
        p = build_system_prompt(maturity="early")
        assert _EARLY in p
        assert "~20%" in p
        assert _MULTI_SURFACE not in p

    def test_scaling_keeps_multisurface(self) -> None:
        p = build_system_prompt(maturity="scaling")
        assert _MULTI_SURFACE in p
        assert "STAGE DISCIPLINE" not in p

    def test_default_equals_scaling_backcompat(self) -> None:
        # Existing callers that don't pass maturity must be unchanged.
        assert build_system_prompt() == build_system_prompt(maturity="scaling")

    def test_unknown_maturity_falls_back_to_scaling(self) -> None:
        # Defensive: a typo'd maturity should not strip the multi-surface
        # mandate (the else-branch is the safe default).
        p = build_system_prompt(maturity="nonsense")
        assert _MULTI_SURFACE in p


def _write_company_yaml(tmp_path: Path, slug: str, doc: dict[str, Any]) -> Path:
    p = tmp_path / "companies" / slug / "company.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return p


class TestSetStrategyInputsMaturity:
    @pytest.mark.asyncio
    async def test_persists_maturity(self, tmp_path: Path) -> None:
        _write_company_yaml(tmp_path, "co", {"name": "Co", "what_we_sell": "X"})
        tool = CompanySetStrategyInputsTool()
        tool._project_root = tmp_path
        r = await tool.execute({"slug": "co", "maturity": "pre_revenue"})
        assert r.success is True
        loaded = yaml.safe_load(
            (tmp_path / "companies" / "co" / "company.yaml").read_text()
        )
        assert loaded["strategy_inputs"]["maturity"] == "pre_revenue"

    @pytest.mark.asyncio
    async def test_unknown_maturity_lenient_still_writes(self, tmp_path: Path) -> None:
        # Mirrors the strategy_mode/focus behavior: log a warning but accept;
        # build_system_prompt's else-branch keeps it safe downstream.
        _write_company_yaml(tmp_path, "co", {"name": "Co", "what_we_sell": "X"})
        tool = CompanySetStrategyInputsTool()
        tool._project_root = tmp_path
        r = await tool.execute({"slug": "co", "maturity": "bogus"})
        assert r.success is True
        loaded = yaml.safe_load(
            (tmp_path / "companies" / "co" / "company.yaml").read_text()
        )
        assert loaded["strategy_inputs"]["maturity"] == "bogus"
