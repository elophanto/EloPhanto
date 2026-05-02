"""TrustLedger — per-agent registry of peers we've seen.

Built on the ``known_agents`` table. Implements SSH-known-hosts semantics:

- First time we see ``(agent_id, public_key)``: insert with ``trust_level='tofu'``.
- Same ``agent_id`` shows up again with the **same** public_key: bump
  ``last_seen`` + ``connection_count``. No surprise.
- Same ``agent_id`` shows up with a **different** public_key: refuse the
  connection and surface a conflict the owner has to resolve manually
  (``agent_trust_set --force`` to overwrite, or block).
- Owner can promote ``tofu → verified`` after manual review, or
  ``verified → blocked`` if the agent misbehaves.

The ledger does NOT control whether unverified peers can connect at
all — that's a config/gateway decision. It records what we've seen and
classifies it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.agent_identity import (
    TRUST_BLOCKED,
    TRUST_TOFU,
    TRUST_VERIFIED,
)

if TYPE_CHECKING:
    from core.database import Database

logger = logging.getLogger(__name__)


# Valid trust levels for owner-settable values. TRUST_UNKNOWN is a
# pre-handshake state, never persisted.
_OWNER_SETTABLE_LEVELS = {TRUST_BLOCKED, TRUST_TOFU, TRUST_VERIFIED}


class TrustConflict(Exception):
    """Raised when a peer claims an agent_id we know with a different key.

    The connection MUST be refused. Caller should surface the conflict so
    the owner can decide: rotate (peer regenerated key — accept), block
    (someone is impersonating), or investigate."""

    def __init__(
        self,
        agent_id: str,
        seen_public_key: str,
        claimed_public_key: str,
    ) -> None:
        self.agent_id = agent_id
        self.seen_public_key = seen_public_key
        self.claimed_public_key = claimed_public_key
        super().__init__(
            f"agent_id {agent_id!r} reappeared with a different public key; "
            "key rotation or impersonation"
        )


@dataclass
class KnownAgent:
    """A row in the trust ledger."""

    agent_id: str
    public_key: str
    trust_level: str = TRUST_TOFU
    first_seen: str = ""
    last_seen: str = ""
    connection_count: int = 1
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_blocked(self) -> bool:
        return self.trust_level == TRUST_BLOCKED

    @property
    def is_verified(self) -> bool:
        """Owner-confirmed (the strongest level). Distinct from TOFU."""
        return self.trust_level == TRUST_VERIFIED


class TrustLedger:
    """Read-write access to the ``known_agents`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    async def get(self, agent_id: str) -> KnownAgent | None:
        rows = await self._db.execute(
            "SELECT * FROM known_agents WHERE agent_id = ?", (agent_id,)
        )
        if not rows:
            return None
        return self._row_to_known(rows[0])

    async def list_all(self, *, include_blocked: bool = True) -> list[KnownAgent]:
        if include_blocked:
            rows = await self._db.execute(
                "SELECT * FROM known_agents ORDER BY last_seen DESC"
            )
        else:
            rows = await self._db.execute(
                "SELECT * FROM known_agents WHERE trust_level != ? "
                "ORDER BY last_seen DESC",
                (TRUST_BLOCKED,),
            )
        return [self._row_to_known(r) for r in rows]

    # ------------------------------------------------------------------
    # Upsert — the core SSH-known-hosts logic
    # ------------------------------------------------------------------

    async def record_handshake(
        self,
        agent_id: str,
        public_key: str,
        *,
        force_overwrite: bool = False,
    ) -> KnownAgent:
        """Record a peer we just shook hands with.

        Returns the resulting ledger entry. Raises ``TrustConflict`` if
        the same ``agent_id`` is already known with a different
        ``public_key`` and ``force_overwrite=False``.

        ``force_overwrite=True`` is the manual escape hatch — used by
        ``agent_trust_set --rotate`` after the owner has confirmed the
        peer legitimately rotated keys.
        """
        existing = await self.get(agent_id)
        now = datetime.now(UTC).isoformat()

        if existing is None:
            # First contact — TOFU.
            entry = KnownAgent(
                agent_id=agent_id,
                public_key=public_key,
                trust_level=TRUST_TOFU,
                first_seen=now,
                last_seen=now,
                connection_count=1,
            )
            await self._persist(entry, is_insert=True)
            logger.info("Trust ledger: new peer %s recorded as TOFU", agent_id)
            return entry

        if existing.is_blocked:
            # Refuse silently — the gateway should never have called us
            # for a blocked peer, but be defensive. Don't bump counters.
            logger.warning("Trust ledger: blocked peer %s tried to connect", agent_id)
            return existing

        if existing.public_key != public_key:
            if not force_overwrite:
                raise TrustConflict(
                    agent_id=agent_id,
                    seen_public_key=existing.public_key,
                    claimed_public_key=public_key,
                )
            # Owner-confirmed rotation — overwrite the key, keep first_seen,
            # demote to TOFU so the owner re-confirms next time.
            existing.public_key = public_key
            existing.trust_level = TRUST_TOFU
            existing.last_seen = now
            existing.connection_count += 1
            await self._persist(existing, is_insert=False)
            logger.warning(
                "Trust ledger: peer %s key rotated (force_overwrite); "
                "demoted to TOFU until re-verified",
                agent_id,
            )
            return existing

        # Same key — bump counters.
        existing.last_seen = now
        existing.connection_count += 1
        await self._persist(existing, is_insert=False)
        return existing

    async def set_trust_level(
        self, agent_id: str, level: str, notes: str = ""
    ) -> KnownAgent:
        """Owner-driven trust level change. ``level`` must be one of
        ``blocked``, ``tofu``, ``verified``."""
        if level not in _OWNER_SETTABLE_LEVELS:
            raise ValueError(
                f"Invalid trust level {level!r}. Must be one of {_OWNER_SETTABLE_LEVELS}"
            )
        existing = await self.get(agent_id)
        if existing is None:
            raise KeyError(f"No known agent {agent_id!r}")
        existing.trust_level = level
        if notes:
            existing.notes = notes
        await self._persist(existing, is_insert=False)
        logger.info(
            "Trust ledger: agent %s set to %s%s",
            agent_id,
            level,
            f" — {notes}" if notes else "",
        )
        return existing

    async def remove(self, agent_id: str) -> bool:
        """Drop a peer from the ledger entirely. They'll re-enter as TOFU
        on next connection. Returns True if a row was removed."""
        existing = await self.get(agent_id)
        if existing is None:
            return False
        await self._db.execute_insert(
            "DELETE FROM known_agents WHERE agent_id = ?", (agent_id,)
        )
        return True

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _persist(self, entry: KnownAgent, *, is_insert: bool) -> None:
        if is_insert:
            await self._db.execute_insert(
                """INSERT INTO known_agents
                   (agent_id, public_key, trust_level, first_seen, last_seen,
                    connection_count, notes, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.agent_id,
                    entry.public_key,
                    entry.trust_level,
                    entry.first_seen,
                    entry.last_seen,
                    entry.connection_count,
                    entry.notes,
                    json.dumps(entry.metadata),
                ),
            )
        else:
            await self._db.execute_insert(
                """UPDATE known_agents
                   SET public_key = ?,
                       trust_level = ?,
                       last_seen = ?,
                       connection_count = ?,
                       notes = ?,
                       metadata_json = ?
                   WHERE agent_id = ?""",
                (
                    entry.public_key,
                    entry.trust_level,
                    entry.last_seen,
                    entry.connection_count,
                    entry.notes,
                    json.dumps(entry.metadata),
                    entry.agent_id,
                ),
            )

    @staticmethod
    def _row_to_known(row: Any) -> KnownAgent:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        return KnownAgent(
            agent_id=row["agent_id"],
            public_key=row["public_key"],
            trust_level=row["trust_level"] or TRUST_TOFU,
            first_seen=row["first_seen"] or "",
            last_seen=row["last_seen"] or "",
            connection_count=int(row["connection_count"] or 0),
            notes=row["notes"] or "",
            metadata=metadata,
        )
