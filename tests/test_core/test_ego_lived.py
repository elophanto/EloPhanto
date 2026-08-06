"""Ego lived-self upgrades — felt_state, caution rules, soft success, gating."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.config import IdentityConfig
from core.database import Database
from core.ego import EgoManager, capability_for_tool


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
                    "self_image": "I am more careful on outreach now.",
                    "ideal_self": "Fluent outreach without corrections.",
                    "ought_self": "I owe the operator clean sends.",
                    "proud_of": "Steady coding.",
                    "embarrassed_by": "Outreach corrections.",
                    "aspiration": "Earn back trust on outreach.",
                    "self_critique": "I claimed fluency I had not earned.",
                }
            )
        )
    )
    return r


class TestFeltStateAndCaution:
    @pytest.mark.asyncio
    async def test_humbling_creates_caution_rule(
        self, db: Database, router: AsyncMock
    ) -> None:
        mgr = EgoManager(db=db, router=router)
        await mgr.load_or_create()
        await mgr.record_humbling(
            capability="outreach",
            claimed="fluent outreach",
            actual="user correction: stop",
            source="correction",
        )
        ego = await mgr.get_ego()
        assert any(r["capability"] == "outreach" for r in ego.caution_rules)
        assert ego.felt_state in ("shame", "questioning")

    @pytest.mark.asyncio
    async def test_caution_survives_confidence_climb(
        self, db: Database, router: AsyncMock
    ) -> None:
        mgr = EgoManager(db=db, router=router)
        await mgr.load_or_create()
        await mgr.record_humbling(
            capability="outreach",
            claimed="ok",
            actual="fail",
            source="correction",
        )
        for _ in range(20):
            await mgr.record_outcome("outreach", success=True)
        ego = await mgr.get_ego()
        assert any(r["capability"] == "outreach" for r in ego.caution_rules)
        # should_attempt forces ask even with high confidence
        verdict = await mgr.should_attempt("outreach", difficulty=0.3)
        assert verdict in ("ask", "decline")

    @pytest.mark.asyncio
    async def test_verification_pass_retires_caution(
        self, db: Database, router: AsyncMock
    ) -> None:
        mgr = EgoManager(db=db, router=router)
        await mgr.load_or_create()
        await mgr.record_humbling(
            capability="outreach",
            claimed="ok",
            actual="fail",
            source="correction",
        )
        ok = await mgr.record_verification(
            "Verification: PASS\nlooks good",
            capability="outreach",
        )
        assert ok is True
        ego = await mgr.get_ego()
        assert not any(r["capability"] == "outreach" for r in ego.caution_rules)

    @pytest.mark.asyncio
    async def test_unknown_is_soft_success(
        self, db: Database, router: AsyncMock
    ) -> None:
        mgr = EgoManager(db=db, router=router)
        await mgr.load_or_create()
        await mgr.record_outcome("coding", success=True)  # baseline
        before = (await mgr.get_ego()).confidence["coding"]
        await mgr.record_verification(
            "Verification: UNKNOWN",
            capability="coding",
        )
        after = (await mgr.get_ego()).confidence["coding"]
        # Soft success should not tank confidence the way FAIL would.
        assert after >= before - 0.05

    @pytest.mark.asyncio
    async def test_felt_state_pride_requires_evidence(
        self, db: Database, router: AsyncMock
    ) -> None:
        mgr = EgoManager(db=db, router=router)
        await mgr.load_or_create()
        for _ in range(10):
            await mgr.record_outcome("coding", success=True)
        ego = await mgr.get_ego()
        assert ego.felt_state == "pride"

    @pytest.mark.asyncio
    async def test_coherence_no_blind_recovery(
        self, db: Database, router: AsyncMock, tmp_path: Path
    ) -> None:
        cfg = IdentityConfig(ego_file=str(tmp_path / "ego.md"))
        mgr = EgoManager(db=db, router=router, config=cfg)
        await mgr.load_or_create()
        await mgr.record_humbling(
            capability="outreach",
            claimed="ok",
            actual="fail",
            source="correction",
        )
        # Force low recent success
        for _ in range(8):
            await mgr.record_outcome("outreach", success=False)
        before = (await mgr.get_ego()).coherence_score
        await mgr.recompute("purpose: test")
        after = (await mgr.get_ego()).coherence_score
        # Blind +0.20 must not apply when recent rate is poor.
        assert after <= before + 0.01

    @pytest.mark.asyncio
    async def test_epoch_is_causal(
        self, db: Database, router: AsyncMock, tmp_path: Path
    ) -> None:
        cfg = IdentityConfig(ego_file=str(tmp_path / "ego.md"))
        mgr = EgoManager(db=db, router=router, config=cfg)
        await mgr.load_or_create()
        await mgr.record_humbling(
            capability="outreach",
            claimed="fluent",
            actual="correction",
            source="correction",
        )
        await mgr.recompute("purpose: test")
        ego = await mgr.get_ego()
        assert ego.self_epochs
        assert "outreach" in ego.self_epochs[-1]["cause"]

    def test_capability_domains_stable(self) -> None:
        assert capability_for_tool("twitter_post") == "social"
        assert capability_for_tool("email_send") == "outreach"
        assert capability_for_tool("crypto_transfer") == "payments"
        assert capability_for_tool("unknown_tool_xyz") == "ops"


class TestEgoQualifierFelt:
    def test_felt_state_maps_footer(self) -> None:
        from cli.dashboard.app import _ego_qualifier

        assert _ego_qualifier({"felt_state": "shame"}) == "shame"
        assert _ego_qualifier({"felt_state": "pride"}) == "settled"
        assert _ego_qualifier({"felt_state": "composure"}) == "steady"
        assert _ego_qualifier({"felt_state": "questioning"}) == "questioning"
