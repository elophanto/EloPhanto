"""Dream tool — helper coverage.

The full execute() path needs an LLM router, so it's exercised in the
integration suite. These tests pin the pure helpers that determine
whether the dream prompt actually contains skills, past-dream context,
and focus rotation — the three changes that matter for autonomy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.autonomous_mind import _DREAM_LENSES, _dream_focus_for_today
from tools.goals.dream_tool import (
    _collect_skills,
    _format_past_dreams,
    _read_skill_description,
)

# ---------------------------------------------------------------------------
# Skill description parsing — the dream prompt is only useful if we
# can actually pull the description out of a SKILL.md's frontmatter.
# ---------------------------------------------------------------------------


class TestReadSkillDescription:
    def test_single_line_description(self, tmp_path: Path) -> None:
        md = tmp_path / "SKILL.md"
        md.write_text(
            "---\nname: test-skill\ndescription: A short skill description.\n---\n\nBody."
        )
        assert _read_skill_description(md) == "A short skill description."

    def test_multiline_description_collapses(self, tmp_path: Path) -> None:
        md = tmp_path / "SKILL.md"
        md.write_text(
            "---\nname: test\n"
            "description: First sentence about the skill. Second sentence.\n"
            "triggers:\n  - foo\n---\n"
        )
        # First sentence is what gets returned (≤220 chars).
        result = _read_skill_description(md)
        assert result is not None
        assert "First sentence about the skill" in result

    def test_truncates_long_description(self, tmp_path: Path) -> None:
        md = tmp_path / "SKILL.md"
        long_desc = "x" * 500
        md.write_text(f"---\ndescription: {long_desc}\n---\n")
        result = _read_skill_description(md)
        assert result is not None
        assert len(result) <= 221  # 220 + trailing period

    def test_no_frontmatter_returns_none(self, tmp_path: Path) -> None:
        md = tmp_path / "SKILL.md"
        md.write_text("# Just a heading\nNo frontmatter here.")
        assert _read_skill_description(md) is None

    def test_missing_description_returns_none(self, tmp_path: Path) -> None:
        md = tmp_path / "SKILL.md"
        md.write_text("---\nname: x\ntriggers:\n  - foo\n---\n")
        assert _read_skill_description(md) is None

    def test_empty_description_returns_none(self, tmp_path: Path) -> None:
        md = tmp_path / "SKILL.md"
        md.write_text("---\ndescription:\n---\n")
        assert _read_skill_description(md) is None

    def test_quoted_description_unquoted(self, tmp_path: Path) -> None:
        md = tmp_path / "SKILL.md"
        md.write_text('---\ndescription: "Quoted body."\n---\n')
        result = _read_skill_description(md)
        assert result == "Quoted body."

    def test_unreadable_file_returns_none(self, tmp_path: Path) -> None:
        """One malformed skill must not break the dream phase."""
        # Pass a path that doesn't exist — read raises, helper returns None.
        assert _read_skill_description(tmp_path / "does-not-exist.md") is None


# ---------------------------------------------------------------------------
# Skill collection — produces (name, description) pairs from skills/,
# skipping templates / __pycache__ / files with no parseable description.
# ---------------------------------------------------------------------------


def _make_skill(root: Path, name: str, description: str | None) -> None:
    d = root / "skills" / name
    d.mkdir(parents=True)
    if description is None:
        (d / "SKILL.md").write_text("# no frontmatter")
    else:
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n\nBody."
        )


class TestCollectSkills:
    def test_collects_alphabetically(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "z-skill", "Last one.")
        _make_skill(tmp_path, "a-skill", "First one.")
        _make_skill(tmp_path, "m-skill", "Middle.")
        pairs = _collect_skills(tmp_path)
        assert [p[0] for p in pairs] == ["a-skill", "m-skill", "z-skill"]

    def test_skips_template_and_pycache(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "_template", "Should be skipped.")
        _make_skill(tmp_path, "__pycache__", "Should be skipped.")
        _make_skill(tmp_path, "real-skill", "Real one.")
        pairs = _collect_skills(tmp_path)
        assert [p[0] for p in pairs] == ["real-skill"]

    def test_skips_skills_with_no_description(self, tmp_path: Path) -> None:
        """Skills whose SKILL.md has no parseable description don't
        belong in the dream prompt — they can't advertise themselves."""
        _make_skill(tmp_path, "no-desc", None)
        _make_skill(tmp_path, "has-desc", "Real description.")
        pairs = _collect_skills(tmp_path)
        assert [p[0] for p in pairs] == ["has-desc"]

    def test_no_skills_dir_returns_empty(self, tmp_path: Path) -> None:
        """Some configs may not have a skills/ dir at all. Don't crash."""
        assert _collect_skills(tmp_path) == []

    def test_limit_caps_count(self, tmp_path: Path) -> None:
        for i in range(20):
            _make_skill(tmp_path, f"skill-{i:02d}", f"Skill number {i}.")
        pairs = _collect_skills(tmp_path, limit=5)
        assert len(pairs) == 5
        # Limit is taken after alphabetical sort.
        assert pairs[0][0] == "skill-00"


