"""fiat_issue_card — provision a bounded virtual card (ABE finance rail, Spend).

Slice 3a. CRITICAL — it provisions a real spending instrument. Issues a
virtual Stripe Issuing card under the operator's configured cardholder,
bounded by an operator-set spend envelope (organ 6). Test mode by default
(test card, no real money); live mode requires the active company's
entity_state == 'verified'.

PCI boundary (spec §6.4): this returns ONLY non-sensitive card fields
(id / last4 / expiry). It NEVER retrieves or returns the raw PAN/CVC — using
the card to pay a vendor (which needs the PAN) is a separate, deliberately
deferred capability that requires a handler proven to keep the PAN out of LLM
prompts and logs.
"""

from __future__ import annotations

import uuid
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

_VALID_INTERVALS = (
    "per_authorization",
    "daily",
    "weekly",
    "monthly",
    "yearly",
    "all_time",
)


class FiatIssueCardTool(BaseTool):
    """Issue a spend-controlled virtual card (PAN never exposed)."""

    @property
    def group(self) -> str:
        return "payments"

    def __init__(self) -> None:
        self._config: Any = None
        self._vault: Any = None
        self._company_manager: Any = None

    @property
    def name(self) -> str:
        return "fiat_issue_card"

    @property
    def description(self) -> str:
        return (
            "Provision a bounded virtual card (Stripe Issuing) for outbound "
            "spend, capped by a spend limit you set. Returns the card id + "
            "last4 + expiry — NEVER the full number/CVC. TEST mode by default "
            "(no real money); LIVE requires the company's KYC "
            "(entity_state=verified) and payments.fiat.issuing_enabled. The "
            "limit is the guardrail — set it to the smallest amount that "
            "covers the intended purchase."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "spend_limit": {
                    "type": "number",
                    "description": "Spend cap in major units (e.g. 200 = $200).",
                },
                "interval": {
                    "type": "string",
                    "enum": list(_VALID_INTERVALS),
                    "description": (
                        "Window the limit applies over. Default "
                        "'per_authorization' (caps each charge) — the "
                        "tightest, safest choice."
                    ),
                },
                "allowed_categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional Stripe merchant-category allowlist "
                        "(e.g. ['cloud_computing']). Omit for no category "
                        "restriction beyond the spend limit."
                    ),
                },
            },
            "required": ["spend_limit"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        # CRITICAL — provisions a real spending instrument.
        return PermissionLevel.CRITICAL

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        fiat = getattr(getattr(self._config, "payments", None), "fiat", None)
        if fiat is None or not getattr(fiat, "enabled", False):
            return ToolResult(success=False, error="Fiat payments not enabled.")
        if not getattr(fiat, "issuing_enabled", False):
            return ToolResult(
                success=False,
                error=(
                    "Card issuing is not enabled. Set "
                    "payments.fiat.issuing_enabled: true (and configure a "
                    "Stripe cardholder id) before issuing cards."
                ),
            )

        mode = (getattr(fiat, "mode", "test") or "test").strip().lower()
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
                        f"(currently '{entity}'). Finish KYC or switch "
                        f"payments.fiat.mode to test."
                    ),
                )

        spend_limit = params.get("spend_limit")
        if spend_limit is None or float(spend_limit) <= 0:
            return ToolResult(
                success=False, error="spend_limit must be a positive number"
            )
        interval = (params.get("interval") or "per_authorization").strip().lower()
        if interval not in _VALID_INTERVALS:
            return ToolResult(
                success=False,
                error=f"invalid interval {interval!r}; expected one of {_VALID_INTERVALS}",
            )
        categories = params.get("allowed_categories")
        if categories is not None and not isinstance(categories, list):
            return ToolResult(
                success=False, error="allowed_categories must be a list of strings"
            )

        from core.payments.fiat_stripe import FiatRailError, StripeFiatProvider

        provider = StripeFiatProvider(fiat, self._vault)
        try:
            result = await provider.create_virtual_card(
                spend_limit=float(spend_limit),
                interval=interval,
                allowed_categories=categories,
                idempotency_key=uuid.uuid4().hex,
            )
        except FiatRailError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:  # defensive — never leak internals
            return ToolResult(
                success=False, error=f"card issue failed: {type(e).__name__}"
            )

        # Defense in depth: guarantee no raw card data ever leaves this tool,
        # even if a future provider change started returning it.
        for sensitive in ("number", "cvc", "cvv"):
            result.pop(sensitive, None)
        result["note"] = (
            "TEST card — no real money"
            if mode != "live"
            else "LIVE card — real spend up to the limit"
        )
        return ToolResult(success=True, data=result)
