"""Mission manager — durable drives the autonomous mind works toward.

A mission is a long-running drive (promote alphascala, grow EloPhanto,
recover $ELO position, develop capabilities). Missions are NEVER
"completed"; the operator pauses or retires them. Goals roll under
missions via ``goals.mission_id``; finishing a goal updates the
mission's momentum, doesn't close it.

See ``docs/75-AUTONOMOUS-MIND-V2.md`` §Phase 2 for the design.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core.company import ALL_COMPANIES, current_company_id
from core.database import Database

logger = logging.getLogger(__name__)


# Status constants — kept as a small enum-like surface so callers
# can reference symbolic names instead of stringly-typed literals.
STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"
STATUS_RETIRED = "retired"
_VALID_STATUSES = frozenset({STATUS_ACTIVE, STATUS_PAUSED, STATUS_RETIRED})

# Momentum decays toward 0 over time so a mission that was hot last
# week but hasn't been touched stops dominating the candidate scorer.
# Half-life chosen so a freshly-touched mission still contributes
# ~50% of its momentum after ~7 days.
_MOMENTUM_HALF_LIFE_DAYS = 7.0
# Per-touch bump. A completed goal under the mission moves it by
# this much before decay; tunable from config later if needed.
_TOUCH_BUMP_DEFAULT = 1.0
# Staleness is the inverse of recency: how long since the mission
# was last touched. The scorer uses it to bias toward neglected
# high-weight missions.
_FRESH_HOURS = 24.0


@dataclass
class Mission:
    mission_id: str
    title: str
    description: str
    status: str
    priority_weight: float
    momentum_score: float
    last_touched_at: str | None
    created_at: str
    updated_at: str
    # ABE Phase 2 (docs/76-ABE-FRAMEWORK.md). Optional role that owns
    # the mandate (e.g. owner_role='sales' for "grow pipeline to 50/wk").
    # None = CEO/EloPhanto owns it directly. The autonomous mind's
    # arbiter biases candidates of role X toward missions with the
    # matching owner_role.
    owner_role: str | None = None
    # ABE Phase 12 (Tier 1 #1, 2026-06-18). Company this mission
    # belongs to. Stamped from the contextvar at INSERT time; pre-
    # migration rows default to 'elophanto-self' via the schema.
    company_id: str = "elophanto-self"

    def staleness_hours(self, now: datetime | None = None) -> float:
        """How many hours since this mission was last touched.

        Returns +inf if never touched — encodes "this needs attention
        first" as a hard maximum staleness rather than a magic sentinel.
        """
        if not self.last_touched_at:
            return float("inf")
        now = now or datetime.now(UTC)
        try:
            t = datetime.fromisoformat(self.last_touched_at)
        except ValueError:
            return float("inf")
        return max(0.0, (now - t).total_seconds() / 3600.0)

    def decayed_momentum(self, now: datetime | None = None) -> float:
        """Momentum after exponential time-decay.

        A mission that scored 3.0 a week ago contributes ~1.5 today.
        Pure read-side calculation — does NOT mutate the stored
        ``momentum_score``. Persisted momentum is updated only by
        ``MissionManager.touch``.
        """
        if not self.last_touched_at or self.momentum_score == 0.0:
            return self.momentum_score
        now = now or datetime.now(UTC)
        try:
            t = datetime.fromisoformat(self.last_touched_at)
        except ValueError:
            return self.momentum_score
        days = max(0.0, (now - t).total_seconds() / 86400.0)
        half_lives = days / _MOMENTUM_HALF_LIFE_DAYS
        return self.momentum_score * (0.5**half_lives)


class MissionManager:
    """CRUD + momentum bookkeeping for missions."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create(
        self,
        title: str,
        description: str = "",
        priority_weight: float = 1.0,
        *,
        mission_id: str | None = None,
        owner_role: str | None = None,
    ) -> Mission:
        """Create a mission. ``mission_id`` is optional — supply a
        stable slug (e.g. ``alphascala-launch``) so seeds and config
        files can reference missions by name, fall back to a uuid for
        ad-hoc missions. ``owner_role`` (ABE Phase 2) optionally
        attaches the mission to a role persona; null = CEO.

        Company is stamped from the contextvar at INSERT time. Before
        Tier 1 #1 (2026-06-18) this relied on the schema DEFAULT,
        which silently routed every create into 'elophanto-self'
        regardless of operator's active company.
        """
        mid = mission_id or f"m_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC).isoformat()
        company_id = current_company_id()
        await self._db.execute_insert(
            "INSERT INTO missions "
            "(mission_id, title, description, status, priority_weight, "
            "momentum_score, last_touched_at, created_at, updated_at, "
            "owner_role, company_id) "
            "VALUES (?, ?, ?, ?, ?, 0.0, NULL, ?, ?, ?, ?)",
            (
                mid,
                title,
                description,
                STATUS_ACTIVE,
                priority_weight,
                now,
                now,
                owner_role,
                company_id,
            ),
        )
        return Mission(
            mission_id=mid,
            title=title,
            description=description,
            status=STATUS_ACTIVE,
            priority_weight=priority_weight,
            momentum_score=0.0,
            last_touched_at=None,
            created_at=now,
            updated_at=now,
            owner_role=owner_role,
            company_id=company_id,
        )

    async def get(
        self, mission_id: str, *, company_id: str | None = None
    ) -> Mission | None:
        """Fetch a mission by id.

        Defaults to the contextvar company — passing a known
        mission_id from another tenant returns None instead of
        leaking the row. Pass ``company_id=ALL_COMPANIES`` to bypass
        the filter (admin / diagnostics only).
        """
        scope = current_company_id() if company_id is None else company_id
        if scope == ALL_COMPANIES:
            rows = await self._db.execute(
                "SELECT * FROM missions WHERE mission_id = ?", (mission_id,)
            )
        else:
            rows = await self._db.execute(
                "SELECT * FROM missions WHERE mission_id = ? AND company_id = ?",
                (mission_id, scope),
            )
        return self._row_to_mission(rows[0]) if rows else None

    async def list_missions(
        self,
        status: str | None = STATUS_ACTIVE,
        limit: int = 100,
        *,
        company_id: str | None = None,
    ) -> list[Mission]:
        """List missions, optionally filtered by status. Default to
        active because that's the common case from the dream phase
        and CLI; pass ``status=None`` to list everything.

        Defaults to the contextvar company. Pass ``company_id=
        ALL_COMPANIES`` to list across every tenant (admin only).
        """
        scope = current_company_id() if company_id is None else company_id
        clauses: list[str] = []
        params: list[Any] = []
        if scope != ALL_COMPANIES:
            clauses.append("company_id = ?")
            params.append(scope)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where_sql = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        params.append(limit)
        rows = await self._db.execute(
            f"SELECT * FROM missions {where_sql}"
            "ORDER BY priority_weight DESC, updated_at DESC LIMIT ?",
            tuple(params),
        )
        return [self._row_to_mission(r) for r in rows]

    async def set_status(self, mission_id: str, status: str) -> bool:
        """Move a mission between active / paused / retired.

        Returns True if the mission exists. Unknown status values are
        rejected — there is no fourth state. ``retired`` is the
        soft-delete; rows are kept for goal history.
        """
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"invalid mission status {status!r}; must be one of {sorted(_VALID_STATUSES)}"
            )
        if not await self.get(mission_id):
            return False
        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            "UPDATE missions SET status = ?, updated_at = ? WHERE mission_id = ?",
            (status, now, mission_id),
        )
        return True

    async def update(
        self,
        mission_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        priority_weight: float | None = None,
    ) -> bool:
        """Partial update. Only fields explicitly passed are changed."""
        fields: list[str] = []
        values: list[Any] = []
        if title is not None:
            fields.append("title = ?")
            values.append(title)
        if description is not None:
            fields.append("description = ?")
            values.append(description)
        if priority_weight is not None:
            fields.append("priority_weight = ?")
            values.append(priority_weight)
        if not fields:
            return False
        if not await self.get(mission_id):
            return False
        fields.append("updated_at = ?")
        values.append(datetime.now(UTC).isoformat())
        values.append(mission_id)
        await self._db.execute_insert(
            f"UPDATE missions SET {', '.join(fields)} WHERE mission_id = ?",
            tuple(values),
        )
        return True

    # ------------------------------------------------------------------
    # Momentum
    # ------------------------------------------------------------------

    async def touch(
        self, mission_id: str, *, bump: float = _TOUCH_BUMP_DEFAULT
    ) -> Mission | None:
        """Record activity on a mission.

        Bumps ``momentum_score`` by ``bump`` and refreshes
        ``last_touched_at`` to now. Called from the goal-completion
        hook (see ``Agent._on_goal_completed``) and from the
        ``mission_touch`` tool when the mind explicitly logs a move
        toward a mission.

        The persisted momentum is a running total; read-side decay
        is applied via ``Mission.decayed_momentum``. Storing the raw
        sum is what lets the scorer compare missions consistently
        even when they were touched at different times.
        """
        if not await self.get(mission_id):
            return None
        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            "UPDATE missions SET "
            "momentum_score = momentum_score + ?, "
            "last_touched_at = ?, updated_at = ? "
            "WHERE mission_id = ?",
            (bump, now, now, mission_id),
        )
        return await self.get(mission_id)

    # ------------------------------------------------------------------
    # Helpers for the dream phase / arbiter
    # ------------------------------------------------------------------

    async def list_by_neglect(self, limit: int = 5) -> list[Mission]:
        """Active missions, ranked by ``priority_weight * staleness``.

        This is the function the dream phase calls when deciding
        which mission to suggest a new goal under. A high-weight
        mission that hasn't been touched in days outranks a
        low-weight mission that was touched an hour ago — that's
        the whole point of the missions tier.

        Note: returns ALL active missions sorted; ``limit`` caps the
        prompt size, not the candidate set.
        """
        active = await self.list_missions(status=STATUS_ACTIVE, limit=100)
        now = datetime.now(UTC)

        def score(m: Mission) -> float:
            stale_h = m.staleness_hours(now)
            # Cap staleness at 14 days when computing the score so a
            # never-touched mission doesn't permanently dominate
            # (the operator may have just seeded it and not had time
            # to act yet).
            stale_h = min(stale_h, 14.0 * 24.0)
            # Saturate below FRESH_HOURS — recently touched missions
            # don't get a neglect bonus.
            neglect = max(0.0, stale_h - _FRESH_HOURS) / 24.0
            return m.priority_weight * neglect

        active.sort(key=score, reverse=True)
        return active[:limit]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_mission(row: Any) -> Mission:
        # owner_role column is present only after the ABE Phase 2
        # migration ran. Defensive lookup so legacy test fixtures
        # that mock the row shape don't break.
        owner_role = row["owner_role"] if "owner_role" in row.keys() else None
        company_id = (
            row["company_id"] if "company_id" in row.keys() else "elophanto-self"
        )
        return Mission(
            mission_id=row["mission_id"],
            title=row["title"],
            description=row["description"],
            status=row["status"],
            priority_weight=float(row["priority_weight"]),
            momentum_score=float(row["momentum_score"]),
            last_touched_at=row["last_touched_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            owner_role=owner_role,
            company_id=company_id,
        )
