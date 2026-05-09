"""AffectManager tests — PAD substrate, decay, OCC label resolution,
repeat compounding, system-prompt block, markdown render.

See docs/69-AFFECT.md for the design rationale these tests pin.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.affect import (
    _DEFAULT_EVENT_HALFLIFE_SECONDS,
    _INJECT_THRESHOLD,
    _LABEL_VECTORS,
    _PAD_CEIL,
    _PAD_FLOOR,
    AffectManager,
    emit_anxiety,
    emit_frustration,
    emit_joy,
    emit_pride,
    emit_relief,
    emit_satisfaction,
)
from core.config import IdentityConfig
from core.database import Database


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


# ---------------------------------------------------------------------------
# PAD substrate
# ---------------------------------------------------------------------------


class TestPADSubstrate:
    @pytest.mark.asyncio
    async def test_load_or_create_starts_at_zero(self, db: Database) -> None:
        mgr = AffectManager(db=db)
        state = await mgr.load_or_create()
        assert state.pleasure == 0.0
        assert state.arousal == 0.0
        assert state.dominance == 0.0

    @pytest.mark.asyncio
    async def test_record_event_moves_state(self, db: Database) -> None:
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        ok = await mgr.record_event(
            label="frustration",
            source="ego",
            pleasure_delta=-0.20,
            arousal_delta=+0.20,
            dominance_delta=-0.15,
        )
        assert ok is True
        state = await mgr.get_state()
        assert state.pleasure < 0
        assert state.arousal > 0
        assert state.dominance < 0

    @pytest.mark.asyncio
    async def test_state_is_clamped_to_pad_bounds(self, db: Database) -> None:
        """Ten consecutive positive frustration events shouldn't push
        any channel past +1 or below -1."""
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        for _ in range(20):
            await mgr.record_event(
                label="anxiety",
                source="ego",
                pleasure_delta=-0.5,
                arousal_delta=+0.5,
                dominance_delta=-0.5,
            )
        state = await mgr.get_state()
        assert _PAD_FLOOR <= state.pleasure <= _PAD_CEIL
        assert _PAD_FLOOR <= state.arousal <= _PAD_CEIL
        assert _PAD_FLOOR <= state.dominance <= _PAD_CEIL

    @pytest.mark.asyncio
    async def test_persistence_round_trip(self, db: Database, tmp_path: Path) -> None:
        """State persists across manager re-instantiation."""
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        await emit_frustration(mgr, source="ego")

        mgr2 = AffectManager(db=db)
        loaded = await mgr2.load_or_create()
        # Correction-like signal should be visible in the second load.
        # We allow tiny drift because load_or_create runs a decay sweep.
        assert loaded.pleasure < 0
        assert loaded.arousal > 0


# ---------------------------------------------------------------------------
# OCC label resolution
# ---------------------------------------------------------------------------


class TestOCCLabels:
    @pytest.mark.asyncio
    async def test_neutral_state_resolves_to_equanimity(self, db: Database) -> None:
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        mood = await mgr.current_mood()
        assert mood["dominant_label"] == "equanimity"

    @pytest.mark.asyncio
    async def test_strong_frustration_resolves_to_frustration_label(
        self, db: Database
    ) -> None:
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        # Push hard so the closest target is unambiguously frustration.
        for _ in range(3):
            await emit_frustration(mgr, source="ego")
        mood = await mgr.current_mood()
        assert mood["dominant_label"] == "frustration"

    @pytest.mark.asyncio
    async def test_pride_state_resolves_to_pride_label(self, db: Database) -> None:
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        await emit_pride(mgr, source="goal")
        mood = await mgr.current_mood()
        # Could land on pride or joy depending on deltas; both are
        # high-pleasure positive states so the test accepts either.
        assert mood["dominant_label"] in ("pride", "joy")

    @pytest.mark.asyncio
    async def test_label_vectors_within_bounds(self) -> None:
        """Every OCC label target vector must live within [-1, +1]^3."""
        for label, (p, a, d) in _LABEL_VECTORS.items():
            assert -1.0 <= p <= 1.0, f"{label} p={p}"
            assert -1.0 <= a <= 1.0, f"{label} a={a}"
            assert -1.0 <= d <= 1.0, f"{label} d={d}"


# ---------------------------------------------------------------------------
# Decay
# ---------------------------------------------------------------------------


class TestDecay:
    @pytest.mark.asyncio
    async def test_decay_pulls_toward_zero(self, db: Database) -> None:
        mgr = AffectManager(db=db)
        state = await mgr.load_or_create()
        await emit_frustration(mgr, source="ego")
        peak_p = abs(state.pleasure)
        peak_a = abs(state.arousal)
        # Backdate last_decay_at by 1 hour to simulate time passing.
        state.last_decay_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        moved = mgr._apply_decay_pure(state)
        assert moved
        # Both channels should have decayed toward zero (smaller |value|).
        assert abs(state.pleasure) < peak_p
        assert abs(state.arousal) < peak_a

    @pytest.mark.asyncio
    async def test_decay_is_rate_limited(self, db: Database) -> None:
        """Calling decay twice in quick succession should be a no-op
        the second time."""
        mgr = AffectManager(db=db)
        state = await mgr.load_or_create()
        await emit_anxiety(mgr, source="verification")
        # Backdate so the first decay actually fires.
        state.last_decay_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        first = mgr._apply_decay_pure(state)
        second = mgr._apply_decay_pure(state)
        assert first
        assert not second

    @pytest.mark.asyncio
    async def test_arousal_decays_faster_than_dominance(self, db: Database) -> None:
        """Per-channel half-lives differ: arousal 10 min vs dominance
        2 hours. After one hour idle, arousal should retain less of
        its original magnitude than dominance does."""
        mgr = AffectManager(db=db)
        state = await mgr.load_or_create()
        # Manually plant equal-magnitude values so we can compare.
        state.arousal = 0.8
        state.dominance = 0.8
        state.last_decay_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        mgr._apply_decay_pure(state)
        # 1h at 10min half-life → 6 half-lives → ~0.0125 of 0.8 → ~0.01
        # 1h at 2h half-life → 0.5 half-lives → ~0.707 of 0.8 → ~0.566
        assert abs(state.arousal) < abs(state.dominance)
        assert abs(state.arousal) < 0.05
        assert abs(state.dominance) > 0.4


# ---------------------------------------------------------------------------
# Repeat compounding
# ---------------------------------------------------------------------------


class TestRepeatCompounding:
    @pytest.mark.asyncio
    async def test_three_frustrations_in_a_row_compound(self, db: Database) -> None:
        """Three frustration events fired within 5 min should produce
        more state movement than a single event would, accounting for
        the repeat multiplier (1 + 0.5 × n, capped at 2.5)."""
        mgr_solo = AffectManager(db=db)
        await mgr_solo.load_or_create()
        await emit_frustration(mgr_solo, source="ego")
        solo_p = (await mgr_solo.get_state()).pleasure

        # Reset with a fresh DB-backed manager.
        # Use a separate db file.
        db2_path = Path(db._db_path).parent / "test_compound.db"
        d2 = Database(db2_path)
        await d2.initialize()
        try:
            mgr_triple = AffectManager(db=d2)
            await mgr_triple.load_or_create()
            for _ in range(3):
                await emit_frustration(mgr_triple, source="ego")
            triple_p = (await mgr_triple.get_state()).pleasure
            # Triple-fire should land further from zero than single.
            assert abs(triple_p) > abs(solo_p)
            # Floor: even with the repeat multiplier, compounding can't
            # exceed (single + 1.5×single + 2.0×single) ≈ 4.5×single.
            assert abs(triple_p) <= max(abs(solo_p) * 5, 1.0)
        finally:
            await d2.close()


# ---------------------------------------------------------------------------
# System prompt block
# ---------------------------------------------------------------------------


class TestSystemPromptBlock:
    @pytest.mark.asyncio
    async def test_neutral_state_returns_empty_block(self, db: Database) -> None:
        """Token-cost gate: when state is near zero, skip injection."""
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        block = await mgr.build_affect_context()
        assert block == ""

    @pytest.mark.asyncio
    async def test_active_state_includes_xml_block(self, db: Database) -> None:
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        for _ in range(3):
            await emit_frustration(mgr, source="ego")
        block = await mgr.build_affect_context()
        assert "<affect>" in block
        assert "</affect>" in block
        assert "frustration" in block
        # Numeric state present.
        assert "pleasure=" in block
        assert "arousal=" in block

    @pytest.mark.asyncio
    async def test_block_includes_recent_events(self, db: Database) -> None:
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        await emit_anxiety(mgr, source="verification")
        await emit_frustration(mgr, source="ego")
        block = await mgr.build_affect_context()
        assert "<recent>" in block
        assert "anxiety" in block

    @pytest.mark.asyncio
    async def test_inject_threshold_respected(self, db: Database) -> None:
        """Verify the gate fires at exactly the documented threshold."""
        mgr = AffectManager(db=db)
        state = await mgr.load_or_create()
        # Plant a state just BELOW threshold (sum of abs < threshold).
        below = _INJECT_THRESHOLD - 0.05
        per_channel = below / 3
        state.pleasure = per_channel
        state.arousal = per_channel
        state.dominance = per_channel
        await mgr._persist_state(state)
        assert (await mgr.build_affect_context()) == ""

        # Plant a state just ABOVE threshold.
        above = _INJECT_THRESHOLD + 0.10
        per_channel = above / 3
        state.pleasure = per_channel
        state.arousal = per_channel
        state.dominance = per_channel
        await mgr._persist_state(state)
        assert "<affect>" in (await mgr.build_affect_context())


# ---------------------------------------------------------------------------
# Markdown render
# ---------------------------------------------------------------------------


class TestMarkdownRender:
    @pytest.mark.asyncio
    async def test_markdown_writes_with_first_person_sections(
        self, db: Database, tmp_path: Path
    ) -> None:
        affect_md = tmp_path / "affect.md"
        cfg = IdentityConfig(affect_file=str(affect_md))
        mgr = AffectManager(db=db, config=cfg)
        await mgr.load_or_create()
        await emit_frustration(mgr, source="ego")
        await mgr.update_markdown()
        text = affect_md.read_text()
        # Frontmatter + key sections.
        assert "scope: identity" in text
        assert "tags: [self, affect, emotion, state-level]" in text
        assert "# Affect (state-level)" in text
        assert "## Right now" in text
        assert "## Recent affective events" in text
        # ASCII gauge present.
        assert "pleasure" in text
        assert "arousal" in text
        assert "dominance" in text

    @pytest.mark.asyncio
    async def test_markdown_no_config_is_noop(self, db: Database) -> None:
        """When no config is provided, update_markdown must not raise."""
        mgr = AffectManager(db=db, config=None)
        await mgr.load_or_create()
        await emit_pride(mgr, source="goal")
        # Should not raise.
        await mgr.update_markdown()


# ---------------------------------------------------------------------------
# Convenience emitters
# ---------------------------------------------------------------------------


class TestConvenienceEmitters:
    @pytest.mark.asyncio
    async def test_emit_relief_is_low_arousal_positive(self, db: Database) -> None:
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        await emit_relief(mgr, source="verification")
        state = await mgr.get_state()
        assert state.pleasure > 0
        # Relief is the LOW-arousal positive state.
        assert state.arousal < 0

    @pytest.mark.asyncio
    async def test_emit_joy_is_high_arousal_positive(self, db: Database) -> None:
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        await emit_joy(mgr, source="user")
        state = await mgr.get_state()
        assert state.pleasure > 0
        assert state.arousal > 0

    @pytest.mark.asyncio
    async def test_default_event_halflife_round_trips(self, db: Database) -> None:
        """A recorded event should keep its halflife on reload."""
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        await emit_frustration(mgr, source="ego")
        mgr2 = AffectManager(db=db)
        state = await mgr2.load_or_create()
        assert state.recent_events
        assert (
            state.recent_events[-1].halflife_seconds == _DEFAULT_EVENT_HALFLIFE_SECONDS
        )


# ---------------------------------------------------------------------------
# Ego ↔ Affect coupling
# ---------------------------------------------------------------------------


class TestEgoAffectCoupling:
    @pytest.mark.asyncio
    async def test_ego_correction_emits_affect_frustration(self, db: Database) -> None:
        """When ego.record_correction fires AND ego._affect is wired,
        the affect manager should see a frustration event without
        ego importing affect at module top level."""
        from core.ego import EgoManager

        affect = AffectManager(db=db)
        await affect.load_or_create()
        ego = EgoManager(db=db, router=AsyncMock(), config=None)
        ego._affect = affect
        await ego.load_or_create()
        await ego.record_outcome("twitter_post", success=True)

        # Bare "no" — severity 1.0, below the anger threshold (2.0).
        # Lands as frustration. Compound messages like "no, that's
        # wrong" sum to severity ≥2.0 and dispatch to anger; that
        # path is covered by test_high_severity_correction_emits_anger.
        ok = await ego.record_correction("no")
        assert ok is True

        state = await affect.get_state()
        # Frustration drops pleasure, raises arousal.
        assert state.pleasure < 0
        assert state.arousal > 0
        # Recent event was recorded.
        labels = [e.label for e in state.recent_events]
        assert "frustration" in labels

    @pytest.mark.asyncio
    async def test_ego_verification_pass_emits_relief(self, db: Database) -> None:
        from core.ego import EgoManager

        affect = AffectManager(db=db)
        await affect.load_or_create()
        ego = EgoManager(db=db, router=AsyncMock(), config=None)
        ego._affect = affect
        await ego.load_or_create()
        await ego.record_outcome("scheduler", success=True)
        await ego.record_verification(
            agent_response="Did the thing.\n\nVerification: PASS",
            capability="scheduler",
        )
        state = await affect.get_state()
        labels = [e.label for e in state.recent_events]
        assert "relief" in labels

    @pytest.mark.asyncio
    async def test_ego_verification_fail_emits_anxiety(self, db: Database) -> None:
        from core.ego import EgoManager

        affect = AffectManager(db=db)
        await affect.load_or_create()
        ego = EgoManager(db=db, router=AsyncMock(), config=None)
        ego._affect = affect
        await ego.load_or_create()
        await ego.record_outcome("file_write", success=True)
        await ego.record_verification(
            agent_response="Tried.\n\nVerification: FAIL",
            capability="file_write",
        )
        state = await affect.get_state()
        labels = [e.label for e in state.recent_events]
        assert "anxiety" in labels

    @pytest.mark.asyncio
    async def test_ego_without_affect_handle_does_not_break(self, db: Database) -> None:
        """Ego must keep working with no affect manager wired."""
        from core.ego import EgoManager

        ego = EgoManager(db=db, router=AsyncMock(), config=None)
        ego._affect = None
        await ego.load_or_create()
        await ego.record_outcome("scheduler", success=True)
        # Should not raise.
        await ego.record_correction("no")
        await ego.record_verification(
            agent_response="Verification: PASS",
            capability="scheduler",
        )


# ---------------------------------------------------------------------------
# Phase 2 — temperature bias
# ---------------------------------------------------------------------------


class TestTemperatureBias:
    @pytest.mark.asyncio
    async def test_neutral_state_returns_zero_modifier(self, db: Database) -> None:
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        assert (await mgr.temperature_modifier()) == 0.0

    @pytest.mark.asyncio
    async def test_negative_pleasure_pulls_temp_down(self, db: Database) -> None:
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        for _ in range(3):
            await emit_frustration(mgr, source="ego")
        delta = await mgr.temperature_modifier()
        assert delta < 0
        assert delta >= -0.2  # capped

    @pytest.mark.asyncio
    async def test_positive_pleasure_pushes_temp_up(self, db: Database) -> None:
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        for _ in range(3):
            await emit_joy(mgr, source="user")
        delta = await mgr.temperature_modifier()
        assert delta > 0
        assert delta <= 0.2  # capped

    @pytest.mark.asyncio
    async def test_modifier_is_bounded(self, db: Database) -> None:
        """Even hammered with anxiety, the modifier never exceeds
        ±0.2 — that's the documented cap."""
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        for _ in range(20):
            await emit_anxiety(mgr, source="executor")
        delta = await mgr.temperature_modifier()
        assert -0.2 <= delta <= 0.2


