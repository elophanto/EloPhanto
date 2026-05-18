"""skill_promote — coverage for the lesson-to-skill promotion path.

The agent learns micro-lessons automatically (core/learner.py writes
knowledge/learned/lessons/*.md), but nothing ever crystallizes those
lessons into reusable skills. This tool closes that gap. Tests cover:
input validation, slug generation, the existing-skill refusal,
malformed-output refusal, and the happy-path write.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tools.knowledge.skill_promote_tool import SkillPromoteTool, _slugify


class _FakeRouter:
    """Captures the LLM call + returns whatever the test wants."""

    def __init__(self, response: str = "") -> None:
        self.response = response
        self.calls: list[Any] = []

    async def complete(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)

        class _R:
            content = self.response  # type: ignore[name-defined]
            cost_usd = 0.0
            prompt_tokens = 0
            completion_tokens = 0
            model = "fake"

        return _R()


def _make_lesson(root: Path, slug: str, body: str) -> Path:
    """Create a lesson md file under knowledge/learned/lessons/."""
    lesson_dir = root / "knowledge" / "learned" / "lessons"
    lesson_dir.mkdir(parents=True, exist_ok=True)
    p = lesson_dir / f"{slug}.md"
    p.write_text(body)
    return p


@pytest.fixture
def tool(tmp_path: Path) -> SkillPromoteTool:
    t = SkillPromoteTool()
    t._project_root = tmp_path
    t._router = _FakeRouter()
    return t


# ---------------------------------------------------------------------------
# Slug generation — protects the filesystem from agent-proposed names
# like "Build X / Y" or "Identity (audit) #2".
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_basic(self) -> None:
        assert _slugify("Identity Audit Playbook") == "identity-audit-playbook"

    def test_strips_punctuation(self) -> None:
        assert _slugify("Build X / Y (audit) #2") == "build-x-y-audit-2"

    def test_collapses_whitespace(self) -> None:
        assert _slugify("  too    many   spaces  ") == "too-many-spaces"

    def test_truncates_long(self) -> None:
        assert len(_slugify("x" * 200)) == 60

    def test_empty_returns_empty(self) -> None:
        assert _slugify("???") == ""


# ---------------------------------------------------------------------------
# Input validation — the tool refuses obviously broken inputs early
# (better than a malformed SKILL.md or a half-written directory).
# ---------------------------------------------------------------------------


class TestValidation:
    @pytest.mark.asyncio
    async def test_missing_name(self, tool: SkillPromoteTool) -> None:
        r = await tool.execute({"lesson_paths": ["a.md", "b.md"]})
        assert r.success is False
        assert "skill_name" in (r.error or "")

    @pytest.mark.asyncio
    async def test_empty_lessons(self, tool: SkillPromoteTool) -> None:
        r = await tool.execute({"skill_name": "x", "lesson_paths": []})
        assert r.success is False
        assert "non-empty" in (r.error or "")

    @pytest.mark.asyncio
    async def test_one_lesson_rejected(self, tool: SkillPromoteTool) -> None:
        """One lesson isn't a cluster — should stay a lesson."""
        r = await tool.execute({"skill_name": "x", "lesson_paths": ["a.md"]})
        assert r.success is False
        assert "at least 2" in (r.error or "")

    @pytest.mark.asyncio
    async def test_more_than_30_rejected(self, tool: SkillPromoteTool) -> None:
        paths = [f"l-{i}.md" for i in range(31)]
        r = await tool.execute({"skill_name": "x", "lesson_paths": paths})
        assert r.success is False
        assert "30" in (r.error or "")

    @pytest.mark.asyncio
    async def test_no_router(self, tmp_path: Path) -> None:
        t = SkillPromoteTool()
        t._project_root = tmp_path
        # router is None
        r = await t.execute({"skill_name": "x", "lesson_paths": ["a.md", "b.md"]})
        assert r.success is False
        assert "router" in (r.error or "").lower()

    @pytest.mark.asyncio
    async def test_no_project_root(self) -> None:
        t = SkillPromoteTool()
        t._router = _FakeRouter()
        r = await t.execute({"skill_name": "x", "lesson_paths": ["a.md", "b.md"]})
        assert r.success is False
        assert "project root" in (r.error or "").lower()


# ---------------------------------------------------------------------------
# Refusal paths — overwrite protection + malformed LLM output.
# ---------------------------------------------------------------------------


