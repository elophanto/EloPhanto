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


@dataclass(frozen=True)
class Metabolism:
    """Per-company economic state INCLUDING the agent's own cognition cost.

    Organ 1 of the founder-autonomy roadmap
    (tmp/founder-vs-elophanto-audit-2026-06-18.md Phase 6): a truly
    autonomous business entity must run its own P&L including what it
    costs to *think* (LLM spend), not just external revenue vs external
    spend.

    IMPORTANT — no double counting: ``CostTracker.flush`` (core/router.py)
    already mirrors every LLM call into ``resource_ledger`` as a
    ``type='usd', direction='out', source_table='llm_usage'`` row. So
    ``spend_usd`` (sum of all usd-out) ALREADY includes the agent's
    cognition cost. ``net_usd`` therefore subtracts ``spend_usd`` once and
    does NOT subtract ``cognition_usd`` again. ``cognition_usd`` (read from
    ``llm_usage``) is surfaced as a *visible sub-component* of spend — "of
    everything you spent, this much was your own thinking" — which is the
    organ-1 insight, not an additional cost.
    """

    revenue_usd: float
    spend_usd: float  # total usd-out — already includes cognition (mirrored)
    cognition_usd: float  # the cognition slice of spend_usd (informational)

    @property
    def net_usd(self) -> float:
        """Revenue minus total spend (which already includes cognition)."""
        return self.revenue_usd - self.spend_usd

    @property
    def is_burning(self) -> bool:
        """True when the company costs more than it earns (incl. cognition)."""
        return self.net_usd < 0.0


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

    async def cognition_cost(
        self, company_id: str, *, since: str | None = None
    ) -> float:
        """Sum the agent's LLM spend (its cost of *thinking*) attributed to a
        company.

        Reads ``llm_usage.cost_usd`` — that table gained a ``company_id``
        column in the ABE Phase 1 migration (pre-migration rows default to
        'elophanto-self'). ``since`` is an ISO8601 lower bound on
        ``created_at`` (inclusive). Lives here, alongside ``sum``, so the
        whole per-company P&L is computed from one place.
        """
        sql = (
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS s FROM llm_usage "
            "WHERE company_id = ?"
        )
        params: list[Any] = [company_id]
        if since is not None:
            sql += " AND created_at >= ?"
            params.append(since)
        rows = await self._db.execute(sql, tuple(params))
        return float(rows[0]["s"]) if rows else 0.0

    async def metabolism(
        self, company_id: str, *, since: str | None = None
    ) -> Metabolism:
        """Per-company P&L INCLUDING the agent's own cognition cost.

        ``since`` (ISO8601) optionally windows all three sums to a trailing
        period — pass it to compute, e.g., trailing-30d metabolism for a
        trend/runway read. Without it, the figures are all-time.
        """
        return Metabolism(
            revenue_usd=await self.sum(
                company_id, type="usd", direction="in", since=since
            ),
            spend_usd=await self.sum(
                company_id, type="usd", direction="out", since=since
            ),
            cognition_usd=await self.cognition_cost(company_id, since=since),
        )
