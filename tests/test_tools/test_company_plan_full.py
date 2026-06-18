"""``company_plan_full`` — bundled PATH B wrapper (Tier 1 #3, 2026-06-18).

Pins the contract that the wrapper:
- Runs the four sub-tools in sequence (capabilities → set_strategy_inputs
  → company_plan → company_plan_apply).
- Surfaces a one-paragraph aggregated summary instead of four nested ones.
- Bails on the first sub-tool failure with a named-error message
  identifying which step failed.
- Forwards strategy_inputs fields and plan overrides correctly.
- Appends the capability-audit preview to the planner's context so the
  strategy is grounded in what's actually registered.
- Refuses to run when the company doesn't exist yet (sets a clear
  pointer to company_onboard).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.base import ToolResult
from tools.companies.plan_full_tool import CompanyPlanFullTool


class FakeTool:
    """Async-executable stand-in for a registered sub-tool. Records the
    params it was called with so tests can assert on passthrough."""

    def __init__(self, result: ToolResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        self.calls.append(dict(params))
        return self.result


class FakeRegistry:
    """Minimal stand-in for ToolRegistry — only the .get() surface the
    wrapper uses."""

    def __init__(self, tools: dict[str, FakeTool | None]) -> None:
        self._tools = dict(tools)

    def get(self, name: str) -> FakeTool | None:
        return self._tools.get(name)


def _write_company_yaml(tmp_path: Path, slug: str) -> Path:
    """Materialize a minimal company.yaml so the wrapper's existence
    check passes."""
    path = tmp_path / "companies" / slug / "company.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"name": slug, "what_we_sell": "Real deliverable."}),
        encoding="utf-8",
    )
    return path


def _make_tool(
    tmp_path: Path,
    *,
    cap_result: ToolResult | None = None,
    set_inputs_result: ToolResult | None = None,
    plan_result: ToolResult | None = None,
    apply_result: ToolResult | None = None,
    register: tuple[str, ...] = (
        "company_capabilities",
        "company_set_strategy_inputs",
        "company_plan",
        "company_plan_apply",
    ),
) -> tuple[CompanyPlanFullTool, dict[str, FakeTool | None]]:
    """Construct a wired CompanyPlanFullTool with FakeTool sub-tools."""
    defaults = {
        "company_capabilities": cap_result
        or ToolResult(
            success=True,
            data={
                "preview": "VAULT: smtp\nTOOLS: email_send, twitter_post",
                "capabilities_md": str(tmp_path / "capabilities.md"),
            },
        ),
        "company_set_strategy_inputs": set_inputs_result
        or ToolResult(
            success=True,
            data={"path": str(tmp_path / "company.yaml")},
        ),
        "company_plan": plan_result
        or ToolResult(
            success=True,
            data={
                "proposal_path": str(tmp_path / "proposed" / "p.yaml"),
                "strategy_name": "Test Strategy",
                "tactic_count": 5,
            },
        ),
        "company_plan_apply": apply_result
        or ToolResult(
            success=True,
            data={
                "mission_id": "m_xyz",
                "goal_count": 3,
                "schedule_count": 2,
                "voice_proposed_path": str(tmp_path / "voice_proposed.yaml"),
                "blockers_count": 1,
                "blockers_md": str(tmp_path / "blockers.md"),
            },
        ),
    }
    tools: dict[str, FakeTool | None] = {
        name: (FakeTool(defaults[name]) if name in register else None)
        for name in defaults
    }
    tool = CompanyPlanFullTool()
    tool._project_root = tmp_path
    tool._registry = FakeRegistry(tools)
    return tool, tools


# ----------------------------------------------------------------------
# Happy path
# ----------------------------------------------------------------------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_runs_four_steps_and_aggregates(self, tmp_path: Path) -> None:
        _write_company_yaml(tmp_path, "acme")
        tool, subs = _make_tool(tmp_path)

        r = await tool.execute(
            {
                "slug": "acme",
                "target_audience": "indie operators",
                "primary_goals": ["Brand Awareness"],
                "risk_tolerance": 50,
                "strategy_mode": "standard",
                "focus": "content",
            }
        )

        assert r.success is True, r.error
        # All four sub-tools fired exactly once.
        assert len(subs["company_capabilities"].calls) == 1
        assert len(subs["company_set_strategy_inputs"].calls) == 1
        assert len(subs["company_plan"].calls) == 1
        assert len(subs["company_plan_apply"].calls) == 1

        # Aggregated data exposes every operator-relevant field.
        d = r.data
        assert d["slug"] == "acme"
        assert d["strategy_name"] == "Test Strategy"
        assert d["mission_id"] == "m_xyz"
        assert d["goal_count"] == 3
        assert d["schedule_count"] == 2
        assert d["tactic_count"] == 5
        assert d["blockers_count"] == 1
        assert "company_plan_approve" in (d["next"] or "")

    @pytest.mark.asyncio
    async def test_strategy_inputs_forwarded_to_set_inputs_tool(
        self, tmp_path: Path
    ) -> None:
        _write_company_yaml(tmp_path, "acme")
        tool, subs = _make_tool(tmp_path)

        await tool.execute(
            {
                "slug": "acme",
                "target_audience": "small SaaS teams",
                "competitors": "hubspot, customer.io",
                "budget_type": "organic",
                "budget_amount": 0,
                "primary_goals": ["Lead Gen"],
                "risk_tolerance": 30,
            }
        )

        set_inputs_call = subs["company_set_strategy_inputs"].calls[0]
        assert set_inputs_call["slug"] == "acme"
        assert set_inputs_call["target_audience"] == "small SaaS teams"
        assert set_inputs_call["competitors"] == "hubspot, customer.io"
        assert set_inputs_call["budget_type"] == "organic"
        assert set_inputs_call["budget_amount"] == 0
        assert set_inputs_call["primary_goals"] == ["Lead Gen"]
        assert set_inputs_call["risk_tolerance"] == 30
        # Slug is the only thing passed when the operator omits everything.
        # None values must not be forwarded (they would clobber existing).
        assert "industry" not in set_inputs_call

    @pytest.mark.asyncio
    async def test_overrides_forwarded_to_plan_tool(self, tmp_path: Path) -> None:
        _write_company_yaml(tmp_path, "acme")
        tool, subs = _make_tool(tmp_path)

        await tool.execute(
            {
                "slug": "acme",
                "override_strategy_mode": "guerrilla",
                "override_focus": "social",
            }
        )

        plan_call = subs["company_plan"].calls[0]
        assert plan_call["override_strategy_mode"] == "guerrilla"
        assert plan_call["override_focus"] == "social"
        assert plan_call["company_id"] == "acme"

    @pytest.mark.asyncio
    async def test_capability_preview_appended_to_plan_context(
        self, tmp_path: Path
    ) -> None:
        _write_company_yaml(tmp_path, "acme")
        cap_preview = "VAULT: smtp, twitter_token\nTOOLS: email_send, twitter_post"
        tool, subs = _make_tool(
            tmp_path,
            cap_result=ToolResult(
                success=True,
                data={
                    "preview": cap_preview,
                    "capabilities_md": str(tmp_path / "cap.md"),
                },
            ),
        )

        await tool.execute(
            {
                "slug": "acme",
                "context": "Prior research: founder reachable on X.",
            }
        )

        plan_call = subs["company_plan"].calls[0]
        # Operator context comes first, then the capability audit, both
        # separated so the LLM can attribute each to its source.
        assert "Prior research" in plan_call["context"]
        assert "CAPABILITY AUDIT" in plan_call["context"]
        assert cap_preview in plan_call["context"]

    @pytest.mark.asyncio
    async def test_proposal_path_threaded_into_apply(self, tmp_path: Path) -> None:
        """A concurrent operator-triggered company_plan can race the
        wrapper if apply picks 'newest proposal' implicitly. The
        wrapper threads the exact proposal_path it just wrote so
        whichever ran first lands its own artifact."""
        _write_company_yaml(tmp_path, "acme")
        proposal_path = str(tmp_path / "proposed" / "wrapper-output.yaml")
        tool, subs = _make_tool(
            tmp_path,
            plan_result=ToolResult(
                success=True,
                data={
                    "proposal_path": proposal_path,
                    "strategy_name": "X",
                    "tactic_count": 1,
                },
            ),
        )

        await tool.execute({"slug": "acme"})

        apply_call = subs["company_plan_apply"].calls[0]
        assert apply_call["proposal_path"] == proposal_path


# ----------------------------------------------------------------------
# Validation + initialization errors
# ----------------------------------------------------------------------


class TestValidation:
    @pytest.mark.asyncio
    async def test_missing_slug(self, tmp_path: Path) -> None:
        tool, _ = _make_tool(tmp_path)
        r = await tool.execute({})
        assert r.success is False
        assert "slug" in (r.error or "")

    @pytest.mark.asyncio
    async def test_missing_company_yaml(self, tmp_path: Path) -> None:
        # No _write_company_yaml — company doesn't exist.
        tool, _ = _make_tool(tmp_path)
        r = await tool.execute({"slug": "ghost"})
        assert r.success is False
        assert "company.yaml" in (r.error or "")
        assert "company_onboard" in (r.error or "")

    @pytest.mark.asyncio
    async def test_uninitialized_project_root(self) -> None:
        tool = CompanyPlanFullTool()
        # registry left None
        r = await tool.execute({"slug": "x"})
        assert r.success is False
        assert "not initialized" in (r.error or "")

    @pytest.mark.asyncio
    async def test_missing_subtools_surface_helpful_error(self, tmp_path: Path) -> None:
        _write_company_yaml(tmp_path, "acme")
        # Only register two of the four — wrapper should refuse with
        # a list naming the missing tools.
        tool, _ = _make_tool(
            tmp_path,
            register=("company_capabilities", "company_plan"),
        )
        r = await tool.execute({"slug": "acme"})
        assert r.success is False
        # The list of missing names appears in the error.
        assert "company_set_strategy_inputs" in (r.error or "")
        assert "company_plan_apply" in (r.error or "")


# ----------------------------------------------------------------------
# Per-step failure modes — wrapper must bail with a named error
# ----------------------------------------------------------------------


class TestStepFailures:
    @pytest.mark.asyncio
    async def test_capabilities_failure_bails_early(self, tmp_path: Path) -> None:
        _write_company_yaml(tmp_path, "acme")
        tool, subs = _make_tool(
            tmp_path,
            cap_result=ToolResult(success=False, error="vault locked"),
        )
        r = await tool.execute({"slug": "acme"})
        assert r.success is False
        assert "company_capabilities" in (r.error or "")
        assert "vault locked" in (r.error or "")
        # Downstream sub-tools must NOT have been called.
        assert subs["company_set_strategy_inputs"].calls == []
        assert subs["company_plan"].calls == []
        assert subs["company_plan_apply"].calls == []

    @pytest.mark.asyncio
    async def test_set_inputs_failure_bails(self, tmp_path: Path) -> None:
        _write_company_yaml(tmp_path, "acme")
        tool, subs = _make_tool(
            tmp_path,
            set_inputs_result=ToolResult(
                success=False, error="company.yaml write failed: permission denied"
            ),
        )
        r = await tool.execute({"slug": "acme"})
        assert r.success is False
        assert "company_set_strategy_inputs" in (r.error or "")
        assert "permission denied" in (r.error or "")
        # Capabilities ran (audit is harmless), but plan/apply didn't.
        assert len(subs["company_capabilities"].calls) == 1
        assert subs["company_plan"].calls == []
        assert subs["company_plan_apply"].calls == []

    @pytest.mark.asyncio
    async def test_plan_failure_bails(self, tmp_path: Path) -> None:
        _write_company_yaml(tmp_path, "acme")
        tool, subs = _make_tool(
            tmp_path,
            plan_result=ToolResult(
                success=False, error="strategy JSON parse failed after retry"
            ),
        )
        r = await tool.execute({"slug": "acme"})
        assert r.success is False
        assert "company_plan" in (r.error or "")
        assert "JSON parse" in (r.error or "")
        # set_inputs already wrote to company.yaml; that's intentional —
        # operator can fix the planner issue and re-run without losing
        # their strategy_inputs.
        assert len(subs["company_set_strategy_inputs"].calls) == 1
        assert subs["company_plan_apply"].calls == []

    @pytest.mark.asyncio
    async def test_apply_failure_bails(self, tmp_path: Path) -> None:
        _write_company_yaml(tmp_path, "acme")
        tool, subs = _make_tool(
            tmp_path,
            apply_result=ToolResult(
                success=False, error="proposal not found: /tmp/x.yaml"
            ),
        )
        r = await tool.execute({"slug": "acme"})
        assert r.success is False
        assert "company_plan_apply" in (r.error or "")
        # All three earlier steps ran.
        assert len(subs["company_capabilities"].calls) == 1
        assert len(subs["company_set_strategy_inputs"].calls) == 1
        assert len(subs["company_plan"].calls) == 1


# ----------------------------------------------------------------------
# Tool-surface metadata
# ----------------------------------------------------------------------


class TestSurface:
    def test_moderate_permission(self) -> None:
        from tools.base import PermissionLevel

        assert CompanyPlanFullTool().permission_level == PermissionLevel.MODERATE

    def test_slug_required_in_schema(self) -> None:
        schema = CompanyPlanFullTool().input_schema
        assert "slug" in schema["required"]
