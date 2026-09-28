"""Knowledge consolidation — keep the search index in step with the files.

Runs during autonomous mind maintenance.

The knowledge base is the markdown files under ``knowledge/``. The
``knowledge_chunks`` table (plus ``vec_chunks``) is a search index built from
them, and the indexer rebuilds it from disk at every startup. So this module
must never treat the index as the data. It used to: it capped the index at
500 chunks by age, pruned "stale" chunks by age alone (``last_accessed_at``
was never written, so every chunk older than 90 days qualified), and then
deleted every ``knowledge/learned/*.md`` file that no longer had chunks —
its own pruning had just orphaned them. The last recorded run capped 1,166
chunks and deleted 52 learned files from disk; ``knowledge/learned/`` is
gitignored, so they were unrecoverable (docs/94 F5).

What it does now:
  1. drop index rows whose source file no longer exists on disk;
  2. drop rows that exactly repeat another (same file, heading and content);
  3. delete the matching ``vec_chunks`` rows for everything it drops.
It never deletes files and never drops rows for files that still exist.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.database import Database

logger = logging.getLogger(__name__)

_CONSOLIDATION_INTERVAL_HOURS = 24
# Missing-file checks per run — bounded so one pass stays cheap.
_MAX_FILES_CHECKED = 5000


class KnowledgeConsolidator:
    """Keeps the knowledge search index consistent with the files on disk."""

    def __init__(self, db: Database, project_root: Path) -> None:
        self._db = db
        self._project_root = project_root

    async def should_run(self) -> bool:
        """Check if consolidation is needed (24+ hours since last run)."""
        try:
            rows = await self._db.execute(
                "SELECT value FROM metadata WHERE key = ?",
                ("last_consolidation",),
            )
            if not rows:
                return True
            last_run = datetime.fromisoformat(rows[0]["value"])
            elapsed = datetime.now(UTC) - last_run
            return elapsed >= timedelta(hours=_CONSOLIDATION_INTERVAL_HOURS)
        except Exception:
            # metadata table may not exist yet, or parse error — run consolidation
            return True

    async def consolidate(self) -> dict[str, int]:
        """Run one consolidation pass. Returns stats."""
        stats: dict[str, int] = {"pruned": 0, "merged": 0, "capped": 0}
        # Rows whose file is gone (the only rows it is safe to drop).
        stats["pruned"] = await self._prune_missing_files()
        # Exact duplicates of the same file + heading.
        stats["merged"] = await self._merge_duplicates()
        await self._log_consolidation(stats)
        logger.info(
            "Knowledge consolidation complete: missing_files=%d merged=%d",
            stats["pruned"],
            stats["merged"],
        )
        return stats

    def _source_exists(self, file_path: str) -> bool:
        """Whether an indexed path still exists on disk.

        Index paths are relative to ``knowledge/`` ("learned/x.md"); some
        callers store them with the ``knowledge/`` prefix or absolute.
        Unknown shapes count as existing — never drop what we cannot place.
        """
        if not file_path:
            return True
        candidate = Path(file_path)
        if candidate.is_absolute():
            return candidate.exists()
        knowledge_dir = self._project_root / "knowledge"
        return (knowledge_dir / file_path).exists() or (
            self._project_root / file_path
        ).exists()

    async def _delete_chunks(self, chunk_ids: list[int]) -> None:
        for cid in chunk_ids:
            await self._db.execute("DELETE FROM knowledge_chunks WHERE id = ?", (cid,))
            if getattr(self._db, "vec_available", False):
                try:
                    await self._db.execute(
                        "DELETE FROM vec_chunks WHERE chunk_id = ?", (cid,)
                    )
                except Exception as e:  # pragma: no cover — vec table optional
                    logger.debug("vec_chunks delete failed for %s: %s", cid, e)

    async def _prune_missing_files(self) -> int:
        """Drop index rows for files that no longer exist on disk."""
        rows = await self._db.execute(
            "SELECT DISTINCT file_path FROM knowledge_chunks LIMIT ?",
            (_MAX_FILES_CHECKED,),
        )
        pruned = 0
        for row in rows or []:
            fp = row["file_path"] or ""
            if self._source_exists(fp):
                continue
            ids = await self._db.execute(
                "SELECT id FROM knowledge_chunks WHERE file_path = ?", (fp,)
            )
            chunk_ids = [r["id"] for r in ids or []]
            await self._delete_chunks(chunk_ids)
            pruned += len(chunk_ids)
            logger.debug("Dropped %d index rows for missing file %s", len(chunk_ids), fp)
        return pruned

    async def _merge_duplicates(self) -> int:
        """Drop rows that repeat another row exactly — same file, heading AND
        content — keeping the newest.

        Grouping on file + heading alone deleted real content: a long
        section is split into several chunks that share one heading (all 6
        such groups in the live index had distinct content).
        """
        rows = await self._db.execute(
            "SELECT file_path, heading_path, content, COUNT(*) as cnt "
            "FROM knowledge_chunks "
            "GROUP BY file_path, heading_path, content HAVING cnt > 1 LIMIT 50",
            (),
        )
        if not rows:
            return 0

        merged = 0
        for row in rows:
            dupes = await self._db.execute(
                "SELECT id FROM knowledge_chunks "
                "WHERE file_path = ? AND heading_path = ? AND content = ? "
                "ORDER BY indexed_at DESC",
                (row["file_path"], row["heading_path"], row["content"]),
            )
            stale_ids = [d["id"] for d in dupes[1:]]
            await self._delete_chunks(stale_ids)
            merged += len(stale_ids)
        return merged

    async def _log_consolidation(self, stats: dict[str, int]) -> None:
        """Record consolidation run in metadata table."""
        try:
            await self._db.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                ("last_consolidation", datetime.now(UTC).isoformat()),
            )
            await self._db.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                ("last_consolidation_stats", str(stats)),
            )
        except Exception:
            pass  # metadata table may not exist — non-critical
