"""payment_history — query transaction history and spending summary."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class PaymentHistoryTool(BaseTool):
    """Query the agent's payment transaction history and spending summary."""

    def __init__(self) -> None:
        self._payments_manager: Any = None

    @property
    def name(self) -> str:
        return "payment_history"

    @property
    def description(self) -> str:
        return (
            "Query payment transaction history. Can filter by status "
            "or show daily/monthly spending totals."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max results to return. Default 20.",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status: executed, failed, denied, pending.",
                },
                "summary": {
                    "type": "boolean",
                    "description": "Show spending totals instead of individual transactions.",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._payments_manager:
            return ToolResult(success=False, error="Payments system not initialized")

        auditor = self._payments_manager.auditor

        if params.get("summary"):
            daily = await auditor.get_daily_total()
            monthly = await auditor.get_monthly_total()
            return ToolResult(
                success=True,
                data={
                    "daily_spent": daily,
                    "monthly_spent": monthly,
                    "daily_limit": self._payments_manager._config.limits.daily,
                    "monthly_limit": self._payments_manager._config.limits.monthly,
                },
            )

        limit = params.get("limit", 20)
        status = params.get("status")
        history = await auditor.get_history(limit=limit, status=status)
        return ToolResult(success=True, data={"transactions": history, "count": len(history)})