class TestRefusals:
    @pytest.mark.asyncio
    async def test_refuses_existing_skill(
        self, tool: SkillPromoteTool, tmp_path: Path
    ) -> None:
        """Existing SKILL.md must not be overwritten silently — skills
        are high-trust artifacts. Force the operator to delete and
        re-promote if they really want to replace one."""
        l1 = _make_lesson(tmp_path, "l1", "## Lesson\nSome text here.")
        l2 = _make_lesson(tmp_path, "l2", "## Lesson\nMore text here.")
        # Pre-create the skill dir.
        skill_dir = tmp_path / "skills" / "existing-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: existing-skill\n---\n")

        r = await tool.execute(
            {
                "skill_name": "existing-skill",
                "lesson_paths": [str(l1), str(l2)],
            }
        )
        assert r.success is False
        assert "already exists" in (r.error or "")

    @pytest.mark.asyncio
    async def test_refuses_malformed_llm_output(
        self, tool: SkillPromoteTool, tmp_path: Path
    ) -> None:
        """If the LLM forgets the frontmatter, refuse to write — we'd
        end up with a SKILL.md that the dream tool can't parse."""
        l1 = _make_lesson(tmp_path, "l1", "## L\nbody body body body")
        l2 = _make_lesson(tmp_path, "l2", "## L\nbody body body body")
        # No leading "---" — invalid frontmatter.
        tool._router = _FakeRouter(response="just some markdown body")

        r = await tool.execute(
            {"skill_name": "bad", "lesson_paths": [str(l1), str(l2)]}
        )
        assert r.success is False
        assert "frontmatter" in (r.error or "").lower()
        # The bad skill must NOT be on disk.
        assert not (tmp_path / "skills" / "bad" / "SKILL.md").exists()

    @pytest.mark.asyncio
    async def test_skips_too_few_readable_lessons(
        self, tool: SkillPromoteTool, tmp_path: Path
    ) -> None:
        """If only 1 lesson path resolves to readable content, the
        synthesis isn't worth doing."""
        l1 = _make_lesson(tmp_path, "l1", "real lesson body content")
        r = await tool.execute(
            {
                "skill_name": "x",
                "lesson_paths": [str(l1), str(tmp_path / "does-not-exist.md")],
            }
        )
        assert r.success is False
        assert "only 1" in (r.error or "")


# ---------------------------------------------------------------------------
# Happy path — lessons → SKILL.md on disk.
# ---------------------------------------------------------------------------


class TestPromotion:
    @pytest.mark.asyncio
    async def test_writes_skill_md(
        self, tool: SkillPromoteTool, tmp_path: Path
    ) -> None:
        l1 = _make_lesson(tmp_path, "lesson-a", "## A\nFirst lesson body.")
        l2 = _make_lesson(tmp_path, "lesson-b", "## B\nSecond lesson body.")
        l3 = _make_lesson(tmp_path, "lesson-c", "## C\nThird lesson body.")
        valid_skill = (
            "---\n"
            "name: identity-audit-playbook\n"
            "description: How to audit identity claims.\n"
            "---\n\n"
            "## Triggers\n- when reviewing claims\n\n"
            "## Steps\n1. Read receipts.\n2. Mark debt.\n"
        )
        tool._router = _FakeRouter(response=valid_skill)

        r = await tool.execute(
            {
                "skill_name": "Identity Audit Playbook",
                "lesson_paths": [str(l1), str(l2), str(l3)],
            }
        )
        assert r.success is True
        skill_path = tmp_path / "skills" / "identity-audit-playbook" / "SKILL.md"
        assert skill_path.exists()
        content = skill_path.read_text()
        assert content.startswith("---")
        assert "identity-audit-playbook" in content

    @pytest.mark.asyncio
    async def test_passes_lesson_bodies_to_llm(
        self, tool: SkillPromoteTool, tmp_path: Path
    ) -> None:
        """Sanity: the lesson bodies must actually reach the LLM
        prompt, otherwise the synthesis is groundless."""
        l1 = _make_lesson(tmp_path, "l1", "DISTINCTIVE_LESSON_TOKEN_A")
        l2 = _make_lesson(tmp_path, "l2", "DISTINCTIVE_LESSON_TOKEN_B")
        tool._router = _FakeRouter(response="---\nname: x\n---\n")

        await tool.execute({"skill_name": "x", "lesson_paths": [str(l1), str(l2)]})
        assert tool._router.calls, "router must be called"
        user_msg = tool._router.calls[0]["messages"][1]["content"]
        assert "DISTINCTIVE_LESSON_TOKEN_A" in user_msg
        assert "DISTINCTIVE_LESSON_TOKEN_B" in user_msg

    @pytest.mark.asyncio
    async def test_strips_code_fences(
        self, tool: SkillPromoteTool, tmp_path: Path
    ) -> None:
        """LLMs sometimes wrap output in ```yaml ... ``` — strip it."""
        l1 = _make_lesson(tmp_path, "l1", "body" * 10)
        l2 = _make_lesson(tmp_path, "l2", "body" * 10)
        wrapped = "```yaml\n---\nname: wrapped\n---\n\n## Steps\n1. do.\n```"
        tool._router = _FakeRouter(response=wrapped)

        r = await tool.execute(
            {"skill_name": "wrapped", "lesson_paths": [str(l1), str(l2)]}
        )
        assert r.success is True
        on_disk = (tmp_path / "skills" / "wrapped" / "SKILL.md").read_text()
        assert "```" not in on_disk
