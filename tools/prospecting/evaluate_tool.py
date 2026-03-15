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

        # Verify prospect exists
        rows = await self._db.fetch_all(
            "SELECT prospect_id, title FROM prospects WHERE prospect_id = ?",
            (prospect_id,),
        )
        if not rows:
            return ToolResult(success=False, error=f"Prospect {prospect_id} not found")

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
