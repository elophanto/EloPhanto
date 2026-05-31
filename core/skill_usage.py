"""Skill usage telemetry — calcification detection for the skill library.

Why this exists
---------------
The skill catalog has grown well past 150 entries, but production logs
show only ~9 distinct skills loaded per 18-hour run. The rest sit
unread. Without telemetry there is no way to tell whether a skill is
load-bearing, stale, or dead weight — so the library accumulates and
the agent calcifies onto a tiny working set.

This module records lightweight per-skill usage in a sidecar JSON file
and derives a state (``active`` / ``stale`` / ``archived``) from the
last-viewed timestamp. The sidecar lives at
``<base_dir>/data/.skill_usage.json`` so it stays out of git
(``/data/`` is already ignored) and never lands in user-authored
SKILL.md frontmatter — operational telemetry has no business mixing
with content.

Design constraints
------------------
- **Read-path safety.** ``bump_view`` is a best-effort fire-and-forget
  call from the ``skill_read`` tool. A broken or unwritable sidecar
  must never break a skill read.
- **Pure state derivation.** ``derive_state`` takes a record + clock +
  thresholds and returns a string. No I/O. Tests pin the table.
- **Pinned wins.** A pinned skill never auto-transitions, even if
  unused for years. Use it for must-always-show skills (e.g.
  ``verification-before-completion``).
- **Crash-safe writes.** Tempfile + ``os.replace`` so a torn write
  during shutdown can't leave a half-written JSON.

What's NOT here
---------------
- Auto-archive (moving files to ``.archive/``). That's a separate
  curator step; this module only tracks and reports.
- Per-skill use-vs-view distinction. The only reliable hook today is
  ``skill_read``, so every read counts as a view. If a future
  ``skill_apply``-style tool lands, add ``bump_use`` alongside.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)


# Lifecycle states. The transitions are derived from `last_viewed_at`
# in `derive_state` — this module never mutates state on its own; the
# state field on disk is a cached derivation, not a source of truth.
STATE_ACTIVE = "active"
STATE_STALE = "stale"
STATE_ARCHIVED = "archived"

# Defaults — overridable per call. 30/90 matches a "read at least once
# a month or it's probably dead" rule of thumb; tune via config when we
# have enough usage data to justify a different number.
DEFAULT_STALE_AFTER_DAYS = 30
DEFAULT_ARCHIVE_AFTER_DAYS = 90


@dataclass(slots=True)
class UsageRecord:
    """Per-skill telemetry snapshot. Pure data — no behavior."""

    skill_name: str
    view_count: int = 0
    last_viewed_at: str | None = None  # ISO-8601 UTC, ``None`` = never
    first_seen_at: str | None = None
    pinned: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "view_count": self.view_count,
            "last_viewed_at": self.last_viewed_at,
            "first_seen_at": self.first_seen_at,
            "pinned": self.pinned,
        }

    @classmethod
    def from_json(cls, skill_name: str, raw: dict[str, Any]) -> UsageRecord:
        return cls(
            skill_name=skill_name,
            view_count=int(raw.get("view_count") or 0),
            last_viewed_at=raw.get("last_viewed_at"),
            first_seen_at=raw.get("first_seen_at"),
            pinned=bool(raw.get("pinned") or False),
        )


def sidecar_path(base_dir: Path) -> Path:
    """Resolve the sidecar location for a given project root."""
    return base_dir / "data" / ".skill_usage.json"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@contextmanager
def _atomic_write(path: Path) -> Iterator[Any]:
    """Yield a file handle that atomically replaces ``path`` on close.

    Writes to a tempfile in the same directory (cross-device renames
    are not atomic on POSIX), then ``os.replace`` swaps it in. A crash
    mid-write leaves the prior file intact, never a truncated one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yield fh
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_all(base_dir: Path) -> dict[str, UsageRecord]:
    """Read the sidecar. Returns ``{}`` on missing / unreadable file."""
    path = sidecar_path(base_dir)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("skill_usage: sidecar unreadable (%s); starting fresh", e)
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        name: UsageRecord.from_json(name, data)
        for name, data in raw.items()
        if isinstance(data, dict)
    }


