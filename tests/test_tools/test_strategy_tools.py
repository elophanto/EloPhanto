"""Strategy tools — audit / plan / apply / approve + set_strategy_inputs
(ABE Phase 11)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.strategy import StrategyManager
from core.voice import VoiceManager  # noqa: F401  (kept for symmetry with apply tests)
from tools.companies.set_strategy_inputs_tool import CompanySetStrategyInputsTool
from tools.strategy.apply_tool import (
    CompanyPlanApplyTool,
    detect_blockers,
)
from tools.strategy.approve_tool import CompanyPlanApproveTool
from tools.strategy.audit_tool import CompanyCapabilitiesTool
from tools.strategy.plan_tool import CompanyPlanTool


@dataclass
class FakeResponse:
    content: str


class FakeRouter:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    async def complete(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return FakeResponse(content=self.payload)


class FakeTool:
    def __init__(self, name: str, group: str) -> None:
        self.name = name
        self.group = group


class FakeRegistry:
    def __init__(self, tools: list[FakeTool]) -> None:
        self._tools = list(tools)

    def all_tools(self) -> list[FakeTool]:
        return list(self._tools)


class FakeVault:
    def __init__(self, keys: list[str]) -> None:
        self._keys = list(keys)

    def list_keys(self) -> list[str]:
        return list(self._keys)


def _write_company_yaml(tmp_path: Path, slug: str, doc: dict[str, Any]) -> Path:
    p = tmp_path / "companies" / slug / "company.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return p


# ── Capabilities tool ────────────────────────────────────────────────


class TestCompanyCapabilities:
    @pytest.mark.asyncio
    async def test_initialized_path_writes_md(self, tmp_path) -> None:
        tool = CompanyCapabilitiesTool()
        tool._project_root = tmp_path
        tool._registry = FakeRegistry(
            [FakeTool("email_send", "email"), FakeTool("twitter_post", "social")]
        )
        tool._vault = FakeVault(["smtp"])
        r = await tool.execute({"company_id": "co"})
        assert r.success is True
        assert r.data["vault_keys_count"] == 1
        assert r.data["tool_count"] == 2
        assert "email" in r.data["tool_groups"]
        assert (tmp_path / "data" / "companies" / "co" / "capabilities.md").is_file()

    @pytest.mark.asyncio
    async def test_uninitialized(self) -> None:
        tool = CompanyCapabilitiesTool()
        r = await tool.execute({"company_id": "co"})
        assert r.success is False
        assert "project_root" in (r.error or "")


# ── Plan tool ────────────────────────────────────────────────────────


class TestCompanyPlan:
    @pytest.mark.asyncio
    async def test_writes_versioned_proposal(self, tmp_path) -> None:
        _write_company_yaml(
            tmp_path,
            "alphascala",
            {
                "name": "AlphaScala",
                "what_we_sell": "Trading platform for systematic traders.",
                "channels": ["twitter", "blog"],
                "strategy_inputs": {
                    "target_audience": "systematic traders",
                    "strategy_mode": "standard",
                    "focus": "content",
                    "primary_goals": ["Brand Awareness"],
                    "risk_tolerance": 50,
                    "budget": {"type": "organic", "amount": 0},
                },
            },
        )
        payload = (
            '{"strategyName": "AlphaScala Voice", "tagline": "Real signals", '
            '"tactics": [{"priority": 1, "name": "Daily X posts", '
            '"description": "Post one signal per day", "channel": "twitter"}], '
            '"voice_seed": {"hookTemplates": ["POV: <scenario>"], '
            '"banned_phrases": ["leverage"]}, '
            '"execution_priority": "staged"}'
        )
        tool = CompanyPlanTool()
        tool._project_root = tmp_path
        tool._router = FakeRouter(payload)
        tool._strategy_manager = StrategyManager(tmp_path)
        r = await tool.execute({"company_id": "alphascala"})
        assert r.success is True, r.error
        assert r.data["tactic_count"] == 1
        assert r.data["strategy_name"] == "AlphaScala Voice"
        prop_path = Path(r.data["proposal_path"])
        assert prop_path.is_file()
        assert prop_path.parent.name == "proposed"

    @pytest.mark.asyncio
    async def test_strips_code_fence(self, tmp_path) -> None:
        _write_company_yaml(
            tmp_path,
            "co",
            {"name": "Co", "what_we_sell": "X", "channels": ["twitter"]},
        )
        fenced = '```json\n{"strategyName": "fenced"}\n```'
        tool = CompanyPlanTool()
        tool._project_root = tmp_path
        tool._router = FakeRouter(fenced)
        tool._strategy_manager = StrategyManager(tmp_path)
        r = await tool.execute({"company_id": "co"})
        assert r.success is True

    @pytest.mark.asyncio
    async def test_handles_bad_json_after_retry(self, tmp_path) -> None:
        _write_company_yaml(
            tmp_path, "co", {"name": "Co", "what_we_sell": "X", "channels": []}
        )
        tool = CompanyPlanTool()
        tool._project_root = tmp_path
        tool._router = FakeRouter("not json at all")
        tool._strategy_manager = StrategyManager(tmp_path)
        r = await tool.execute({"company_id": "co"})
        assert r.success is False
        assert "JSON parse failed" in (r.error or "")

    @pytest.mark.asyncio
    async def test_refuses_without_company_yaml(self, tmp_path) -> None:
        tool = CompanyPlanTool()
        tool._project_root = tmp_path
        tool._router = FakeRouter("{}")
        tool._strategy_manager = StrategyManager(tmp_path)
        r = await tool.execute({"company_id": "missing"})
        assert r.success is False
        assert "company.yaml missing" in (r.error or "")

    @pytest.mark.asyncio
    async def test_uninitialized(self) -> None:
        tool = CompanyPlanTool()
        r = await tool.execute({"company_id": "co"})
        assert r.success is False


# ── Blocker detection ────────────────────────────────────────────────


class TestBlockerDetection:
    def test_missing_vault_credential(self) -> None:
        from core.capability_audit import CapabilityMap

        cap = CapabilityMap(vault_keys=["smtp"], vault_locked=False)
        proposal = {
            "vault_requirements": [
                {
                    "key": "twitter_session",
                    "needed_for_tactics": ["t1"],
                    "resolution_proposal": "ask",
                }
            ]
        }
        blockers = detect_blockers(proposal, cap)
        assert len(blockers) == 1
        assert blockers[0].type == "missing_vault_credential"
        assert blockers[0].resolution_proposal == "ask"

    def test_vault_locked_treats_as_unknown(self) -> None:
        from core.capability_audit import CapabilityMap

        cap = CapabilityMap(vault_keys=[], vault_locked=True)
        proposal = {
            "vault_requirements": [{"key": "smtp", "needed_for_tactics": ["t1"]}]
        }
        blockers = detect_blockers(proposal, cap)
        assert len(blockers) == 1
        assert "vault is locked" in blockers[0].description.lower()

    def test_missing_tool_build_proposal(self) -> None:
        from core.capability_audit import CapabilityMap

        cap = CapabilityMap(
            tools_by_group={"social": ["twitter_post"]}, vault_locked=True
        )
        proposal = {
            "tool_requirements": [
                {
                    "tool_name": "linkedin_post",
                    "needed_for_tactics": ["t5"],
                    "resolution_proposal": "build",
                    "build_method": "self_create_plugin",
                    "build_hint": "Selenium-based",
                }
            ]
        }
        blockers = detect_blockers(proposal, cap)
        assert len(blockers) == 1
        assert blockers[0].type == "missing_tool"
        assert blockers[0].resolution_proposal == "build"
        assert blockers[0].build_method == "self_create_plugin"

    def test_skip_when_tool_present(self) -> None:
        from core.capability_audit import CapabilityMap

        cap = CapabilityMap(tools_by_group={"email": ["email_send"]}, vault_locked=True)
        proposal = {
            "tool_requirements": [
                {"tool_name": "email_send", "needed_for_tactics": ["t1"]}
            ]
        }
        assert detect_blockers(proposal, cap) == []

    def test_voice_conflict(self) -> None:
        from core.capability_audit import CapabilityMap

        cap = CapabilityMap(vault_locked=True)
        proposal = {
            "creativeDirections": [
                {
                    "angleName": "Founder",
                    "hookTemplates": ["We leverage AI to ship faster"],
                }
            ]
        }
        voice = {"banned_phrases": ["leverage"]}
        blockers = detect_blockers(proposal, cap, voice)
        assert any(b.type == "voice_conflict" for b in blockers)


# ── Apply tool ───────────────────────────────────────────────────────


class FakeMission:
    def __init__(self) -> None:
        self.mission_id = "m_test"


class FakeMissionManager:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create(self, title, description, priority_weight=1.0, *, mission_id=None, owner_role=None):  # type: ignore[no-untyped-def]
        self.calls.append(
            {"title": title, "description": description, "owner_role": owner_role}
        )
        return FakeMission()


class FakeGoal:
    def __init__(self, goal_id: str) -> None:
        self.goal_id = goal_id


class FakeGoalManager:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create_goal(self, goal, session_id=None, *, mission_id=None, assigned_to_role=None, tactic_metadata=None):  # type: ignore[no-untyped-def]
        self.calls.append(
            {
                "goal": goal,
                "mission_id": mission_id,
                "assigned_to_role": assigned_to_role,
                "tactic_metadata": dict(tactic_metadata or {}),
            }
        )
        return FakeGoal(f"g_{len(self.calls)}")


class FakeScheduleEntry:
    def __init__(self, sid: str) -> None:
        self.schedule_id = sid


class FakeScheduler:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create_schedule(self, name, task_goal, cron_expression, description="", **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(
            {
                "name": name,
                "task_goal": task_goal,
                "cron": cron_expression,
            }
        )
        return FakeScheduleEntry(f"s_{len(self.calls)}")


def _seed_proposal(tmp_path: Path, slug: str, payload: dict[str, Any]) -> Path:
    mgr = StrategyManager(tmp_path)
    return mgr.write_proposal(slug, payload)


class TestCompanyPlanApply:
    @pytest.mark.asyncio
    async def test_promotes_creates_mission_and_goals(self, tmp_path) -> None:
        _seed_proposal(
            tmp_path,
            "alphascala",
            {
                "strategyName": "AlphaScala Voice",
                "overview": "Build organic distribution.",
                "tactics": [
                    {
                        "priority": 1,
                        "name": "Daily X posts",
                        "description": "Post one signal per day on Twitter",
                        "channel": "twitter",
                        "expectedImpact": "High",
                    },
                    {
                        "priority": 2,
                        "name": "Weekly blog",
                        "description": "One blog post per week",
                        "channel": "blog",
                    },
                ],
                "timeline": {
                    "month1": ["daily X posts"],
                    "month2": ["weekly blog"],
                },
                "voice_seed": {
                    "hookTemplates": ["POV: <scenario>"],
                    "banned_phrases": ["leverage"],
                },
                "execution_priority": "staged",
            },
        )
        tool = CompanyPlanApplyTool()
        tool._project_root = tmp_path
        tool._registry = FakeRegistry([])
        tool._vault = FakeVault([])
        tool._strategy_manager = StrategyManager(tmp_path)
        tool._mission_manager = FakeMissionManager()
        tool._goal_manager = FakeGoalManager()
        tool._scheduler = FakeScheduler()

        r = await tool.execute({"company_id": "alphascala"})
        assert r.success is True, r.error
        assert r.data["goals_created"] == 2
        assert r.data["schedules_created"] == 2
        # Active strategy now in place
        active = (
            tmp_path
            / "data"
            / "companies"
            / "alphascala"
            / "strategy"
            / "active"
            / "strategy.yaml"
        )
        assert active.is_file()
        # voice_proposed.yaml seeded
        voice_proposed = (
            tmp_path / "data" / "companies" / "alphascala" / "voice_proposed.yaml"
        )
        assert voice_proposed.is_file()
        text = voice_proposed.read_text()
        assert "leverage" in text
        # Goals carry tactic_metadata
        assert tool._goal_manager.calls[0]["tactic_metadata"]["tactic_id"] == "t1"
        assert tool._goal_manager.calls[0]["tactic_metadata"]["channel"] == "twitter"
        # Twitter tactic gets marketing role via channel mapping
        assert tool._goal_manager.calls[0]["assigned_to_role"] == "marketing"

    @pytest.mark.asyncio
    async def test_skips_voice_seed_when_active_voice_exists(self, tmp_path) -> None:
        # Active voice.yaml present — apply must NOT overwrite via voice_proposed
        voice_active = tmp_path / "data" / "companies" / "co" / "voice.yaml"
        voice_active.parent.mkdir(parents=True, exist_ok=True)
        voice_active.write_text("banned_phrases: [synergy]\n", encoding="utf-8")

        _seed_proposal(
            tmp_path,
            "co",
            {
                "strategyName": "v1",
                "tactics": [],
                "voice_seed": {"hookTemplates": ["x"]},
            },
        )
        tool = CompanyPlanApplyTool()
        tool._project_root = tmp_path
        tool._registry = FakeRegistry([])
        tool._vault = FakeVault([])
        tool._strategy_manager = StrategyManager(tmp_path)
        tool._mission_manager = FakeMissionManager()
        tool._goal_manager = FakeGoalManager()
        r = await tool.execute({"company_id": "co"})
        assert r.success is True
        # voice_proposed should NOT have been created
        assert not (
            tmp_path / "data" / "companies" / "co" / "voice_proposed.yaml"
        ).is_file()

    @pytest.mark.asyncio
    async def test_no_proposal(self, tmp_path) -> None:
        tool = CompanyPlanApplyTool()
        tool._project_root = tmp_path
        tool._registry = FakeRegistry([])
        tool._strategy_manager = StrategyManager(tmp_path)
        tool._mission_manager = FakeMissionManager()
        tool._goal_manager = FakeGoalManager()
        r = await tool.execute({"company_id": "co"})
        assert r.success is False
        assert "No proposals" in (r.error or "")

    @pytest.mark.asyncio
    async def test_writes_blockers(self, tmp_path) -> None:
        _seed_proposal(
            tmp_path,
            "co",
            {
                "strategyName": "v1",
                "tactics": [],
                "vault_requirements": [
                    {
                        "key": "twitter_session",
                        "needed_for_tactics": ["t1"],
                        "resolution_proposal": "ask",
                    }
                ],
                "tool_requirements": [
                    {
                        "tool_name": "linkedin_post",
                        "needed_for_tactics": ["t5"],
                        "resolution_proposal": "build",
                        "build_method": "self_create_plugin",
                        "build_hint": "Selenium",
                    }
                ],
            },
        )
        tool = CompanyPlanApplyTool()
        tool._project_root = tmp_path
        tool._registry = FakeRegistry([])
        tool._vault = FakeVault(["smtp"])  # vault unlocked, no matching keys
        tool._strategy_manager = StrategyManager(tmp_path)
        tool._mission_manager = FakeMissionManager()
        tool._goal_manager = FakeGoalManager()
        r = await tool.execute({"company_id": "co"})
        assert r.success is True
        assert r.data["blockers_total"] == 2
        bf = tmp_path / "data" / "companies" / "co" / "blockers.yaml"
        assert bf.is_file()
        loaded = yaml.safe_load(bf.read_text())
        assert len(loaded["blockers"]) == 2


# ── Approve tool ─────────────────────────────────────────────────────


class TestApprove:
    @pytest.mark.asyncio
    async def test_no_active_strategy(self, tmp_path) -> None:
        tool = CompanyPlanApproveTool()
        tool._strategy_manager = StrategyManager(tmp_path)
        r = await tool.execute({"company_id": "co"})
        assert r.success is False
        assert "No active strategy" in (r.error or "")

    @pytest.mark.asyncio
    async def test_active_strategy_summary(self, tmp_path) -> None:
        mgr = StrategyManager(tmp_path)
        prop = mgr.write_proposal("co", {"strategyName": "Approved Plan"})
        mgr.promote_proposal("co", prop)
        tool = CompanyPlanApproveTool()
        tool._strategy_manager = mgr
        r = await tool.execute({"company_id": "co"})
        assert r.success is True
        assert r.data["strategy_name"] == "Approved Plan"


# ── set_strategy_inputs ──────────────────────────────────────────────


class TestSetStrategyInputs:
    @pytest.mark.asyncio
    async def test_refuses_without_company_yaml(self, tmp_path) -> None:
        tool = CompanySetStrategyInputsTool()
        tool._project_root = tmp_path
        r = await tool.execute({"slug": "missing"})
        assert r.success is False
        assert "does not exist" in (r.error or "")

    @pytest.mark.asyncio
    async def test_writes_section(self, tmp_path) -> None:
        _write_company_yaml(tmp_path, "co", {"name": "Co", "what_we_sell": "X"})
        tool = CompanySetStrategyInputsTool()
        tool._project_root = tmp_path
        r = await tool.execute(
            {
                "slug": "co",
                "target_audience": "founders",
                "budget_type": "organic",
                "budget_amount": 0,
                "risk_tolerance": 60,
                "primary_goals": ["Brand Awareness"],
                "strategy_mode": "standard",
                "focus": "content",
            }
        )
        assert r.success is True
        loaded = yaml.safe_load(
            (tmp_path / "companies" / "co" / "company.yaml").read_text()
        )
        si = loaded["strategy_inputs"]
        assert si["target_audience"] == "founders"
        assert si["budget"]["type"] == "organic"
        assert si["risk_tolerance"] == 60
        assert si["primary_goals"] == ["Brand Awareness"]

    @pytest.mark.asyncio
    async def test_partial_update_preserves_prior(self, tmp_path) -> None:
        _write_company_yaml(
            tmp_path,
            "co",
            {
                "name": "Co",
                "what_we_sell": "X",
                "strategy_inputs": {
                    "target_audience": "old audience",
                    "risk_tolerance": 30,
                },
            },
        )
        tool = CompanySetStrategyInputsTool()
        tool._project_root = tmp_path
        r = await tool.execute({"slug": "co", "risk_tolerance": 80})
        assert r.success is True
        loaded = yaml.safe_load(
            (tmp_path / "companies" / "co" / "company.yaml").read_text()
        )
        si = loaded["strategy_inputs"]
        # Updated field
        assert si["risk_tolerance"] == 80
        # Preserved field
        assert si["target_audience"] == "old audience"
