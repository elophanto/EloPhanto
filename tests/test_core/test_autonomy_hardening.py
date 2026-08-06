"""Autonomy hardening — kill, receipt, CRITICAL, approval pause, budget, trust."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.approval_wait import ApprovalTimeoutPause, wait_for_operator_approval
from core.checkpoint_receipt import verify_checkpoint_receipt
from core.config import GoalsConfig
from core.database import Database
from core.goal_manager import Goal, GoalManager
from core.trust_gate import (
    confirm_trust_promotion,
    propose_trust_promotion,
)
from tools.base import PermissionLevel


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def gm(db: Database) -> GoalManager:
    return GoalManager(db=db, router=AsyncMock(), config=GoalsConfig())


class TestApprovalPause:
    @pytest.mark.asyncio
    async def test_timeout_raises_pause_not_deny(self) -> None:
        future_holder: dict[str, object] = {}

        class FakeGW:
            def __init__(self) -> None:
                self._pending_approvals: dict = {}

            async def broadcast(self, msg, session_id=None) -> None:
                future_holder["id"] = msg.id

        gw = FakeGW()

        with pytest.raises(ApprovalTimeoutPause) as ei:
            await wait_for_operator_approval(
                gw,
                tool_name="shell_execute",
                description="run rm",
                params={"command": "rm"},
                first_timeout_s=0.01,
                second_timeout_s=0.01,
            )
        assert ei.value.tool_name == "shell_execute"


class TestKillCriterion:
    @pytest.mark.asyncio
    async def test_kill_fires_on_low_count_after_window(self, gm: GoalManager) -> None:
        created = datetime.now(UTC) - timedelta(days=15)
        goal = Goal(
            goal_id="killtest01ab",
            session_id=None,
            goal="Get pre-orders",
            status="active",
            kill_criterion="<5 pre-orders in 14 days",
            created_at=created.isoformat(),
            context_summary="pre-orders: 3",
        )
        await gm._persist_goal(goal)
        triggered, reason = await gm.evaluate_kill_criterion(
            goal,
            evidence_text="pre-orders: 3",
            now=datetime.now(UTC),
        )
        assert triggered is True
        assert "observed=3" in reason

    @pytest.mark.asyncio
    async def test_kill_not_before_window(self, gm: GoalManager) -> None:
        created = datetime.now(UTC) - timedelta(days=2)
        goal = Goal(
            goal_id="killtest02cd",
            session_id=None,
            goal="Get pre-orders",
            status="active",
            kill_criterion="<5 pre-orders in 14 days",
            created_at=created.isoformat(),
            context_summary="pre-orders: 1",
        )
        triggered, _ = await gm.evaluate_kill_criterion(
            goal, evidence_text="pre-orders: 1", now=datetime.now(UTC)
        )
        assert triggered is False

    @pytest.mark.asyncio
    async def test_undo_kill_within_grace(self, gm: GoalManager) -> None:
        goal = await gm.create_goal("undo me")
        await gm._update_status(goal.goal_id, "active")
        await gm.cancel_goal(goal.goal_id, kill_reason="test kill")
        ok = await gm.undo_kill(goal.goal_id, grace_minutes=15.0)
        assert ok is True
        refreshed = await gm.get_goal(goal.goal_id)
        assert refreshed is not None
        assert refreshed.status == "active"


class TestReceiptGate:
    def test_empty_trail_fails(self) -> None:
        v = verify_checkpoint_receipt(
            "5 pre-orders confirmed",
            tool_trace=[],
            assistant_summary="Done, we have 5 pre-orders",
        )
        assert v.ok is False

    def test_grounded_trail_passes(self) -> None:
        v = verify_checkpoint_receipt(
            "5 pre-orders confirmed",
            tool_trace=[
                {
                    "tool": "db_query",
                    "status": "ok",
                    "summary": "counted pre-orders",
                    "data": {"pre-orders": 5},
                }
            ],
        )
        assert v.ok is True


class TestCriticalAlwaysAsk:
    @pytest.mark.asyncio
    async def test_full_auto_still_asks_critical(self) -> None:
        from core.config import Config
        from core.executor import Executor

        asked: list[str] = []

        async def _cb(name: str, desc: str, params: dict) -> bool:
            asked.append(name)
            return False

        cfg = Config(permission_mode="full_auto")
        ex = Executor(config=cfg, registry=MagicMock())
        ex.set_approval_callback(_cb)

        tool = MagicMock()
        tool.name = "crypto_transfer"
        tool.permission_level = PermissionLevel.CRITICAL

        ok = await ex._check_permission(tool, {"amount": 1})
        assert ok is False
        assert asked == ["crypto_transfer"]


class TestBudgetPaused:
    @pytest.mark.asyncio
    async def test_resume_requires_raised_limit(self, gm: GoalManager) -> None:
        goal = await gm.create_goal("budget me")
        await gm._update_status(goal.goal_id, "active")
        await gm.pause_goal(
            goal.goal_id,
            status="budget_paused",
            reason=("limit_cost=5.0 limit_time=7200.0 limit_llm=200 | Cost limit"),
        )
        # Same limits → refuse
        assert (
            await gm.resume_goal(
                goal.goal_id,
                cost_budget_usd=5.0,
                max_time_seconds=7200.0,
                max_llm_calls=200,
            )
            is False
        )
        # Raised cost → allow
        assert (
            await gm.resume_goal(
                goal.goal_id,
                cost_budget_usd=10.0,
                max_time_seconds=7200.0,
                max_llm_calls=200,
            )
            is True
        )


class TestTrustPropose:
    def test_propose_and_confirm(self, tmp_path: Path) -> None:
        slug = "acme-inc"
        approved = tmp_path / "companies" / slug / "drafts" / "email" / "approved"
        approved.mkdir(parents=True)
        for i in range(3):
            (approved / f"draft-{i}.md").write_text("# hi\n", encoding="utf-8")

        ok, evidence, path = propose_trust_promotion(
            tmp_path, slug, current_state="learning"
        )
        assert ok is True
        assert evidence.proposed_state == "trial"
        assert path is not None and path.is_file()

        cok, state, _msg = confirm_trust_promotion(tmp_path, slug)
        assert cok is True
        assert state == "trial"

    def test_not_ready_without_drafts(self, tmp_path: Path) -> None:
        ok, evidence, _ = propose_trust_promotion(
            tmp_path, "empty-co", current_state="learning"
        )
        assert ok is False
        assert evidence.ready is False
