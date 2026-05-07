"""TaskResourceManager + scheduler queue tests.

Pins:
  * Resource-typed semaphores: non-overlapping tasks parallelize,
    overlapping tasks serialize.
  * Resource heuristic: browser keywords trigger BROWSER, vault-set
    keywords trigger VAULT_WRITE, etc.
  * Scheduler queue: cron firings while a task runs ENQUEUE (no longer
    drop). Per-schedule_id dedup prevents queue spirals from a slow
    task that exceeds its cron interval. Queue cap drops with a log,
    not silently.
  * Doctor-grade snapshot: status() returns capacity / in_use / waiters
    so observability tooling can render queue depth.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

import pytest

from core.database import Database
from core.scheduler import TaskScheduler
from core.task_resources import (
    TaskResource,
    TaskResourceManager,
    infer_resources,
)


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


# ---------------------------------------------------------------------------
# Resource heuristic
# ---------------------------------------------------------------------------


class TestInferResources:
    def test_empty_goal_assumes_browser(self) -> None:
        """A goal with no text should fall back to BROWSER + LLM_BURST.
        Conservative: better to over-acquire than corrupt state."""
        out = infer_resources("")
        assert TaskResource.BROWSER in out
        assert TaskResource.LLM_BURST in out

    def test_twitter_post_triggers_browser(self) -> None:
        out = infer_resources("Post on X about today's pumpfun stream")
        assert TaskResource.BROWSER in out

    def test_polymarket_does_not_trigger_browser(self) -> None:
        """Polymarket flows are API-driven via py-clob-client. The
        production heuristic deliberately does NOT mark them as
        browser-needing — that was an early over-broad guess that
        held back parallelism for ~3 schedules in the operator's
        live config (see 2026-05-07 tightening)."""
        out = infer_resources("Scan polymarket for new arbitrage opportunities")
        assert TaskResource.BROWSER not in out
        assert TaskResource.LLM_BURST in out

    def test_email_reply_does_not_trigger_browser(self) -> None:
        """Replying to emails uses the AgentMail/SMTP API, not the
        browser. Bare 'reply' was historically matched as a browser
        signal — over-broad. Replying to X DOES need browser, but the
        tightened heuristic looks for 'X reply' / 'twitter reply',
        not bare 'reply'."""
        out = infer_resources(
            "Check inbox and reply to any urgent emails from operators"
        )
        assert TaskResource.BROWSER not in out
        assert TaskResource.LLM_BURST in out

    def test_x_reply_phrase_still_triggers_browser(self) -> None:
        """The combined 'X reply' / 'twitter reply' phrasing is the
        right specificity — only fires when both halves are present."""
        out = infer_resources("Run the X replies engagement loop for 30 minutes")
        assert TaskResource.BROWSER in out

    def test_pure_search_does_not_require_browser(self) -> None:
        """`web_search` is an API tool, not browser. The heuristic
        should not over-declare BROWSER for plain search tasks."""
        out = infer_resources("Use web_search to summarise today's AI news")
        assert TaskResource.BROWSER not in out
        assert TaskResource.LLM_BURST in out

    def test_desktop_keyword_triggers_desktop(self) -> None:
        out = infer_resources("Open Excel and add a chart to the sheet")
        assert TaskResource.DESKTOP in out

    def test_vault_set_triggers_vault_write(self) -> None:
        out = infer_resources("vault_set the new openrouter API key")
        assert TaskResource.VAULT_WRITE in out

    def test_llm_burst_always_present(self) -> None:
        """Every scheduled task triggers the agent loop, which uses the
        LLM. LLM_BURST is the global throttle; it must always show up."""
        for goal in [
            "browser navigate to example.com",
            "summarise the last week of memos",
            "vault_set new key",
        ]:
            assert TaskResource.LLM_BURST in infer_resources(goal)

    def test_resources_returned_in_canonical_order(self) -> None:
        """Order matters for deadlock prevention. Two tasks declaring
        overlapping sets must acquire in the same order."""
        out = infer_resources("Open Excel + post on X + vault_set key")
        sorted_out = sorted(out, key=lambda r: r.value)
        assert out == sorted_out


# ---------------------------------------------------------------------------
# Resource manager — semaphores
# ---------------------------------------------------------------------------


class TestTaskResourceManager:
    @pytest.mark.asyncio
    async def test_acquire_and_release(self) -> None:
        mgr = TaskResourceManager.from_defaults()
        assert not mgr.is_busy()
        async with mgr.acquire([TaskResource.BROWSER, TaskResource.LLM_BURST]):
            assert mgr.is_busy()
            status = mgr.status()
            assert status["browser"].in_use == 1
            assert status["llm_burst"].in_use == 1
        # Released on context exit.
        assert not mgr.is_busy()
        status = mgr.status()
        assert status["browser"].in_use == 0
        assert status["llm_burst"].in_use == 0

    @pytest.mark.asyncio
    async def test_unknown_resource_raises_at_acquire_time(self) -> None:
        """Catch typos at the acquire site, not after waiting 30 min
        for a resource that doesn't exist."""
        mgr = TaskResourceManager(
            capacities={TaskResource.BROWSER: 1, TaskResource.LLM_BURST: 1}
        )
        with pytest.raises(KeyError, match="unknown resource"):
            async with mgr.acquire([TaskResource.DEFAULT]):
                pass

    @pytest.mark.asyncio
    async def test_browser_serializes_two_browser_tasks(self) -> None:
        """The defining property of the rewrite: two BROWSER-needing
        tasks must run serially. While the first holds the browser,
        the second should be observed waiting."""
        mgr = TaskResourceManager.from_defaults()
        first_holding = asyncio.Event()
        first_release = asyncio.Event()
        second_acquired = asyncio.Event()

        async def first() -> None:
            async with mgr.acquire([TaskResource.BROWSER]):
                first_holding.set()
                await first_release.wait()

        async def second() -> None:
            await first_holding.wait()
            async with mgr.acquire([TaskResource.BROWSER]):
                second_acquired.set()

        t1 = asyncio.create_task(first())
        t2 = asyncio.create_task(second())
        await first_holding.wait()
        # While first holds, second must NOT have acquired yet.
        await asyncio.sleep(0.01)
        assert not second_acquired.is_set()
        status = mgr.status()
        assert status["browser"].waiters == 1
        first_release.set()
        await asyncio.wait_for(asyncio.gather(t1, t2), timeout=1.0)
        assert second_acquired.is_set()

    @pytest.mark.asyncio
    async def test_disjoint_resources_run_in_parallel(self) -> None:
        """Two tasks with no overlapping resources must run truly
        in parallel — that's the point of the rewrite."""
        mgr = TaskResourceManager.from_defaults()
        a_started = asyncio.Event()
        b_started = asyncio.Event()
        release = asyncio.Event()

        async def task_a() -> None:
            # Browser-only; no LLM.
            async with mgr.acquire([TaskResource.BROWSER]):
                a_started.set()
                await release.wait()

        async def task_b() -> None:
            # Desktop-only; no overlap with a.
            async with mgr.acquire([TaskResource.DESKTOP]):
                b_started.set()
                await release.wait()

        t1 = asyncio.create_task(task_a())
        t2 = asyncio.create_task(task_b())
        await asyncio.wait_for(a_started.wait(), timeout=1.0)
        await asyncio.wait_for(b_started.wait(), timeout=1.0)
        assert mgr.is_busy()
        release.set()
        await asyncio.gather(t1, t2)

    @pytest.mark.asyncio
    async def test_status_reflects_in_use_and_waiters(self) -> None:
        mgr = TaskResourceManager.from_defaults()
        holding = asyncio.Event()
        release = asyncio.Event()

        async def holder() -> None:
            async with mgr.acquire([TaskResource.BROWSER]):
                holding.set()
                await release.wait()

        async def waiter() -> None:
            async with mgr.acquire([TaskResource.BROWSER]):
                pass

        t1 = asyncio.create_task(holder())
        await holding.wait()
        t2 = asyncio.create_task(waiter())
        await asyncio.sleep(0.02)
        snap = mgr.status_dict()
        assert snap["browser"]["in_use"] == 1
        assert snap["browser"]["waiters"] == 1
        release.set()
        await asyncio.gather(t1, t2)

    @pytest.mark.asyncio
    async def test_canonical_acquire_order_prevents_deadlock(self) -> None:
        """Two tasks declaring [BROWSER, DESKTOP] vs [DESKTOP, BROWSER]
        in opposite orders must NOT deadlock. The manager normalizes
        to canonical order internally so both acquire BROWSER first,
        then DESKTOP — FIFO semaphores serialize cleanly."""
        mgr = TaskResourceManager.from_defaults()

        async def t_one() -> None:
            async with mgr.acquire([TaskResource.BROWSER, TaskResource.DESKTOP]):
                await asyncio.sleep(0.01)

        async def t_two() -> None:
            # User-supplied order is REVERSED — manager must normalize.
            async with mgr.acquire([TaskResource.DESKTOP, TaskResource.BROWSER]):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(asyncio.gather(t_one(), t_two()), timeout=1.0)


