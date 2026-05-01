"""SwarmProject persistence + lookup tests.

Spawn() itself shells out to git/tmux which we don't run in unit tests; here
we test the project layer directly: persist, load, list, archive, idempotent
upsert, and that archived projects don't reappear in default listings.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.config import SwarmConfig
from core.database import Database
from core.swarm import SwarmManager, SwarmProject


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def swarm_manager(db: Database, tmp_path: Path) -> SwarmManager:
    config = SwarmConfig(enabled=True)
    return SwarmManager(
        db=db,
        config=config,
        project_root=tmp_path,
        gateway=MagicMock(),
    )


class TestSwarmProjects:
    @pytest.mark.asyncio
    async def test_persist_and_load(self, swarm_manager: SwarmManager) -> None:
        proj = SwarmProject(
            name="wellness-tracker",
            repo_kind="local",
            repo=None,
            worktree_path="/tmp/elophanto/swarm/wellness",
            main_branch="main",
            last_branch="swarm/wellness/init",
            agents_run=1,
            status="active",
            created_at="2026-05-01T00:00:00+00:00",
            last_spawn_at="2026-05-01T00:00:00+00:00",
            description="wellness app v1",
        )
        await swarm_manager._persist_project(proj)

        loaded = await swarm_manager._load_project("wellness-tracker")
        assert loaded is not None
        assert loaded.name == "wellness-tracker"
        assert loaded.repo_kind == "local"
        assert loaded.repo is None
        assert loaded.worktree_path == "/tmp/elophanto/swarm/wellness"
        assert loaded.agents_run == 1

    @pytest.mark.asyncio
    async def test_persist_is_upsert(self, swarm_manager: SwarmManager) -> None:
        """Persisting twice with the same name updates, doesn't duplicate."""
        proj = SwarmProject(
            name="invoice-bot",
            repo_kind="github",
            repo="https://github.com/me/invoice-bot",
            worktree_path="/tmp/wt/invoice-bot",
            agents_run=1,
            created_at="2026-05-01T00:00:00+00:00",
            last_spawn_at="2026-05-01T00:00:00+00:00",
        )
        await swarm_manager._persist_project(proj)

        proj.agents_run = 2
        proj.last_spawn_at = "2026-05-02T00:00:00+00:00"
        proj.last_branch = "swarm/invoice-bot/update-fix-totals"
        proj.last_pr_url = "https://github.com/me/invoice-bot/pull/3"
        await swarm_manager._persist_project(proj)

        all_projects = await swarm_manager.list_projects()
        assert len(all_projects) == 1
        assert all_projects[0].agents_run == 2
        assert all_projects[0].last_branch == "swarm/invoice-bot/update-fix-totals"
        assert all_projects[0].last_pr_url == "https://github.com/me/invoice-bot/pull/3"

    @pytest.mark.asyncio
    async def test_list_orders_by_last_spawn(self, swarm_manager: SwarmManager) -> None:
        """Most recently active project comes first."""
        await swarm_manager._persist_project(
            SwarmProject(
                name="older",
                repo_kind="local",
                repo=None,
                worktree_path="/tmp/older",
                created_at="2026-01-01T00:00:00+00:00",
                last_spawn_at="2026-01-01T00:00:00+00:00",
            )
        )
        await swarm_manager._persist_project(
            SwarmProject(
                name="newer",
                repo_kind="local",
                repo=None,
                worktree_path="/tmp/newer",
                created_at="2026-05-01T00:00:00+00:00",
                last_spawn_at="2026-05-01T00:00:00+00:00",
            )
        )
        projects = await swarm_manager.list_projects()
        assert [p.name for p in projects] == ["newer", "older"]

    @pytest.mark.asyncio
    async def test_archive_hides_from_default_list(
        self, swarm_manager: SwarmManager
    ) -> None:
        await swarm_manager._persist_project(
            SwarmProject(
                name="dead-project",
                repo_kind="local",
                repo=None,
                worktree_path="/tmp/dead",
                created_at="2026-01-01T00:00:00+00:00",
                last_spawn_at="2026-01-01T00:00:00+00:00",
            )
        )
        ok = await swarm_manager.archive_project("dead-project", reason="shipped")
        assert ok is True

        # Default list excludes archived
        active = await swarm_manager.list_projects()
        assert active == []

        # Explicit include_archived shows it
        all_projects = await swarm_manager.list_projects(include_archived=True)
        assert len(all_projects) == 1
        assert all_projects[0].status == "archived"
        assert all_projects[0].metadata.get("archive_reason") == "shipped"

    @pytest.mark.asyncio
    async def test_archive_unknown_project_returns_false(
        self, swarm_manager: SwarmManager
    ) -> None:
        ok = await swarm_manager.archive_project("nonexistent")
        assert ok is False

    @pytest.mark.asyncio
    async def test_repo_kind_local_with_no_remote(
        self, swarm_manager: SwarmManager
    ) -> None:
        """Local-only projects must persist with repo=None and survive round-trip."""
        await swarm_manager._persist_project(
            SwarmProject(
                name="private-tool",
                repo_kind="local",
                repo=None,
                worktree_path="/tmp/private",
                created_at="2026-05-01T00:00:00+00:00",
                last_spawn_at="2026-05-01T00:00:00+00:00",
            )
        )
        loaded = await swarm_manager._load_project("private-tool")
        assert loaded is not None
        assert loaded.repo_kind == "local"
        assert loaded.repo is None

    @pytest.mark.asyncio
    async def test_auto_project_name_strips_leading_verb(
        self, swarm_manager: SwarmManager
    ) -> None:
        """build a wellness app → wellness-app, not build-a-wellness-app."""
        slug = await swarm_manager._auto_project_name("build a wellness tracker app")
        assert slug == "wellness-tracker-app"

        slug = await swarm_manager._auto_project_name("Create the invoice bot")
        assert slug == "invoice-bot"

        slug = await swarm_manager._auto_project_name("ship a landing page")
        assert slug == "landing-page"

    @pytest.mark.asyncio
    async def test_auto_project_name_dedups_on_collision(
        self, swarm_manager: SwarmManager
    ) -> None:
        await swarm_manager._persist_project(
            SwarmProject(
                name="wellness-tracker-app",
                repo_kind="local",
                repo=None,
                worktree_path="/tmp/wt",
                created_at="2026-05-01T00:00:00+00:00",
                last_spawn_at="2026-05-01T00:00:00+00:00",
            )
        )
        slug = await swarm_manager._auto_project_name("build a wellness tracker app")
        assert slug == "wellness-tracker-app-2"

        await swarm_manager._persist_project(
            SwarmProject(
                name="wellness-tracker-app-2",
                repo_kind="local",
                repo=None,
                worktree_path="/tmp/wt2",
                created_at="2026-05-01T00:00:00+00:00",
                last_spawn_at="2026-05-01T00:00:00+00:00",
            )
        )
        slug = await swarm_manager._auto_project_name("build a wellness tracker app")
        assert slug == "wellness-tracker-app-3"

    @pytest.mark.asyncio
    async def test_get_project_normalizes_slug(
        self, swarm_manager: SwarmManager
    ) -> None:
        """get_project should accept user-friendly names and find the slugged row."""
        await swarm_manager._persist_project(
            SwarmProject(
                name="wellness-tracker",
                repo_kind="local",
                repo=None,
                worktree_path="/tmp/wt",
                created_at="2026-05-01T00:00:00+00:00",
                last_spawn_at="2026-05-01T00:00:00+00:00",
            )
        )
        # Same as exact slug
        assert (await swarm_manager.get_project("wellness-tracker")) is not None
        # User typed it with spaces / different casing
        loaded = await swarm_manager.get_project("Wellness Tracker")
        assert loaded is not None
        assert loaded.name == "wellness-tracker"
