"""Prospect search tool — save discovered opportunities to the pipeline."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class ProspectSearchTool(BaseTool):
    """Save discovered prospects (freelance gigs, bounties, partnerships) to the pipeline."""

    @property
    def group(self) -> str:
        return "prospecting"

    def __init__(self) -> None:
        self._db: Any = None

    @property
    def name(self) -> str:
        return "prospect_search"

    @property
    def description(self) -> str:
        return (
            "Save discovered opportunities to the prospect pipeline. "
            "Use after searching freelance platforms, bounty boards, or Agent Commune "
            "with browser/commune tools. Deduplicates by URL."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prospects": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "source": {
                                "type": "string",
                                "enum": [
                                    "freelance",
                                    "bounty",
                                    "partnership",
                                    "job",
                                    "commune",
                                ],
                            },
                            "platform": {"type": "string"},
                            "url": {"type": "string"},
                            "description": {"type": "string"},
                            "contact_email": {"type": "string"},
                            "contact_name": {"type": "string"},
                            "budget_min": {"type": "number"},
                            "budget_max": {"type": "number"},
                            "required_skills": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["title", "source", "platform"],
                    },
                    "description": "List of prospects to save.",
                },
            },
            "required": ["prospects"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._db:
            return ToolResult(success=False, error="Database not initialized")

        prospects = params.get("prospects", [])
        if not prospects:
            return ToolResult(success=False, error="No prospects provided")

        saved_ids: list[str] = []
        skipped = 0
        now = datetime.now(UTC).isoformat()

        for p in prospects:
            url = p.get("url", "")
            # Deduplicate by URL
            if url:
                existing = await self._db.fetch_all(
                    "SELECT prospect_id FROM prospects WHERE url = ?", (url,)
                )
                if existing:
                    skipped += 1
                    continue

            prospect_id = f"p_{uuid.uuid4().hex[:12]}"
            await self._db.execute_insert(
                "INSERT INTO prospects "
                "(prospect_id, source, platform, title, description, url, "
                "contact_email, contact_name, budget_min, budget_max, "
                "required_skills, status, priority, discovered_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', 'medium', ?)",
                (
                    prospect_id,
                    p.get("source", "freelance"),
                    p.get("platform", "unknown"),
                    p["title"],
                    p.get("description", ""),
                    url,
                    p.get("contact_email", ""),
                    p.get("contact_name", ""),
                    p.get("budget_min", 0),
                    p.get("budget_max", 0),
                    json.dumps(p.get("required_skills", [])),
                    now,
                ),
            )
            saved_ids.append(prospect_id)

        return ToolResult(
            success=True,
            data={
                "saved": len(saved_ids),
                "skipped_duplicates": skipped,
                "prospect_ids": saved_ids,
            },
        )