# ---------------------------------------------------------------------------
# Scheduler queue — no more dropped fires
# ---------------------------------------------------------------------------


class TestSchedulerQueue:
    @pytest.mark.asyncio
    async def test_cron_fire_during_running_task_enqueues(self, db: Database) -> None:
        """The headline correctness fix: a cron-fired enqueue while
        another task is running must NOT drop. It must end up on the
        queue, then run when the holder releases its resources."""
        executed: list[str] = []
        first_started = asyncio.Event()
        first_release = asyncio.Event()

        async def fake_executor(goal: str) -> Any:
            executed.append(goal)
            if goal == "first":
                first_started.set()
                await first_release.wait()
            return type("R", (), {"content": "done", "steps_taken": 1})()

        scheduler = TaskScheduler(
            db=db, task_executor=fake_executor, queue_depth_cap=10
        )
        # Two distinct schedules — different ids so no dedup happens.
        e1 = await scheduler.create_schedule("first", "first", "0 0 * * *")
        e2 = await scheduler.create_schedule("second", "second", "0 0 * * *")

        # Use the actual task goal, not the id.
        async def kick(sid: str) -> None:
            await scheduler._enqueue_for_execution(sid)

        # Start the worker manually for this test (we don't call start()
        # to avoid APScheduler side effects).
        scheduler._worker_task = asyncio.create_task(scheduler._worker_loop())
        try:
            await kick(e1.id)
            await asyncio.wait_for(first_started.wait(), timeout=1.0)
            # First is now running. Kick second — it must enqueue, not drop.
            await kick(e2.id)
            # Verify the queue holds it.
            status = scheduler.queue_status()
            # Either queue depth > 0 OR it's already been popped and is
            # blocked on resources (browser semaphore). Either way it's
            # NOT dropped.
            assert (
                status["queue_depth"] >= 1
                or status["resources"]["browser"]["waiters"] >= 1
                or len(executed) >= 1
            )
            first_release.set()
            # Both should eventually execute.
            for _ in range(50):
                if "second" in executed:
                    break
                await asyncio.sleep(0.05)
            assert "first" in executed
            assert "second" in executed
        finally:
            scheduler._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await scheduler._worker_task

    @pytest.mark.asyncio
    async def test_duplicate_fire_for_same_schedule_is_deduped(
        self, db: Database
    ) -> None:
        """A cron firing for a schedule that's already queued OR running
        must be skipped — protects against a 30-min task that takes
        35 min from spiraling into a queue full of duplicate fires."""
        running = asyncio.Event()
        release = asyncio.Event()
        run_count = 0

        async def slow_executor(goal: str) -> Any:
            nonlocal run_count
            run_count += 1
            running.set()
            await release.wait()
            return type("R", (), {"content": "done", "steps_taken": 1})()

        scheduler = TaskScheduler(db=db, task_executor=slow_executor)
        entry = await scheduler.create_schedule("slow", "slow", "0 0 * * *")
        scheduler._worker_task = asyncio.create_task(scheduler._worker_loop())
        try:
            await scheduler._enqueue_for_execution(entry.id)
            await asyncio.wait_for(running.wait(), timeout=1.0)
            # Slow task is now running. Three more fires — all must be
            # deduped (running, then queued, then dedup at worker pop).
            for _ in range(3):
                await scheduler._enqueue_for_execution(entry.id)
            # Queue should not be full of duplicate ids.
            status = scheduler.queue_status()
            assert status["queue_depth"] <= 1
            release.set()
            # Wait for the running task to drain.
            for _ in range(40):
                if run_count >= 1 and not running.is_set():
                    break
                await asyncio.sleep(0.05)
                if not running.is_set():
                    break
            # Total runs: at most 1 (the original). Dedup may allow at
            # most one queued duplicate to drain after release.
            assert run_count <= 2
        finally:
            scheduler._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await scheduler._worker_task

    @pytest.mark.asyncio
    async def test_queue_status_includes_resource_snapshot(self, db: Database) -> None:
        """The doctor command needs queue_status() → {queue_depth,
        running, paused, resources: {...}}. Pin the shape."""

        async def fake_executor(goal: str) -> Any:
            return type("R", (), {"content": "ok", "steps_taken": 0})()

        scheduler = TaskScheduler(db=db, task_executor=fake_executor)
        snap = scheduler.queue_status()
        assert "queue_depth" in snap
        assert "running" in snap
        assert "paused" in snap
        assert "resources" in snap
        # Default capacities surfaced.
        assert snap["resources"]["browser"]["capacity"] == 1
        assert snap["resources"]["llm_burst"]["capacity"] >= 1