# ---------------------------------------------------------------------------
# Phase 3 — affect feeds ego
# ---------------------------------------------------------------------------


class TestAffectFeedsEgo:
    @pytest.mark.asyncio
    async def test_summarize_for_ego_neutral_returns_empty(self, db: Database) -> None:
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        assert (await mgr.summarize_for_ego()) == ""

    @pytest.mark.asyncio
    async def test_summarize_for_ego_includes_label_and_pad(self, db: Database) -> None:
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        for _ in range(3):
            await emit_frustration(mgr, source="ego")
        summary = await mgr.summarize_for_ego()
        assert summary
        assert "frustration" in summary
        assert "PAD" in summary
        assert "frustration×" in summary


# ---------------------------------------------------------------------------
# Phase 4 — pause suggestion (opt-in)
# ---------------------------------------------------------------------------


class TestPauseSuggestion:
    @pytest.mark.asyncio
    async def test_neutral_state_does_not_suggest_pause(self, db: Database) -> None:
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        assert (await mgr.should_suggest_pause()) is False

    @pytest.mark.asyncio
    async def test_strong_frustration_suggests_pause(self, db: Database) -> None:
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        for _ in range(10):
            await emit_frustration(mgr, source="ego")
        assert (await mgr.should_suggest_pause()) is True

    @pytest.mark.asyncio
    async def test_strong_joy_does_not_suggest_pause(self, db: Database) -> None:
        """Pause is gated to NEGATIVE labels only — a manic-joyful state
        is high-magnitude but should not trigger a pause."""
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        for _ in range(10):
            await emit_joy(mgr, source="user")
        assert (await mgr.should_suggest_pause()) is False

    @pytest.mark.asyncio
    async def test_pause_note_only_appears_when_allowed(self, db: Database) -> None:
        """build_affect_context must NOT emit the pause guidance unless
        explicitly allowed via the keyword arg, even when state would
        otherwise warrant it."""
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        for _ in range(10):
            await emit_frustration(mgr, source="ego")
        block_default = await mgr.build_affect_context()
        assert "stretched" not in block_default.lower()
        block_opted = await mgr.build_affect_context(allow_pause_note=True)
        assert "stretched" in block_opted.lower()


