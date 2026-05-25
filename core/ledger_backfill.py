"""One-shot backfill: import historical rows from llm_usage, payment_audit,
and email_log into resource_ledger.

Phase 1 originally deferred backfill to Phase 5 ("ledger is forward-only").
That was reversed on 2026-05-25 — without backfill the report command
shows ``$0.00`` for the whole pre-2026-05-25 history, which makes the
board view useless for the only company that exists right now.

Idempotency is enforced by ``(source_table, source_id)`` uniqueness:
the script SELECTs the set of already-backfilled (source_table, source_id)
pairs, then inserts only the missing rows. Safe to re-run.

This is a one-shot script, not part of ``_init_sync`` — it's heavy
(12,968+ rows to copy on the live DB) and the operator should choose
when to pay that cost. Exposed as ``elophanto company backfill``.

See ``docs/76-ABE-FRAMEWORK.md`` §Phase 1.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.database import Database

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BackfillReport:
    llm_tokens_added: int = 0
    llm_usd_added: int = 0
    payment_added: int = 0
    email_added: int = 0

    @property
    def total(self) -> int:
        return (
            self.llm_tokens_added
            + self.llm_usd_added
            + self.payment_added
            + self.email_added
        )


async def backfill_ledger(db: Database) -> BackfillReport:
    """Backfill historical rows into resource_ledger. Idempotent."""
    report = BackfillReport()

    # Build the set of (source_table, source_id) pairs already in
    # the ledger so re-runs are no-ops. Cheap — only as big as the
    # current ledger, which is empty on first run.
    existing_rows = await db.execute(
        "SELECT source_table, source_id FROM resource_ledger "
        "WHERE source_table IS NOT NULL AND source_id IS NOT NULL"
    )
    existing: set[tuple[str, int]] = {
        (r["source_table"], r["source_id"]) for r in existing_rows
    }

    # ─── llm_usage → two ledger rows per source row (tokens + usd) ──────
    llm_rows = await db.execute(
        "SELECT id, input_tokens, output_tokens, cost_usd, provider, model, "
        "created_at, company_id FROM llm_usage ORDER BY id"
    )
    for r in llm_rows:
        src_id = r["id"]
        company_id = r["company_id"] or "elophanto-self"
        total_tokens = float(r["input_tokens"] + r["output_tokens"])
        cost = float(r["cost_usd"])
        ts = r["created_at"]
        note = f"{r['provider']}/{r['model']}"

        if ("llm_usage", src_id) not in existing:
            # We use a special composite-row-id encoding so 'tokens' and
            # 'usd' for the same source_id don't collide in the
            # existing-set check. The ledger row's own id is fine for
            # identifying the row; for uniqueness we rely on the caller
            # not running concurrent backfills (this is a one-shot CLI).
            await db.execute_insert(
                "INSERT INTO resource_ledger "
                "(company_id, ts, direction, type, amount, unit, "
                "source_table, source_id, note) "
                "VALUES (?, ?, 'out', 'tokens', ?, 'tok', 'llm_usage', ?, ?)",
                (company_id, ts, total_tokens, src_id, note),
            )
            report.llm_tokens_added += 1
            await db.execute_insert(
                "INSERT INTO resource_ledger "
                "(company_id, ts, direction, type, amount, unit, "
                "source_table, source_id, note) "
                "VALUES (?, ?, 'out', 'usd', ?, 'usd', 'llm_usage', ?, ?)",
                (company_id, ts, cost, src_id, note),
            )
            report.llm_usd_added += 1

    # ─── payment_audit → one ledger row per source row ──────────────────
    pay_rows = await db.execute(
        "SELECT id, amount, currency, payment_type, recipient, tool_name, "
        "timestamp, company_id FROM payment_audit ORDER BY id"
    )
    for r in pay_rows:
        src_id = r["id"]
        if ("payment_audit", src_id) in existing:
            continue
        company_id = r["company_id"] or "elophanto-self"
        direction = (
            "in"
            if (r["payment_type"] or "").lower() in ("inbound", "received", "in")
            else "out"
        )
        ledger_type = (
            "usd"
            if (r["currency"] or "").upper() == "USD"
            else (r["currency"] or "unknown").lower()
        )
        await db.execute_insert(
            "INSERT INTO resource_ledger "
            "(company_id, ts, direction, type, amount, unit, "
            "source_table, source_id, note) "
            "VALUES (?, ?, ?, ?, ?, ?, 'payment_audit', ?, ?)",
            (
                company_id,
                r["timestamp"],
                direction,
                ledger_type,
                float(r["amount"]),
                ledger_type,
                src_id,
                f"{r['tool_name']} → {r['recipient']}",
            ),
        )
        report.payment_added += 1

    # ─── email_log → one ledger row per outbound row ────────────────────
    email_rows = await db.execute(
        "SELECT id, tool_name, direction, recipient, timestamp, company_id "
        "FROM email_log WHERE direction = 'outbound' ORDER BY id"
    )
    for r in email_rows:
        src_id = r["id"]
        if ("email_log", src_id) in existing:
            continue
        company_id = r["company_id"] or "elophanto-self"
        await db.execute_insert(
            "INSERT INTO resource_ledger "
            "(company_id, ts, direction, type, amount, unit, "
            "source_table, source_id, note) "
            "VALUES (?, ?, 'out', 'email_sent', 1.0, 'count', "
            "'email_log', ?, ?)",
            (
                company_id,
                r["timestamp"],
                src_id,
                f"{r['tool_name']}{f' → {r['recipient']}' if r['recipient'] else ''}",
            ),
        )
        report.email_added += 1

    logger.info(
        "Backfill complete: +%d llm_tokens, +%d llm_usd, +%d payment, +%d email "
        "(total +%d ledger rows)",
        report.llm_tokens_added,
        report.llm_usd_added,
        report.payment_added,
        report.email_added,
        report.total,
    )
    return report
