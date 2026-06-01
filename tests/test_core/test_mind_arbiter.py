"""Mind arbiter — scoring, dedup, ranking, menu rendering.

Locks in the Phase 3 contract from docs/75-AUTONOMOUS-MIND-V2.md:
- Higher score wins.
- Duplicate ``dedup_key`` → keep the highest-scoring one.
- Sort is stable for equal scores; insertion order preserved.
- Empty input → empty output (caller falls through to dream).
- Mission weight multiplier respects the live priority map.
"""

from __future__ import annotations

import pytest

from core.mind_arbiter import (
    ArbiterWeights,
    Candidate,
    arbitrate,
    render_menu,
    score_candidate,
)


class TestCandidateBasics:
    def test_default_dedup_key_is_stable_hash(self) -> None:
        c1 = Candidate(source="dream", action_spec="go dream")
        c2 = Candidate(source="dream", action_spec="go dream")
        assert c1.stable_dedup_key() == c2.stable_dedup_key()

    def test_default_dedup_key_changes_with_action_spec(self) -> None:
        c1 = Candidate(source="dream", action_spec="A")
        c2 = Candidate(source="dream", action_spec="B")
        assert c1.stable_dedup_key() != c2.stable_dedup_key()

    def test_explicit_dedup_key_overrides_hash(self) -> None:
        c = Candidate(source="x", action_spec="y", dedup_key="explicit")
        assert c.stable_dedup_key() == "explicit"


class TestScoring:
    def test_higher_value_wins(self) -> None:
        w = ArbiterWeights()
        low = Candidate(source="s", action_spec="x", expected_value=3.0)
        high = Candidate(source="s", action_spec="y", expected_value=8.0)
        assert score_candidate(high, w) > score_candidate(low, w)

    def test_feasibility_multiplies_value(self) -> None:
        """A high-value low-feasibility candidate can lose to a
        moderate-value high-feasibility one — the scorer doesn't
        reward fantasies."""
        w = ArbiterWeights()
        risky = Candidate(
            source="s", action_spec="x", expected_value=10.0, feasibility=0.1
        )
        safe = Candidate(
            source="s", action_spec="y", expected_value=5.0, feasibility=0.9
        )
        assert score_candidate(safe, w) > score_candidate(risky, w)

    def test_cost_penalty(self) -> None:
        w = ArbiterWeights()
        cheap = Candidate(source="s", action_spec="x", cost=1.0)
        expensive = Candidate(source="s", action_spec="y", cost=8.0)
        # Equal value/feasibility → cheaper wins.
        assert score_candidate(cheap, w) > score_candidate(expensive, w)

    def test_lens_match_boosts(self) -> None:
        w = ArbiterWeights()
        on = Candidate(source="s", action_spec="x", lens_match=1.0)
        off = Candidate(source="s", action_spec="y", lens_match=0.0)
        assert score_candidate(on, w) > score_candidate(off, w)

    def test_staleness_bonus_lifts_neglected(self) -> None:
        w = ArbiterWeights()
        stale = Candidate(source="s", action_spec="x", staleness_bonus=8.0)
        fresh = Candidate(source="s", action_spec="y", staleness_bonus=0.0)
        assert score_candidate(stale, w) > score_candidate(fresh, w)

    def test_affect_bias_can_go_negative(self) -> None:
        w = ArbiterWeights()
        meh = Candidate(source="s", action_spec="x", affect_bias=-2.0)
        normal = Candidate(source="s", action_spec="y", affect_bias=0.0)
        assert score_candidate(meh, w) < score_candidate(normal, w)

    def test_mission_weight_bonus(self) -> None:
        w = ArbiterWeights()
        c = Candidate(source="s", action_spec="x", mission_id="alphascala")
        no_map = score_candidate(c, w)
        with_map = score_candidate(c, w, mission_weights={"alphascala": 2.5})
        assert with_map > no_map

    def test_unparented_candidate_no_mission_bonus(self) -> None:
        """Candidates without ``mission_id`` shouldn't be penalized OR
        bonused by the mission term — neutral."""
        w = ArbiterWeights()
        c = Candidate(source="s", action_spec="x")
        assert score_candidate(c, w, mission_weights={"x": 5.0}) == score_candidate(
            c, w
        )