# ---------------------------------------------------------------------------
# Past-dreams formatter — the block injected into the prompt that
# breaks the amnesia loop. Cold-start cycles get None.
# ---------------------------------------------------------------------------


class _FakeDream:
    """Stand-in for DreamEntry — we don't want a DB fixture here."""

    def __init__(
        self,
        focus: str,
        candidates: list[dict[str, Any]],
        recommendation: dict[str, Any],
        chosen: str | None = None,
        created: str = "2026-05-17T10:00:00Z",
    ) -> None:
        self.focus = focus
        self.candidates = candidates
        self.recommendation = recommendation
        self.chosen_goal_id = chosen
        self.created_at = created


class TestFormatPastDreams:
    def test_fewer_than_three_returns_none(self) -> None:
        """Cold-start: showing 1-2 stale dreams is distraction, not signal."""
        dreams = [
            _FakeDream("balanced", [{"title": "A"}], {"index": 0}),
            _FakeDream("balanced", [{"title": "B"}], {"index": 0}),
        ]
        assert _format_past_dreams(dreams) is None

    def test_three_or_more_returns_block(self) -> None:
        dreams = [
            _FakeDream(
                "research",
                [{"title": "Test X claim"}, {"title": "Alt"}],
                {"index": 0},
                chosen="goal-1",
            ),
            _FakeDream("creation", [{"title": "Build a poem-bot"}], {"index": 0}),
            _FakeDream("compounding", [{"title": "Lead list"}], {"index": 0}),
        ]
        out = _format_past_dreams(dreams)
        assert out is not None
        assert "PREVIOUSLY PROPOSED" in out
        assert "Test X claim" in out
        assert "Lead list" in out

    def test_chosen_vs_not_pursued_marked(self) -> None:
        dreams = [
            _FakeDream("research", [{"title": "X"}], {"index": 0}, chosen="goal-1"),
            _FakeDream("creation", [{"title": "Y"}], {"index": 0}),
            _FakeDream("creation", [{"title": "Z"}], {"index": 0}),
        ]
        out = _format_past_dreams(dreams)
        assert out is not None
        assert "became goal" in out  # the chosen one
        assert "not pursued" in out  # the unchosen ones

    def test_includes_all_candidate_titles(self) -> None:
        """The LLM needs to see EVERY candidate it proposed, not just
        the recommended one — otherwise it re-proposes the runners-up
        every cycle."""
        dreams = [
            _FakeDream(
                "balanced",
                [{"title": "A"}, {"title": "B"}, {"title": "C"}],
                {"index": 0},
            ),
            _FakeDream("balanced", [{"title": "D"}], {"index": 0}),
            _FakeDream("balanced", [{"title": "E"}], {"index": 0}),
        ]
        out = _format_past_dreams(dreams)
        assert out is not None
        for letter in "ABCDE":
            assert letter in out


# ---------------------------------------------------------------------------
# Focus rotation — deterministic across days, stable within a day.
# ---------------------------------------------------------------------------


class TestFocusRotation:
    def test_returns_one_of_the_lenses(self) -> None:
        focus = _dream_focus_for_today()
        assert focus in _DREAM_LENSES

    def test_lens_count_is_seven(self) -> None:
        """If someone adds a lens without updating the doctrine docs,
        this test reminds them. The rotation only works cleanly with
        a coprime-with-365 count; 7 is the chosen value."""
        assert len(_DREAM_LENSES) == 7

    def test_all_lenses_distinct(self) -> None:
        assert len(set(_DREAM_LENSES)) == len(_DREAM_LENSES)

    def test_idempotent_within_same_call_stack(self) -> None:
        """Two calls in the same second must return the same focus."""
        a = _dream_focus_for_today()
        b = _dream_focus_for_today()
        assert a == b


# ---------------------------------------------------------------------------
# Pre-dream dedup — when an embedder is wired, candidates whose
# cosine similarity to any existing goal exceeds 0.85 are dropped
# before the journal records the dream. Without this, the dream
# kept proposing variants of the same idea each cycle.
# ---------------------------------------------------------------------------


