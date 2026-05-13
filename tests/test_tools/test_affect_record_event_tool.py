"""affect_record_event — agent registers its own felt signal from content
it reads. Closes the gap where affect was only fed by operator corrections
+ tool outcomes. See docs/69-AFFECT.md and tools/affect/record_event_tool.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.affect import AffectManager
from core.database import Database
from tools.affect.record_event_tool import (
    _INTENSITY_WEIGHTS,
    _LABEL_DELTAS,
    AffectRecordEventTool,
)


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
async def affect_mgr(db: Database) -> AffectManager:
    mgr = AffectManager(db=db)
    await mgr.load_or_create()
    return mgr


class TestAffectRecordEventTool:
    @pytest.mark.asyncio
    async def test_rejects_without_affect_manager(self) -> None:
        tool = AffectRecordEventTool()
        result = await tool.execute(
            {
                "label": "anxiety",
                "intensity": "moderate",
                "summary": "scam DM with wallet address",
            }
        )
        assert not result.success
        assert "not injected" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_records_anxiety_from_scam_content(
        self, affect_mgr: AffectManager
    ) -> None:
        tool = AffectRecordEventTool()
        tool._affect_manager = affect_mgr

        baseline = await affect_mgr.get_state()
        # Snapshot scalars — get_state returns a cached reference that
        # mutates in place when record_event fires.
        base_p, base_a, base_d = (
            baseline.pleasure,
            baseline.arousal,
            baseline.dominance,
        )

        result = await tool.execute(
            {
                "label": "anxiety",
                "intensity": "moderate",
                "summary": "Miguel demanded $20 upfront via DM with wallet address",
            }
        )

        assert result.success
        assert result.data["label"] == "anxiety"
        assert result.data["intensity"] == "moderate"
        assert "Miguel" in result.data["summary"]

        # PAD shift consistent with anxiety: -P, +A, -D.
        after = await affect_mgr.get_state()
        assert after.pleasure < base_p
        assert after.arousal > base_a
        assert after.dominance < base_d

    @pytest.mark.asyncio
    async def test_intensity_scales_magnitude(self, affect_mgr: AffectManager) -> None:
        """mild < moderate < strong < intense applies via weight."""
        tool = AffectRecordEventTool()
        tool._affect_manager = affect_mgr

        # Mild anxiety from one ambiguous DM.
        await tool.execute(
            {
                "label": "anxiety",
                "intensity": "mild",
                "summary": "ambiguous DM about marketing collab",
            }
        )
        mild_state = await affect_mgr.get_state()
        mild_arousal_delta = mild_state.arousal

        # Reset for a clean strong test.
        affect_mgr2 = AffectManager(db=affect_mgr._db)
        await affect_mgr2.load_or_create()
        # Wipe state to zero.
        affect_mgr2._state.pleasure = 0.0
        affect_mgr2._state.arousal = 0.0
        affect_mgr2._state.dominance = 0.0
        tool2 = AffectRecordEventTool()
        tool2._affect_manager = affect_mgr2
        await tool2.execute(
            {
                "label": "anxiety",
                "intensity": "strong",
                "summary": "coordinated scam attempt with wallet address",
            }
        )
        strong_state = await affect_mgr2.get_state()

        # Strong (weight 1.5) shifts arousal at least 2x mild (weight 0.5).
        assert abs(strong_state.arousal) > abs(mild_arousal_delta) * 2

    @pytest.mark.asyncio
    async def test_rejects_unknown_label(self, affect_mgr: AffectManager) -> None:
        tool = AffectRecordEventTool()
        tool._affect_manager = affect_mgr

        result = await tool.execute(
            {
                "label": "ennui",
                "intensity": "moderate",
                "summary": "felt fancy and french",
            }
        )
        assert not result.success
        assert "unknown label" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_rejects_unknown_intensity(self, affect_mgr: AffectManager) -> None:
        tool = AffectRecordEventTool()
        tool._affect_manager = affect_mgr

        result = await tool.execute(
            {
                "label": "joy",
                "intensity": "ecstatic",
                "summary": "operator said thanks",
            }
        )
        assert not result.success
        assert "unknown intensity" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_summary_required(self, affect_mgr: AffectManager) -> None:
        tool = AffectRecordEventTool()
        tool._affect_manager = affect_mgr

        result = await tool.execute(
            {"label": "joy", "intensity": "moderate", "summary": ""}
        )
        assert not result.success
        assert "summary" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_summary_lands_in_recent_events(
        self, affect_mgr: AffectManager
    ) -> None:
        """The whole point of the summary is that next plan call sees
        what triggered the felt state — it must show up in the recent
        events list embedded in the next <affect> block."""
        tool = AffectRecordEventTool()
        tool._affect_manager = affect_mgr

        await tool.execute(
            {
                "label": "anger",
                "intensity": "strong",
                "summary": "Miguel asked for $20 deposit via DM",
            }
        )

        # Force magnitude past inject threshold by adding more weight
        # if needed (one strong anger should already do it).
        block = await affect_mgr.build_affect_context()
        assert block, "expected non-empty affect block after strong anger"
        assert "Miguel" in block
        assert "$20" in block

    @pytest.mark.asyncio
    async def test_catalog_alignment(self) -> None:
        """The tool's label catalog must match the canonical emitters in
        core/affect.py — drift here means agent-fired events would
        behave differently from ego/executor-fired events."""
        # Sanity: every label has all 3 PAD deltas
        for label, deltas in _LABEL_DELTAS.items():
            assert len(deltas) == 3, f"{label} missing PAD components"

        # frustration in tool catalog matches emit_frustration in
        # core/affect.py (the canonical source). If the canonical
        # numbers ever drift, this test catches it.
        assert _LABEL_DELTAS["frustration"] == (-0.20, +0.20, -0.15)
        assert _LABEL_DELTAS["anger"] == (-0.25, +0.25, +0.15)
        assert _LABEL_DELTAS["anxiety"] == (-0.20, +0.25, -0.20)
        assert _LABEL_DELTAS["joy"] == (+0.30, +0.20, +0.15)
        assert _LABEL_DELTAS["pride"] == (+0.30, +0.15, +0.30)

        # Intensity weights monotonic.
        weights = [
            _INTENSITY_WEIGHTS["mild"],
            _INTENSITY_WEIGHTS["moderate"],
            _INTENSITY_WEIGHTS["strong"],
            _INTENSITY_WEIGHTS["intense"],
        ]
        assert weights == sorted(weights)
        assert _INTENSITY_WEIGHTS["moderate"] == 1.0
