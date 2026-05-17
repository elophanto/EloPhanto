"""Dream journal — persistent log of goal_dream output.

The autonomous mind's dream phase had a convergence problem: every
cycle proposed roughly the same ideas ("paid automation lead list",
"newsletter SaaS", etc.). Root cause was **amnesia** — the dream
prompt saw recently *completed* goals but never recently *proposed*
ones. So day-3's dream cheerfully re-proposed day-1's ideas, scored
them the same, and recommended the same one.

This module persists every dream output and lets the next dream call
read recent history. The dream prompt receives a "PREVIOUSLY PROPOSED"
block when ≥3 prior dreams exist (cold-start cycles see nothing, by
design — pinning yourself to an empty history isn't useful).

The data is also useful for post-hoc analysis: how often does dream
converge? Which ideas keep coming back? Did the operator's chosen
goals correlate with high-scored or low-scored candidates?

Pure persistence — no LLM call, no decision logic. The journal is the
substrate; ``tools/goals/dream_tool.py`` is the consumer.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DreamEntry:
    """One persisted dream cycle. ``candidates`` is the raw list as
    returned by the LLM (each candidate is a dict with title /
    description / scores). ``recommendation`` is the LLM's chosen
    index + reasoning."""

    id: int
    focus: str
    candidates: list[dict[str, Any]]
    recommendation: dict[str, Any]
    chosen_goal_id: str | None
    created_at: str


class DreamJournal:
    """Thin SQLite wrapper for the ``dream_journal`` table.

    Single responsibility: persist + recall. Does not interpret
    candidates, does not score, does not dedupe — that lives in the
    dream tool. Keeping this layer dumb makes it easy to test and
    easy to swap (e.g. for an embedding-based recall in v2).
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    async def record(
        self,
        focus: str,
        candidates: list[dict[str, Any]],
        recommendation: dict[str, Any],
    ) -> int:
        """Persist one dream output. Returns the row id so the caller
        can link a subsequent ``goal_create`` back to the dream that
        spawned it (via ``set_chosen_goal``)."""
        now = datetime.now(UTC).isoformat()
        row_id = await self._db.execute_insert(
            "INSERT INTO dream_journal "
            "(focus, candidates_json, recommendation_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            (focus, json.dumps(candidates), json.dumps(recommendation), now),
        )
        return int(row_id)

    async def set_chosen_goal(self, dream_id: int, goal_id: str) -> None:
        """Link a created goal back to its originating dream. Lets
        post-hoc analysis answer 'which dreams led to actual goals
        vs. which were ignored'."""
        await self._db.execute(
            "UPDATE dream_journal SET chosen_goal_id = ? WHERE id = ?",
            (goal_id, dream_id),
        )

    async def recent(self, limit: int = 10) -> list[DreamEntry]:
        """Return the most recent ``limit`` dreams, newest first.

        The dream tool uses this to inject a 'PREVIOUSLY PROPOSED'
        block. Limit defaults to 10 because the LLM's working memory
        for context blocks degrades past that; if you raise it,
        consider also truncating each entry's candidate descriptions.
        """
        rows = await self._db.execute(
            "SELECT id, focus, candidates_json, recommendation_json, "
            "chosen_goal_id, created_at "
            "FROM dream_journal ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        out: list[DreamEntry] = []
        for r in rows:
            try:
                candidates = json.loads(r["candidates_json"] or "[]")
            except (json.JSONDecodeError, TypeError):
                candidates = []
            try:
                rec = json.loads(r["recommendation_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                rec = {}
            out.append(
                DreamEntry(
                    id=int(r["id"]),
                    focus=str(r["focus"] or "balanced"),
                    candidates=candidates,
                    recommendation=rec,
                    chosen_goal_id=r["chosen_goal_id"],
                    created_at=str(r["created_at"]),
                )
            )
        return out

    async def count(self) -> int:
        """Total dreams persisted. Used by the tool to decide whether
        to inject the 'PREVIOUSLY PROPOSED' block at all — cold start
        with <3 entries skips it (showing one stale dream isn't
        useful pressure against repetition)."""
        rows = await self._db.execute("SELECT COUNT(*) AS n FROM dream_journal", ())
        if not rows:
            return 0
        return int(rows[0]["n"] or 0)
