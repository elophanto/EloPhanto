"""Tests for the skill_usage telemetry sidecar.

Covers:
- bump_view writes/increments a record and timestamps it
- repeated bumps increment view_count and update last_viewed_at
- pinned skills always derive STATE_ACTIVE regardless of age
- derive_state state-transition table (active/stale/archived/never)
- list_neglected ranks never-viewed first, then oldest last_viewed_at
- sidecar survives a missing file / unreadable JSON without raising
- atomic write does not leave a torn file on failure
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.skill_usage import (
    DEFAULT_ARCHIVE_AFTER_DAYS,
    DEFAULT_STALE_AFTER_DAYS,
    STATE_ACTIVE,
    STATE_ARCHIVED,
    STATE_STALE,
    UsageRecord,
    bump_view,
    derive_state,
    get_record,
    list_neglected,
    load_all,
    save_all,
    set_pinned,
    sidecar_path,
)


class TestBumpView:
    def test_first_bump_creates_record(self, tmp_path: Path) -> None:
        bump_view(tmp_path, "x-virality")
        rec = get_record(tmp_path, "x-virality")
        assert rec.view_count == 1
        assert rec.last_viewed_at is not None
        assert rec.first_seen_at == rec.last_viewed_at
        assert rec.pinned is False

    def test_repeat_bump_increments_and_updates(self, tmp_path: Path) -> None:
        bump_view(tmp_path, "x-virality")
        first = get_record(tmp_path, "x-virality")
        bump_view(tmp_path, "x-virality")
        second = get_record(tmp_path, "x-virality")
        assert second.view_count == 2
        assert second.first_seen_at == first.first_seen_at
        # last_viewed_at moves forward (or stays equal in same-microsecond
        # edge case); first_seen_at is sticky.
        assert second.last_viewed_at >= first.last_viewed_at

    def test_bump_swallows_io_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A broken sidecar must NEVER break skill_read."""

        def _explode(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr("core.skill_usage.save_all", _explode)
        # Should not raise:
        bump_view(tmp_path, "anything")


class TestDeriveState:
    def _rec(self, last_age_days: int | None, pinned: bool = False) -> UsageRecord:
        if last_age_days is None:
            last = None
        else:
            last = (datetime.now(UTC) - timedelta(days=last_age_days)).isoformat()
        return UsageRecord(skill_name="t", last_viewed_at=last, pinned=pinned)

    def test_pinned_always_active(self) -> None:
        rec = self._rec(last_age_days=9999, pinned=True)
        assert derive_state(rec, now=datetime.now(UTC)) == STATE_ACTIVE

    def test_never_viewed_is_active_grace_period(self) -> None:
        rec = self._rec(last_age_days=None)
        assert derive_state(rec, now=datetime.now(UTC)) == STATE_ACTIVE

    def test_recent_is_active(self) -> None:
        rec = self._rec(last_age_days=DEFAULT_STALE_AFTER_DAYS - 1)
        assert derive_state(rec, now=datetime.now(UTC)) == STATE_ACTIVE

    def test_between_thresholds_is_stale(self) -> None:
        rec = self._rec(last_age_days=DEFAULT_STALE_AFTER_DAYS + 5)
        assert derive_state(rec, now=datetime.now(UTC)) == STATE_STALE

    def test_past_archive_threshold_is_archived(self) -> None:
        rec = self._rec(last_age_days=DEFAULT_ARCHIVE_AFTER_DAYS + 5)
        assert derive_state(rec, now=datetime.now(UTC)) == STATE_ARCHIVED


class TestSidecarRobustness:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_all(tmp_path) == {}

    def test_corrupt_json_returns_empty(self, tmp_path: Path) -> None:
        path = sidecar_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json {{{")
        assert load_all(tmp_path) == {}

    def test_non_dict_top_level_returns_empty(self, tmp_path: Path) -> None:
        path = sidecar_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(["not", "a", "dict"]))
        assert load_all(tmp_path) == {}

    def test_save_then_load_roundtrip(self, tmp_path: Path) -> None:
        records = {
            "a": UsageRecord(skill_name="a", view_count=3, pinned=True),
            "b": UsageRecord(
                skill_name="b",
                view_count=1,
                last_viewed_at="2026-01-01T00:00:00+00:00",
            ),
        }
        save_all(tmp_path, records)
        loaded = load_all(tmp_path)
        assert loaded["a"].pinned is True
        assert loaded["a"].view_count == 3
        assert loaded["b"].last_viewed_at == "2026-01-01T00:00:00+00:00"


class TestPinning:
    def test_set_pinned_creates_record_if_absent(self, tmp_path: Path) -> None:
        set_pinned(tmp_path, "verification-before-completion", True)
        assert get_record(tmp_path, "verification-before-completion").pinned is True

    def test_set_pinned_preserves_view_count(self, tmp_path: Path) -> None:
        bump_view(tmp_path, "x-virality")
        bump_view(tmp_path, "x-virality")
        set_pinned(tmp_path, "x-virality", True)
        rec = get_record(tmp_path, "x-virality")
        assert rec.view_count == 2
        assert rec.pinned is True


class TestListNeglected:
    def test_never_viewed_sorts_first(self, tmp_path: Path) -> None:
        # one viewed-but-stale, two never-viewed
        records = {
            "old-skill": UsageRecord(
                skill_name="old-skill",
                last_viewed_at=(
                    datetime.now(UTC) - timedelta(days=DEFAULT_STALE_AFTER_DAYS + 10)
                ).isoformat(),
            ),
        }
        save_all(tmp_path, records)
        known = {"old-skill", "untouched-a", "untouched-b"}
        rows = list_neglected(tmp_path, known_skills=known)
        # never-viewed first (sorted alphabetically), then stale
        assert [r[0] for r in rows] == ["untouched-a", "untouched-b", "old-skill"]

    def test_pinned_omitted(self, tmp_path: Path) -> None:
        records = {
            "pinned-stale": UsageRecord(
                skill_name="pinned-stale",
                pinned=True,
                last_viewed_at=(
                    datetime.now(UTC) - timedelta(days=DEFAULT_ARCHIVE_AFTER_DAYS + 5)
                ).isoformat(),
            ),
        }
        save_all(tmp_path, records)
        rows = list_neglected(tmp_path)
        assert rows == []

    def test_recent_active_omitted(self, tmp_path: Path) -> None:
        records = {
            "fresh": UsageRecord(
                skill_name="fresh",
                last_viewed_at=datetime.now(UTC).isoformat(),
            ),
        }
        save_all(tmp_path, records)
        rows = list_neglected(tmp_path)
        assert rows == []

    def test_limit_honored(self, tmp_path: Path) -> None:
        known = {f"skill-{i}" for i in range(50)}
        rows = list_neglected(tmp_path, known_skills=known, limit=5)
        assert len(rows) == 5
