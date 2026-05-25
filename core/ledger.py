"""Resource ledger — typed event log for the ABE framework.

ABE (Autonomous Business Entity) is a concept originated by Petr
Royce in 2023.

The ledger is **general**, not money-specific:

- Money flows: ``type='usd'``, ``unit='usd'``
- LLM token spend: ``type='tokens'``, ``unit='tok'``
- Email touches: ``type='email_sent'``, ``unit='count'``
- Pipeline advances: ``type='pipeline_advance'``, ``unit='count'``
- Decisions: ``type='decision'``, ``unit='count'`` (Phase 2)
- Time in a role: ``type='time_in_role'``, ``unit='min'`` (Phase 2)

Every meaningful action writes a ledger event. This doubles as the
**honest progress signal** that fixes the bounded-reconciliation loop
in ``docs/75-AUTONOMOUS-MIND-V2.md``: a cycle that produces zero ledger
events made zero progress regardless of what the LLM narrates.

See ``docs/76-ABE-FRAMEWORK.md`` §Phase 1.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.database import Database

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LedgerEntry:
    company_id: str
    direction: str  # 'in' | 'out'
    type: str
    amount: float
    unit: str
    source_table: str | None = None
    source_id: int | None = None
    role_name: str | None = None
    note: str | None = None


class ResourceLedger:
    """Single writer for the ``resource_ledger`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def write(self, entry: LedgerEntry) -> int:
        """Append a ledger row. Returns the new row id.

        Never raises on ledger-write failure — logs a warning and
        returns 0. The ledger is a denormalized read model; the source
        tables (``llm_usage``, ``payment_audit``, etc.) remain the
        truth. Losing a ledger row is recoverable from those sources;
        crashing the writing tool is not.
        """
        if entry.direction not in ("in", "out"):
            raise ValueError(f"invalid direction: {entry.direction!r}")
        now_iso = datetime.now(UTC).isoformat()
        try:
            return await self._db.execute_insert(
                "INSERT INTO resource_ledger "
                "(company_id, ts, direction, type, amount, unit, "
                "source_table, source_id, role_name, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.company_id,
                    now_iso,
                    entry.direction,
                    entry.type,
                    entry.amount,
                    entry.unit,
                    entry.source_table,
                    entry.source_id,
                    entry.role_name,
                    entry.note,
                ),
            )
        except Exception as e:
            logger.warning(
                "resource_ledger write failed (entry=%s/%s/%s): %s",
                entry.company_id,
                entry.type,
                entry.direction,
                e,
            )
            return 0

    async def sum(
        self,
        company_id: str,
        *,
        type: str | None = None,
        direction: str | None = None,
        since: str | None = None,
    ) -> float:
        """Sum ledger amounts for a company, optionally filtered.

        ``since`` is an ISO8601 lower bound (inclusive). Returns 0.0 on
        no rows. Caller should know what units they're summing —
        summing ``type='usd'`` is meaningful; summing across types is
        not.
        """
        sql = "SELECT COALESCE(SUM(amount), 0.0) AS s FROM resource_ledger WHERE company_id = ?"
        params: list[Any] = [company_id]
        if type is not None:
            sql += " AND type = ?"
            params.append(type)
        if direction is not None:
            sql += " AND direction = ?"
            params.append(direction)
        if since is not None:
            sql += " AND ts >= ?"
            params.append(since)
        rows = await self._db.execute(sql, tuple(params))
        return float(rows[0]["s"]) if rows else 0.0

    async def recent(self, company_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Most recent ledger rows for a company, newest first."""
        rows = await self._db.execute(
            "SELECT id, ts, direction, type, amount, unit, "
            "source_table, source_id, role_name, note "
            "FROM resource_ledger WHERE company_id = ? "
            "ORDER BY ts DESC LIMIT ?",
            (company_id, limit),
        )
        return [dict(r) for r in rows]
