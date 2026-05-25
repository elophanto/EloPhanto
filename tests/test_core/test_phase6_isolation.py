"""Multi-company isolation primitives (ABE framework Phase 6).

Locks in the Phase 6 contract from docs/76-ABE-FRAMEWORK.md:
- ClientConnection defaults company_id to 'elophanto-self'.
- Gateway.broadcast(company_id=...) filters fan-out by connection
  company; no filter = legacy fan-to-all behavior.
- CompanyManager.create materializes per-company data dir when
  project_root is set; no-op when unset; idempotent.
- Scheduler dispatch sets current_company contextvar for the task
  scope and restores it afterward (incl. on failure).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.company import (
    CompanyManager,
    current_company_id,
    reset_current_company,
    set_current_company,
)
from core.database import Database
from core.gateway import ClientConnection, Gateway
from core.protocol import GatewayMessage
from core.session import SessionManager


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()
    return db


class TestClientConnectionDefault:
    def test_default_company_is_elophanto_self(self) -> None:
        conn = ClientConnection(client_id="x", websocket=MagicMock())
        assert conn.company_id == "elophanto-self"

    def test_company_can_be_overridden(self) -> None:
        conn = ClientConnection(
            client_id="x",
            websocket=MagicMock(),
            company_id="acme-inc",
        )
        assert conn.company_id == "acme-inc"


class TestGatewayBroadcastFilter:
    """Phase 6 added an optional ``company_id`` filter on
    ``Gateway.broadcast``. Tests use the gateway's internal dicts
    directly rather than starting a real websockets server."""

    def _build_gateway(self) -> Gateway:
        agent = MagicMock()
        sessions = MagicMock(spec=SessionManager)
        return Gateway(agent=agent, session_manager=sessions)

    @pytest.mark.asyncio
    async def test_filter_only_fans_to_matching_company(self) -> None:
        gw = self._build_gateway()
        ws_a, ws_b = AsyncMock(), AsyncMock()
        gw._clients["a"] = ClientConnection(
            client_id="a", websocket=ws_a, company_id="acme-inc"
        )
        gw._clients["b"] = ClientConnection(
            client_id="b", websocket=ws_b, company_id="elophanto-self"
        )

        msg = GatewayMessage(type="event", data={"hello": "world"})
        await gw.broadcast(msg, company_id="acme-inc")

        ws_a.send.assert_awaited_once()
        ws_b.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_filter_fans_to_all(self) -> None:
        gw = self._build_gateway()
        ws_a, ws_b = AsyncMock(), AsyncMock()
        gw._clients["a"] = ClientConnection(
            client_id="a", websocket=ws_a, company_id="acme-inc"
        )
        gw._clients["b"] = ClientConnection(
            client_id="b", websocket=ws_b, company_id="elophanto-self"
        )

        msg = GatewayMessage(type="event", data={"hello": "world"})
        await gw.broadcast(msg)

        ws_a.send.assert_awaited_once()
        ws_b.send.assert_awaited_once()


class TestPerCompanyDataDir:
    @pytest.mark.asyncio
    async def test_create_makes_data_dir(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        await mgr.create("acme-inc", "Acme Inc")
        expected = tmp_path / "data" / "companies" / "acme-inc"
        assert expected.is_dir()

    @pytest.mark.asyncio
    async def test_ensure_data_dir_idempotent(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        path1 = mgr.ensure_data_dir("seed-co")
        path2 = mgr.ensure_data_dir("seed-co")
        assert path1 is not None
        assert path1 == path2
        assert path1.is_dir()

    @pytest.mark.asyncio
    async def test_no_project_root_no_dir(self, db: Database) -> None:
        mgr = CompanyManager(db=db)  # no project_root
        # create() still works; data_dir resolves to None
        await mgr.create("rootless-co", "Rootless")
        assert mgr.data_dir("rootless-co") is None
        assert mgr.ensure_data_dir("rootless-co") is None


class TestSchedulerCompanyScope:
    """Scheduler should activate the task's company in the contextvar
    for the task's execution scope and restore it afterward, even on
    failure. We assert the contextvar behaviour at the
    ``_execute_schedule_body`` level — a real cron firing isn't
    needed for this contract."""

    @pytest.mark.asyncio
    async def test_dispatch_sets_and_restores_current_company(
        self, db: Database
    ) -> None:
        from core.scheduler import ScheduleEntry, TaskScheduler

        seen: list[str] = []

        async def _task_executor(goal: str, **kwargs):
            # Read the active company while the task is running.
            seen.append(current_company_id())
            # Return something shaped like the agent's response —
            # the scheduler reads .content / .steps_taken / .preempted
            return MagicMock(content="ok", steps_taken=1, preempted=False)

        sched = TaskScheduler(
            db=db,
            task_executor=_task_executor,
        )

        # Seed a schedule row so the body's UPDATE doesn't fail.
        await db.execute_insert(
            "INSERT INTO scheduled_tasks "
            "(id, name, description, cron_expression, task_goal, "
            "created_at, updated_at, company_id) "
            "VALUES (?, ?, '', '* * * * *', 'do x', ?, ?, ?)",
            ("sch-1", "Test", "2026-05-25", "2026-05-25", "acme-inc"),
        )

        entry = ScheduleEntry(
            id="sch-1",
            name="Test",
            description="",
            cron_expression="* * * * *",
            task_goal="do x",
            company_id="acme-inc",
        )

        # Pin the operator's "currently active" company to something
        # else so we can prove the scheduler swaps in the task's
        # company for the dispatch scope only.
        prev_token = set_current_company("elophanto-self")
        try:
            assert current_company_id() == "elophanto-self"
            await sched._execute_schedule_body("sch-1", entry)
            # Inside the task callback the contextvar was acme-inc.
            assert seen == ["acme-inc"]
            # Outside the task callback the contextvar is restored.
            assert current_company_id() == "elophanto-self"
        finally:
            reset_current_company(prev_token)

    @pytest.mark.asyncio
    async def test_dispatch_restores_company_on_failure(self, db: Database) -> None:
        from core.scheduler import ScheduleEntry, TaskScheduler

        async def _failing_executor(goal: str, **kwargs):
            raise RuntimeError("boom")

        sched = TaskScheduler(db=db, task_executor=_failing_executor)
        await db.execute_insert(
            "INSERT INTO scheduled_tasks "
            "(id, name, description, cron_expression, task_goal, "
            "created_at, updated_at, company_id) "
            "VALUES (?, ?, '', '* * * * *', 'do x', ?, ?, ?)",
            ("sch-2", "Failer", "2026-05-25", "2026-05-25", "acme-inc"),
        )
        entry = ScheduleEntry(
            id="sch-2",
            name="Failer",
            description="",
            cron_expression="* * * * *",
            task_goal="do x",
            company_id="acme-inc",
        )

        prev_token = set_current_company("elophanto-self")
        try:
            # _execute_schedule_body swallows exceptions internally
            # (logs failure to schedule_runs) so we don't expect it
            # to raise. The important contract is restoration.
            await sched._execute_schedule_body("sch-2", entry)
            assert current_company_id() == "elophanto-self"
        finally:
            reset_current_company(prev_token)
