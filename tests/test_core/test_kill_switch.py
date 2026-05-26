"""Kill switch primitives + parser (data/STOP sentinel)."""

from __future__ import annotations

import pytest

from core.kill_switch import (
    StopResult,
    cancel_active_goals,
    clear_sentinel,
    disable_enabled_schedules,
    hard_stop,
    is_stopped,
    parse_kill_command,
    stop_file_path,
    write_sentinel,
)

# ── Parser ──────────────────────────────────────────────────────────


class TestParseKillCommand:
    def test_stop_minimal(self) -> None:
        verb, flags = parse_kill_command("stop")
        assert verb == "stop"
        assert flags == {
            "cancel_goals": False,
            "cancel_schedules": False,
            "hard": False,
        }

    def test_slash_stop(self) -> None:
        assert parse_kill_command("/stop")[0] == "stop"

    def test_synonyms_stop(self) -> None:
        for token in ("halt", "kill", "pause", "/halt", "/kill", "/pause"):
            verb, _ = parse_kill_command(token)
            assert verb == "stop", token

    def test_case_insensitive(self) -> None:
        assert parse_kill_command("STOP")[0] == "stop"
        assert parse_kill_command("Resume")[0] == "resume"

    def test_whitespace(self) -> None:
        assert parse_kill_command("  stop  ")[0] == "stop"

    def test_hard_flag(self) -> None:
        verb, flags = parse_kill_command("/stop --hard")
        assert verb == "stop"
        assert flags["hard"] is True
        assert flags["cancel_goals"] is True
        assert flags["cancel_schedules"] is True

    def test_cancel_goals_flag(self) -> None:
        verb, flags = parse_kill_command("stop --cancel-goals")
        assert verb == "stop"
        assert flags["cancel_goals"] is True
        assert flags["cancel_schedules"] is False

    def test_cancel_schedules_flag(self) -> None:
        verb, flags = parse_kill_command("stop --cancel-schedules")
        assert verb == "stop"
        assert flags["cancel_schedules"] is True

    def test_resume_synonyms(self) -> None:
        for token in (
            "resume",
            "/resume",
            "go",
            "continue",
            "unpause",
            "/go",
            "/continue",
        ):
            assert parse_kill_command(token)[0] == "resume", token

    def test_free_form_followup_not_a_kill(self) -> None:
        # Critical: "stop talking about X" / "pause the X loop" must
        # NOT be parsed as a hard kill. Only "stop" alone or with
        # valid flags trips the deterministic path.
        assert parse_kill_command("stop talking about that")[0] is None
        assert parse_kill_command("pause the X growth loop")[0] is None
        assert parse_kill_command("can you halt the email outreach")[0] is None

    def test_resume_with_followup_not_a_kill(self) -> None:
        assert parse_kill_command("resume the email loop")[0] is None

    def test_empty(self) -> None:
        assert parse_kill_command("")[0] is None
        assert parse_kill_command("   ")[0] is None

    def test_unrelated_text(self) -> None:
        assert parse_kill_command("hello, drive my business")[0] is None
        assert parse_kill_command("what's up")[0] is None


# ── Sentinel I/O ────────────────────────────────────────────────────


class TestSentinel:
    def test_write_then_is_stopped(self, tmp_path) -> None:
        assert is_stopped(tmp_path) is False
        result = write_sentinel(tmp_path)
        assert result.already_stopped is False
        assert is_stopped(tmp_path) is True
        assert stop_file_path(tmp_path).is_file()

    def test_idempotent_write(self, tmp_path) -> None:
        write_sentinel(tmp_path)
        result2 = write_sentinel(tmp_path)
        assert result2.already_stopped is True

    def test_clear_when_present(self, tmp_path) -> None:
        write_sentinel(tmp_path)
        result = clear_sentinel(tmp_path)
        assert result.was_stopped is True
        assert is_stopped(tmp_path) is False

    def test_clear_when_absent(self, tmp_path) -> None:
        result = clear_sentinel(tmp_path)
        assert result.was_stopped is False


# ── DB cancellations ────────────────────────────────────────────────


@pytest.fixture
async def db(tmp_path):
    from core.database import Database

    db = Database(str(tmp_path / "test.db"))
    await db.initialize()
    return db


class TestDbCancels:
    @pytest.mark.asyncio
    async def test_cancel_active_goals(self, db) -> None:
        # Seed a couple of active/planning goals
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        await db.execute_insert(
            "INSERT INTO goals (goal_id, goal, status, attempts, max_attempts, "
            "llm_calls_used, cost_usd, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, 3, 0, 0.0, ?, ?)",
            ("g1", "x", "active", now, now),
        )
        await db.execute_insert(
            "INSERT INTO goals (goal_id, goal, status, attempts, max_attempts, "
            "llm_calls_used, cost_usd, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, 3, 0, 0.0, ?, ?)",
            ("g2", "y", "planning", now, now),
        )
        await db.execute_insert(
            "INSERT INTO goals (goal_id, goal, status, attempts, max_attempts, "
            "llm_calls_used, cost_usd, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, 3, 0, 0.0, ?, ?)",
            ("g3", "z", "completed", now, now),
        )

        n = await cancel_active_goals(db)
        assert n == 2
        rows = await db.execute("SELECT goal_id, status FROM goals ORDER BY goal_id")
        statuses = {r["goal_id"]: r["status"] for r in rows}
        assert statuses["g1"] == "cancelled"
        assert statuses["g2"] == "cancelled"
        assert statuses["g3"] == "completed"  # untouched

    @pytest.mark.asyncio
    async def test_disable_enabled_schedules(self, db) -> None:
        # Seed schedules — one enabled, one already disabled
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        await db.execute_insert(
            "INSERT INTO scheduled_tasks (id, name, task_goal, "
            "cron_expression, enabled, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 1, ?, ?)",
            ("s1", "n1", "g", "* * * * *", now, now),
        )
        await db.execute_insert(
            "INSERT INTO scheduled_tasks (id, name, task_goal, "
            "cron_expression, enabled, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 0, ?, ?)",
            ("s2", "n2", "g", "* * * * *", now, now),
        )
        n = await disable_enabled_schedules(db)
        assert n == 1
        rows = await db.execute("SELECT id, enabled FROM scheduled_tasks")
        enabled = {r["id"]: r["enabled"] for r in rows}
        assert enabled["s1"] == 0
        assert enabled["s2"] == 0  # was already 0; unchanged

    @pytest.mark.asyncio
    async def test_hard_stop_writes_sentinel_and_cancels(self, db, tmp_path) -> None:
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        await db.execute_insert(
            "INSERT INTO goals (goal_id, goal, status, attempts, max_attempts, "
            "llm_calls_used, cost_usd, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, 3, 0, 0.0, ?, ?)",
            ("g1", "x", "active", now, now),
        )
        result: StopResult = await hard_stop(
            data_dir=tmp_path,
            db=db,
            cancel_goals=True,
            cancel_schedules=True,
        )
        assert result.already_stopped is False
        assert result.cancelled_goals == 1
        assert result.disabled_schedules == 0
        assert is_stopped(tmp_path) is True

    @pytest.mark.asyncio
    async def test_hard_stop_without_db(self, tmp_path) -> None:
        # No DB injected — sentinel still writes, no cancels.
        result = await hard_stop(data_dir=tmp_path, db=None, cancel_goals=True)
        assert result.cancelled_goals == 0
        assert is_stopped(tmp_path) is True
