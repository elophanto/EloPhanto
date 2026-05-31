"""Role manager + role overlay (ABE framework Phase 2).

Locks in the Phase 2 contract from docs/76-ABE-FRAMEWORK.md:
- RoleManager.sync_from_disk reads roles/*.yaml and upserts idempotently
- is_tool_allowed pure-function semantics (empty → full; name OR group match)
- Identity context appends <role> when contextvar is set
- Executor role gate denies tools outside allowlist
- Mission.owner_role + Goal.assigned_to_role round-trip
- from_role_neglect yields candidates ranked by neglect
- Role contextvar defaults to None
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from core.database import Database
from core.role import Role, RoleManager
from core.role_context import (
    current_role,
    reset_current_role,
    set_current_role,
)


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()
    return db


@pytest.fixture
async def mgr(db: Database, tmp_path) -> RoleManager:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    return RoleManager(db=db, roles_dir=roles_dir)


def _write_yaml(dir: Path, name: str, data: dict) -> Path:
    path = dir / f"{name}.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


class TestYamlSync:
    @pytest.mark.asyncio
    async def test_role_yaml_sync_creates_rows(self, db: Database, tmp_path) -> None:
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir()
        _write_yaml(
            roles_dir,
            "sales",
            {
                "name": "sales",
                "description": "Pipeline movement",
                "prompt_overlay": "You are SALES.",
                "allowed_tools": ["email_send"],
                "kpi": {"email_sent": 20},
            },
        )
        _write_yaml(
            roles_dir,
            "support",
            {"name": "support", "description": "Inbound triage"},
        )
        mgr = RoleManager(db=db, roles_dir=roles_dir)

        count = await mgr.sync_from_disk()
        assert count == 2

        # Idempotent — second sync inserts nothing new.
        count2 = await mgr.sync_from_disk()
        assert count2 == 2  # upsert returns same count
        roles = await mgr.list_roles()
        assert {r.name for r in roles} == {"sales", "support"}
        sales = await mgr.get("sales")
        assert sales is not None
        assert sales.allowed_tools == ["email_send"]
        assert sales.kpi == {"email_sent": 20}
        assert sales.prompt_overlay == "You are SALES."


class TestIsToolAllowed:
    def test_empty_means_full(self) -> None:
        role = Role(
            name="ceo",
            allowed_tools=[],
            allowed_tool_groups=[],
        )
        assert RoleManager.is_tool_allowed(role, "shell_execute", None) is True
        assert RoleManager.is_tool_allowed(role, "anything", "any_group") is True

    def test_name_match(self) -> None:
        role = Role(
            name="sales",
            allowed_tools=["email_send"],
            allowed_tool_groups=[],
        )
        assert RoleManager.is_tool_allowed(role, "email_send", None) is True
        assert RoleManager.is_tool_allowed(role, "shell_execute", None) is False

    def test_group_match(self) -> None:
        role = Role(
            name="support",
            allowed_tools=[],
            allowed_tool_groups=["email"],
        )
        # name not in list, but group is → allowed
        assert RoleManager.is_tool_allowed(role, "email_send", "email") is True
        assert RoleManager.is_tool_allowed(role, "email_reply", "email") is True
        # different group → denied
        assert RoleManager.is_tool_allowed(role, "shell_execute", "system") is False

    def test_meta_tools_exempt_from_role_gate(self) -> None:
        """Meta / mind-internal tools must bypass even a very narrow allowlist.

        Reproduces the production paralysis where an OPS-style role
        (allowlist of one) denied the autonomous mind from updating
        its scratchpad, scheduling its next wakeup, switching roles,
        and reading skills.
        """
        narrow = Role(
            name="ops",
            allowed_tools=["http_get"],
            allowed_tool_groups=[],
        )
        # Mind-internal bookkeeping
        assert RoleManager.is_tool_allowed(narrow, "update_scratchpad") is True
        assert RoleManager.is_tool_allowed(narrow, "set_next_wakeup") is True
        assert RoleManager.is_tool_allowed(narrow, "affect_record_event") is True
        # Role meta — the agent must always be able to escape the role
        assert RoleManager.is_tool_allowed(narrow, "role_list") is True
        assert RoleManager.is_tool_allowed(narrow, "role_show") is True
        assert RoleManager.is_tool_allowed(narrow, "role_use") is True
        # Read-only introspection
        assert RoleManager.is_tool_allowed(narrow, "skill_list") is True
        assert RoleManager.is_tool_allowed(narrow, "skill_read") is True
        assert RoleManager.is_tool_allowed(narrow, "company_list") is True
        assert RoleManager.is_tool_allowed(narrow, "company_report") is True
        # Write-side tools stay gated (denying these is correct)
        assert RoleManager.is_tool_allowed(narrow, "company_set_product") is False
        assert RoleManager.is_tool_allowed(narrow, "company_plan_apply") is False
        assert RoleManager.is_tool_allowed(narrow, "shell_execute") is False


class TestIdentityRoleOverlay:
    @pytest.mark.asyncio
    async def test_role_persona_persists_on_identity(self, db: Database) -> None:
        await db.execute_insert(
            "INSERT INTO identity (id, created_at, updated_at, role_persona) "
            "VALUES ('self', ?, ?, ?)",
            ("2026-05-25", "2026-05-25", "sales"),
        )
        rows = await db.execute("SELECT role_persona FROM identity")
        assert rows[0]["role_persona"] == "sales"

    @pytest.mark.asyncio
    async def test_identity_context_includes_role(
        self, db: Database, mgr: RoleManager
    ) -> None:
        # Minimal identity setup without bootstrapping the LLM.
        from unittest.mock import MagicMock

        from core.config import IdentityConfig
        from core.identity import IdentityManager

        await mgr.upsert(
            name="sales",
            description="Pipeline",
            prompt_overlay="You are SALES.",
        )
        ident_cfg = IdentityConfig(enabled=True)
        router = MagicMock()
        im = IdentityManager(db=db, router=router, config=ident_cfg)
        im._role_manager = mgr
        # Skip first-awakening LLM by inserting a default identity row
        await db.execute_insert(
            "INSERT INTO identity (id, created_at, updated_at) "
            "VALUES ('self', ?, ?)",
            ("2026-05-25", "2026-05-25"),
        )
        await im.load_or_create()

        token = set_current_role("sales")
        try:
            ctx = await im.build_identity_context()
        finally:
            reset_current_role(token)

        assert "<role>sales</role>" in ctx
        assert "You are SALES." in ctx

    @pytest.mark.asyncio
    async def test_identity_context_no_role_unchanged(
        self, db: Database, mgr: RoleManager
    ) -> None:
        from unittest.mock import MagicMock

        from core.config import IdentityConfig
        from core.identity import IdentityManager

        ident_cfg = IdentityConfig(enabled=True)
        router = MagicMock()
        im = IdentityManager(db=db, router=router, config=ident_cfg)
        im._role_manager = mgr
        await db.execute_insert(
            "INSERT INTO identity (id, created_at, updated_at) "
            "VALUES ('self', ?, ?)",
            ("2026-05-25", "2026-05-25"),
        )
        await im.load_or_create()

        # Default contextvar = None — no role overlay should appear.
        ctx = await im.build_identity_context()
        assert "<role>" not in ctx
        assert "<role_overlay>" not in ctx


class TestRoleContextVar:
    def test_default_is_none(self) -> None:
        # Wrap in a fresh sub-context so other tests' state can't leak.
        import contextvars

        ctx = contextvars.copy_context()

        def _check() -> str | None:
            return current_role()

        # Default contextvar value: None means "playing CEO".
        assert ctx.run(_check) is None

    def test_set_and_reset(self) -> None:
        token = set_current_role("sales")
        try:
            assert current_role() == "sales"
        finally:
            reset_current_role(token)
        assert current_role() is None


class TestMissionGoalRoleFields:
    @pytest.mark.asyncio
    async def test_mission_create_with_owner_role(self, db: Database) -> None:
        from core.mission_manager import MissionManager

        mm = MissionManager(db=db)
        m = await mm.create(
            title="Grow pipeline",
            description="50 qualified/wk",
            owner_role="sales",
        )
        assert m.owner_role == "sales"

        # Round-trip through DB
        m2 = await mm.get(m.mission_id)
        assert m2 is not None
        assert m2.owner_role == "sales"

    @pytest.mark.asyncio
    async def test_goal_create_with_assigned_to_role(self, db: Database) -> None:
        from unittest.mock import MagicMock

        from core.config import GoalsConfig
        from core.goal_manager import GoalManager

        gm_cfg = GoalsConfig()
        router = MagicMock()
        gm = GoalManager(db=db, router=router, config=gm_cfg)
        g = await gm.create_goal("ship the demo", assigned_to_role="sales")
        assert g.assigned_to_role == "sales"

        g2 = await gm.get_goal(g.goal_id)
        assert g2 is not None
        assert g2.assigned_to_role == "sales"


class TestFromRoleNeglect:
    @pytest.mark.asyncio
    async def test_yields_candidate_per_role_ranked_by_neglect(
        self, db: Database, mgr: RoleManager
    ) -> None:
        from core.mind_candidates import CandidateContext, from_role_neglect

        # Three roles: one never active, one stale 48h, one fresh 1h.
        await mgr.upsert(name="never", description="Never run")
        await mgr.upsert(name="stale", description="Stale")
        await mgr.upsert(name="fresh", description="Fresh")

        # Manually set last_active_at to control ordering.
        now = datetime.now(UTC)
        await db.execute(
            "UPDATE roles SET last_active_at = ? WHERE role_name = ?",
            ((now - timedelta(hours=48)).isoformat(), "stale"),
        )
        await db.execute(
            "UPDATE roles SET last_active_at = ? WHERE role_name = ?",
            ((now - timedelta(hours=1)).isoformat(), "fresh"),
        )

        ctx = CandidateContext(role_manager=mgr)
        candidates = await from_role_neglect(ctx)

        # All three roles surface as candidates
        names = [c.metadata["role_name"] for c in candidates]
        assert set(names) == {"never", "stale", "fresh"}

        # 'never' should rank first (highest staleness_bonus)
        by_name = {c.metadata["role_name"]: c for c in candidates}
        assert by_name["never"].staleness_bonus >= by_name["stale"].staleness_bonus
        assert by_name["stale"].staleness_bonus >= by_name["fresh"].staleness_bonus

    @pytest.mark.asyncio
    async def test_empty_without_role_manager(self) -> None:
        from core.mind_candidates import CandidateContext, from_role_neglect

        ctx = CandidateContext()  # no role_manager
        assert await from_role_neglect(ctx) == []


class TestExecutorRoleGate:
    @pytest.mark.asyncio
    async def test_denies_tool_outside_role(
        self, db: Database, mgr: RoleManager
    ) -> None:
        # Set up a sales role with only email_send allowed.
        await mgr.upsert(
            name="sales",
            description="Pipeline",
            allowed_tools=["email_send"],
        )

        from core.config import load_config
        from core.executor import Executor
        from core.registry import ToolRegistry
        from tools.base import BaseTool, PermissionLevel, ToolResult

        config = load_config()
        registry = ToolRegistry(project_root=config.project_root)

        # Register a minimal stub tool so executor's tool-lookup
        # doesn't short-circuit before the role gate fires.
        class _StubShell(BaseTool):
            name = "shell_execute"
            description = "stub"
            input_schema = {"type": "object", "properties": {}}
            permission_level = PermissionLevel.SAFE

            async def execute(self, params):
                return ToolResult(success=True, data={})

        registry.register(_StubShell())

        ex = Executor(config=config, registry=registry)
        ex._role_manager = mgr

        token = set_current_role("sales")
        try:
            # 'shell_execute' is not in the sales allowlist.
            result = await ex.execute(
                {
                    "id": "call-1",
                    "function": {
                        "name": "shell_execute",
                        "arguments": "{}",
                    },
                }
            )
        finally:
            reset_current_role(token)

        assert result.denied is True
        assert result.error is not None
        assert "sales" in result.error
        assert "shell_execute" in result.error
