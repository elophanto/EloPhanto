"""Ambient signal inbox — durable typed events for the anticipation spine.

Adapters and /hooks/wake write here; mind_candidates.from_external_signals
reads open rows. Dedup bumps urgency on repeats instead of flooding the
arbiter menu.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.company import current_company_id
from core.database import Database

logger = logging.getLogger(__name__)

_STATUS_OPEN = "open"
_STATUS_CONSUMED = "consumed"
_STATUS_EXPIRED = "expired"
_STATUS_SUPPRESSED = "suppressed"


@dataclass
class AmbientSignal:
    signal_id: str
    company_id: str
    household_id: str | None
    kind: str
    source: str
    subject_ref: str | None
    urgency: float
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = _STATUS_OPEN
    dedup_key: str | None = None
    received_at: str = ""
    expires_at: str | None = None
    consumed_at: str | None = None


class AmbientSignalStore:
    """CRUD + dedup ingest for ``ambient_signals``."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def ingest(
        self,
        kind: str,
        source: str,
        *,
        company_id: str | None = None,
        household_id: str | None = None,
        subject_ref: str | None = None,
        urgency: float = 0.5,
        payload: dict[str, Any] | None = None,
        dedup_key: str | None = None,
        expires_at: str | None = None,
    ) -> str:
        """Insert a signal, or bump an existing open row with the same dedup_key.

        Returns the signal_id (new or existing).
        """
        cid = company_id or current_company_id()
        urgency = max(0.0, min(1.0, float(urgency)))
        now = datetime.now(UTC).isoformat()
        payload = payload or {}

        if dedup_key:
            existing = await self._db.execute(
                "SELECT signal_id, urgency FROM ambient_signals "
                "WHERE company_id = ? AND dedup_key = ? AND status = ? "
                "LIMIT 1",
                (cid, dedup_key, _STATUS_OPEN),
            )
            if existing:
                row = existing[0]
                sid = row["signal_id"]
                new_urgency = max(float(row["urgency"] or 0.0), urgency)
                await self._db.execute_insert(
                    "UPDATE ambient_signals SET urgency = ?, received_at = ?, "
                    "payload_json = ?, subject_ref = COALESCE(?, subject_ref), "
                    "expires_at = COALESCE(?, expires_at) "
                    "WHERE signal_id = ?",
                    (
                        new_urgency,
                        now,
                        json.dumps(payload),
                        subject_ref,
                        expires_at,
                        sid,
                    ),
                )
                logger.debug(
                    "[ambient_signals] dedup bump signal_id=%s urgency=%.2f",
                    sid,
                    new_urgency,
                )
                return sid

        sid = f"sig_{uuid.uuid4().hex[:16]}"
        await self._db.execute_insert(
            "INSERT INTO ambient_signals "
            "(signal_id, company_id, household_id, kind, source, subject_ref, "
            "urgency, payload_json, status, dedup_key, received_at, expires_at, "
            "consumed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                sid,
                cid,
                household_id,
                kind,
                source,
                subject_ref,
                urgency,
                json.dumps(payload),
                _STATUS_OPEN,
                dedup_key,
                now,
                expires_at,
            ),
        )
        logger.info(
            "[ambient_signals] ingested %s kind=%s source=%s urgency=%.2f",
            sid,
            kind,
            source,
            urgency,
        )
        return sid

    async def list_open(
        self,
        company_id: str | None = None,
        min_urgency: float = 0.0,
        limit: int = 20,
    ) -> list[AmbientSignal]:
        cid = company_id or current_company_id()
        rows = await self._db.execute(
            "SELECT * FROM ambient_signals "
            "WHERE company_id = ? AND status = ? AND urgency >= ? "
            "ORDER BY urgency DESC, received_at DESC LIMIT ?",
            (cid, _STATUS_OPEN, float(min_urgency), int(limit)),
        )
        return [self._row_to_signal(r) for r in rows]

    async def get(self, signal_id: str) -> AmbientSignal | None:
        rows = await self._db.execute(
            "SELECT * FROM ambient_signals WHERE signal_id = ?",
            (signal_id,),
        )
        return self._row_to_signal(rows[0]) if rows else None

    async def consume(self, signal_id: str) -> bool:
        now = datetime.now(UTC).isoformat()
        rows = await self._db.execute(
            "SELECT signal_id FROM ambient_signals "
            "WHERE signal_id = ? AND status = ?",
            (signal_id, _STATUS_OPEN),
        )
        if not rows:
            return False
        await self._db.execute_insert(
            "UPDATE ambient_signals SET status = ?, consumed_at = ? "
            "WHERE signal_id = ?",
            (_STATUS_CONSUMED, now, signal_id),
        )
        return True

    async def suppress(self, signal_id: str) -> bool:
        rows = await self._db.execute(
            "SELECT signal_id FROM ambient_signals WHERE signal_id = ?",
            (signal_id,),
        )
        if not rows:
            return False
        await self._db.execute_insert(
            "UPDATE ambient_signals SET status = ? WHERE signal_id = ?",
            (_STATUS_SUPPRESSED, signal_id),
        )
        return True

    async def expire_due(self, *, now: datetime | None = None) -> int:
        """Mark open signals past expires_at as expired. Returns count."""
        now_iso = (now or datetime.now(UTC)).isoformat()
        rows = await self._db.execute(
            "SELECT signal_id FROM ambient_signals "
            "WHERE status = ? AND expires_at IS NOT NULL AND expires_at <= ?",
            (_STATUS_OPEN, now_iso),
        )
        if not rows:
            return 0
        ids = [r["signal_id"] for r in rows]
        for sid in ids:
            await self._db.execute_insert(
                "UPDATE ambient_signals SET status = ? WHERE signal_id = ?",
                (_STATUS_EXPIRED, sid),
            )
        logger.info("[ambient_signals] expired %d signal(s)", len(ids))
        return len(ids)

    @staticmethod
    def _row_to_signal(row: Any) -> AmbientSignal:
        raw = row["payload_json"] or "{}"
        try:
            payload = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except (json.JSONDecodeError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return AmbientSignal(
            signal_id=row["signal_id"],
            company_id=row["company_id"],
            household_id=row["household_id"],
            kind=row["kind"],
            source=row["source"],
            subject_ref=row["subject_ref"],
            urgency=float(row["urgency"] or 0.0),
            payload=payload,
            status=row["status"] or _STATUS_OPEN,
            dedup_key=row["dedup_key"],
            received_at=row["received_at"] or "",
            expires_at=row["expires_at"],
            consumed_at=row["consumed_at"],
        )
