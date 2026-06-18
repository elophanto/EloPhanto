"""Founder-doctrine Stage 0 tests — goal/checkpoint `stage`, goal-level
`kill_criterion`, the validate-first decompose gate, and the lenient
object/array JSON parsing.

See tmp/founder-vs-elophanto-audit-2026-06-18.md Phase 6 (§6.10/§6.11).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.config import GoalsConfig
from core.database import Database
from core.goal_manager import (
    GOAL_STAGES,
    Checkpoint,
    GoalManager,
    _loads_json_lenient,
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
def gm(db: Database) -> GoalManager:
    return GoalManager(db=db, router=AsyncMock(), config=GoalsConfig())


# A Stage-0 decompose response: object shape, validate-first, kill_criterion.
_OBJECT_PLAN = json.dumps(
    {
        "kill_criterion": "If <5 paid pre-orders in 14 days, abandon.",
        "checkpoints": [
            {
                "order": 1,
                "title": "Pre-sell to 50 targets",
                "description": "Cold outreach asking for a $49 pre-order.",
                "success_criteria": ">=5 paid pre-orders",
                "stage": "validate",
            },
            {
                "order": 2,
                "title": "Build the MVP",
                "description": "Smallest deliverable that fulfils the pre-orders.",
                "success_criteria": "A stranger can pay and receive it",
                "stage": "build",
            },
        ],
    }
)

# Legacy / revise shape: a bare array, no stage, no kill_criterion.
_LEGACY_ARRAY = json.dumps(
    [
        {
            "order": 1,
            "title": "Research",
            "description": "Look things up",
            "success_criteria": "Notes written",
        }
    ]
)


class TestGoalStageAndKill:
    @pytest.mark.asyncio
    async def test_create_goal_persists_stage_and_kill(self, gm: GoalManager) -> None:
        g = await gm.create_goal(
            "Launch X", stage="validate", kill_criterion="kill if no signal in 14d"
        )
        reloaded = await gm.get_goal(g.goal_id)
        assert reloaded is not None
        assert reloaded.stage == "validate"
        assert reloaded.kill_criterion == "kill if no signal in 14d"

    @pytest.mark.asyncio
    async def test_create_goal_defaults(self, gm: GoalManager) -> None:
        g = await gm.create_goal("Plain goal")
        reloaded = await gm.get_goal(g.goal_id)
        assert reloaded is not None
        assert reloaded.stage == "unknown"
        assert reloaded.kill_criterion is None

    @pytest.mark.asyncio
    async def test_decompose_object_shape_sets_stage_and_kill(
        self, gm: GoalManager
    ) -> None:
        gm._router.complete.return_value = FakeLLMResponse(content=_OBJECT_PLAN)
        goal = await gm.create_goal("Launch a paid PDF guide")
        cps = await gm.decompose(goal)
        assert len(cps) == 2
        # goal.stage tracks checkpoint 1 (where the goal currently sits).
        assert goal.stage == "validate"
        assert goal.kill_criterion == "If <5 paid pre-orders in 14 days, abandon."
        # First checkpoint is the validate gate, not research/build.
        assert cps[0].stage == "validate"
        assert cps[1].stage == "build"
        # Round-trips through the DB.
        reloaded = await gm.get_goal(goal.goal_id)
        assert reloaded.stage == "validate"
        assert reloaded.kill_criterion.startswith("If <5")

    @pytest.mark.asyncio
    async def test_checkpoint_stage_round_trips(self, gm: GoalManager) -> None:
        gm._router.complete.return_value = FakeLLMResponse(content=_OBJECT_PLAN)
        goal = await gm.create_goal("Launch")
        await gm.decompose(goal)
        stored = await gm.get_checkpoints(goal.goal_id)
        assert [c.stage for c in stored] == ["validate", "build"]

    @pytest.mark.asyncio
    async def test_decompose_legacy_array_still_parses(self, gm: GoalManager) -> None:
        gm._router.complete.return_value = FakeLLMResponse(content=_LEGACY_ARRAY)
        goal = await gm.create_goal("Legacy")
        cps = await gm.decompose(goal)
        assert len(cps) == 1
        assert cps[0].stage == "unknown"
        # No kill_criterion in a bare array → goal keeps None.
        reloaded = await gm.get_goal(goal.goal_id)
        assert reloaded.kill_criterion is None

    @pytest.mark.asyncio
    async def test_decompose_does_not_overwrite_caller_kill(
        self, gm: GoalManager
    ) -> None:
        gm._router.complete.return_value = FakeLLMResponse(content=_OBJECT_PLAN)
        # Caller already set a kill criterion — decompose must not clobber it.
        goal = await gm.create_goal("Launch", kill_criterion="operator-set threshold")
        await gm.decompose(goal)
        assert goal.kill_criterion == "operator-set threshold"


class TestLenientJsonAndKill:
    def test_extract_kill_criterion_object(self) -> None:
        assert (
            GoalManager._extract_kill_criterion(_OBJECT_PLAN)
            == "If <5 paid pre-orders in 14 days, abandon."
        )

    def test_extract_kill_criterion_array_is_none(self) -> None:
        assert GoalManager._extract_kill_criterion(_LEGACY_ARRAY) is None

    def test_extract_kill_criterion_garbage_is_none(self) -> None:
        assert GoalManager._extract_kill_criterion("not json") is None

    def test_loads_lenient_fenced(self) -> None:
        fenced = f"```json\n{_OBJECT_PLAN}\n```"
        data = _loads_json_lenient(fenced)
        assert isinstance(data, dict)
        assert data["checkpoints"][0]["stage"] == "validate"

    def test_loads_lenient_prose_wrapped(self) -> None:
        prose = f"Here is the plan:\n{_OBJECT_PLAN}\nLet me know!"
        data = _loads_json_lenient(prose)
        assert isinstance(data, dict)
        assert "checkpoints" in data

    def test_loads_lenient_garbage_is_none(self) -> None:
        assert _loads_json_lenient("totally not json") is None

    def test_bad_stage_falls_back_unknown(self) -> None:
        gm = GoalManager.__new__(GoalManager)
        bad = json.dumps([{"title": "x", "stage": "frobnicate"}])
        cps = gm._parse_checkpoint_json(bad, "g")
        assert cps[0].stage == "unknown"

    def test_all_valid_stages_accepted(self) -> None:
        gm = GoalManager.__new__(GoalManager)
        items = [{"title": s, "stage": s} for s in GOAL_STAGES]
        cps = gm._parse_checkpoint_json(json.dumps(items), "g")
        assert [c.stage for c in cps] == list(GOAL_STAGES)


class TestDecomposePromptContent:
    def test_validate_first_gate_present(self) -> None:
        from core.goal_manager import _DECOMPOSE_SYSTEM

        assert "VALIDATE-FIRST GATE" in _DECOMPOSE_SYSTEM
        assert "kill_criterion" in _DECOMPOSE_SYSTEM
        # The old "research first" default must be gone.
        assert "First checkpoint should always be research" not in _DECOMPOSE_SYSTEM
        for stage in ("scan", "validate", "build", "launch", "acquire"):
            assert stage in _DECOMPOSE_SYSTEM

    def test_checkpoint_dataclass_defaults_unknown(self) -> None:
        cp = Checkpoint(goal_id="g", order=1, title="t", description="d")
        assert cp.stage == "unknown"