class TestArbitrate:
    def test_empty_input_empty_output(self) -> None:
        assert arbitrate([], ArbiterWeights()) == []

    def test_top_k_truncates(self) -> None:
        cs = [
            Candidate(source="s", action_spec=f"a{i}", expected_value=float(i))
            for i in range(10)
        ]
        result = arbitrate(cs, ArbiterWeights(), top_k=3)
        assert len(result) == 3
        # Highest expected_value should be first.
        assert result[0].candidate.action_spec == "a9"

    def test_dedup_keeps_highest_score(self) -> None:
        """Two candidates with the same ``dedup_key`` collapse to the
        one with the higher score."""
        low = Candidate(source="s", action_spec="A", expected_value=2.0, dedup_key="K")
        high = Candidate(
            source="s", action_spec="A-better", expected_value=8.0, dedup_key="K"
        )
        result = arbitrate([low, high], ArbiterWeights(), top_k=5)
        assert len(result) == 1
        assert result[0].candidate.action_spec == "A-better"

    def test_dedup_across_different_sources(self) -> None:
        """The dedup_key is the contract — two generators proposing
        the same underlying action with the same key still collapse,
        even if their `source` differs."""
        a = Candidate(source="src1", action_spec="X", expected_value=3.0, dedup_key="K")
        b = Candidate(source="src2", action_spec="X", expected_value=6.0, dedup_key="K")
        result = arbitrate([a, b], ArbiterWeights())
        assert len(result) == 1
        assert result[0].candidate.source == "src2"

    def test_default_dedup_collapses_identical_action_spec(self) -> None:
        a = Candidate(source="s", action_spec="same", expected_value=3.0)
        b = Candidate(source="s", action_spec="same", expected_value=5.0)
        result = arbitrate([a, b], ArbiterWeights())
        assert len(result) == 1
        assert result[0].candidate.expected_value == 5.0

    def test_sort_descending_by_score(self) -> None:
        cs = [
            Candidate(source="s", action_spec="a", expected_value=2.0),
            Candidate(source="s", action_spec="b", expected_value=8.0),
            Candidate(source="s", action_spec="c", expected_value=5.0),
        ]
        result = arbitrate(cs, ArbiterWeights())
        scores = [sc.score for sc in result]
        assert scores == sorted(scores, reverse=True)

    def test_mission_weight_breaks_ties(self) -> None:
        """Two candidates identical except for mission_id — the one
        parented to a high-weight mission ranks first."""
        a = Candidate(
            source="s", action_spec="aaa", expected_value=5.0, mission_id="hot"
        )
        b = Candidate(
            source="s", action_spec="bbb", expected_value=5.0, mission_id="cold"
        )
        result = arbitrate(
            [a, b],
            ArbiterWeights(),
            mission_weights={"hot": 3.0, "cold": 0.5},
        )
        assert result[0].candidate.mission_id == "hot"


class TestArbiterWeights:
    def test_from_config_dict_uses_defaults_when_missing(self) -> None:
        defaults = ArbiterWeights()
        w = ArbiterWeights.from_config_dict({})
        assert w == defaults

    def test_from_config_dict_overrides_partial(self) -> None:
        w = ArbiterWeights.from_config_dict({"cost": 0.0})
        assert w.cost == 0.0
        # Untouched fields keep defaults.
        assert w.value == ArbiterWeights().value

    def test_from_config_dict_ignores_unknown_keys(self) -> None:
        # Future-config that adds a knob this version doesn't know
        # about must not crash the existing weights.
        w = ArbiterWeights.from_config_dict({"future_knob": 99.0})
        assert w == ArbiterWeights()

    def test_from_none(self) -> None:
        assert ArbiterWeights.from_config_dict(None) == ArbiterWeights()


class TestRenderMenu:
    def test_empty_returns_fallthrough_marker(self) -> None:
        text = render_menu([])
        assert "no candidates" in text.lower()

    def test_renders_each_candidate_on_a_line(self) -> None:
        from core.mind_arbiter import ScoredCandidate

        items = [
            ScoredCandidate(
                candidate=Candidate(source="s", action_spec="A"), score=5.0
            ),
            ScoredCandidate(
                candidate=Candidate(source="s", action_spec="B"), score=4.0
            ),
        ]
        text = render_menu(items)
        assert "1." in text and "2." in text
        assert "A" in text and "B" in text

    def test_truncates_long_actions(self) -> None:
        from core.mind_arbiter import ScoredCandidate

        long_spec = "x" * 5000
        items = [
            ScoredCandidate(
                candidate=Candidate(source="s", action_spec=long_spec), score=1.0
            )
        ]
        text = render_menu(items, max_chars=500)
        assert len(text) <= 600  # generous slack for headline
        assert "…" in text or "x" in text