class _StubEmbedder:
    """Returns deterministic vectors based on a token map. Same tokens
    in the text produce same vectors → identical text yields identical
    cosine = 1.0. Different tokens yield orthogonal vectors."""

    def __init__(self, token_to_dim: dict[str, int], dims: int = 16) -> None:
        self.token_to_dim = token_to_dim
        self.dims = dims

    async def embed_batch(self, texts, model=None):
        class _R:
            def __init__(self, vector):
                self.vector = vector
                self.model = "stub"
                self.dimensions = len(vector)

        out = []
        for t in texts:
            vec = [0.0] * self.dims
            for token, dim in self.token_to_dim.items():
                if token.lower() in t.lower():
                    vec[dim] += 1.0
            out.append(_R(vec))
        return out


class _FakeGoal:
    def __init__(self, text: str) -> None:
        self.goal = text


class _StubGoalManager:
    def __init__(self, goals: dict[str, list[str]]) -> None:
        # {status: [goal_text, ...]}
        self._goals = goals

    async def list_goals(self, status: str, limit: int):
        return [_FakeGoal(g) for g in self._goals.get(status, [])[:limit]]


@pytest.mark.asyncio
async def test_dedup_drops_near_duplicate_of_existing_goal() -> None:
    """Candidate sharing all tokens with an existing goal must be
    dropped. The dedup catches the 'Build identity index' vs 'Build
    identity memory index' class of overlap that string Jaccard
    misses."""
    from tools.goals.dream_tool import GoalDreamTool

    tool = GoalDreamTool()
    tool._embedder = _StubEmbedder(
        {"identity": 0, "memory": 1, "build": 2, "fresh": 3, "research": 4}
    )
    tool._goal_manager = _StubGoalManager(
        {"completed": ["Build identity memory index"]}
    )

    candidates = [
        {
            "title": "Build identity memory index",
            "description": "same as existing",
        },
        {
            "title": "Fresh research topic",
            "description": "totally different vector",
        },
    ]
    kept, dropped = await tool._dedup_candidates(candidates)
    assert len(kept) == 1
    assert kept[0]["title"] == "Fresh research topic"
    assert len(dropped) == 1
    assert "identity memory" in dropped[0].lower()


@pytest.mark.asyncio
async def test_dedup_keeps_distinct_candidates() -> None:
    """Different-topic candidates pass through unchanged."""
    from tools.goals.dream_tool import GoalDreamTool

    tool = GoalDreamTool()
    tool._embedder = _StubEmbedder(
        {"identity": 0, "compounding": 1, "research": 2, "creation": 3}
    )
    tool._goal_manager = _StubGoalManager({"completed": ["Run identity audit"]})
    candidates = [
        {"title": "Compounding revenue test", "description": "compounding"},
        {"title": "Research bet on X", "description": "research"},
        {"title": "Creation of a poem-bot", "description": "creation"},
    ]
    kept, dropped = await tool._dedup_candidates(candidates)
    assert len(kept) == 3
    assert dropped == []


@pytest.mark.asyncio
async def test_dedup_skipped_without_embedder() -> None:
    """No embedder = no dedup = all candidates pass through. The
    pre-dream dedup is opportunistic; absent dependencies must not
    break the tool."""
    from tools.goals.dream_tool import GoalDreamTool

    tool = GoalDreamTool()
    tool._embedder = None
    tool._goal_manager = _StubGoalManager({"completed": ["X"]})
    cands = [{"title": "A"}, {"title": "B"}]
    kept, dropped = await tool._dedup_candidates(cands)
    assert kept == cands
    assert dropped == []


@pytest.mark.asyncio
async def test_dedup_no_existing_goals_keeps_all() -> None:
    """First-ever dream cycle (or post-cleanup): nothing to dedup
    against, every candidate survives."""
    from tools.goals.dream_tool import GoalDreamTool

    tool = GoalDreamTool()
    tool._embedder = _StubEmbedder({"x": 0})
    tool._goal_manager = _StubGoalManager({})
    cands = [{"title": "A"}, {"title": "B"}]
    kept, dropped = await tool._dedup_candidates(cands)
    assert kept == cands
    assert dropped == []


def test_cosine_orthogonal_vectors() -> None:
    """Sanity on the cosine helper — orthogonal vectors return 0,
    identical vectors return 1, zero vectors return 0 (not NaN)."""
    from tools.goals.dream_tool import GoalDreamTool

    cos = GoalDreamTool._cosine
    assert cos([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cos([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cos([0.0, 0.0], [1.0, 1.0]) == 0.0  # degenerate, not NaN
    assert cos([1.0, 2.0], [2.0, 4.0]) == pytest.approx(1.0)  # parallel
