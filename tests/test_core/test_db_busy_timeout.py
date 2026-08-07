"""SQLite write contention must wait, not crash.

WAL gives concurrent readers, but writers still serialize. SQLite's default
busy timeout is ZERO, so the loser of a write race raises "database is locked"
immediately. The agent writes from several places at once (mind cycle,
scheduler dispatch, gateway session, cost tracker) and the CLI/dashboard open
their own connections to the same file, so that race is routine.
"""

from __future__ import annotations

import sqlite3
import threading
import time

import pytest

from core.database import BUSY_TIMEOUT_MS, Database


@pytest.mark.asyncio
async def test_busy_timeout_is_set_on_the_connection(tmp_path) -> None:
    db = Database(str(tmp_path / "t.db"))
    await db.initialize()
    try:
        rows = await db.execute("PRAGMA busy_timeout")
        assert int(rows[0][0]) == BUSY_TIMEOUT_MS
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_wal_mode_still_enabled(tmp_path) -> None:
    db = Database(str(tmp_path / "t.db"))
    await db.initialize()
    try:
        rows = await db.execute("PRAGMA journal_mode")
        assert str(rows[0][0]).lower() == "wal"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_write_waits_out_a_competing_writer(tmp_path) -> None:
    """The regression this exists for.

    A second connection holds a write lock briefly; our write must block and
    then succeed. With busy_timeout=0 this raises OperationalError instantly.
    """
    path = str(tmp_path / "t.db")
    db = Database(path)
    await db.initialize()
    try:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)"
        )

        holder_ready = threading.Event()
        release = threading.Event()

        def hold_write_lock() -> None:
            conn = sqlite3.connect(path, timeout=10)
            try:
                conn.execute("PRAGMA busy_timeout=5000")
                conn.execute("BEGIN IMMEDIATE")  # takes the write lock
                conn.execute("INSERT INTO t (v) VALUES ('holder')")
                holder_ready.set()
                release.wait(timeout=5)
                conn.commit()
            finally:
                conn.close()

        t = threading.Thread(target=hold_write_lock, daemon=True)
        t.start()
        assert holder_ready.wait(timeout=5), "lock holder never started"

        # Let go shortly after our write begins, so we genuinely contend.
        threading.Timer(0.35, release.set).start()

        started = time.monotonic()
        await db.execute_insert("INSERT INTO t (v) VALUES (?)", ("waiter",))
        waited = time.monotonic() - started
        t.join(timeout=5)

        # It blocked (rather than failing fast) and then succeeded.
        assert waited >= 0.2, f"did not actually contend (waited {waited:.3f}s)"
        rows = await db.execute("SELECT v FROM t ORDER BY id")
        assert [r[0] for r in rows] == ["holder", "waiter"]
    finally:
        await db.close()


def test_zero_timeout_would_fail_fast(tmp_path) -> None:
    """Proves the test above is meaningful — the same race with the SQLite
    default really does raise, so the passing case is the timeout working and
    not just a race that never happened."""
    path = str(tmp_path / "t2.db")
    setup = sqlite3.connect(path)
    setup.execute("PRAGMA journal_mode=WAL")
    setup.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    setup.commit()

    holder = sqlite3.connect(path)
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("INSERT INTO t (v) VALUES ('holder')")
    try:
        loser = sqlite3.connect(path, timeout=0)
        loser.execute("PRAGMA busy_timeout=0")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            loser.execute("BEGIN IMMEDIATE")
            loser.execute("INSERT INTO t (v) VALUES ('loser')")
        loser.close()
    finally:
        holder.rollback()
        holder.close()
        setup.close()
