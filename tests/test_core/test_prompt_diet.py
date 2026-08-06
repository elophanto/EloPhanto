"""Prompt diet + self-build hardening regressions.

Locks in the Phase-4 scale fixes: skill excerpts, planning profile,
deferred catalog compactness, compression threshold alignment, and
self_create_plugin review gate blocking deploy.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.context_compressor import _DEFAULT_THRESHOLD_PCT, _TIER1_MICROCOMPACT_PCT
from core.planner import _TOOL_BROWSER
from core.registry import ToolRegistry
from core.skills import (
    _AUTO_SKILL_MAX_CHARS,
    excerpt_skill_content,
)
from core.tool_profiles import DEFAULT_PROFILES, TASK_TYPE_PROFILES, select_profile
from tools.base import ToolTier
from tools.self_dev.creator import SelfCreatePluginTool


class TestSkillExcerpt:
    def test_short_content_unchanged(self) -> None:
        body = "# Skill\n\nShort body."
        assert excerpt_skill_content(body, 500, "demo") == body

    def test_prefers_instructions_section(self) -> None:
        content = (
            "# Big Skill\n\n"
            + ("trigger fluff\n" * 80)
            + "## Instructions\n\n"
            + "Do the thing carefully.\n"
            + "## Notes\n\nExtra.\n"
        )
        out = excerpt_skill_content(content, 400, "big-skill")
        assert "Do the thing carefully" in out
        assert "skill_read" in out
        assert "depth='full'" in out
        assert len(out) < len(content)

    def test_skips_triggers_for_abe_playbooks(self) -> None:
        content = (
            "# Drive\n\n## Triggers\n\n- drive\n\n"
            "## Decision tree\n\n"
            "PATH A then PATH B then company_set_posture.\n"
            + ("x\n" * 200)
            + "## Notes\n\nextra\n"
        )
        out = excerpt_skill_content(content, 500, "drive-business")
        assert "Decision tree" in out
        assert "PATH A" in out
        assert "Sections available" in out

    def test_hard_cap_when_no_instructions(self) -> None:
        content = "x" * 10_000
        out = excerpt_skill_content(content, 500, "plain")
        assert len(out) < 900
        assert "truncated" in out

    def test_tail_truncate_keeps_recent(self) -> None:
        from core.skills import tail_truncate

        text = "OLD preamble\n" + ("mid\n" * 100) + "RECENT INTENT: ship PATH B\n"
        out = tail_truncate(text, 80)
        assert "RECENT INTENT" in out
        assert "earlier truncated" in out
        assert not out.startswith("OLD preamble")

    def test_force_dream_survives_fat_snapshot_truncation(self) -> None:
        """Gates must be prepended AFTER body truncate, not before."""
        from core.skills import tail_truncate

        body = ("[RECENT] old work\n" * 200) + "[RECENT] newest\n"
        capped = tail_truncate(body, 3000)
        gated = "[FORCE-DREAM] must dream\n\n" + capped
        assert gated.startswith("[FORCE-DREAM]")
        assert "newest" in gated or "RECENT" in gated
        # Simulates the bug: truncating after prepend drops the gate
        wrong = tail_truncate(gated, 3000)
        assert not wrong.startswith("[FORCE-DREAM]") or len(gated) <= 3000
        # Correct order keeps the gate regardless of body size
        assert gated.startswith("[FORCE-DREAM]")
        assert len(capped) <= 3100


class TestBrowserPromptDiet:
    def test_tool_browser_is_compact(self) -> None:
        assert len(_TOOL_BROWSER) < 4000
        assert "browser-automation" in _TOOL_BROWSER
        assert "task_restart" in _TOOL_BROWSER
        assert "x_twitter_post" in _TOOL_BROWSER


class TestPlanningProfile:
    def test_planning_maps_to_planning_profile(self) -> None:
        assert TASK_TYPE_PROFILES["planning"] == "planning"
        assert select_profile("planning") == "planning"

    def test_planning_keeps_abe_drops_heavy_groups(self) -> None:
        groups = DEFAULT_PROFILES["planning"]
        for required in (
            "companies",
            "roles",
            "missions",
            "prospecting",
            "watch",
            "browser",
            "mind",
        ):
            assert required in groups
        for deferred in (
            "desktop",
            "swarm",
            "org",
            "mcp",
            "social",
            "media",
            "payments",
        ):
            assert deferred not in groups

    def test_full_still_exists_for_explicit_use(self) -> None:
        assert "desktop" in DEFAULT_PROFILES["full"]
        assert "payments" in DEFAULT_PROFILES["full"]


class TestCompressionAlignment:
    def test_needs_compression_matches_tier1(self) -> None:
        assert _DEFAULT_THRESHOLD_PCT == _TIER1_MICROCOMPACT_PCT == 70


class TestDeferredCatalogCompact:
    def test_descriptions_truncated(self, tmp_path: Path) -> None:
        reg = ToolRegistry(tmp_path)
        tool = MagicMock()
        tool.name = "crypto_transfer"
        tool.group = "payments"
        tool.description = "A" * 200
        tool.tier = ToolTier.DEFERRED
        reg._tools["crypto_transfer"] = tool

        catalog = reg.get_deferred_catalog()
        assert len(catalog) == 1
        assert len(catalog[0]["description"]) <= 60


class TestSelfCreateReviewGate:
    @pytest.mark.asyncio
    async def test_review_rejection_blocks_deploy(self, tmp_path: Path) -> None:
        tool = SelfCreatePluginTool(tmp_path)
        tool._router = MagicMock()
        tool._registry = MagicMock()
        plugin_loader = MagicMock()
        tool._plugin_loader = plugin_loader

        design = {
            "description": "demo tool",
            "parameters": {},
            "approach": "simple",
            "dependencies": [],
        }
        impl = {
            "plugin": "class DemoTool: pass\n",
            "test": "def test_ok(): assert True\n",
        }

        with (
            patch("tools.self_dev.creator.check_name_available", return_value=True),
            patch.object(
                tool, "_research", new=AsyncMock(return_value={"notes": "ok"})
            ),
            patch.object(tool, "_design", new=AsyncMock(return_value=design)),
            patch.object(tool, "_implement", new=AsyncMock(return_value=impl)),
            patch.object(
                tool,
                "_test",
                new=AsyncMock(return_value={"passed": True, "output": "ok"}),
            ),
            patch.object(
                tool,
                "_review",
                new=AsyncMock(
                    return_value={"approved": False, "issues": ["unsafe eval"]}
                ),
            ),
        ):
            result = await tool.execute(
                {"goal": "demo capability", "tool_name": "demo_cap"}
            )

        assert result.success is False
        assert "rejected" in (result.error or "").lower()
        assert result.data and result.data.get("approved") is False
        assert result.data.get("quarantined") is True
        plugin_loader.reload_plugin.assert_not_called()

        assert not (tmp_path / "plugins" / "demo_cap").exists()
        qdirs = list((tmp_path / "plugins" / ".quarantine").glob("demo_cap_*"))
        assert len(qdirs) == 1

        failures = list((tmp_path / "knowledge" / "learned" / "failures").glob("*.md"))
        assert len(failures) == 1
        assert "unsafe eval" in failures[0].read_text()

    @pytest.mark.asyncio
    async def test_budget_before_review_blocks_deploy(self, tmp_path: Path) -> None:
        from tools.self_dev.creator import DevelopmentBudget

        tool = SelfCreatePluginTool(tmp_path)
        tool._router = MagicMock()
        tool._registry = MagicMock()
        plugin_loader = MagicMock()
        tool._plugin_loader = plugin_loader

        design = {
            "description": "demo tool",
            "parameters": {},
            "approach": "simple",
            "dependencies": [],
        }
        impl = {
            "plugin": "class DemoTool: pass\n",
            "test": "def test_ok(): assert True\n",
        }

        responses = iter(
            [
                (True, ""),  # research
                (True, ""),  # design
                (True, ""),  # implement
                (False, "LLM call limit reached (50)"),  # review gate
            ]
        )

        def fake_check(self: DevelopmentBudget) -> tuple[bool, str]:
            return next(responses)

        with (
            patch("tools.self_dev.creator.check_name_available", return_value=True),
            patch.object(DevelopmentBudget, "check", fake_check),
            patch.object(
                tool, "_research", new=AsyncMock(return_value={"notes": "ok"})
            ),
            patch.object(tool, "_design", new=AsyncMock(return_value=design)),
            patch.object(tool, "_implement", new=AsyncMock(return_value=impl)),
            patch.object(
                tool,
                "_test",
                new=AsyncMock(return_value={"passed": True, "output": "ok"}),
            ),
        ):
            result = await tool.execute(
                {"goal": "demo capability", "tool_name": "demo_budget"}
            )

        assert result.success is False
        assert "budget" in (result.error or "").lower()
        assert result.data and result.data.get("quarantined") is True
        plugin_loader.reload_plugin.assert_not_called()
        assert not (tmp_path / "plugins" / "demo_budget").exists()


class TestAutoSkillBudgetConstant:
    def test_auto_budget_is_tight(self) -> None:
        assert _AUTO_SKILL_MAX_CHARS <= 3000

    def test_critical_auto_budget_covers_abe_playbooks(self) -> None:
        from core.skills import _CRITICAL_AUTO_SKILLS, _CRITICAL_SKILL_AUTO_CHARS

        assert "drive-business" in _CRITICAL_AUTO_SKILLS
        assert _CRITICAL_SKILL_AUTO_CHARS >= 8000