# ---------------------------------------------------------------------------
# Candidate generators — focused tests against in-memory state.
# Each generator should degrade gracefully when managers are None.
# ---------------------------------------------------------------------------


class TestGeneratorsDegradeWithoutManagers:
    @pytest.mark.asyncio
    async def test_all_generators_return_lists_with_no_managers(self) -> None:
        from core.mind_candidates import (
            CandidateContext,
            from_dream,
            from_external_signals,
            from_mission_momentum,
            from_reflexes,
            from_workable_checkpoints,
        )

        ctx = CandidateContext()  # everything None
        for gen in (
            from_workable_checkpoints,
            from_mission_momentum,
            from_dream,
            from_reflexes,
            from_external_signals,
        ):
            result = await gen(ctx)
            assert isinstance(result, list)


class TestWorkableCheckpointStalledRecovery:
    """Operator 2026-06-01: 'the goal is still at 5/15, what is it
    doing with it?' Production state: 5 completed rows + 0 pending +
    total_checkpoints=15 (the other 10 never made it into the DB
    after an earlier revise_plan crash). from_workable_checkpoints
    skipped the goal silently (no pending → next_workable=None →
    continue), so the arbiter menu had no workable_checkpoint
    candidate. Goal sat stalled forever. Fix: detect the
    completed_in_db < total_checkpoints state and propose a
    goal_manage(action='revise') candidate."""

    @pytest.mark.asyncio
    async def test_stalled_goal_yields_revise_candidate(self, tmp_path) -> None:
        from unittest.mock import AsyncMock
        from core.config import GoalsConfig
        from core.database import Database
        from core.goal_manager import GoalManager
        from core.mind_candidates import CandidateContext, from_workable_checkpoints

        db = Database(str(tmp_path / "t.db"))
        await db.initialize()
        router = AsyncMock()
        gm = GoalManager(db, router, GoalsConfig())

        # Seed a goal that claims 15 checkpoints but only has 5 rows,
        # all completed. Matches the production state at the time the
        # operator complained.
        goal_id = "stalled-goal-id"
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        await db.execute_insert(
            "INSERT INTO goals (goal_id, session_id, goal, status, plan_json, "
            "context_summary, current_checkpoint, total_checkpoints, attempts, "
            "max_attempts, llm_calls_used, cost_usd, created_at, updated_at) "
            "VALUES (?, ?, ?, 'active', '[]', '', 5, 15, 0, 3, 0, 0.0, ?, ?)",
            (goal_id, None, "stalled goal", now, now),
        )
        for i in range(1, 6):
            await db.execute_insert(
                "INSERT INTO goal_checkpoints "
                "(goal_id, checkpoint_order, title, description, "
                "success_criteria, status, completed_at) "
                "VALUES (?, ?, ?, '', '', 'completed', ?)",
                (goal_id, i, f"Step {i}", now),
            )

        ctx = CandidateContext(goal_manager=gm)
        candidates = await from_workable_checkpoints(ctx)

        # Must surface a revise candidate so the agent can recover.
        revise_cands = [c for c in candidates if c.metadata.get("kind") == "revise"]
        assert len(revise_cands) == 1, (
            f"stalled goal should yield exactly one revise candidate; "
            f"got {len(revise_cands)} (full menu: "
            f"{[c.metadata for c in candidates]})"
        )
        c = revise_cands[0]
        assert c.metadata["goal_id"] == goal_id
        assert c.metadata["completed_in_db"] == 5
        assert c.metadata["expected_total"] == 15
        # Score signal: expected_value high enough to outrank role_neglect
        # (2.5) and reflex_capability_review (5.0). 7.5 puts the
        # quality term (7.5*0.85 = 6.4) above both.
        assert c.expected_value >= 7.0


class TestMissionMomentumGenerator:
    @pytest.mark.asyncio
    async def test_proposes_one_candidate_per_neglected_mission(self, tmp_path) -> None:
        from core.database import Database
        from core.mind_candidates import CandidateContext, from_mission_momentum
        from core.mission_manager import MissionManager

        db = Database(str(tmp_path / "t.db"))
        await db.initialize()
        mm = MissionManager(db)
        await mm.create("M1", priority_weight=2.0, mission_id="m1")
        await mm.create("M2", priority_weight=1.0, mission_id="m2")

        ctx = CandidateContext(mission_manager=mm, dream_focus="research")
        out = await from_mission_momentum(ctx)
        assert len(out) == 2
        assert all(c.source == "mission_momentum" for c in out)
        assert {c.mission_id for c in out} == {"m1", "m2"}

    @pytest.mark.asyncio
    async def test_never_touched_gets_strong_stale_bonus(self, tmp_path) -> None:
        from core.database import Database
        from core.mind_candidates import CandidateContext, from_mission_momentum
        from core.mission_manager import MissionManager

        db = Database(str(tmp_path / "t.db"))
        await db.initialize()
        mm = MissionManager(db)
        await mm.create("Fresh", priority_weight=1.0, mission_id="m1")

        ctx = CandidateContext(mission_manager=mm)
        out = await from_mission_momentum(ctx)
        assert out
        assert out[0].staleness_bonus >= 5.0


