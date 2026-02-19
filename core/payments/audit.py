"""Payment audit trail — logs every payment attempt to the database."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


class PaymentAuditor:
    """Logs every payment attempt to the payment_audit table."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def log(
        self,
        *,
        tool_name: str,
        amount: float,
        currency: str,
        recipient: str,
        payment_type: str,
        provider: str | None = None,
        chain: str | None = None,
        status: str = "pending",
        session_id: str | None = None,
        channel: str | None = None,
        task_context: str | None = None,
        transaction_ref: str | None = None,
        fee_amount: float | None = None,
        fee_currency: str | None = None,
        error: str | None = None,
    ) -> int:
        """Insert an audit record. Returns the row ID."""
        now = datetime.now(UTC).isoformat()
        row_id: int = await self._db.execute_insert(
            "INSERT INTO payment_audit "
            "(timestamp, tool_name, amount, currency, recipient, payment_type, "
            "provider, chain, status, session_id, channel, task_context, "
            "transaction_ref, fee_amount, fee_currency, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                now,
                tool_name,
                amount,
                currency,
                recipient,
                payment_type,
                provider,
                chain,
                status,
                session_id,
                channel,
                task_context,
                transaction_ref,
                fee_amount,
                fee_currency,
                error,
            ),
        )
        return row_id

    async def update_status(
        self,
        audit_id: int,
        status: str,
        transaction_ref: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update an existing audit record after execution."""
        if transaction_ref:
            await self._db.execute(
                "UPDATE payment_audit SET status = ?, transaction_ref = ?, error = ? WHERE id = ?",
                (status, transaction_ref, error, audit_id),
            )
        else:
            await self._db.execute(
                "UPDATE payment_audit SET status = ?, error = ? WHERE id = ?",
                (status, error, audit_id),
            )

    async def get_history(self, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
        """Query payment history."""
        if status:
            rows = await self._db.execute(
                "SELECT * FROM payment_audit WHERE status = ? ORDER BY timestamp DESC LIMIT ?",
                (status, limit),
            )
        else:
            rows = await self._db.execute(
                "SELECT * FROM payment_audit ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in rows]

    async def get_daily_total(self) -> float:
        """Sum of executed amounts in the last 24 hours."""
        rows = await self._db.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM payment_audit "
            "WHERE status = 'executed' AND timestamp > datetime('now', '-24 hours')",
        )
        return float(rows[0]["total"]) if rows else 0.0

    async def get_monthly_total(self) -> float:
        """Sum of executed amounts in the current calendar month."""
        now = datetime.now(UTC)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        rows = await self._db.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM payment_audit "
            "WHERE status = 'executed' AND timestamp >= ?",
            (month_start,),
        )
        return float(rows[0]["total"]) if rows else 0.0

    async def get_recipient_daily_total(self, recipient: str) -> float:
        """Sum of executed amounts to a specific recipient in the last 24 hours."""
        rows = await self._db.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM payment_audit "
            "WHERE status = 'executed' AND recipient = ? "
            "AND timestamp > datetime('now', '-24 hours')",
            (recipient,),
        )
        return float(rows[0]["total"]) if rows else 0.0

    async def get_hourly_count(self) -> int:
        """Count of executed transactions in the last hour."""
        rows = await self._db.execute(
            "SELECT COUNT(*) AS cnt FROM payment_audit "
            "WHERE status = 'executed' AND timestamp > datetime('now', '-1 hour')",
        )
        return int(rows[0]["cnt"]) if rows else 0

    async def has_recent_duplicate(self, amount: float, recipient: str) -> bool:
        """Check if same amount+recipient exists within the last hour."""
        rows = await self._db.execute(
            "SELECT COUNT(*) AS cnt FROM payment_audit "
            "WHERE status = 'executed' AND amount = ? AND recipient = ? "
            "AND timestamp > datetime('now', '-1 hour')",
            (amount, recipient),
        )
        return int(rows[0]["cnt"]) > 0 if rows else False
