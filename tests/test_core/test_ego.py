"""EgoManager tests — outcome recording, confidence dynamics, recompute,
and self-perception context."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.config import IdentityConfig
from core.database import Database
from core.ego import (
    _CONF_CEIL,
    _CONF_DEFAULT,
    _CONF_FLOOR,
    _RECOMPUTE_EVERY,
    EgoManager,
)


@dataclass
class FakeLLMResponse:
    content: str


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def router() -> AsyncMock:
    r = AsyncMock()
    r.complete = AsyncMock(
        return_value=FakeLLMResponse(
            content=json.dumps(
                {
                    "self_image": "Honest about gaps; better at writing than betting.",
                    "self_critique": "Overconfident on polymarket given recent losses.",
                }
            )
        )
    )
    return r


class TestEgoManager:
    @pytest.mark.asyncio
    async def test_load_or_create_creates_default(
        self, db: Database, router: AsyncMock
    ) -> None:
        mgr = EgoManager(db=db, router=router)
        ego = await mgr.load_or_create()
        assert ego.confidence == {}
        assert ego.coherence_score == 1.0
        assert ego.tasks_since_recompute == 0

    @pytest.mark.asyncio
    async def test_load_or_create_idempotent(
        self, db: Database, router: AsyncMock
    ) -> None:
        mgr = EgoManager(db=db, router=router)
        await mgr.load_or_create()
        await mgr.record_outcome("polymarket_trading", success=False)
        # Reload via a fresh manager — state must persist
        mgr2 = EgoManager(db=db, router=router)
        ego2 = await mgr2.load_or_create()
        assert "polymarket_trading" in ego2.confidence
        assert ego2.confidence["polymarket_trading"] < _CONF_DEFAULT

    @pytest.mark.asyncio
    async def test_failure_lowers_confidence_more_than_success_raises(
        self, db: Database, router: AsyncMock
    ) -> None:
        """Asymmetric updates — one failure should outweigh one routine success."""
        mgr = EgoManager(db=db, router=router)
        await mgr.load_or_create()
        await mgr.record_outcome("x_engagement", success=True)
        ego = await mgr.get_ego()
        after_success = ego.confidence["x_engagement"]
        await mgr.record_outcome("x_engagement", success=False)
        ego = await mgr.get_ego()
        after_failure = ego.confidence["x_engagement"]
        # The failure step should move strictly further from prior than the
        # success step did — i.e., asymmetric weighting is real.
        assert (_CONF_DEFAULT - after_failure) > (after_success - _CONF_DEFAULT)

    @pytest.mark.asyncio
    async def test_confidence_bounded(self, db: Database, router: AsyncMock) -> None:
        mgr = EgoManager(db=db, router=router)
        await mgr.load_or_create()
        for _ in range(200):
            await mgr.record_outcome("code_editing", success=True)
        ego = await mgr.get_ego()
        assert ego.confidence["code_editing"] <= _CONF_CEIL

        for _ in range(200):
            await mgr.record_outcome("code_editing", success=False)
        ego = await mgr.get_ego()
        assert ego.confidence["code_editing"] >= _CONF_FLOOR

    @pytest.mark.asyncio
    async def test_humbling_event_capped_and_lowers_coherence(
        self, db: Database, router: AsyncMock
    ) -> None:
        mgr = EgoManager(db=db, router=router)
        await mgr.load_or_create()
        for i in range(8):  # exceeds the in-memory cap of 5
            await mgr.record_humbling(
                capability="polymarket_trading",
                claimed=f"careful with money #{i}",
                actual=f"lost money #{i}",
            )
        ego = await mgr.get_ego()
        assert len(ego.humbling_events) == 5
        # Most recent should be retained
        assert ego.humbling_events[-1].claimed == "careful with money #7"
        assert ego.coherence_score < 1.0

    @pytest.mark.asyncio
    async def test_should_attempt(self, db: Database, router: AsyncMock) -> None:
        mgr = EgoManager(db=db, router=router)
        await mgr.load_or_create()
        # Drive confidence high
        for _ in range(50):
            await mgr.record_outcome("knowledge_management", success=True)
        assert await mgr.should_attempt("knowledge_management", difficulty=0.3) == "yes"

        # Drive a different cap low
        for _ in range(50):
            await mgr.record_outcome("polymarket_trading", success=False)
        assert (
            await mgr.should_attempt("polymarket_trading", difficulty=0.5) == "decline"
        )

    @pytest.mark.asyncio
    async def test_maybe_recompute_runs_at_threshold(
        self, db: Database, router: AsyncMock
    ) -> None:
        mgr = EgoManager(db=db, router=router)
        await mgr.load_or_create()
        for _ in range(_RECOMPUTE_EVERY - 1):
            await mgr.record_outcome("x_engagement", success=True)
        assert not await mgr.maybe_recompute("identity-summary")
        await mgr.record_outcome("x_engagement", success=True)
        assert await mgr.maybe_recompute("identity-summary")
        ego = await mgr.get_ego()
        assert ego.self_image.startswith("Honest")
        assert "polymarket" in ego.last_self_critique
        assert ego.tasks_since_recompute == 0
        router.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_recompute_failure_keeps_previous_state(self, db: Database) -> None:
        bad_router = AsyncMock()
        bad_router.complete = AsyncMock(side_effect=RuntimeError("LLM down"))
        mgr = EgoManager(db=db, router=bad_router)
        await mgr.load_or_create()
        await mgr.record_outcome("x_engagement", success=True)
        ego_before = await mgr.get_ego()
        prior_image = ego_before.self_image
        await mgr.recompute("identity-summary")
        ego_after = await mgr.get_ego()
        # Failure must not blank the self-image or crash
        assert ego_after.self_image == prior_image

    @pytest.mark.asyncio
    async def test_build_self_perception_context_empty_when_unused(
        self, db: Database, router: AsyncMock
    ) -> None:
        mgr = EgoManager(db=db, router=router)
        await mgr.load_or_create()
        assert await mgr.build_self_perception_context() == ""

    @pytest.mark.asyncio
    async def test_markdown_mirror_written_on_humbling_and_recompute(
        self, db: Database, router: AsyncMock, tmp_path: Path
    ) -> None:
        ego_md = tmp_path / "knowledge" / "self" / "ego.md"
        config = IdentityConfig(ego_file=str(ego_md))
        mgr = EgoManager(db=db, router=router, config=config)
        await mgr.load_or_create()

        await mgr.record_humbling(
            capability="polymarket_trading",
            claimed="careful with money",
            actual="lost $40 on bad sig_type",
        )
        assert ego_md.exists()
        text = ego_md.read_text()
        assert "polymarket_trading" in text
        assert "lost $40" in text
        assert "scope: identity" in text  # frontmatter pattern matches nature.md

        # Drive a recompute and confirm the self_image is written through
        for _ in range(_RECOMPUTE_EVERY):
            await mgr.record_outcome("x_engagement", success=True)
        await mgr.maybe_recompute("identity-summary")
        text = ego_md.read_text()
        assert "Honest about gaps" in text
        assert "Overconfident on polymarket" in text

    @pytest.mark.asyncio
    async def test_markdown_skipped_when_no_config(
        self, db: Database, router: AsyncMock
    ) -> None:
        """No config = no markdown write. Must not crash."""
        mgr = EgoManager(db=db, router=router, config=None)
        await mgr.load_or_create()
        await mgr.record_humbling(
            capability="x", claimed="a", actual="b"
        )  # must not raise

    @pytest.mark.asyncio
    async def test_build_self_perception_context_includes_signals(
        self, db: Database, router: AsyncMock
    ) -> None:
        mgr = EgoManager(db=db, router=router)
        await mgr.load_or_create()
        await mgr.record_outcome("x_engagement", success=True)
        await mgr.record_humbling(
            capability="polymarket_trading",
            claimed="careful with money",
            actual="lost $40 on bad sig_type",
        )
        ctx = await mgr.build_self_perception_context()
        assert "<self_perception>" in ctx
        assert "x_engagement" in ctx
        assert "polymarket_trading" in ctx
        assert "lost $40" in ctx
        assert "<coherence>" in ctx


class TestEgoVoiceFields:
    """Ego-v2: first-person voice fields (proud_of / embarrassed_by /
    aspiration) and prior-self continuity are what make this an ego layer
    rather than a self-image dashboard."""

    def _voice_router(self) -> AsyncMock:
        """A router that returns all 5 ego-v2 fields."""
        r = AsyncMock()
        r.complete = AsyncMock(
            return_value=FakeLLMResponse(
                content=json.dumps(
                    {
                        "self_image": "I notice I'm steady on read-only ops but I keep flinching from web_search.",
                        "proud_of": "I shipped the pumpfun stream without faking a single line.",
                        "embarrassed_by": "I'm at 0.55 on web_search and I keep finding reasons not to use it.",
                        "aspiration": "I want to be the agent that picks up unfamiliar tools without ceremony.",
                        "self_critique": "I'm trading breadth for the comfort of the loops I already know.",
                    }
                )
            )
        )
        return r

    @pytest.mark.asyncio
    async def test_recompute_persists_all_voice_fields(self, db: Database) -> None:
        mgr = EgoManager(db=db, router=self._voice_router())
        await mgr.load_or_create()
        await mgr.record_outcome("x_engagement", success=True)
        await mgr.recompute("identity-summary")

        ego = await mgr.get_ego()
        assert "I notice" in ego.self_image
        assert "pumpfun stream" in ego.proud_of
        assert "0.55 on web_search" in ego.embarrassed_by
        assert "unfamiliar tools" in ego.aspiration
        assert "trading breadth" in ego.last_self_critique

        # Round-trip through DB — fresh manager must read the same values.
        mgr2 = EgoManager(db=db, router=self._voice_router())
        ego2 = await mgr2.load_or_create()
        assert ego2.proud_of == ego.proud_of
        assert ego2.embarrassed_by == ego.embarrassed_by
        assert ego2.aspiration == ego.aspiration

    @pytest.mark.asyncio
    async def test_prior_self_image_fed_into_next_recompute(self, db: Database) -> None:
        """Continuity invariant: the second recompute must see the previous
        self_image in the user message. Without this, ego loses narrative
        arc and just rewrites itself stateless every time."""
        captured: list[str] = []

        async def fake_complete(*args, **kwargs):
            user_msg = kwargs.get("messages", [{}, {}])[1].get("content", "")
            captured.append(user_msg)
            return FakeLLMResponse(
                content=json.dumps(
                    {
                        "self_image": f"version-{len(captured)}",
                        "proud_of": "x",
                        "embarrassed_by": "y",
                        "aspiration": "z",
                        "self_critique": "w",
                    }
                )
            )

        r = AsyncMock()
        r.complete = AsyncMock(side_effect=fake_complete)

        mgr = EgoManager(db=db, router=r)
        await mgr.load_or_create()

        # First recompute — no prior self.
        await mgr.recompute("identity-summary")
        assert "no prior view" in captured[0]
        assert "version-1" in (await mgr.get_ego()).self_image

        # Second recompute — prior self_image must appear in the prompt.
        await mgr.recompute("identity-summary")
        assert "Previous self_image" in captured[1]
        assert "version-1" in captured[1], (
            "Second recompute did not include the prior self_image — "
            "ego has no continuity"
        )

        # And the new ego now has version-1 stored as prior_self_image.
        ego = await mgr.get_ego()
        assert ego.self_image.startswith("version-2")
        assert ego.prior_self_image == "version-1"

    @pytest.mark.asyncio
    async def test_voice_fields_appear_in_system_context(self, db: Database) -> None:
        """The ego context block injected into the system prompt must
        carry the voice fields, not just the dashboard ones — otherwise
        the planner can't see them."""
        mgr = EgoManager(db=db, router=self._voice_router())
        await mgr.load_or_create()
        await mgr.record_outcome("x_engagement", success=True)
        await mgr.recompute("identity-summary")
        ctx = await mgr.build_self_perception_context()
        assert "<proud_of>" in ctx
        assert "<embarrassed_by>" in ctx
        assert "<aspiration>" in ctx
        assert "I shipped the pumpfun stream" in ctx

    @pytest.mark.asyncio
    async def test_markdown_renders_first_person_sections(
        self, db: Database, tmp_path: Path
    ) -> None:
        """The .md mirror should use first-person section titles ("Who I
        am", "What I'm proud of") rather than the old dashboard headers."""
        from core.config import IdentityConfig

        ego_md = tmp_path / "ego.md"
        cfg = IdentityConfig(ego_file=str(ego_md))
        mgr = EgoManager(db=db, router=self._voice_router(), config=cfg)
        await mgr.load_or_create()
        await mgr.record_outcome("x_engagement", success=True)
        await mgr.recompute("identity-summary")

        text = ego_md.read_text()
        assert "## Who I am right now" in text
        assert "## What I'm proud of" in text
        assert "## What bothers me" in text
        assert "## What I'm pulled toward" in text
        assert "I shipped the pumpfun stream" in text