# ---------------------------------------------------------------------------
# Anger — escalation from frustration when severity is high
# ---------------------------------------------------------------------------


class TestAnger:
    @pytest.mark.asyncio
    async def test_emit_anger_resolves_to_anger_label(self, db: Database) -> None:
        from core.affect import emit_anger

        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        for _ in range(3):
            await emit_anger(mgr, source="ego")
        mood = await mgr.current_mood()
        assert mood["dominant_label"] == "anger"

    @pytest.mark.asyncio
    async def test_anger_has_positive_dominance(self, db: Database) -> None:
        """The defining feature of anger vs frustration is +D — pushing
        back, not blocked. Three angers should land at +D, three
        frustrations should land at -D."""
        from core.affect import emit_anger

        mgr_a = AffectManager(db=db)
        await mgr_a.load_or_create()
        for _ in range(3):
            await emit_anger(mgr_a, source="ego")
        anger_d = (await mgr_a.get_state()).dominance
        assert anger_d > 0

        # Frustration on a separate DB to avoid label compounding.
        from core.database import Database as _DB

        db2_path = Path(db._db_path).parent / "test_anger_vs_frust.db"
        d2 = _DB(db2_path)
        await d2.initialize()
        try:
            mgr_f = AffectManager(db=d2)
            await mgr_f.load_or_create()
            for _ in range(3):
                await emit_frustration(mgr_f, source="ego")
            frust_d = (await mgr_f.get_state()).dominance
            assert frust_d < 0
            assert anger_d > frust_d
        finally:
            await d2.close()

    @pytest.mark.asyncio
    async def test_anger_is_pause_eligible(self, db: Database) -> None:
        """Anger should suggest a pause once magnitude crosses the gate."""
        from core.affect import emit_anger

        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        for _ in range(8):
            await emit_anger(mgr, source="ego")
        assert (await mgr.should_suggest_pause()) is True

    @pytest.mark.asyncio
    async def test_high_severity_correction_emits_anger_not_frustration(
        self, db: Database
    ) -> None:
        """ego.record_correction must dispatch on severity:
        - severity >= 2.0 ('Nth time I told you') → anger
        - severity < 2.0 ('no', 'wrong')          → frustration
        """
        from core.ego import EgoManager

        affect = AffectManager(db=db)
        await affect.load_or_create()
        ego = EgoManager(db=db, router=AsyncMock(), config=None)
        ego._affect = affect
        await ego.load_or_create()
        await ego.record_outcome("scheduler", success=True)

        # The "Nth time I told you" pattern has severity 2.5.
        await ego.record_correction("this is the 10th time i told you to stop")
        labels = [e.label for e in (await affect.get_state()).recent_events]
        assert "anger" in labels
        assert "frustration" not in labels

    @pytest.mark.asyncio
    async def test_low_severity_correction_still_emits_frustration(
        self, db: Database
    ) -> None:
        from core.ego import EgoManager

        affect = AffectManager(db=db)
        await affect.load_or_create()
        ego = EgoManager(db=db, router=AsyncMock(), config=None)
        ego._affect = affect
        await ego.load_or_create()
        await ego.record_outcome("scheduler", success=True)

        # A bare "no" has severity 1.0 — should land as frustration.
        await ego.record_correction("no")
        labels = [e.label for e in (await affect.get_state()).recent_events]
        assert "frustration" in labels
        assert "anger" not in labels


