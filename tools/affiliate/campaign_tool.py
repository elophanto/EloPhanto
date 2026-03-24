"""affiliate_campaign — Create and track affiliate marketing campaigns."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class AffiliateCampaignTool(BaseTool):
    """Create and track affiliate marketing campaigns."""

    def __init__(self) -> None:
        self._db: Any = None

    @property
    def group(self) -> str:
        return "monetization"

    @property
    def name(self) -> str:
        return "affiliate_campaign"

    @property
    def description(self) -> str:
        return (
            "Create and manage affiliate marketing campaigns. Create a "
            "campaign for a product, track pitches and posts across "
            "platforms, and check campaign status."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "status", "list", "update"],
                    "description": "Action to perform.",
                },
                "product_url": {
                    "type": "string",
                    "description": "Product page URL (required for create).",
                },
                "product_title": {
                    "type": "string",
                    "description": "Product title (required for create).",
                },
                "product_data": {
                    "type": "object",
                    "description": "Full product data from affiliate_scrape.",
                },
                "affiliate_link": {
                    "type": "string",
                    "description": "Affiliate tracking URL (required for create).",
                },
                "platforms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Target platforms: twitter, tiktok, youtube.",
                },
                "pitches": {
                    "type": "object",
                    "description": "Generated pitches keyed by platform.",
                },
                "campaign_id": {
                    "type": "string",
                    "description": "Campaign ID (for status/update).",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "paused", "completed"],
                    "description": "New status (for update action).",
                },
            },
            "required": ["action"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._db:
            return ToolResult(success=False, error="Database not initialized.")

        action = params["action"]

        if action == "create":
            return await self._create(params)
        elif action == "status":
            return await self._status(params)
        elif action == "list":
            return await self._list_campaigns()
        elif action == "update":
            return await self._update(params)
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}")

    async def _create(self, params: dict[str, Any]) -> ToolResult:
        product_url = params.get("product_url", "")
        product_title = params.get("product_title", "")
        affiliate_link = params.get("affiliate_link", "")
        platforms = params.get("platforms", ["twitter"])
        product_data = params.get("product_data", {})
        pitches = params.get("pitches", {})

        if not product_url or not affiliate_link:
            return ToolResult(
                success=False,
                error="'product_url' and 'affiliate_link' are required for create.",
            )

        campaign_id = f"aff_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC).isoformat()

        try:
            await self._db.execute_insert(
                "INSERT INTO affiliate_campaigns "
                "(campaign_id, product_url, product_title, product_data_json, "
                "affiliate_link, platforms_json, pitches_json, status, "
                "posts_count, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0, ?, ?)",
                (
                    campaign_id,
                    product_url,
                    product_title,
                    json.dumps(product_data),
                    affiliate_link,
                    json.dumps(platforms),
                    json.dumps(pitches),
                    now,
                    now,
                ),
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to create campaign: {e}")

        return ToolResult(
            success=True,
            data={
                "campaign_id": campaign_id,
                "product_title": product_title,
                "platforms": platforms,
                "affiliate_link": affiliate_link,
                "status": "active",
            },
        )

    async def _status(self, params: dict[str, Any]) -> ToolResult:
        campaign_id = params.get("campaign_id", "")
        if not campaign_id:
            return ToolResult(success=False, error="'campaign_id' required.")

        rows = await self._db.fetch_all(
            "SELECT * FROM affiliate_campaigns WHERE campaign_id = ?",
            (campaign_id,),
        )
        if not rows:
            return ToolResult(success=False, error=f"Campaign not found: {campaign_id}")

        row = rows[0]
        # Count related publishes
        pub_rows = await self._db.fetch_all(
            "SELECT platform, status FROM publishing_log WHERE campaign_id = ?",
            (campaign_id,),
        )

        return ToolResult(
            success=True,
            data={
                "campaign_id": row[0],
                "product_url": row[1],
                "product_title": row[2],
                "affiliate_link": row[4],
                "platforms": json.loads(row[5]) if row[5] else [],
                "pitches": json.loads(row[6]) if row[6] else {},
                "status": row[7],
                "posts_count": row[8],
                "created_at": row[9],
                "publishes": [{"platform": p[0], "status": p[1]} for p in pub_rows],
            },
        )

    async def _list_campaigns(self) -> ToolResult:
        rows = await self._db.fetch_all(
            "SELECT campaign_id, product_title, affiliate_link, status, "
            "posts_count, created_at FROM affiliate_campaigns "
            "ORDER BY created_at DESC LIMIT 20"
        )

        campaigns = [
            {
                "campaign_id": r[0],
                "product_title": r[1],
                "affiliate_link": r[2],
                "status": r[3],
                "posts_count": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

        return ToolResult(
            success=True,
            data={"campaigns": campaigns, "total": len(campaigns)},
        )

    async def _update(self, params: dict[str, Any]) -> ToolResult:
        campaign_id = params.get("campaign_id", "")
        new_status = params.get("status", "")

        if not campaign_id or not new_status:
            return ToolResult(
                success=False, error="'campaign_id' and 'status' required for update."
            )

        now = datetime.now(UTC).isoformat()
        try:
            await self._db.execute_insert(
                "UPDATE affiliate_campaigns SET status = ?, updated_at = ? "
                "WHERE campaign_id = ?",
                (new_status, now, campaign_id),
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Update failed: {e}")

        return ToolResult(
            success=True,
            data={
                "campaign_id": campaign_id,
                "status": new_status,
                "updated_at": now,
            },
        )