class TestFailureSignalPipeline:
    """Tier-1 fix: ego must move on user corrections, verification fails,
    and time-based decay — not just on hardcoded `success=True` outcomes.

    Before this fix, the production code recorded 1,136 outcomes with
    1,136 successes and 0 failures, leaving coherence stuck at 1.00 and
    confidence climbing to 0.95 for every active capability. These tests
    prove the failure-signal channels are wired up.
    """

    def _voice_router(self) -> AsyncMock:
        r = AsyncMock()
        r.complete = AsyncMock(
            return_value=FakeLLMResponse(
                content=json.dumps(
                    {
                        "ideal_self": "I want to be steady.",
                        "ought_self": "I owe users a clean exit.",
                        "self_image": "I notice I keep getting cut off.",
                        "proud_of": "I keep retrying.",
                        "embarrassed_by": "User said no.",
                        "aspiration": "Listen the first time.",
                        "self_critique": "I don't update fast enough.",
                    }
                )
            )
        )
        return r

    @pytest.mark.asyncio
    async def test_correction_detector_fires_on_no(self, db: Database) -> None:
        mgr = EgoManager(db=db, router=AsyncMock(), config=None)
        await mgr.load_or_create()
        await mgr.record_outcome("twitter_post", success=True)
        # Confidence climbed slightly above the default. Confirm before correction.
        ego_before = await mgr.get_ego()
        prior_conf = ego_before.confidence["twitter_post"]
        assert prior_conf > _CONF_DEFAULT

        fired = await mgr.record_correction("no, that's wrong")
        assert fired is True
        ego_after = await mgr.get_ego()
        # Confidence dropped.
        assert ego_after.confidence["twitter_post"] < prior_conf
        # Coherence dropped.
        assert ego_after.coherence_score < 1.0
        # Humbling event was recorded.
        assert len(ego_after.humbling_events) == 1
        assert "user correction" in ego_after.humbling_events[0].actual

    @pytest.mark.asyncio
    async def test_correction_detector_ignores_affirmations(self, db: Database) -> None:
        """`"thanks, no problem"` should NOT trigger a humbling event."""
        mgr = EgoManager(db=db, router=AsyncMock(), config=None)
        await mgr.load_or_create()
        await mgr.record_outcome("twitter_post", success=True)
        for affirm in ["thanks!", "perfect", "yes, exactly", "no problem"]:
            fired = await mgr.record_correction(affirm)
            assert fired is False, f"should not fire on: {affirm!r}"

    @pytest.mark.asyncio
    async def test_repeat_correction_hits_harder(self, db: Database) -> None:
        """`10th time I told you` should hit confidence harder than `no`."""
        mgr = EgoManager(db=db, router=AsyncMock(), config=None)
        await mgr.load_or_create()
        await mgr.record_outcome("scheduler", success=True)
        soft = mgr.detect_correction("no")
        loud = mgr.detect_correction("10th time i told you to stop")
        assert soft is not None
        assert loud is not None
        assert loud[1] > soft[1]

    @pytest.mark.asyncio
    async def test_verification_fail_records_humbling(self, db: Database) -> None:
        mgr = EgoManager(db=db, router=AsyncMock(), config=None)
        await mgr.load_or_create()
        await mgr.record_outcome("file_write", success=True)
        prior = (await mgr.get_ego()).confidence["file_write"]
        fired = await mgr.record_verification(
            agent_response="Did the thing.\n\nVerification: FAIL",
            capability="file_write",
            task_goal="write file",
        )
        assert fired is True
        ego = await mgr.get_ego()
        assert len(ego.humbling_events) == 1
        assert ego.confidence["file_write"] < prior

    @pytest.mark.asyncio
    async def test_verification_unknown_records_failure_no_humbling(
        self, db: Database
    ) -> None:
        mgr = EgoManager(db=db, router=AsyncMock(), config=None)
        await mgr.load_or_create()
        await mgr.record_outcome("web_search", success=True)
        await mgr.record_verification(
            agent_response="Tried.\n\nVerification: UNKNOWN",
            capability="web_search",
        )
        ego = await mgr.get_ego()
        # No humbling event for UNKNOWN — couldn't confirm ≠ confirmed wrong.
        assert len(ego.humbling_events) == 0
        # But the outcome was recorded as failure-class.
        rows = await db.execute(
            "SELECT success, source FROM ego_outcomes WHERE capability='web_search'"
        )
        assert any(r["success"] == 0 and r["source"] == "verification" for r in rows)

    @pytest.mark.asyncio
    async def test_decay_drifts_unused_capabilities_toward_default(
        self, db: Database
    ) -> None:
        """A capability sitting at high confidence with no recent use
        should drift toward 0.50 when decay runs."""
        from datetime import UTC, datetime, timedelta

        mgr = EgoManager(db=db, router=AsyncMock(), config=None)
        ego = await mgr.load_or_create()
        # Pump up confidence on one capability.
        for _ in range(20):
            await mgr.record_outcome("rare_thing", success=True)
        ego = await mgr.get_ego()
        peak = ego.confidence["rare_thing"]
        assert peak > 0.85  # confirmed climbed

        # Backdate the last_used and last_decay so decay actually fires.
        long_ago = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        ego.last_used["rare_thing"] = long_ago
        ego.last_decay_at = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        moved = mgr._apply_decay(ego)
        assert moved >= 1
        # Should have drifted toward 0.50, but not all the way (one month
        # is ~4.3 half-lives at 168h half-life — retains ~5% of the gap).
        assert ego.confidence["rare_thing"] < peak
        assert ego.confidence["rare_thing"] >= _CONF_DEFAULT  # didn't overshoot

    @pytest.mark.asyncio
    async def test_decay_is_rate_limited(self, db: Database) -> None:
        """Calling decay twice in quick succession should be a no-op
        the second time — the recompute interval gates it."""
        from datetime import UTC, datetime, timedelta

        mgr = EgoManager(db=db, router=AsyncMock(), config=None)
        ego = await mgr.load_or_create()
        await mgr.record_outcome("a", success=True)
        ego.last_used["a"] = (datetime.now(UTC) - timedelta(days=14)).isoformat()
        # load_or_create stamps last_decay_at = now, which would gate the
        # first call. Backdate it past the rate-limit window to let the
        # first sweep run, then verify the second is the no-op.
        ego.last_decay_at = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        first = mgr._apply_decay(ego)
        second = mgr._apply_decay(ego)
        assert first >= 1
        assert second == 0  # rate-limited

    @pytest.mark.asyncio
    async def test_correction_attaches_to_last_capability(self, db: Database) -> None:
        """A correction with no explicit capability should attach to the
        most recently used one."""
        mgr = EgoManager(db=db, router=AsyncMock(), config=None)
        await mgr.load_or_create()
        await mgr.record_outcome("twitter_post", success=True)
        await mgr.record_correction("that didn't work")
        ego = await mgr.get_ego()
        assert ego.humbling_events[-1].capability == "twitter_post"

    @pytest.mark.asyncio
    async def test_correction_severity_scales_with_phrase(self, db: Database) -> None:
        """A 'this is the 10th time' message should detect with higher
        severity than a casual 'no'."""
        mgr = EgoManager(db=db, router=AsyncMock(), config=None)
        await mgr.load_or_create()
        sigs = []
        for msg in [
            "no",
            "this is the 10th time i told you",
            "you forgot something",
            "didn't work",
        ]:
            res = mgr.detect_correction(msg)
            assert res is not None
            sigs.append(res[1])
        # 10th-time should be the loudest; "no" should be the quietest.
        assert max(sigs) >= 2.0
        assert min(sigs) <= 1.0
