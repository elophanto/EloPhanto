"""Ambient life model — households, persons, places, routines.

Thin CRUD mirroring MissionManager. Scoped by company_id (+ household_id).
Adapters and predictors consume these entities; they are not a home OS.
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

STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"
STATUS_RETIRED = "retired"
_VALID_ROUTINE_STATUSES = frozenset({STATUS_ACTIVE, STATUS_PAUSED, STATUS_RETIRED})

ROLE_OPERATOR = "operator"


@dataclass
class Household:
    household_id: str
    company_id: str
    name: str
    timezone: str = "UTC"
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Person:
    person_id: str
    household_id: str
    company_id: str
    display_name: str
    role: str | None = None
    channel_refs: list[Any] = field(default_factory=list)
    consent: dict[str, Any] = field(default_factory=dict)
    prefs: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Place:
    place_id: str
    household_id: str
    company_id: str
    name: str
    kind: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass
class Routine:
    routine_id: str
    household_id: str
    company_id: str
    title: str
    person_id: str | None = None
    rrule: str | None = None
    window_start: str | None = None
    window_end: str | None = None
    place_id: str | None = None
    signal_kinds: list[str] = field(default_factory=list)
    status: str = STATUS_ACTIVE
    attrs: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class AmbientModelManager:
    """CRUD for households / persons / places / routines."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Households
    # ------------------------------------------------------------------

    async def create_household(
        self,
        name: str,
        *,
        household_id: str | None = None,
        timezone: str = "UTC",
        company_id: str | None = None,
    ) -> Household:
        hid = household_id or f"hh_{uuid.uuid4().hex[:12]}"
        cid = company_id or current_company_id()
        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            "INSERT INTO households "
            "(household_id, company_id, name, timezone, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (hid, cid, name, timezone, now, now),
        )
        return Household(
            household_id=hid,
            company_id=cid,
            name=name,
            timezone=timezone,
            created_at=now,
            updated_at=now,
        )

    async def get_household(self, household_id: str) -> Household | None:
        rows = await self._db.execute(
            "SELECT * FROM households WHERE household_id = ?",
            (household_id,),
        )
        return self._row_to_household(rows[0]) if rows else None

    async def get_primary_household(
        self, company_id: str | None = None
    ) -> Household | None:
        cid = company_id or current_company_id()
        rows = await self._db.execute(
            "SELECT * FROM households WHERE company_id = ? "
            "ORDER BY created_at ASC LIMIT 1",
            (cid,),
        )
        return self._row_to_household(rows[0]) if rows else None

    async def update_household_timezone(
        self, household_id: str, timezone: str
    ) -> Household | None:
        tz = (timezone or "").strip() or "UTC"
        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            "UPDATE households SET timezone = ?, updated_at = ? "
            "WHERE household_id = ?",
            (tz, now, household_id),
        )
        return await self.get_household(household_id)

    async def ensure_household_timezone(
        self,
        household_id: str,
        *,
        preferred: str | None = None,
    ) -> Household | None:
        """Sync env/preferred TZ onto household when missing or still UTC.

        If ``ELOPHANTO_HOUSEHOLD_TZ`` is set, always prefer it. Else if
        household is UTC and ``preferred``/``TZ`` is non-UTC, upgrade.
        """
        import os

        hh = await self.get_household(household_id)
        if hh is None:
            return None
        explicit = (os.environ.get("ELOPHANTO_HOUSEHOLD_TZ") or "").strip()
        fallback = (
            (preferred or "").strip() or (os.environ.get("TZ") or "").strip() or "UTC"
        )
        if explicit:
            target = explicit
        elif (hh.timezone or "UTC") == "UTC" and fallback != "UTC":
            target = fallback
        else:
            return hh
        if target == (hh.timezone or "UTC"):
            return hh
        return await self.update_household_timezone(household_id, target)

    # ------------------------------------------------------------------
    # Persons
    # ------------------------------------------------------------------

    async def create_person(
        self,
        household_id: str,
        display_name: str,
        *,
        person_id: str | None = None,
        role: str | None = None,
        company_id: str | None = None,
        channel_refs: list[Any] | None = None,
        consent: dict[str, Any] | None = None,
        prefs: dict[str, Any] | None = None,
    ) -> Person:
        pid = person_id or f"per_{uuid.uuid4().hex[:12]}"
        cid = company_id or current_company_id()
        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            "INSERT INTO persons "
            "(person_id, household_id, company_id, display_name, role, "
            "channel_refs_json, consent_json, prefs_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pid,
                household_id,
                cid,
                display_name,
                role,
                json.dumps(channel_refs or []),
                json.dumps(consent or {}),
                json.dumps(prefs or {}),
                now,
                now,
            ),
        )
        return Person(
            person_id=pid,
            household_id=household_id,
            company_id=cid,
            display_name=display_name,
            role=role,
            channel_refs=list(channel_refs or []),
            consent=dict(consent or {}),
            prefs=dict(prefs or {}),
            created_at=now,
            updated_at=now,
        )

    async def ensure_operator_person(
        self,
        household_id: str,
        display_name: str,
        *,
        company_id: str | None = None,
    ) -> Person:
        """Idempotent operator person for a household (role=operator)."""
        cid = company_id or current_company_id()
        rows = await self._db.execute(
            "SELECT * FROM persons "
            "WHERE household_id = ? AND company_id = ? AND role = ? "
            "LIMIT 1",
            (household_id, cid, ROLE_OPERATOR),
        )
        if rows:
            return self._row_to_person(rows[0])
        return await self.create_person(
            household_id,
            display_name,
            role=ROLE_OPERATOR,
            company_id=cid,
        )

    async def get_person(self, person_id: str) -> Person | None:
        rows = await self._db.execute(
            "SELECT * FROM persons WHERE person_id = ?",
            (person_id,),
        )
        return self._row_to_person(rows[0]) if rows else None

    async def list_persons(self, household_id: str) -> list[Person]:
        rows = await self._db.execute(
            "SELECT * FROM persons WHERE household_id = ? " "ORDER BY display_name ASC",
            (household_id,),
        )
        return [self._row_to_person(r) for r in rows]

    # ------------------------------------------------------------------
    # Places
    # ------------------------------------------------------------------

    async def create_place(
        self,
        household_id: str,
        name: str,
        *,
        place_id: str | None = None,
        kind: str | None = None,
        attrs: dict[str, Any] | None = None,
        company_id: str | None = None,
    ) -> Place:
        plid = place_id or f"plc_{uuid.uuid4().hex[:12]}"
        cid = company_id or current_company_id()
        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            "INSERT INTO places "
            "(place_id, household_id, company_id, name, kind, attrs_json, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (plid, household_id, cid, name, kind, json.dumps(attrs or {}), now),
        )
        return Place(
            place_id=plid,
            household_id=household_id,
            company_id=cid,
            name=name,
            kind=kind,
            attrs=dict(attrs or {}),
            created_at=now,
        )

    async def get_place(self, place_id: str) -> Place | None:
        rows = await self._db.execute(
            "SELECT * FROM places WHERE place_id = ?",
            (place_id,),
        )
        return self._row_to_place(rows[0]) if rows else None

    # ------------------------------------------------------------------
    # Routines
    # ------------------------------------------------------------------

    async def create_routine(
        self,
        household_id: str,
        title: str,
        *,
        routine_id: str | None = None,
        person_id: str | None = None,
        rrule: str | None = None,
        window_start: str | None = None,
        window_end: str | None = None,
        place_id: str | None = None,
        signal_kinds: list[str] | None = None,
        status: str = STATUS_ACTIVE,
        attrs: dict[str, Any] | None = None,
        company_id: str | None = None,
    ) -> Routine:
        if status not in _VALID_ROUTINE_STATUSES:
            raise ValueError(
                f"invalid routine status {status!r}; "
                f"must be one of {sorted(_VALID_ROUTINE_STATUSES)}"
            )
        rid = routine_id or f"rtn_{uuid.uuid4().hex[:12]}"
        cid = company_id or current_company_id()
        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            "INSERT INTO routines "
            "(routine_id, household_id, company_id, person_id, title, rrule, "
            "window_start, window_end, place_id, signal_kinds_json, status, "
            "attrs_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rid,
                household_id,
                cid,
                person_id,
                title,
                rrule,
                window_start,
                window_end,
                place_id,
                json.dumps(signal_kinds or []),
                status,
                json.dumps(attrs or {}),
                now,
                now,
            ),
        )
        return Routine(
            routine_id=rid,
            household_id=household_id,
            company_id=cid,
            title=title,
            person_id=person_id,
            rrule=rrule,
            window_start=window_start,
            window_end=window_end,
            place_id=place_id,
            signal_kinds=list(signal_kinds or []),
            status=status,
            attrs=dict(attrs or {}),
            created_at=now,
            updated_at=now,
        )

    async def list_routines(
        self,
        household_id: str,
        status: str | None = STATUS_ACTIVE,
        *,
        company_id: str | None = None,
        limit: int = 100,
    ) -> list[Routine]:
        cid = company_id or current_company_id()
        clauses = ["household_id = ?", "company_id = ?"]
        params: list[Any] = [household_id, cid]
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        params.append(int(limit))
        rows = await self._db.execute(
            f"SELECT * FROM routines WHERE {' AND '.join(clauses)} "
            "ORDER BY window_start ASC, title ASC LIMIT ?",
            tuple(params),
        )
        return [self._row_to_routine(r) for r in rows]

    async def list_active_routines(
        self,
        *,
        company_id: str | None = None,
        limit: int = 200,
    ) -> list[Routine]:
        cid = company_id or current_company_id()
        rows = await self._db.execute(
            "SELECT * FROM routines WHERE company_id = ? AND status = ? "
            "ORDER BY window_start ASC LIMIT ?",
            (cid, STATUS_ACTIVE, int(limit)),
        )
        return [self._row_to_routine(r) for r in rows]

    async def get_routine(self, routine_id: str) -> Routine | None:
        rows = await self._db.execute(
            "SELECT * FROM routines WHERE routine_id = ?",
            (routine_id,),
        )
        return self._row_to_routine(rows[0]) if rows else None

    async def set_routine_status(self, routine_id: str, status: str) -> Routine | None:
        if status not in _VALID_ROUTINE_STATUSES:
            raise ValueError(
                f"invalid routine status {status!r}; "
                f"must be one of {sorted(_VALID_ROUTINE_STATUSES)}"
            )
        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            "UPDATE routines SET status = ?, updated_at = ? WHERE routine_id = ?",
            (status, now, routine_id),
        )
        return await self.get_routine(routine_id)

    # ------------------------------------------------------------------
    # Row helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _loads_dict(raw: Any) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _loads_list(raw: Any) -> list[Any]:
        if not raw:
            return []
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return []
        return list(data) if isinstance(data, list) else []

    @classmethod
    def _row_to_household(cls, row: Any) -> Household:
        return Household(
            household_id=row["household_id"],
            company_id=row["company_id"],
            name=row["name"],
            timezone=row["timezone"] or "UTC",
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )

    @classmethod
    def _row_to_person(cls, row: Any) -> Person:
        return Person(
            person_id=row["person_id"],
            household_id=row["household_id"],
            company_id=row["company_id"],
            display_name=row["display_name"],
            role=row["role"],
            channel_refs=cls._loads_list(row["channel_refs_json"]),
            consent=cls._loads_dict(row["consent_json"]),
            prefs=cls._loads_dict(row["prefs_json"]),
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )

    @classmethod
    def _row_to_place(cls, row: Any) -> Place:
        return Place(
            place_id=row["place_id"],
            household_id=row["household_id"],
            company_id=row["company_id"],
            name=row["name"],
            kind=row["kind"],
            attrs=cls._loads_dict(row["attrs_json"]),
            created_at=row["created_at"] or "",
        )

    @classmethod
    def _row_to_routine(cls, row: Any) -> Routine:
        return Routine(
            routine_id=row["routine_id"],
            household_id=row["household_id"],
            company_id=row["company_id"],
            title=row["title"],
            person_id=row["person_id"],
            rrule=row["rrule"],
            window_start=row["window_start"],
            window_end=row["window_end"],
            place_id=row["place_id"],
            signal_kinds=[str(x) for x in cls._loads_list(row["signal_kinds_json"])],
            status=row["status"] or STATUS_ACTIVE,
            attrs=cls._loads_dict(row["attrs_json"]),
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )


# Back-compat alias used by agent wiring / tests
AmbientModel = AmbientModelManager
