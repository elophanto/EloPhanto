"""KidManager tests — registry, persistence, dedup, destroy, restart-from-DB.

Container-actually-running cases are integration-only; here we mock the
runtime so unit tests run anywhere (no docker required)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.config import KidConfig
from core.database import Database
from core.kid_manager import KidAgent, KidManager
from core.kid_runtime import ContainerRuntime, ContainerRuntimeError


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


def _fake_runtime() -> MagicMock:
    """A mock runtime that records calls and pretends operations succeed."""
    rt = MagicMock(spec=ContainerRuntime)
    rt.name = "docker"
    rt.is_available = AsyncMock(return_value=True)
    rt.create_volume = AsyncMock()
    rt.remove_volume = AsyncMock()
    rt.start = AsyncMock(return_value="container-id-12345abcdef")
    rt.stop = AsyncMock()
    rt.remove = AsyncMock()
    rt.inspect = AsyncMock(return_value={"State": {"Running": True}})
    return rt


@pytest.fixture
def config() -> KidConfig:
    return KidConfig(
        enabled=True,
        spawn_cooldown_seconds=0,  # disable for fast tests
        max_concurrent_kids=3,
    )


class TestKidManagerLifecycle:
    @pytest.mark.asyncio
    async def test_runtime_unavailable_does_not_crash_start(
        self, db: Database, config: KidConfig
    ) -> None:
        """Missing runtime is a known state — start() must succeed but
        flag runtime_available=False."""
        from unittest.mock import patch

        with patch("core.kid_manager.detect_runtime", AsyncMock(return_value=None)):
            mgr = KidManager(db=db, config=config)
            await mgr.start()
            try:
                assert mgr.runtime_available is False
                # spawn must refuse with a clear error
                with pytest.raises(RuntimeError, match="No container runtime"):
                    await mgr.spawn(purpose="test")
            finally:
                await mgr.stop()

    @pytest.mark.asyncio
    async def test_disabled_config_skips_setup(self, db: Database) -> None:
        """When kids.enabled=false, start() is a no-op and spawn refuses."""
        cfg = KidConfig(enabled=False)
        mgr = KidManager(db=db, config=cfg)
        await mgr.start()  # should not raise
        with pytest.raises(RuntimeError, match="disabled"):
            await mgr.spawn(purpose="test")


class TestKidManagerSpawn:
    @pytest.mark.asyncio
    async def test_spawn_persists_kid_to_db(
        self, db: Database, config: KidConfig
    ) -> None:
        mgr = KidManager(db=db, config=config)
        mgr._runtime = _fake_runtime()  # bypass detect

        kid = await mgr.spawn(
            purpose="test installing cowsay",
            vault_scope=[],
        )
        assert kid.kid_id
        assert kid.name.startswith("test-installing-cowsay")
        assert kid.status == "running"
        assert kid.volume_name.startswith("elophanto-kid-")
        assert kid.vault_scope == []  # empty by default

        # Verify it's in DB
        rows = await db.execute(
            "SELECT * FROM kid_agents WHERE kid_id = ?", (kid.kid_id,)
        )
        assert len(rows) == 1
        assert rows[0]["status"] == "running"
        assert rows[0]["name"] == kid.name

    @pytest.mark.asyncio
    async def test_spawn_dedups_name(self, db: Database, config: KidConfig) -> None:
        mgr = KidManager(db=db, config=config)
        mgr._runtime = _fake_runtime()

        kid1 = await mgr.spawn(purpose="install nodejs")
        kid2 = await mgr.spawn(purpose="install nodejs")
        # Same purpose → first gets clean slug, second gets a unique suffix
        assert kid1.name != kid2.name

    @pytest.mark.asyncio
    async def test_spawn_respects_max_concurrent(
        self, db: Database, config: KidConfig
    ) -> None:
        cfg = KidConfig(enabled=True, spawn_cooldown_seconds=0, max_concurrent_kids=2)
        mgr = KidManager(db=db, config=cfg)
        mgr._runtime = _fake_runtime()

        await mgr.spawn(purpose="task one")
        await mgr.spawn(purpose="task two")
        with pytest.raises(RuntimeError, match="Max concurrent kids"):
            await mgr.spawn(purpose="task three")

    @pytest.mark.asyncio
    async def test_spawn_cleans_volume_on_runtime_failure(
        self, db: Database, config: KidConfig
    ) -> None:
        """If the container fails to start, the volume must NOT leak."""
        mgr = KidManager(db=db, config=config)
        rt = _fake_runtime()
        rt.start = AsyncMock(side_effect=ContainerRuntimeError("boom"))
        mgr._runtime = rt

        with pytest.raises(ContainerRuntimeError):
            await mgr.spawn(purpose="failing")
        # Volume cleanup attempted
        rt.remove_volume.assert_called_once()


class TestKidManagerVaultScoping:
    @pytest.mark.asyncio
    async def test_default_scope_is_empty(
        self, db: Database, config: KidConfig, tmp_path: Path
    ) -> None:
        """No secrets reach the kid by default."""
        from core.vault import Vault

        vault_dir = tmp_path / "vault"
        vault_dir.mkdir(exist_ok=True)
        vault = Vault.create(vault_dir, "pw")
        vault.set("openrouter", "secret-key")
        vault.set("payment", "stripe-secret")

        mgr = KidManager(db=db, config=config, vault=vault)
        mgr._runtime = _fake_runtime()
        kid = await mgr.spawn(purpose="test")
        assert kid.vault_scope == []
        # Inspect the env passed to runtime.start — KID_VAULT_JSON should be absent
        call_kwargs = mgr._runtime.start.call_args.kwargs
        assert "KID_VAULT_JSON" not in call_kwargs["env"]

    @pytest.mark.asyncio
    async def test_explicit_scope_passes_only_listed_keys(
        self, db: Database, config: KidConfig, tmp_path: Path
    ) -> None:
        from core.vault import Vault

        vault_dir = tmp_path / "vault2"
        vault_dir.mkdir(exist_ok=True)
        vault = Vault.create(vault_dir, "pw")
        vault.set("openrouter", "or-key")
        vault.set("payment", "STRIPE-NEVER-LEAK")

        mgr = KidManager(db=db, config=config, vault=vault)
        mgr._runtime = _fake_runtime()
        await mgr.spawn(purpose="needs-or", vault_scope=["openrouter"])
        env = mgr._runtime.start.call_args.kwargs["env"]
        assert "KID_VAULT_JSON" in env
        scoped = json.loads(env["KID_VAULT_JSON"])
        assert scoped == {"openrouter": "or-key"}
        assert "payment" not in scoped


class TestKidManagerLifecycleOps:
    @pytest.mark.asyncio
    async def test_destroy_removes_volume(
        self, db: Database, config: KidConfig
    ) -> None:
        mgr = KidManager(db=db, config=config)
        mgr._runtime = _fake_runtime()
        kid = await mgr.spawn(purpose="ephemeral")
        ok = await mgr.destroy(kid.kid_id)
        assert ok is True
        # Volume removal attempted exactly for this kid's volume
        mgr._runtime.remove_volume.assert_called_with(kid.volume_name)
        # DB row marked stopped
        rows = await db.execute(
            "SELECT status FROM kid_agents WHERE kid_id = ?", (kid.kid_id,)
        )
        assert rows[0]["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_destroy_unknown_returns_false(
        self, db: Database, config: KidConfig
    ) -> None:
        mgr = KidManager(db=db, config=config)
        mgr._runtime = _fake_runtime()
        ok = await mgr.destroy("does-not-exist")
        assert ok is False

    @pytest.mark.asyncio
    async def test_list_excludes_stopped_by_default(
        self, db: Database, config: KidConfig
    ) -> None:
        mgr = KidManager(db=db, config=config)
        mgr._runtime = _fake_runtime()
        a = await mgr.spawn(purpose="alive")
        b = await mgr.spawn(purpose="dead")
        await mgr.destroy(b.kid_id)
        active = await mgr.list_kids()
        assert {k.name for k in active} == {a.name}
        all_kids = await mgr.list_kids(include_stopped=True)
        assert {k.name for k in all_kids} == {a.name, b.name}

    @pytest.mark.asyncio
    async def test_get_kid_by_id_or_name(self, db: Database, config: KidConfig) -> None:
        mgr = KidManager(db=db, config=config)
        mgr._runtime = _fake_runtime()
        kid = await mgr.spawn(purpose="lookup-target")
        assert (await mgr.get_kid(kid.kid_id)) is not None
        assert (await mgr.get_kid(kid.name)) is not None
        assert (await mgr.get_kid("nonexistent")) is None


class TestKidManagerExec:
    @pytest.mark.asyncio
    async def test_exec_returns_kid_response(
        self, db: Database, config: KidConfig
    ) -> None:
        """exec() awaits the kid's terminal message and returns it."""
        mgr = KidManager(db=db, config=config)
        mgr._runtime = _fake_runtime()
        kid = await mgr.spawn(purpose="echo task")

        # Simulate the kid posting a final response back via the gateway.
        async def fake_kid_response() -> None:
            # Tiny delay so exec() has a chance to start awaiting first.
            await asyncio.sleep(0.05)

            class FakeMsg:
                user_id = kid.kid_id
                data = {"content": "[kid echo-task done in 2 steps]\n\nhello"}

            await mgr.handle_kid_message(FakeMsg())

        asyncio.create_task(fake_kid_response())
        response = await mgr.exec(kid.kid_id, "say hello", timeout=2.0)
        assert "done in 2 steps" in response
        assert "hello" in response

    @pytest.mark.asyncio
    async def test_exec_timeout_when_kid_silent(
        self, db: Database, config: KidConfig
    ) -> None:
        """No response within timeout → TimeoutError, not hang forever."""
        mgr = KidManager(db=db, config=config)
        mgr._runtime = _fake_runtime()
        kid = await mgr.spawn(purpose="silent-kid")
        with pytest.raises(TimeoutError):
            await mgr.exec(kid.kid_id, "do something", timeout=0.2)

    @pytest.mark.asyncio
    async def test_exec_drains_stale_messages_before_waiting(
        self, db: Database, config: KidConfig
    ) -> None:
        """A previous task's leftover messages must NOT be returned as
        the response to a new task. Each exec() drains the inbox first."""
        mgr = KidManager(db=db, config=config)
        mgr._runtime = _fake_runtime()
        kid = await mgr.spawn(purpose="drain test")

        # Simulate stale "done" messages from a prior run still in queue.
        class StaleMsg:
            user_id = kid.kid_id
            data = {"content": "[kid drain-test done in 99 steps]\n\nSTALE"}

        await mgr.handle_kid_message(StaleMsg())
        await mgr.handle_kid_message(StaleMsg())

        # Now exec — should drain stale, then time out cleanly because
        # nothing fresh comes in.
        with pytest.raises(TimeoutError):
            await mgr.exec(kid.kid_id, "fresh task", timeout=0.2)

    @pytest.mark.asyncio
    async def test_handle_kid_message_ignores_unknown_kid(
        self, db: Database, config: KidConfig
    ) -> None:
        """Messages from kids the manager doesn't know about don't crash;
        they create an inbox lazily but are otherwise harmless."""
        mgr = KidManager(db=db, config=config)
        mgr._runtime = _fake_runtime()

        class GhostMsg:
            user_id = "ghost-kid-id"
            data = {"content": "from a ghost"}

        await mgr.handle_kid_message(GhostMsg())  # must not raise


