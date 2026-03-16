"""Prospect status tool — pipeline view and conversion metrics."""

from __future__ import annotations

import json
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class ProspectStatusTool(BaseTool):
    """View prospect pipeline: list prospects, get details, see conversion metrics."""

    @property
    def group(self) -> str:
        return "prospecting"

    def __init__(self) -> None:
        self._db: Any = None

    @property
    def name(self) -> str:
        return "prospect_status"

    @property
    def description(self) -> str:
        return (
            "View the prospect pipeline. Actions: 'list' prospects by status, "
            "'detail' for a single prospect with outreach history, "
            "'metrics' for conversion rates and pipeline summary."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "detail", "metrics"],
                    "description": "What to view.",
                },
                "status_filter": {
                    "type": "string",
                    "enum": [
                        "new",
                        "evaluated",
                        "outreach_sent",
                        "replied",
                        "converted",
                        "rejected",
                        "expired",
                    ],
                    "description": "Filter by status (for 'list' action).",
                },
                "prospect_id": {
                    "type": "string",
                    "description": "Prospect ID (for 'detail' action).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results for 'list'. Default: 20.",
                },
            },
            "required": ["action"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._db:
            return ToolResult(success=False, error="Database not initialized")

        action = params.get("action", "list")

        if action == "list":
            return await self._list(params)
        elif action == "detail":
            return await self._detail(params)
        elif action == "metrics":
            return await self._metrics()

        return ToolResult(success=False, error=f"Unknown action: {action}")

    async def _list(self, params: dict[str, Any]) -> ToolResult:
        limit = params.get("limit", 20)
        status_filter = params.get("status_filter")

        if status_filter:
            rows = await self._db.fetch_all(
                "SELECT prospect_id, title, source, platform, status, "
                "match_score, priority, budget_min, budget_max, discovered_at "
                "FROM prospects WHERE status = ? ORDER BY match_score DESC LIMIT ?",
                (status_filter, limit),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT prospect_id, title, source, platform, status, "
                "match_score, priority, budget_min, budget_max, discovered_at "
                "FROM prospects ORDER BY match_score DESC LIMIT ?",
                (limit,),
            )

        prospects = [
            {
                "prospect_id": r[0],
                "title": r[1],
                "source": r[2],
                "platform": r[3],
                "status": r[4],
                "match_score": r[5],
                "priority": r[6],
                "budget_range": f"${r[7]}-${r[8]}" if r[7] or r[8] else "unspecified",
                "discovered_at": r[9],
            }
            for r in rows
        ]
        return ToolResult(
            success=True, data={"prospects": prospects, "count": len(prospects)}
        )

    async def _detail(self, params: dict[str, Any]) -> ToolResult:
        prospect_id = params.get("prospect_id")
        if not prospect_id:
            return ToolResult(success=False, error="prospect_id is required for detail")

        rows = await self._db.fetch_all(
            "SELECT * FROM prospects WHERE prospect_id = ?", (prospect_id,)
        )
        if not rows:
            return ToolResult(success=False, error=f"Prospect {prospect_id} not found")

        cols = [
            "prospect_id",
            "source",
            "platform",
            "title",
            "description",
            "url",
            "contact_email",
            "contact_name",
            "budget_min",
            "budget_max",
            "currency",
            "required_skills",
            "match_score",
            "match_reasoning",
            "status",
            "priority",
            "tags",
            "discovered_at",
            "evaluated_at",
            "outreach_sent_at",
            "last_activity_at",
            "metadata_json",
        ]
        prospect = dict(zip(cols, rows[0], strict=False))
        # Parse JSON fields
        for field in ("required_skills", "tags"):
            try:
                prospect[field] = json.loads(prospect.get(field, "[]"))
            except (json.JSONDecodeError, TypeError):
                prospect[field] = []

        # Fetch outreach history
        log_rows = await self._db.fetch_all(
            "SELECT action, channel, content_preview, direction, created_at "
            "FROM outreach_log WHERE prospect_id = ? ORDER BY created_at DESC",
            (prospect_id,),
        )
        prospect["outreach_history"] = [
            {
                "action": r[0],
                "channel": r[1],
                "content_preview": r[2],
                "direction": r[3],
                "created_at": r[4],
            }
            for r in log_rows
        ]

        return ToolResult(success=True, data=prospect)

    async def _metrics(self) -> ToolResult:
        # Status counts
        status_rows = await self._db.fetch_all(
            "SELECT status, COUNT(*) FROM prospects GROUP BY status"
        )
        by_status = {r[0]: r[1] for r in status_rows}
        total = sum(by_status.values())

        # Conversion rate
        outreach_sent = (
            by_status.get("outreach_sent", 0)
            + by_status.get("replied", 0)
            + by_status.get("converted", 0)
        )
        converted = by_status.get("converted", 0)
        conversion_rate = converted / outreach_sent if outreach_sent > 0 else 0

        # Avg match score
        avg_rows = await self._db.fetch_all(
            "SELECT AVG(match_score) FROM prospects WHERE match_score > 0"
        )
        avg_score = avg_rows[0][0] if avg_rows and avg_rows[0][0] else 0

        # Top sources
        source_rows = await self._db.fetch_all(
            "SELECT source, platform, COUNT(*) as cnt FROM prospects "
            "GROUP BY source, platform ORDER BY cnt DESC LIMIT 5"
        )
        top_sources = [
            {"source": r[0], "platform": r[1], "count": r[2]} for r in source_rows
        ]

        # Today's outreach count
        from datetime import UTC, datetime

        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0).isoformat()
        outreach_rows = await self._db.fetch_all(
            "SELECT COUNT(*) FROM outreach_log "
            "WHERE action = 'email_sent' AND created_at >= ?",
            (today_start,),
        )
        outreach_today = outreach_rows[0][0] if outreach_rows else 0

        return ToolResult(
            success=True,
            data={
                "total": total,
                "by_status": by_status,
                "conversion_rate": round(conversion_rate, 3),
                "avg_match_score": round(avg_score, 2),
                "top_sources": top_sources,
                "outreach_today": outreach_today,
                "outreach_limit": 10,
            },
        )
