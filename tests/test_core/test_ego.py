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