class TestDreamGenerator:
    @pytest.mark.asyncio
    async def test_always_returns_one_candidate(self) -> None:
        from core.mind_candidates import CandidateContext, from_dream

        out = await from_dream(CandidateContext())
        assert len(out) == 1
        assert out[0].source == "dream"
        assert out[0].lens_match == 1.0  # dream is always on-focus

    @pytest.mark.asyncio
    async def test_value_decays_with_workable_count(self, tmp_path) -> None:
        """When goals already exist, dreaming up new ones is worth
        less — encoded via reduced expected_value."""
        from core.mind_candidates import CandidateContext, from_dream

        class FakeGM:
            def __init__(self, count: int) -> None:
                self._count = count

            async def list_goals(self, status: str = None, limit: int = 20):
                return [object()] * self._count if status == "active" else []

        no_goals = await from_dream(CandidateContext(goal_manager=FakeGM(0)))
        many_goals = await from_dream(CandidateContext(goal_manager=FakeGM(5)))
        assert no_goals[0].expected_value > many_goals[0].expected_value

    @pytest.mark.asyncio
    async def test_one_active_goal_already_demotes_dream(self) -> None:
        """Operator regression: the agent kept dreaming up new goals
        while existing ones sat incomplete (legal-pdf at 5/15,
        operating stance at 11/12). Old decay was 1.0 per goal —
        2 active goals → expected=5.0, still competitive. New shape
        is a hard knee: ANY active goal collapses dream to 2.0 so
        it ranks below role rotation / workable_checkpoint / reflexes.
        """
        from core.mind_candidates import CandidateContext, from_dream

        class FakeGM:
            def __init__(self, count: int) -> None:
                self._count = count

            async def list_goals(self, status: str = None, limit: int = 20):
                return [object()] * self._count if status == "active" else []

        zero = await from_dream(CandidateContext(goal_manager=FakeGM(0)))
        one = await from_dream(CandidateContext(goal_manager=FakeGM(1)))
        # Hard knee: 0 → 7.0, 1+ → 2.0 (anything well below
        # workable_checkpoint's typical 4.0–8.0 range).
        assert zero[0].expected_value == 7.0
        assert one[0].expected_value == 2.0
        # And the workable-count is surfaced in metadata for debug.
        assert one[0].metadata.get("workable_goals") == 1


class TestEndToEndArbiter:
    @pytest.mark.asyncio
    async def test_stuck_state_yields_dream_or_reflex_as_top_pick(
        self, tmp_path
    ) -> None:
        """The exact failure mode that drove this redesign: no
        workable goals, several never-touched missions. The arbiter
        must surface DREAM or MISSION_MOMENTUM at the top — never an
        empty menu, never "bounded reconciliation"."""
        from core.database import Database
        from core.mind_arbiter import ArbiterWeights, arbitrate
        from core.mind_candidates import CandidateContext, collect_all
        from core.mission_manager import MissionManager

        db = Database(str(tmp_path / "t.db"))
        await db.initialize()
        mm = MissionManager(db)
        await mm.create("Promote alphascala", priority_weight=2.5, mission_id="a")
        await mm.create("Grow EloPhanto", priority_weight=2.0, mission_id="b")

        class NoGoalsGM:
            def __init__(self, db):
                self._db = db

            async def list_goals(self, status: str = None, limit: int = 20):
                return []

        ctx = CandidateContext(
            goal_manager=NoGoalsGM(db),
            mission_manager=mm,
            dream_focus="research",
        )
        candidates = await collect_all(ctx)
        assert candidates, "arbiter must never produce empty menu in stuck state"

        scored = arbitrate(
            candidates,
            ArbiterWeights(),
            mission_weights={"a": 2.5, "b": 2.0},
            top_k=5,
        )
        top_sources = {sc.candidate.source for sc in scored[:3]}
        # The first three should include either dream or a mission move.
        assert top_sources & {"dream", "mission_momentum"}
