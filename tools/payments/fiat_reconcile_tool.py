"""fiat_reconcile — record received Stripe payments into the ledger.

Slice 2b of the ABE finance rail: closes the receive loop. Pulls recent
SUCCEEDED Stripe payments and writes any not-yet-recorded ones as `usd`/`in`
ledger rows, so a paid link becomes measurable revenue (→ "first unattended
dollar"). Idempotent — deduped by the Stripe payment id (note=`stripe:<id>`).

Test-mode receipts are recorded with mode='test', which metabolism/runway
exclude from real revenue (spec §6.8) — so rehearsing checkout in the sandbox
never inflates the books. SAFE permission: it records completed external
events, it does not move money.
"""

from __future__ import annotations

import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class FiatReconcileTool(BaseTool):
    """Mirror recent paid Stripe payments into the resource ledger."""

    @property
    def group(self) -> str:
        return "payments"

    def __init__(self) -> None:
        self._config: Any = None
        self._vault: Any = None
        self._db: Any = None
        self._company_manager: Any = None

    @property
    def name(self) -> str:
        return "fiat_reconcile"

    @property
    def description(self) -> str:
        return (
            "Reconcile Stripe: pull recent succeeded payments and record any "
            "not already in the ledger as revenue. Idempotent (deduped by "
            "Stripe id). Run after a payment or periodically. Test-mode "
            "payments are recorded as test and excluded from real revenue."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max recent payments to scan (default 100).",
                },
                "company_id": {
                    "type": "string",
                    "description": (
                        "Company to attribute recorded payments to. Defaults "
                        "to the active company. A scheduled reconcile passes "
                        "this explicitly so it records under the right "
                        "business regardless of fire-time context."
                    ),
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        fiat = getattr(getattr(self._config, "payments", None), "fiat", None)
        if fiat is None or not getattr(fiat, "enabled", False):
            return ToolResult(success=False, error="Fiat payments not enabled.")
        if self._db is None:
            return ToolResult(success=False, error="Ledger not available.")

        from core.company import current_company_id
        from core.ledger import LedgerEntry, ResourceLedger
        from core.payments.fiat_stripe import FiatRailError, StripeFiatProvider

        # Explicit company_id wins (a scheduled reconcile passes it so it
        # records under the right business even though the scheduler's
        # direct-tool path doesn't set the company contextvar — see
        # scheduler._run_direct_tool). Falls back to the active company.
        company_id = (params.get("company_id") or "").strip() or current_company_id()
        mode = (getattr(fiat, "mode", "test") or "test").strip().lower()
        provider = StripeFiatProvider(fiat, self._vault)
        ledger = ResourceLedger(self._db)

        try:
            limit = int(params.get("limit") or 100)
        except (TypeError, ValueError):
            limit = 100

        try:
            payments = await provider.list_recent_payments(limit=limit)
        except FiatRailError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:  # defensive — never leak internals
            return ToolResult(
                success=False, error=f"reconcile failed: {type(e).__name__}"
            )

        mirrored = 0
        already = 0
        total = 0.0
        for p in payments:
            pid = p.get("id")
            amount = float(p.get("amount") or 0.0)
            if not pid or amount <= 0:
                continue
            note = f"stripe:{pid}"
            if await ledger.note_exists(company_id, note):
                already += 1
                continue
            await ledger.write(
                LedgerEntry(
                    company_id=company_id,
                    direction="in",
                    type="usd",
                    amount=amount,
                    unit="usd",
                    source_table="stripe",
                    note=note,
                    mode=mode,
                )
            )
            mirrored += 1
            total += amount

        # Refund reversal (spec §6.5): a refund reduces realized revenue, so
        # record each as a compensating usd-OUT row (net drops by the refund).
        # Best-effort — a refund-list failure must not undo the payment
        # recording above; surface refunds_checked=False so the operator knows
        # refunds weren't reconciled this run (don't silently overstate net).
        refunds_recorded = 0
        refund_total = 0.0
        refunds_checked = True
        try:
            refunds = await provider.list_recent_refunds(limit=limit)
            for rf in refunds:
                rid = rf.get("id")
                amt = float(rf.get("amount") or 0.0)
                if not rid or amt <= 0:
                    continue
                rnote = f"stripe:refund:{rid}"
                if await ledger.note_exists(company_id, rnote):
                    continue
                await ledger.write(
                    LedgerEntry(
                        company_id=company_id,
                        direction="out",
                        type="usd",
                        amount=amt,
                        unit="usd",
                        source_table="stripe_refund",
                        note=rnote,
                        mode=mode,
                    )
                )
                refunds_recorded += 1
                refund_total += amt
        except Exception as e:
            refunds_checked = False
            logger.warning("fiat_reconcile: refund pass skipped: %s", e)

        return ToolResult(
            success=True,
            data={
                "mirrored": mirrored,
                "already_recorded": already,
                "total_recorded_usd": round(total, 2),
                "refunds_recorded": refunds_recorded,
                "refunds_total_usd": round(refund_total, 2),
                "refunds_checked": refunds_checked,
                "net_recorded_usd": round(total - refund_total, 2),
                "mode": mode,
                "note": (
                    "recorded as live revenue"
                    if mode == "live"
                    else "test-mode receipts — excluded from real revenue"
                ),
            },
        )