def save_all(base_dir: Path, records: dict[str, UsageRecord]) -> None:
    """Write the sidecar atomically. Best-effort — logs but never raises."""
    try:
        with _atomic_write(sidecar_path(base_dir)) as fh:
            json.dump(
                {name: r.to_json() for name, r in records.items()},
                fh,
                indent=2,
                sort_keys=True,
            )
    except OSError as e:
        logger.warning("skill_usage: could not write sidecar: %s", e)


def get_record(base_dir: Path, skill_name: str) -> UsageRecord:
    """Return the record for one skill, or a fresh zero record."""
    return load_all(base_dir).get(skill_name) or UsageRecord(skill_name=skill_name)


def bump_view(base_dir: Path, skill_name: str) -> None:
    """Record a skill view. Best-effort — never raises.

    Called from ``SkillReadTool`` on successful read. Wrapped in
    try/except so a broken sidecar can never break the read itself.
    """
    try:
        records = load_all(base_dir)
        rec = records.get(skill_name) or UsageRecord(skill_name=skill_name)
        now = _now_iso()
        rec.view_count += 1
        rec.last_viewed_at = now
        if rec.first_seen_at is None:
            rec.first_seen_at = now
        records[skill_name] = rec
        save_all(base_dir, records)
    except Exception as e:  # noqa: BLE001 — telemetry must never propagate
        logger.debug("skill_usage: bump_view(%s) swallowed: %s", skill_name, e)


def set_pinned(base_dir: Path, skill_name: str, pinned: bool) -> None:
    """Toggle the pinned flag for a skill. Creates the record if absent."""
    records = load_all(base_dir)
    rec = records.get(skill_name) or UsageRecord(skill_name=skill_name)
    rec.pinned = pinned
    records[skill_name] = rec
    save_all(base_dir, records)


def derive_state(
    record: UsageRecord,
    *,
    now: datetime,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    archive_after_days: int = DEFAULT_ARCHIVE_AFTER_DAYS,
) -> str:
    """Derive the lifecycle state from the record. Pure function.

    Rules:
      - ``pinned`` → always ``active`` (override).
      - never viewed → ``active`` (grace period; we don't know how
        long the skill has existed, so don't auto-stale it).
      - viewed in the last ``stale_after_days`` → ``active``.
      - viewed between ``stale_after_days`` and ``archive_after_days``
        ago → ``stale``.
      - viewed longer ago than ``archive_after_days`` → ``archived``.
    """
    if record.pinned:
        return STATE_ACTIVE
    last = _parse_iso(record.last_viewed_at)
    if last is None:
        return STATE_ACTIVE
    age = now - last
    if age < timedelta(days=stale_after_days):
        return STATE_ACTIVE
    if age < timedelta(days=archive_after_days):
        return STATE_STALE
    return STATE_ARCHIVED


def list_neglected(
    base_dir: Path,
    *,
    known_skills: set[str] | None = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    archive_after_days: int = DEFAULT_ARCHIVE_AFTER_DAYS,
    limit: int = 20,
    include_never_viewed: bool = True,
) -> list[tuple[str, str, str | None]]:
    """Return ``[(skill_name, state, last_viewed_at)]`` sorted by neglect.

    Never-viewed (when ``known_skills`` is supplied) sort first, then
    by oldest ``last_viewed_at`` ascending. Pinned skills are omitted —
    pinning is the operator's way of saying "I know it's quiet, leave
    it alone."
    """
    records = load_all(base_dir)
    now = datetime.now(UTC)
    rows: list[tuple[str, str, str | None, datetime | None]] = []

    seen = set(records.keys())
    if known_skills and include_never_viewed:
        for name in sorted(known_skills - seen):
            rows.append((name, STATE_ACTIVE, None, None))  # never viewed → no clock

    for name, rec in records.items():
        if rec.pinned:
            continue
        state = derive_state(
            rec,
            now=now,
            stale_after_days=stale_after_days,
            archive_after_days=archive_after_days,
        )
        if state == STATE_ACTIVE and rec.last_viewed_at is not None:
            continue  # only surface stale/archived/never-viewed
        rows.append((name, state, rec.last_viewed_at, _parse_iso(rec.last_viewed_at)))

    # never-viewed (clock=None) first, then oldest last_viewed_at first
    rows.sort(key=lambda r: (r[3] is not None, r[3] or now))
    return [(name, state, last_iso) for name, state, last_iso, _ in rows[:limit]]