class TestSatisfactionEmitter:
    """Pin the common-positive-baseline emitter added 2026-05-09. Three
    days of prod data showed zero positive events ever fired because
    pride and joy required rare events. Satisfaction is the everyday
    win signal; magnitudes are intentionally one-third of pride/joy."""

    @pytest.mark.asyncio
    async def test_satisfaction_lands_as_positive_pleasure(self, db: Database) -> None:
        affect = AffectManager(db=db)
        await affect.load_or_create()
        await emit_satisfaction(affect, source="task")
        state = await affect.get_state()
        assert state.pleasure > 0
        assert state.dominance > 0

    @pytest.mark.asyncio
    async def test_satisfaction_smaller_than_pride(self, tmp_path: Path) -> None:
        """A win at task-completion granularity must not eclipse a real
        pride-grade event. Otherwise routine completions would flood
        the channel and the agent would never feel a real triumph."""
        db1 = Database(tmp_path / "sat.db")
        await db1.initialize()
        a1 = AffectManager(db=db1)
        await a1.load_or_create()
        await emit_satisfaction(a1, source="task")
        sat_state = await a1.get_state()
        await db1.close()

        db2 = Database(tmp_path / "pride.db")
        await db2.initialize()
        a2 = AffectManager(db=db2)
        await a2.load_or_create()
        await emit_pride(a2, source="goal")
        pride_state = await a2.get_state()
        await db2.close()

        assert sat_state.pleasure < pride_state.pleasure
        assert sat_state.dominance < pride_state.dominance
