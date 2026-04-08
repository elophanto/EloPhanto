"""Knowledge consolidation — prune stale, merge duplicates, enforce caps.

Runs during autonomous mind maintenance phase to maintain knowledge hygiene.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.database import Database

logger = logging.getLogger(__name__)

_MAX_KNOWLEDGE_ENTRIES = 500
_STALE_DAYS = 90  # Entries older than this with zero recent access are prunable
_CONSOLIDATION_INTERVAL_HOURS = 24


class KnowledgeConsolidator:
    """Prunes, merges, and maintains knowledge base hygiene."""

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
        """Run full consolidation cycle. Returns stats dict."""
        stats: dict[str, int] = {
            "pruned": 0,
            "merged": 0,
            "capped": 0,
        }

        # Phase 1: Prune stale entries
        stats["pruned"] = await self._prune_stale()

        # Phase 2: Merge near-duplicates
        stats["merged"] = await self._merge_duplicates()

        # Phase 3: Enforce entry cap
        stats["capped"] = await self._enforce_cap()

        # Phase 4: Clean orphaned disk files
        stats["disk_cleaned"] = await self._clean_orphaned_files()

        # Phase 5: Log consolidation
        await self._log_consolidation(stats)

        logger.info(
            "Knowledge consolidation complete: pruned=%d merged=%d capped=%d disk_cleaned=%d",
            stats["pruned"],
            stats["merged"],
            stats["capped"],
            stats.get("disk_cleaned", 0),
        )
        return stats

    async def _prune_stale(self) -> int:
        """Remove knowledge entries older than _STALE_DAYS with no recent access."""
        cutoff = (datetime.now(UTC) - timedelta(days=_STALE_DAYS)).isoformat()
        # Find entries that haven't been accessed recently and are old
        rows = await self._db.execute(
            "SELECT id, file_path, heading_path FROM knowledge_chunks "
            "WHERE indexed_at < ? AND last_accessed_at IS NULL "
            "ORDER BY indexed_at ASC LIMIT 50",
            (cutoff,),
        )
        if not rows:
            return 0

        pruned = 0
        for row in rows:
            await self._db.execute(
                "DELETE FROM knowledge_chunks WHERE id = ?", (row["id"],)
            )
            pruned += 1
            logger.debug(
                "Pruned stale knowledge: %s / %s",
                row["file_path"],
                row["heading_path"],
            )

        return pruned

    async def _merge_duplicates(self) -> int:
        """Find and merge near-duplicate entries by file_path+heading_path match."""
        # Exact file_path+heading_path duplicates — keep newest, delete rest
        rows = await self._db.execute(
            "SELECT file_path, heading_path, COUNT(*) as cnt "
            "FROM knowledge_chunks "
            "GROUP BY file_path, heading_path HAVING cnt > 1 LIMIT 20",
            (),
        )
        if not rows:
            return 0

        merged = 0
        for row in rows:
            dupes = await self._db.execute(
                "SELECT id, content, indexed_at FROM knowledge_chunks "
                "WHERE file_path = ? AND heading_path = ? "
                "ORDER BY indexed_at DESC",
                (row["file_path"], row["heading_path"]),
            )
            # Keep the newest, delete the rest
            for dupe in dupes[1:]:
                await self._db.execute(
                    "DELETE FROM knowledge_chunks WHERE id = ?", (dupe["id"],)
                )
                merged += 1

        return merged

    async def _enforce_cap(self) -> int:
        """Remove oldest entries if total exceeds _MAX_KNOWLEDGE_ENTRIES."""
        count_rows = await self._db.execute(
            "SELECT COUNT(*) as cnt FROM knowledge_chunks", ()
        )
        total = count_rows[0]["cnt"] if count_rows else 0

        if total <= _MAX_KNOWLEDGE_ENTRIES:
            return 0

        excess = total - _MAX_KNOWLEDGE_ENTRIES
        # Delete oldest entries (by indexed_at)
        rows = await self._db.execute(
            "SELECT id FROM knowledge_chunks ORDER BY indexed_at ASC LIMIT ?",
            (excess,),
        )
        for row in rows:
            await self._db.execute(
                "DELETE FROM knowledge_chunks WHERE id = ?", (row["id"],)
            )

        logger.info(
            "Capped knowledge: removed %d entries (was %d, cap %d)",
            excess,
            total,
            _MAX_KNOWLEDGE_ENTRIES,
        )
        return excess

    async def _clean_orphaned_files(self) -> int:
        """Remove learned/ markdown files that have no DB index entries.

        Files accumulate on disk as the learner creates them, but are never
        deleted when their DB entries are pruned. This phase finds files in
        ``knowledge/learned/`` that have zero corresponding rows in
        ``knowledge_chunks`` and removes them.
        """
        learned_dir = self._project_root / "knowledge" / "learned"
        if not learned_dir.is_dir():
            return 0

        # Get all indexed file paths from DB
        rows = await self._db.execute(
            "SELECT DISTINCT file_path FROM knowledge_chunks", ()
        )
        indexed_paths: set[str] = set()
        for row in rows:
            fp = row["file_path"]
            if fp:
                # Normalize: DB stores relative paths like "learned/strategy/x.md"
                indexed_paths.add(fp)
                # Also add with "knowledge/" prefix variant
                if not fp.startswith("knowledge/"):
                    indexed_paths.add(f"knowledge/{fp}")

        cleaned = 0
        for md_file in learned_dir.rglob("*.md"):
            # Build relative path variants to check against DB
            rel = md_file.relative_to(self._project_root)
            rel_str = str(rel)
            # Also try without "knowledge/" prefix
            alt_str = str(rel).removeprefix("knowledge/")

            if rel_str not in indexed_paths and alt_str not in indexed_paths:
                try:
                    md_file.unlink()
                    cleaned += 1
                    logger.debug("Cleaned orphaned file: %s", rel_str)
                except OSError as e:
                    logger.debug("Failed to clean %s: %s", rel_str, e)

        # Clean empty directories left behind
        if cleaned:
            for dirpath in sorted(learned_dir.rglob("*"), reverse=True):
                if dirpath.is_dir() and not any(dirpath.iterdir()):
                    try:
                        dirpath.rmdir()
                    except OSError:
                        pass

        if cleaned:
            logger.info("Cleaned %d orphaned knowledge files from disk", cleaned)
        return cleaned

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
