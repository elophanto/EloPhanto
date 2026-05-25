"""Prospect evaluate tool — score and decide on prospects."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class ProspectEvaluateTool(BaseTool):
    """Evaluate a prospect against agent capabilities and update match score."""

    @property
    def group(self) -> str:
        return "prospecting"

    def __init__(self) -> None:
        self._db: Any = None

    @property
    def name(self) -> str:
        return "prospect_evaluate"

    @property
    def description(self) -> str:
        return (
            "Evaluate a prospect against agent capabilities. Set match score, "
            "reasoning, priority, and decide whether to pursue, skip, or defer."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prospect_id": {
                    "type": "string",
                    "description": "ID of the prospect to evaluate.",
                },
                "match_score": {
                    "type": "number",
                    "description": "Capability match score (0.0 to 1.0).",
                },
                "match_reasoning": {
                    "type": "string",
                    "description": "Why this prospect matches or doesn't match agent capabilities.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Priority level.",
                },
                "decision": {
                    "type": "string",
                    "enum": ["pursue", "skip", "defer"],
                    "description": "Decision: pursue (outreach), skip (reject), defer (revisit later).",
                },
            },
            "required": ["prospect_id", "match_score", "match_reasoning", "decision"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._db:
            return ToolResult(success=False, error="Database not initialized")

        prospect_id = params["prospect_id"]
        now = datetime.now(UTC).isoformat()

        # Verify prospect exists. ABE Phase 3: also pull company_id so
        # the pipeline_advance ledger event below can attribute to
        # the prospect's own company without a second SELECT.
        rows = await self._db.fetch_all(
            "SELECT prospect_id, title, company_id FROM prospects "
            "WHERE prospect_id = ?",
            (prospect_id,),
        )
        if not rows:
            return ToolResult(success=False, error=f"Prospect {prospect_id} not found")
        prospect_company_id = (
            rows[0][2] if len(rows[0]) > 2 else None
        ) or "elophanto-self"

        decision = params["decision"]
        new_status = (
            "evaluated"
            if decision == "pursue"
            else ("rejected" if decision == "skip" else "new")
        )

        await self._db.execute(
            "UPDATE prospects SET match_score = ?, match_reasoning = ?, "
            "priority = ?, status = ?, evaluated_at = ?, last_activity_at = ? "
            "WHERE prospect_id = ?",
            (
                params["match_score"],
                params["match_reasoning"],
                params.get("priority", "medium"),
                new_status,
                now,
                now,
                prospect_id,
            ),
        )

        # ABE Phase 3 — pipeline advance ledger mirror. Only the
        # 'pursue' decision (status='evaluated') counts as a positive
        # transition. 'skip' (rejected) and 'hold' (new) do not.
        # Attribute to the prospect's own company (the funnel that
        # advanced) — not the operator's currently-active company.
        # Failures swallowed: prospects.status is the source of truth,
        # ledger is a denormalized read model.
        if new_status == "evaluated":
            try:
                from core.ledger import LedgerEntry, ResourceLedger

                ledger = ResourceLedger(self._db)
                await ledger.write(
                    LedgerEntry(
                        company_id=prospect_company_id,
                        direction="in",
                        type="pipeline_advance",
                        amount=1.0,
                        unit="count",
                        source_table="prospects",
                        source_id=None,  # prospect_id is TEXT, not int
                        note=f"{prospect_id} → evaluated",
                    )
                )
            except Exception:
                pass

        return ToolResult(
            success=True,
            data={
                "prospect_id": prospect_id,
                "title": rows[0][1],
                "match_score": params["match_score"],
                "decision": decision,
                "status": new_status,
            },
        )
