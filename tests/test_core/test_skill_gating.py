"""Tests for conditional skill gating via requires_tools / fallback_for_tools.

The gate semantics live on ``Skill.is_available`` and propagate through
``match_skills``, ``match_skills_with_scores``, and
``format_available_skills``. These tests pin both the pure function
behaviour and the integrated SkillManager behaviour.
"""

from __future__ import annotations

from pathlib import Path

from core.skills import Skill, SkillManager


def _write_skill(
    base: Path,
    name: str,
    description: str = "test skill",
    triggers: list[str] | None = None,
    requires_tools: list[str] | None = None,
    fallback_for_tools: list[str] | None = None,
) -> None:
    """Write a minimal SKILL.md under ``base/<name>/``."""
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    fm_lines = ["---", f"name: {name}", f"description: {description}"]
    if triggers:
        fm_lines.append("triggers: [" + ", ".join(triggers) + "]")
    if requires_tools:
        fm_lines.append("requires_tools: [" + ", ".join(requires_tools) + "]")
    if fallback_for_tools:
        fm_lines.append("fallback_for_tools: [" + ", ".join(fallback_for_tools) + "]")
    fm_lines.append("---")
    (d / "SKILL.md").write_text("\n".join(fm_lines) + "\n\nBody.\n")


class TestIsAvailablePureFunction:
    def test_no_constraints_always_available(self) -> None:
        s = Skill(name="t", path=Path("/tmp"))
        assert s.is_available(None) is True
        assert s.is_available(set()) is True
        assert s.is_available({"any_tool"}) is True

    def test_unknown_tools_degrades_open(self) -> None:
        """``available_tools=None`` = caller doesn't know → always show."""
        s = Skill(name="t", path=Path("/tmp"), requires_tools=["polymarket_get"])
        assert s.is_available(None) is True

    def test_requires_tools_all_must_be_present(self) -> None:
        s = Skill(
            name="t",
            path=Path("/tmp"),
            requires_tools=["polymarket_get", "polymarket_post"],
        )
        # only one of two present
        assert s.is_available({"polymarket_get"}) is False
        # both present
        assert s.is_available({"polymarket_get", "polymarket_post"}) is True
        # extras don't matter
        assert (
            s.is_available({"polymarket_get", "polymarket_post", "browser_navigate"})
            is True
        )

    def test_fallback_for_tools_hidden_when_primary_present(self) -> None:
        s = Skill(name="t", path=Path("/tmp"), fallback_for_tools=["http_get"])
        # primary loaded → fallback hidden
        assert s.is_available({"http_get"}) is False
        # primary missing → fallback shown
        assert s.is_available({"other_tool"}) is True
        assert s.is_available(set()) is True

    def test_combined_requires_and_fallback(self) -> None:
        """A skill can declare BOTH: 'needs X but only when Y is missing.'"""
        s = Skill(
            name="t",
            path=Path("/tmp"),
            requires_tools=["browser_navigate"],
            fallback_for_tools=["web_search"],
        )
        # requires met, primary missing → show
        assert s.is_available({"browser_navigate"}) is True
        # requires met, primary present → hide
        assert s.is_available({"browser_navigate", "web_search"}) is False
        # requires missing → hide regardless
        assert s.is_available({"web_search"}) is False


class TestFrontmatterParsing:
    def test_requires_tools_parsed(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path, "polymarket-flow", requires_tools=["polymarket_get", "http_get"]
        )
        mgr = SkillManager(tmp_path)
        mgr.discover()
        s = mgr.get_skill("polymarket-flow")
        assert s is not None
        assert s.requires_tools == ["polymarket_get", "http_get"]
        assert s.fallback_for_tools == []

    def test_fallback_for_tools_parsed(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path, "curl-fallback", fallback_for_tools=["web_search", "http_get"]
        )
        mgr = SkillManager(tmp_path)
        mgr.discover()
        s = mgr.get_skill("curl-fallback")
        assert s is not None
        assert s.fallback_for_tools == ["web_search", "http_get"]

    def test_skill_without_constraints_loads_with_empty_lists(
        self, tmp_path: Path
    ) -> None:
        _write_skill(tmp_path, "plain")
        mgr = SkillManager(tmp_path)
        mgr.discover()
        s = mgr.get_skill("plain")
        assert s is not None
        assert s.requires_tools == []
        assert s.fallback_for_tools == []


class TestMatchSkillsRespectsGate:
    def test_requires_missing_skill_omitted_from_matches(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path,
            "polymarket-flow",
            description="Polymarket prediction market queries",
            triggers=["polymarket", "prediction market"],
            requires_tools=["polymarket_get"],
        )
        _write_skill(
            tmp_path,
            "research-general",
            description="General research approach",
            triggers=["research", "market"],
        )
        mgr = SkillManager(tmp_path)
        mgr.discover()

        # polymarket_get NOT loaded → polymarket skill hidden
        matches = mgr.match_skills(
            "research the prediction market", available_tools={"http_get"}
        )
        names = [s.name for s in matches]
        assert "research-general" in names
        assert "polymarket-flow" not in names

        # polymarket_get loaded → polymarket skill appears
        matches = mgr.match_skills(
            "research the prediction market",
            available_tools={"http_get", "polymarket_get"},
        )
        names = [s.name for s in matches]
        assert "polymarket-flow" in names

    def test_none_available_tools_disables_filter(self, tmp_path: Path) -> None:
        """Backwards-compat: legacy callers passing nothing still see all skills."""
        _write_skill(
            tmp_path,
            "polymarket-flow",
            triggers=["polymarket"],
            requires_tools=["polymarket_get"],
        )
        mgr = SkillManager(tmp_path)
        mgr.discover()
        matches = mgr.match_skills("polymarket")
        assert any(s.name == "polymarket-flow" for s in matches)


class TestFormatAvailableSkillsRespectsGate:
    def test_total_count_reflects_visible_set(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path,
            "needs-poly",
            requires_tools=["polymarket_get"],
            triggers=["polymarket"],
        )
        _write_skill(tmp_path, "always-on", triggers=["anything"])
        mgr = SkillManager(tmp_path)
        mgr.discover()

        xml = mgr.format_available_skills(
            query="unrelated greeting", available_tools={"http_get"}
        )
        # The compact-no-matches branch surfaces only the visible total
        assert "1 skills available" in xml
        assert "needs-poly" not in xml

    def test_hidden_skill_not_listed_in_other_skills(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path,
            "needs-poly",
            requires_tools=["polymarket_get"],
            triggers=["polymarket"],
        )
        _write_skill(
            tmp_path,
            "voice-tone",
            description="Voice tone calibration",
            triggers=["voice", "tone"],
        )
        mgr = SkillManager(tmp_path)
        mgr.discover()

        xml = mgr.format_available_skills(
            query="calibrate voice tone", available_tools={"http_get"}
        )
        assert "voice-tone" in xml
        assert "needs-poly" not in xml
