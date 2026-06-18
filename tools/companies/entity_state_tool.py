"""company_set_entity_state — advance a company's KYC / financial-readiness.

ABE finance rail (tmp/abe-finance-rail-spec-2026-06-18.md §2). The entity
state machine is orthogonal to the trust ladder: the trust ladder gates live
ACTIONS; entity_state gates live MONEY. Real fiat money movement requires
``verified``. This tool is how the operator walks a company up the ladder as
KYC progresses (e.g. after Stripe Atlas finishes, or a BYO Stripe account
clears review). MODERATE — setting 'verified' asserts the legal entity + KYC
are actually in place, so it goes through operator approval.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class CompanySetEntityStateTool(BaseTool):
    """Advance a company's financial-readiness / KYC state."""

    def __init__(self) -> None:
        self._company_manager: Any = None

    @property
    def group(self) -> str:
        return "companies"

    @property
    def name(self) -> str:
        return "company_set_entity_state"

    @property
    def description(self) -> str:
        return (
            "Advance a company's financial-readiness / KYC state: "
            "none -> forming -> kyc_pending -> verified -> restricted. Real "
            "money movement (live fiat) requires 'verified' — only set it "
            "once the operator confirms the legal entity + KYC are actually "
            "in place. Defaults to the active company. 'restricted' = the "
            "processor froze the account (money blocked)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "enum": [
                        "none",
                        "forming",
                        "kyc_pending",
                        "verified",
                        "restricted",
                    ],
                    "description": "The new entity / KYC state.",
                },
                "slug": {
                    "type": "string",
                    "description": "Company slug (default: the active company).",
                },
            },
            "required": ["state"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._company_manager is None:
            return ToolResult(
                success=False,
                error="company_set_entity_state not initialized (company_manager)",
            )
        from core.company import VALID_ENTITY_STATES, current_company_id

        state = str(params.get("state", "")).strip().lower()
        if state not in VALID_ENTITY_STATES:
            return ToolResult(
                success=False,
                error=f"invalid state {state!r}; expected one of {VALID_ENTITY_STATES}",
            )
        slug = str(params.get("slug") or "").strip() or current_company_id()
        try:
            ok = await self._company_manager.set_entity_state(slug, state)
        except ValueError as e:
            return ToolResult(success=False, error=str(e))
        if not ok:
            return ToolResult(success=False, error=f"company {slug!r} not found")

        note = None
        if state == "verified":
            note = (
                "Verified — live fiat money movement is now permitted "
                "(still gated by payments.fiat.mode=live + per-tool approval)."
            )
        elif state == "restricted":
            note = (
                "Restricted — money movement blocked. Investigate the "
                "processor hold before relying on this company's funds."
            )
        return ToolResult(
            success=True,
            data={"slug": slug, "entity_state": state, "note": note},
        )
