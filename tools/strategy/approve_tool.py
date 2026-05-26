"""company_plan_approve — finalize after operator review (Phase 11).

`company_plan_apply` materializes the strategy but starts the mission
in ``active`` status (default) — that's enough for autonomous
execution. But the operator may want a checkpoint to review the
blockers AND voice_proposed AND the created goal set BEFORE the
autonomous mind starts picking up tactics.

This tool is the explicit "go ahead" gate. It:
- Verifies an active strategy exists.
- Reports the unresolved-blocker count (warning, not refusal).
- Touches the mission's `last_touched_at` to push it up the arbiter
  ranking — Phase 11's strategy execution should jump to the front
  when the operator approves.
- Returns the next-step pointer (resolve remaining blockers /
  approve the voice / let the autonomous mind run).
"""

from __future__ import annotations

import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class CompanyPlanApproveTool(BaseTool):
    def __init__(self) -> None:
        self._strategy_manager: Any = None
        self._mission_manager: Any = None
        self._db: Any = None

    @property
    def name(self) -> str:
        return "company_plan_approve"

    @property
    def group(self) -> str:
        return "companies"

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    @property
    def description(self) -> str:
        return (
            "Operator finalize after company_plan_apply. Touches the "
            "strategy mission so arbiter ranks it high next wakeup. "
            "Reports unresolved blocker count. MODERATE."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "note": {
                    "type": "string",
                    "description": "Optional approval note.",
                },
            },
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._strategy_manager is None:
            return ToolResult(
                success=False,
                error="company_plan_approve not initialized (strategy_manager)",
            )
        from core.company import current_company_id

        company_id = str(params.get("company_id") or current_company_id())

        if not self._strategy_manager.has_active(company_id):
            return ToolResult(
                success=False,
                error=(
                    f"No active strategy for {company_id}. Run "
                    "company_plan then company_plan_apply first."
                ),
            )
        strategy = self._strategy_manager.reload(company_id)
        if strategy is None:
            return ToolResult(
                success=False,
                error=(
                    f"strategy/active/strategy.yaml exists but failed to "
                    f"parse for {company_id}."
                ),
            )

        unresolved = self._strategy_manager.blocker_count(company_id)

        # Optionally bump the strategy mission's last_touched_at so it
        # ranks high on the next arbiter wakeup. Best-effort; missing
        # mission manager is non-fatal.
        bumped_mission = False
        if self._mission_manager is not None and self._db is not None:
            try:
                from datetime import UTC, datetime

                now = datetime.now(UTC).isoformat()
                await self._db.execute(
                    "UPDATE missions SET last_touched_at = ?, "
                    "updated_at = ? WHERE title LIKE ?",
                    (now, now, f"{company_id} — %"),
                )
                bumped_mission = True
            except Exception as e:
                logger.warning("approve: mission bump failed: %s", e)

        return ToolResult(
            success=True,
            data={
                "company_id": company_id,
                "strategy_name": strategy.strategy_name,
                "unresolved_blockers": unresolved,
                "mission_touched": bumped_mission,
                "note": params.get("note") or "",
                "next": (
                    "Autonomous mind will pick up the strategy's "
                    "goals on the next wakeup."
                    + (
                        f" {unresolved} blocker(s) remain — review at "
                        f"`elophanto company blockers {company_id}`. "
                        "Build-able blockers may surface as "
                        "`from_buildable_blockers` arbiter candidates."
                        if unresolved
                        else " All blockers resolved."
                    )
                ),
            },
        )
