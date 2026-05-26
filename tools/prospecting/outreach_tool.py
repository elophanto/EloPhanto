"""Prospect outreach tool — log outreach activity for prospects."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class ProspectOutreachTool(BaseTool):
    """Record outreach activity for a prospect (email sent, reply received, etc.)."""

    @property
    def group(self) -> str:
        return "prospecting"

    def __init__(self) -> None:
        self._db: Any = None

    @property
    def name(self) -> str:
        return "prospect_outreach"

    @property
    def description(self) -> str:
        return (
            "Record outreach activity for a prospect: email sent, reply received, "
            "follow-up, platform application, status change, or note. "
            "Actual email sending is done via email_send — this tool tracks metadata."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prospect_id": {
                    "type": "string",
                    "description": "ID of the prospect.",
                },
                "action": {
                    "type": "string",
                    "enum": [
                        "email_sent",
                        "reply_received",
                        "follow_up",
                        "platform_applied",
                        "status_change",
                        "note",
                    ],
                    "description": "Type of outreach activity.",
                },
                "channel": {
                    "type": "string",
                    "description": "Channel used (email, commune, browser). Default: email.",
                },
                "message_id": {
                    "type": "string",
                    "description": "Email message ID for cross-referencing.",
                },
                "content_preview": {
                    "type": "string",
                    "description": "First ~200 chars of the outreach message.",
                },
                "new_status": {
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
                    "description": "Update prospect status (optional).",
                },
            },
            "required": ["prospect_id", "action"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._db:
            return ToolResult(success=False, error="Database not initialized")

        prospect_id = params["prospect_id"]
        action = params["action"]
        now = datetime.now(UTC).isoformat()

        # Verify prospect exists. ABE Phase 3: read its company_id at
        # the same time so the pipeline_advance ledger event is
        # attributed to the company that OWNS the prospect (the funnel
        # advancing), not whatever company is currently active in the
        # contextvar (which could be a different operator role context).
        rows = await self._db.fetch_all(
            "SELECT prospect_id, company_id FROM prospects WHERE prospect_id = ?",
            (prospect_id,),
        )
        if not rows:
            return ToolResult(success=False, error=f"Prospect {prospect_id} not found")

        # ABE Phase 9 trust gate — refuse live outreach when the
        # prospect's company is in 'learning' state. Gate keyed on
        # the PROSPECT's company (the funnel being touched), not the
        # operator's active session company — same rule as the
        # pipeline_advance ledger attribution in this tool. Only
        # gates outbound actions; 'note' and 'reply_received' are
        # bookkeeping, not communication.
        if action in ("email_sent", "follow_up", "platform_applied"):
            prospect_company_id_for_gate = (
                rows[0][1] if len(rows[0]) > 1 else None
            ) or "elophanto-self"
            from core.trust_gate import check_outreach_allowed

            allowed, reason = await check_outreach_allowed(
                self._db, "prospect_outreach", prospect_company_id_for_gate
            )
            if not allowed:
                return ToolResult(success=False, error=reason)
        prospect_company_id = (
            rows[0][1] if len(rows[0]) > 1 else None
        ) or "elophanto-self"

        # Check daily outreach limit (max 10 per day)
        if action == "email_sent":
            today_start = (
                datetime.now(UTC).replace(hour=0, minute=0, second=0).isoformat()
            )
            count_rows = await self._db.fetch_all(
                "SELECT COUNT(*) FROM outreach_log "
                "WHERE action = 'email_sent' AND created_at >= ?",
                (today_start,),
            )
            daily_count = count_rows[0][0] if count_rows else 0
            if daily_count >= 10:
                return ToolResult(
                    success=False,
                    error=f"Daily outreach limit reached ({daily_count}/10). Try again tomorrow.",
                )

        # Insert outreach log entry. ABE Phase 3: attribute to the
        # prospect's company (its funnel is what activity is being
        # logged for) — same rule as the ledger event below. This
        # keeps the outreach history coherent if a prospect ever
        # changes hands between companies.
        direction = "inbound" if action == "reply_received" else "outbound"
        outreach_id = await self._db.execute_insert(
            "INSERT INTO outreach_log "
            "(prospect_id, action, channel, message_id, content_preview, "
            "direction, created_at, company_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                prospect_id,
                action,
                params.get("channel", "email"),
                params.get("message_id", ""),
                params.get("content_preview", "")[:200],
                direction,
                now,
                prospect_company_id,
            ),
        )

        # Update prospect status if requested
        new_status = params.get("new_status")
        if not new_status and action == "email_sent":
            new_status = "outreach_sent"
        if not new_status and action == "reply_received":
            new_status = "replied"

        if new_status:
            update_fields = "status = ?, last_activity_at = ?"
            update_params: list[Any] = [new_status, now]
            if action == "email_sent":
                update_fields += ", outreach_sent_at = ?"
                update_params.append(now)
            update_params.append(prospect_id)
            await self._db.execute(
                f"UPDATE prospects SET {update_fields} WHERE prospect_id = ?",
                tuple(update_params),
            )

        # ABE Phase 3 — pipeline advance ledger mirror. Positive stage
        # transitions (evaluated, outreach_sent, replied, converted)
        # count as pipeline_advance events. Negative outcomes
        # (rejected, expired) do NOT — those are pipeline shrinkage,
        # not progress. Failures swallowed: outreach_log is the source
        # of truth, ledger is a denormalized read model.
        if new_status in ("evaluated", "outreach_sent", "replied", "converted"):
            try:
                from core.ledger import LedgerEntry, ResourceLedger

                ledger = ResourceLedger(self._db)
                await ledger.write(
                    LedgerEntry(
                        # Attribute to the prospect's company (its
                        # funnel is what advanced) not the operator's
                        # currently-active company.
                        company_id=prospect_company_id,
                        direction="in",
                        type="pipeline_advance",
                        amount=1.0,
                        unit="count",
                        source_table="outreach_log",
                        source_id=outreach_id,
                        note=f"{prospect_id} → {new_status}",
                    )
                )
            except Exception:
                pass

        return ToolResult(
            success=True,
            data={
                "prospect_id": prospect_id,
                "action": action,
                "status": new_status or "unchanged",
                "logged_at": now,
            },
        )