class TestKidManagerRestart:
    @pytest.mark.asyncio
    async def test_reload_restores_active_kids(
        self, db: Database, config: KidConfig
    ) -> None:
        """Parent restart should re-attach to existing running kids."""
        mgr1 = KidManager(db=db, config=config)
        mgr1._runtime = _fake_runtime()
        kid = await mgr1.spawn(purpose="long-running")
        assert kid.status == "running"

        # Simulate parent restart with a new manager pointed at same DB
        mgr2 = KidManager(db=db, config=config)
        mgr2._runtime = _fake_runtime()
        await mgr2._reload_from_db()
        assert kid.kid_id in mgr2._kids
        assert mgr2._kids[kid.kid_id].name == kid.name

    @pytest.mark.asyncio
    async def test_reload_skips_stopped_kids(
        self, db: Database, config: KidConfig
    ) -> None:
        mgr1 = KidManager(db=db, config=config)
        mgr1._runtime = _fake_runtime()
        a = await mgr1.spawn(purpose="alive")
        b = await mgr1.spawn(purpose="dead")
        await mgr1.destroy(b.kid_id)

        mgr2 = KidManager(db=db, config=config)
        mgr2._runtime = _fake_runtime()
        await mgr2._reload_from_db()
        assert a.kid_id in mgr2._kids
        assert b.kid_id not in mgr2._kids
