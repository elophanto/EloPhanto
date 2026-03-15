"""Payment request tool — create, check, list, cancel payment requests."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class PaymentRequestTool(BaseTool):
    """Create and track payment requests (invoices) for receiving crypto."""

    @property
    def group(self) -> str:
        return "payments"

    def __init__(self) -> None:
        self._payments_manager: Any = None

    @property
    def name(self) -> str:
        return "payment_request"

    @property
    def description(self) -> str:
        return (
            "Create a payment request (invoice) with the agent's wallet address, "
            "amount, and token. Check if a request has been paid by scanning the "
            "blockchain. List pending/paid requests or cancel a request."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "check", "list", "cancel"],
                    "description": "Action to perform.",
                },
                "amount": {
                    "type": "number",
                    "description": "Amount to request (required for 'create').",
                },
                "token": {
                    "type": "string",
                    "description": "Token symbol (e.g. USDC, SOL, ETH). Default: USDC.",
                },
                "memo": {
                    "type": "string",
                    "description": "Description or memo for the payment request.",
                },
                "ttl_minutes": {
                    "type": "integer",
                    "description": "Minutes until request expires. Default: 1440 (24h).",
                },
                "request_id": {
                    "type": "string",
                    "description": "Request ID (required for 'check' and 'cancel').",
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "paid", "expired", "cancelled"],
                    "description": "Status filter for 'list' action.",
                },
            },
            "required": ["action"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._payments_manager:
            return ToolResult(success=False, error="Payments system not initialized")

        action = params.get("action", "create")

        if action == "create":
            amount = params.get("amount")
            if not amount or amount <= 0:
                return ToolResult(
                    success=False, error="Amount is required and must be > 0"
                )
            result = await self._payments_manager.create_payment_request(
                amount=amount,
                token=params.get("token", "USDC"),
                memo=params.get("memo"),
                ttl_minutes=params.get("ttl_minutes", 1440),
                task_context=params.get("memo"),
            )
            return ToolResult(success=True, data=result)

        elif action == "check":
            request_id = params.get("request_id")
            if not request_id:
                return ToolResult(
                    success=False, error="request_id is required for check"
                )
            result = await self._payments_manager.check_payment_request(request_id)
            if "error" in result:
                return ToolResult(success=False, error=result["error"])
            return ToolResult(success=True, data=result)

        elif action == "list":
            requests = await self._payments_manager.list_payment_requests(
                status=params.get("status"),
            )
            return ToolResult(
                success=True,
                data={"requests": requests, "count": len(requests)},
            )

        elif action == "cancel":
            request_id = params.get("request_id")
            if not request_id:
                return ToolResult(
                    success=False, error="request_id is required for cancel"
                )
            cancelled = await self._payments_manager.cancel_payment_request(request_id)
            return ToolResult(
                success=cancelled,
                error=None if cancelled else "Request not found or not pending",
            )

        return ToolResult(success=False, error=f"Unknown action: {action}")
