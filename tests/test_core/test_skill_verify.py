"""Tests for the optional `## Verify` section on skills.

The verify section turns a skill from prose ("here's how to do X") into
a contract ("X is done only if these post-conditions hold"). Parsing is
permissive (accept several bullet styles) but strict about what counts
as a check (only bulleted/numbered list items — prose is ignored).
"""

from __future__ import annotations

from pathlib import Path

from core.skills import SkillManager


def _make_manager(tmp_path: Path) -> SkillManager:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    return SkillManager(skills_dir)


def _write_skill(tmp_path: Path, name: str, content: str) -> None:
    skill_dir = tmp_path / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


class TestVerifyParsing:
    def test_no_verify_section_means_empty_list(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        _write_skill(
            tmp_path,
            "no_verify",
            "## Description\nDoes a thing.\n\n## Instructions\nDo it.\n",
        )
        mgr.discover()
        skill = mgr.get_skill("no_verify")
        assert skill is not None
        assert skill.verify_checks == []

    def test_dash_bullets_extracted(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        _write_skill(
            tmp_path,
            "with_verify",
            "## Description\nx\n\n## Verify\n"
            "- tests pass\n"
            "- output file exists\n"
            "- no errors in log\n",
        )
        mgr.discover()
        skill = mgr.get_skill("with_verify")
        assert skill is not None
        assert skill.verify_checks == [
            "tests pass",
            "output file exists",
            "no errors in log",
        ]

    def test_star_and_plus_bullets_accepted(self, tmp_path: Path) -> None:
        """Markdown allows -, *, + as bullet markers."""
        mgr = _make_manager(tmp_path)
        _write_skill(
            tmp_path,
            "mixed",
            "## Verify\n* a\n+ b\n- c\n",
        )
        mgr.discover()
        assert mgr.get_skill("mixed").verify_checks == ["a", "b", "c"]

    def test_numbered_list_accepted(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        _write_skill(
            tmp_path,
            "numbered",
            "## Verify\n1. first\n2. second\n3) third\n",
        )
        mgr.discover()
        assert mgr.get_skill("numbered").verify_checks == [
            "first",
            "second",
            "third",
        ]

    def test_prose_lines_ignored(self, tmp_path: Path) -> None:
        """Only bullet/numbered items are checks — leading prose is commentary."""
        mgr = _make_manager(tmp_path)
        _write_skill(
            tmp_path,
            "prose",
            "## Verify\nThe agent must confirm:\n\n- check one\n- check two\n",
        )
        mgr.discover()
        assert mgr.get_skill("prose").verify_checks == ["check one", "check two"]

    def test_section_header_case_insensitive(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        _write_skill(
            tmp_path,
            "case",
            "## verify\n- a\n",
        )
        mgr.discover()
        assert mgr.get_skill("case").verify_checks == ["a"]

    def test_verify_section_terminated_by_next_heading(self, tmp_path: Path) -> None:
        """Bullets after the next ## must NOT leak into verify_checks."""
        mgr = _make_manager(tmp_path)
        _write_skill(
            tmp_path,
            "terminated",
            "## Verify\n- real check\n\n## Notes\n- not a check\n- also not\n",
        )
        mgr.discover()
        assert mgr.get_skill("terminated").verify_checks == ["real check"]

    def test_quoted_check_is_unquoted(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        _write_skill(
            tmp_path,
            "quoted",
            "## Verify\n- \"tests pass\"\n- 'output exists'\n",
        )
        mgr.discover()
        assert mgr.get_skill("quoted").verify_checks == [
            "tests pass",
            "output exists",
        ]

    def test_match_with_scores_separates_real_from_noise(self, tmp_path: Path) -> None:
        """The score is the gate input for verification injection.
        A trigger-phrase match must score well above an incidental
        keyword brush against a description — otherwise we'd force
        Verification blocks on every casual chat that grazes a skill."""
        mgr = _make_manager(tmp_path)
        _write_skill(
            tmp_path,
            "deploy-to-prod",
            "---\nname: deploy-to-prod\ndescription: Ship the build to production\n---\n"
            "## Triggers\n- deploy to prod\n- ship to production\n",
        )
        mgr.discover()
        # Strong: trigger phrase verbatim.
        strong = mgr.match_skills_with_scores("deploy to prod now", max_results=1)
        assert strong and strong[0][0] >= 6
        # Noise: shares one description word ("build") only.
        noise = mgr.match_skills_with_scores(
            "how do I build a sandcastle", max_results=1
        )
        # Either no match, or a low score.
        if noise:
            assert noise[0][0] < 6

    def test_real_api_testing_skill_has_verify(self) -> None:
        """Smoke test: the prototype skill we added Verify to actually parses."""
        from pathlib import Path as _P

        skills_root = _P(__file__).resolve().parents[2] / "skills"
        mgr = SkillManager(skills_root)
        mgr.discover()
        skill = mgr.get_skill("api-testing")
        assert skill is not None
        assert len(skill.verify_checks) >= 3
        # Each check should be a real sentence, not a fragment
        for c in skill.verify_checks:
            assert len(c) > 10
