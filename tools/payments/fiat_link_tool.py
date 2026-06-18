"""fiat_payment_link — create a Stripe payment link to GET PAID (fiat rail).

Slice 2 (Receive) of the ABE finance rail. MODERATE permission. In test mode
(the default) this creates a sandbox link — no real money, no KYC. In live
mode it is gated on the active company's entity_state == 'verified' (KYC done)
— the agent cannot collect real money on an unverified entity.
See tmp/abe-finance-rail-spec-2026-06-18.md §7 (Receive).
"""

from __future__ import annotations

import uuid
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class FiatPaymentLinkTool(BaseTool):
    """Create a shareable Stripe payment link for a one-off amount."""

    @property
    def group(self) -> str:
        return "payments"

    def __init__(self) -> None:
        # Injected by Agent._inject_payment_deps (gated on payments.enabled).
        self._config: Any = None
        self._vault: Any = None
        self._company_manager: Any = None

    @property
    def name(self) -> str:
        return "fiat_payment_link"

    @property
    def description(self) -> str:
        return (
            "Create a Stripe payment link to GET PAID in fiat (cards/bank). "
            "Returns a shareable URL. In TEST mode (default) it's a sandbox "
            "link — no real money. LIVE mode requires the company's KYC "
            "(entity_state=verified). Amount is in the business's base "
            "currency (USD by default)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "amount": {
                    "type": "number",
                    "description": "Amount to charge, in major units (e.g. 49 = $49.00).",
                },
                "description": {
                    "type": "string",
                    "description": "What the payment is for (shown to the payer).",
                },
                "currency": {
                    "type": "string",
                    "description": "ISO currency (default: the business base currency).",
                },
            },
            "required": ["amount", "description"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        fiat = getattr(getattr(self._config, "payments", None), "fiat", None)
        if fiat is None or not getattr(fiat, "enabled", False):
            return ToolResult(
                success=False,
                error=(
                    "Fiat payments not enabled. Enable it with the setup "
                    "wizard or set payments.fiat.enabled: true (test mode "
                    "needs only a free sk_test_ key)."
                ),
            )

        mode = (getattr(fiat, "mode", "test") or "test").strip().lower()
        # Live-mode KYC gate — no collecting real money on an unverified entity.
        if mode == "live":
            entity = "none"
            if self._company_manager is not None:
                from core.company import current_company_id

                entity = await self._company_manager.get_entity_state(
                    current_company_id()
                )
            if entity != "verified":
                return ToolResult(
                    success=False,
                    error=(
                        f"Live mode requires company entity_state=verified "
                        f"(currently '{entity}'). Finish KYC (BYO entity or "
                        f"Atlas) or switch payments.fiat.mode to test."
                    ),
                )

        amount = params.get("amount")
        description = (params.get("description") or "").strip()
        if amount is None or float(amount) <= 0:
            return ToolResult(success=False, error="amount must be a positive number")
        if not description:
            return ToolResult(success=False, error="description is required")

        from core.payments.fiat_stripe import FiatRailError, StripeFiatProvider

        provider = StripeFiatProvider(fiat, self._vault)
        try:
            result = await provider.create_payment_link(
                amount=float(amount),
                description=description,
                currency=params.get("currency"),
                idempotency_key=uuid.uuid4().hex,
            )
        except FiatRailError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:  # defensive — never leak internals
            return ToolResult(
                success=False, error=f"payment link failed: {type(e).__name__}"
            )

        result["note"] = (
            "TEST mode — no real money will be collected"
            if mode != "live"
            else "LIVE — real money"
        )
        return ToolResult(success=True, data=result)
