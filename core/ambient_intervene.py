"""Ambient interventions — propose → decide → execute with receipts.

act/escalate never auto-approve; they stay proposed until an explicit
operator decision. daily_proposal_count supports the silence cap.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from core.ambient_signals import AmbientSignal
from core.company import current_company_id
from core.database import Database

logger = logging.getLogger(__name__)

STRENGTH_OBSERVE = "observe"
STRENGTH_NUDGE = "nudge"
STRENGTH_ACT = "act"
STRENGTH_ESCALATE = "escalate"
_VALID_STRENGTHS = frozenset(
    {STRENGTH_OBSERVE, STRENGTH_NUDGE, STRENGTH_ACT, STRENGTH_ESCALATE}
)
_AUTO_APPROVE_FORBIDDEN = frozenset({STRENGTH_ACT, STRENGTH_ESCALATE})

STATUS_PROPOSED = "proposed"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"
STATUS_EXECUTED = "executed"
STATUS_EXPIRED = "expired"
STATUS_KILLED = "killed"
_VALID_STATUSES = frozenset(
    {
        STATUS_PROPOSED,
        STATUS_APPROVED,
        STATUS_DENIED,
        STATUS_EXECUTED,
        STATUS_EXPIRED,
        STATUS_KILLED,
    }
)
_DECISIONS = frozenset({"approved", "denied"})


@dataclass
class Intervention:
    intervention_id: str
    company_id: str
    strength: str
    channel: str
    proposal: dict[str, Any]
    status: str = STATUS_PROPOSED
    household_id: str | None = None
    prediction_id: str | None = None
    signal_id: str | None = None
    person_id: str | None = None
    receipt: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    decided_at: str | None = None
    executed_at: str | None = None


class InterventionManager:
    """Propose/decide/execute lifecycle for ambient interventions."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def propose_from_prediction(
        self,
        prediction: Any,
        *,
        strength: str = STRENGTH_NUDGE,
        channel: str = "chat",
        proposal: dict[str, Any],
    ) -> Intervention:
        strength = self._validate_strength(strength)
        pred = self._as_mapping(prediction)
        return await self._insert(
            company_id=str(pred.get("company_id") or current_company_id()),
            household_id=pred.get("household_id"),
            prediction_id=pred.get("prediction_id"),
            signal_id=None,
            person_id=pred.get("person_id"),
            strength=strength,
            channel=channel,
            proposal=proposal,
        )

    async def propose_from_signal(
        self,
        signal: AmbientSignal | Any,
        *,
        strength: str = STRENGTH_NUDGE,
        channel: str = "chat",
        proposal: dict[str, Any],
    ) -> Intervention:
        strength = self._validate_strength(strength)
        if isinstance(signal, AmbientSignal):
            company_id = signal.company_id
            household_id = signal.household_id
            signal_id = signal.signal_id
            person_id = signal.subject_ref
        else:
            m = self._as_mapping(signal)
            company_id = str(m.get("company_id") or current_company_id())
            household_id = m.get("household_id")
            signal_id = m.get("signal_id")
            person_id = m.get("subject_ref") or m.get("person_id")
        return await self._insert(
            company_id=company_id,
            household_id=household_id,
            prediction_id=None,
            signal_id=signal_id,
            person_id=person_id,
            strength=strength,
            channel=channel,
            proposal=proposal,
        )

    async def list_by_status(
        self,
        status: str,
        limit: int = 50,
        *,
        company_id: str | None = None,
    ) -> list[Intervention]:
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"invalid intervention status {status!r}; "
                f"must be one of {sorted(_VALID_STATUSES)}"
            )
        cid = company_id or current_company_id()
        rows = await self._db.execute(
            "SELECT * FROM ambient_interventions "
            "WHERE company_id = ? AND status = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (cid, status, int(limit)),
        )
        return [self._row_to_intervention(r) for r in rows]

    async def decide(
        self,
        intervention_id: str,
        decision: str,
        receipt: dict[str, Any],
    ) -> Intervention | None:
        """Operator approve|deny. act/escalate cannot be auto-approved.

        Callers must pass an explicit operator decision; this method never
        soft-approves on timeout for act/escalate.
        """
        if decision not in _DECISIONS:
            raise ValueError(f"invalid decision {decision!r}; must be approved|denied")
        row = await self._get_row(intervention_id)
        if not row:
            return None
        strength = row["strength"]
        if decision == "approved" and strength in _AUTO_APPROVE_FORBIDDEN:
            # Explicit operator path only — still allowed when decide() is
            # called with decision='approved', but receipt must record who.
            if not receipt.get("operator") and not receipt.get("approval_id"):
                raise ValueError(
                    f"strength={strength} requires operator or approval_id "
                    "in receipt; never auto-approve"
                )

        now = datetime.now(UTC).isoformat()
        new_status = STATUS_APPROVED if decision == "approved" else STATUS_DENIED
        merged = self._merge_receipt(row["receipt_json"], receipt)
        merged["decision"] = decision
        await self._db.execute_insert(
            "UPDATE ambient_interventions SET status = ?, receipt_json = ?, "
            "decided_at = ? WHERE intervention_id = ?",
            (new_status, json.dumps(merged), now, intervention_id),
        )
        logger.info(
            "[ambient_intervene] %s decision=%s strength=%s",
            intervention_id,
            decision,
            strength,
        )
        return await self.get(intervention_id)

    async def mark_executed(
        self,
        intervention_id: str,
        receipt: dict[str, Any],
    ) -> Intervention | None:
        row = await self._get_row(intervention_id)
        if not row:
            return None
        strength = row["strength"]
        status = row["status"]
        if status not in (STATUS_APPROVED, STATUS_PROPOSED):
            raise ValueError(f"cannot execute intervention in status={status!r}")
        # act/escalate must be explicitly approved with operator receipt first.
        if strength in _AUTO_APPROVE_FORBIDDEN:
            if status != STATUS_APPROVED:
                raise ValueError(
                    f"strength={strength} requires prior operator approval; "
                    "never soft-execute from proposed"
                )
            if not receipt.get("operator") and not receipt.get("approval_id"):
                raise ValueError(
                    f"strength={strength} requires operator or approval_id "
                    "in execute receipt"
                )
        now = datetime.now(UTC).isoformat()
        merged = self._merge_receipt(row["receipt_json"], receipt)
        await self._db.execute_insert(
            "UPDATE ambient_interventions SET status = ?, receipt_json = ?, "
            "executed_at = ? WHERE intervention_id = ?",
            (STATUS_EXECUTED, json.dumps(merged), now, intervention_id),
        )
        return await self.get(intervention_id)

    async def mark_killed(self, intervention_id: str) -> Intervention | None:
        row = await self._get_row(intervention_id)
        if not row:
            return None
        now = datetime.now(UTC).isoformat()
        merged = self._merge_receipt(
            row["receipt_json"], {"killed_at": now, "reason": "kill_switch"}
        )
        await self._db.execute_insert(
            "UPDATE ambient_interventions SET status = ?, receipt_json = ?, "
            "decided_at = COALESCE(decided_at, ?) WHERE intervention_id = ?",
            (STATUS_KILLED, json.dumps(merged), now, intervention_id),
        )
        logger.info("[ambient_intervene] killed %s", intervention_id)
        return await self.get(intervention_id)

    async def daily_proposal_count(
        self,
        company_id: str | None = None,
        day_iso: str | None = None,
        *,
        timezone: str | None = None,
    ) -> int:
        """Count proposals for the local calendar day (silence cap).

        Uses ``ELOPHANTO_HOUSEHOLD_TZ`` / ``TZ`` / UTC when timezone is
        omitted. Compares against UTC ``created_at`` via local midnight
        bounds so US timezones don't reset the cap mid-afternoon.
        """
        import os
        from zoneinfo import ZoneInfo

        cid = company_id or current_company_id()
        if day_iso:
            # Legacy: treat day_iso as a UTC date prefix (tests may pass this).
            rows = await self._db.execute(
                "SELECT COUNT(*) AS n FROM ambient_interventions "
                "WHERE company_id = ? AND created_at LIKE ?",
                (cid, f"{day_iso[:10]}%"),
            )
        else:
            tz_name = timezone
            if not tz_name:
                try:
                    hh_rows = await self._db.execute(
                        "SELECT timezone FROM households WHERE company_id = ? "
                        "ORDER BY created_at ASC LIMIT 1",
                        (cid,),
                    )
                    if hh_rows and hh_rows[0]["timezone"]:
                        tz_name = str(hh_rows[0]["timezone"])
                except Exception:
                    tz_name = None
            tz_name = (
                tz_name
                or os.environ.get("ELOPHANTO_HOUSEHOLD_TZ")
                or os.environ.get("TZ")
                or "UTC"
            )
            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                tz = ZoneInfo("UTC")
            local_now = datetime.now(tz)
            start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_local = start_local + timedelta(days=1)
            start_utc = start_local.astimezone(UTC).isoformat()
            end_utc = end_local.astimezone(UTC).isoformat()
            rows = await self._db.execute(
                "SELECT COUNT(*) AS n FROM ambient_interventions "
                "WHERE company_id = ? AND created_at >= ? AND created_at < ?",
                (cid, start_utc, end_utc),
            )
        if not rows:
            return 0
        return int(rows[0]["n"] or 0)

    async def propose(
        self,
        *,
        strength: str,
        channel: str,
        proposal: dict[str, Any],
        company_id: str | None = None,
        household_id: str | None = None,
        prediction_id: str | None = None,
        signal_id: str | None = None,
        person_id: str | None = None,
    ) -> Intervention:
        """Generic propose entry used by tests and tools."""
        strength = self._validate_strength(strength)
        return await self._insert(
            company_id=company_id or current_company_id(),
            household_id=household_id,
            prediction_id=prediction_id,
            signal_id=signal_id,
            person_id=person_id,
            strength=strength,
            channel=channel,
            proposal=proposal,
        )

    async def has_intervention_for_prediction(
        self,
        prediction_id: str,
        *,
        company_id: str | None = None,
    ) -> bool:
        """True if any ledger row already covers this prediction (any status)."""
        if not prediction_id:
            return False
        cid = company_id or current_company_id()
        rows = await self._db.execute(
            "SELECT intervention_id FROM ambient_interventions "
            "WHERE company_id = ? AND prediction_id = ? LIMIT 1",
            (cid, prediction_id),
        )
        return bool(rows)

    async def get(self, intervention_id: str) -> Intervention | None:
        row = await self._get_row(intervention_id)
        return self._row_to_intervention(row) if row else None

    def may_auto_approve(self, strength: str) -> bool:
        """False for act/escalate — callers must not soft-approve those."""
        return strength not in _AUTO_APPROVE_FORBIDDEN

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _insert(
        self,
        *,
        company_id: str,
        household_id: str | None,
        prediction_id: str | None,
        signal_id: str | None,
        person_id: str | None,
        strength: str,
        channel: str,
        proposal: dict[str, Any],
    ) -> Intervention:
        iid = f"int_{uuid.uuid4().hex[:16]}"
        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            "INSERT INTO ambient_interventions "
            "(intervention_id, company_id, household_id, prediction_id, "
            "signal_id, person_id, strength, channel, proposal_json, status, "
            "receipt_json, created_at, decided_at, executed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, NULL, NULL)",
            (
                iid,
                company_id,
                household_id,
                prediction_id,
                signal_id,
                person_id,
                strength,
                channel,
                json.dumps(proposal or {}),
                STATUS_PROPOSED,
                now,
            ),
        )
        logger.info(
            "[ambient_intervene] proposed %s strength=%s channel=%s",
            iid,
            strength,
            channel,
        )
        return Intervention(
            intervention_id=iid,
            company_id=company_id,
            household_id=household_id,
            prediction_id=prediction_id,
            signal_id=signal_id,
            person_id=person_id,
            strength=strength,
            channel=channel,
            proposal=dict(proposal or {}),
            status=STATUS_PROPOSED,
            receipt={},
            created_at=now,
        )

    async def _get_row(self, intervention_id: str) -> Any | None:
        rows = await self._db.execute(
            "SELECT * FROM ambient_interventions WHERE intervention_id = ?",
            (intervention_id,),
        )
        return rows[0] if rows else None

    @staticmethod
    def _validate_strength(strength: str) -> str:
        if strength not in _VALID_STRENGTHS:
            raise ValueError(
                f"invalid strength {strength!r}; "
                f"must be one of {sorted(_VALID_STRENGTHS)}"
            )
        return strength

    @staticmethod
    def _as_mapping(obj: Any) -> dict[str, Any]:
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "__dataclass_fields__"):
            return {
                k: getattr(obj, k)
                for k in obj.__dataclass_fields__  # type: ignore[attr-defined]
            }
        # sqlite Row / attribute bag
        out: dict[str, Any] = {}
        for key in (
            "company_id",
            "household_id",
            "prediction_id",
            "signal_id",
            "person_id",
            "subject_ref",
        ):
            if hasattr(obj, key):
                out[key] = getattr(obj, key)
            elif hasattr(obj, "__getitem__"):
                try:
                    out[key] = obj[key]
                except (KeyError, IndexError, TypeError):
                    pass
        return out

    @staticmethod
    def _merge_receipt(existing_raw: Any, update: dict[str, Any]) -> dict[str, Any]:
        try:
            base = (
                json.loads(existing_raw or "{}")
                if isinstance(existing_raw, str)
                else dict(existing_raw or {})
            )
        except (json.JSONDecodeError, TypeError):
            base = {}
        if not isinstance(base, dict):
            base = {}
        base.update(update or {})
        return base

    @staticmethod
    def _row_to_intervention(row: Any) -> Intervention:
        try:
            proposal = json.loads(row["proposal_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            proposal = {}
        if not isinstance(proposal, dict):
            proposal = {}
        try:
            receipt = json.loads(row["receipt_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            receipt = {}
        if not isinstance(receipt, dict):
            receipt = {}
        return Intervention(
            intervention_id=row["intervention_id"],
            company_id=row["company_id"],
            household_id=row["household_id"],
            prediction_id=row["prediction_id"],
            signal_id=row["signal_id"],
            person_id=row["person_id"],
            strength=row["strength"],
            channel=row["channel"],
            proposal=proposal,
            status=row["status"] or STATUS_PROPOSED,
            receipt=receipt,
            created_at=row["created_at"] or "",
            decided_at=row["decided_at"],
            executed_at=row["executed_at"],
        )
