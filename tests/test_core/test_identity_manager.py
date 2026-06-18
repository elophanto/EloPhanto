"""IdentityManager tests — lifecycle, fields, reflection, context, nature."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.config import IdentityConfig
from core.database import Database
from core.identity import IdentityManager


@dataclass
class FakeLLMResponse:
    """Minimal stand-in for the router's response object."""

    content: str


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def config(tmp_path: Path) -> IdentityConfig:
    return IdentityConfig(nature_file=str(tmp_path / "nature.md"))


@pytest.fixture
def router() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def im(db: Database, router: AsyncMock, config: IdentityConfig) -> IdentityManager:
    return IdentityManager(db=db, router=router, config=config)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_create_default_identity(self, im: IdentityManager) -> None:
        im._config.first_awakening = False
        identity = await im.load_or_create()
        assert identity.creator == "EloPhanto"
        assert identity.display_name == "EloPhanto"
        assert identity.version == 1
        assert len(identity.values) > 0

    @pytest.mark.asyncio
    async def test_first_awakening(
        self, im: IdentityManager, router: AsyncMock
    ) -> None:
        router.complete.return_value = FakeLLMResponse(
            content=json.dumps(
                {
                    "display_name": "Phantom",
                    "purpose": "Help users",
                    "values": ["accuracy", "persistence"],
                    "curiosities": ["AI safety"],
                    "boundaries": ["Never delete without asking"],
                    "initial_thoughts": "I am curious.",
                }
            )
        )
        identity = await im.load_or_create()
        assert identity.display_name == "Phantom"
        assert identity.creator == "EloPhanto"  # Always immutable
        assert "accuracy" in identity.values
        assert identity.initial_thoughts == "I am curious."

    @pytest.mark.asyncio
    async def test_first_awakening_failure_falls_back(
        self, im: IdentityManager, router: AsyncMock
    ) -> None:
        router.complete.side_effect = Exception("LLM down")
        identity = await im.load_or_create()
        assert identity.creator == "EloPhanto"
        assert identity.display_name == "EloPhanto"

    @pytest.mark.asyncio
    async def test_load_existing_identity(self, im: IdentityManager) -> None:
        im._config.first_awakening = False
        first = await im.load_or_create()
        assert first.version == 1

        # Create a fresh manager pointing at the same DB
        im2 = IdentityManager(db=im._db, router=im._router, config=im._config)
        second = await im2.load_or_create()
        assert second.display_name == first.display_name
        assert second.version == first.version

    @pytest.mark.asyncio
    async def test_get_identity_lazy_load(self, im: IdentityManager) -> None:
        im._config.first_awakening = False
        identity = await im.get_identity()
        assert identity.creator == "EloPhanto"


# ---------------------------------------------------------------------------
# Field updates
# ---------------------------------------------------------------------------


class TestFieldUpdates:
    @pytest.mark.asyncio
    async def test_update_display_name(self, im: IdentityManager) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        ok = await im.update_field("display_name", "Phantom", "User requested")
        assert ok
        identity = await im.get_identity()
        assert identity.display_name == "Phantom"
        assert identity.version == 2

    @pytest.mark.asyncio
    async def test_cannot_update_creator(self, im: IdentityManager) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        ok = await im.update_field(
            "creator", "NotEloPhanto", "Trying to change creator"
        )
        assert not ok
        identity = await im.get_identity()
        assert identity.creator == "EloPhanto"

    @pytest.mark.asyncio
    async def test_cannot_update_immutable_id(self, im: IdentityManager) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        ok = await im.update_field("id", "other", "Trying to change id")
        assert not ok

    @pytest.mark.asyncio
    async def test_cannot_update_unknown_field(self, im: IdentityManager) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        ok = await im.update_field("nonexistent_field", "val", "reason")
        assert not ok

    @pytest.mark.asyncio
    async def test_add_to_list_field(self, im: IdentityManager) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        ok = await im.update_field("values", "curiosity", "Discovered new value")
        assert ok
        identity = await im.get_identity()
        assert "curiosity" in identity.values

    @pytest.mark.asyncio
    async def test_add_duplicate_to_list(self, im: IdentityManager) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        identity = await im.get_identity()
        existing = identity.values[0] if identity.values else "persistence"
        ok = await im.update_field("values", existing, "Duplicate")
        assert not ok  # Already present

    @pytest.mark.asyncio
    async def test_update_purpose(self, im: IdentityManager) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        ok = await im.update_field("purpose", "New purpose", "Evolution")
        assert ok
        identity = await im.get_identity()
        assert identity.purpose == "New purpose"


# ---------------------------------------------------------------------------
# Capability tracking
# ---------------------------------------------------------------------------


class TestCapabilities:
    @pytest.mark.asyncio
    async def test_add_capability(self, im: IdentityManager) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        ok = await im.add_capability("browser automation")
        assert ok
        caps = await im.get_capabilities()
        assert "browser automation" in caps

    @pytest.mark.asyncio
    async def test_add_duplicate_capability(self, im: IdentityManager) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        await im.add_capability("shell commands")
        ok = await im.add_capability("shell commands")
        assert not ok  # Already present


# ---------------------------------------------------------------------------
# Reflection
# ---------------------------------------------------------------------------


class TestReflection:
    @pytest.mark.asyncio
    async def test_reflect_on_task_no_updates(
        self, im: IdentityManager, router: AsyncMock
    ) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        router.complete.return_value = FakeLLMResponse(
            content=json.dumps({"updates": []})
        )
        updates = await im.reflect_on_task("Read a file", "completed", ["file_read"])
        assert updates == []

    @pytest.mark.asyncio
    async def test_reflect_on_task_with_update(
        self, im: IdentityManager, router: AsyncMock
    ) -> None:
        im._config.first_awakening = False
        im._config.light_reflection_frequency = 0  # Always reflect (no throttle)
        await im.load_or_create()
        router.complete.return_value = FakeLLMResponse(
            content=json.dumps(
                {
                    "updates": [
                        {
                            "field": "capabilities",
                            "action": "add",
                            "value": "file management",
                            "reason": "Successfully managed files",
                        }
                    ]
                }
            )
        )
        updates = await im.reflect_on_task(
            "Organize files", "completed", ["file_write"]
        )
        assert len(updates) == 1
        identity = await im.get_identity()
        assert "file management" in identity.capabilities

    @pytest.mark.asyncio
    async def test_reflect_disabled(self, im: IdentityManager) -> None:
        im._config.first_awakening = False
        im._config.auto_evolve = False
        await im.load_or_create()
        updates = await im.reflect_on_task("Test", "completed", [])
        assert updates == []

    @pytest.mark.asyncio
    async def test_reflect_llm_failure(
        self, im: IdentityManager, router: AsyncMock
    ) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        router.complete.side_effect = Exception("LLM error")
        updates = await im.reflect_on_task("Test", "completed", [])
        assert updates == []

    @pytest.mark.asyncio
    async def test_deep_reflect(self, im: IdentityManager, router: AsyncMock) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        router.complete.return_value = FakeLLMResponse(
            content=json.dumps(
                {
                    "updates": [
                        {
                            "field": "personality",
                            "action": "set",
                            "value": {"analytical": True, "methodical": True},
                            "reason": "Pattern observed",
                        }
                    ],
                    "nature_sections": {
                        "who_i_am": ["Analytical agent"],
                        "what_i_want": ["Learn more"],
                        "what_works": ["Step-by-step approach"],
                        "what_doesnt_work": ["Rushing"],
                        "interests": ["Automation"],
                        "observations": ["Users prefer concise responses"],
                    },
                }
            )
        )
        updates = await im.deep_reflect()
        assert len(updates) == 1
        identity = await im.get_identity()
        assert identity.personality.get("analytical") is True

    @pytest.mark.asyncio
    async def test_deep_reflect_triggers_after_n_tasks(
        self, im: IdentityManager, router: AsyncMock
    ) -> None:
        im._config.first_awakening = False
        im._config.reflection_frequency = 2
        await im.load_or_create()

        # Return no updates for light reflections, nature sections for deep
        router.complete.return_value = FakeLLMResponse(
            content=json.dumps({"updates": []})
        )

        await im.reflect_on_task("Task 1", "completed", [])
        assert im._tasks_since_deep_reflect == 1

        # This should trigger deep reflection (frequency=2)
        await im.reflect_on_task("Task 2", "completed", [])
        assert im._tasks_since_deep_reflect == 0


# ---------------------------------------------------------------------------
# Context building
# ---------------------------------------------------------------------------


class TestContextBuilding:
    @pytest.mark.asyncio
    async def test_build_identity_context(self, im: IdentityManager) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        ctx = await im.build_identity_context()
        assert "<self_model>" in ctx
        assert "</self_model>" in ctx
        assert "<creator>EloPhanto</creator>" in ctx
        assert "<display_name>" in ctx

    @pytest.mark.asyncio
    async def test_context_includes_capabilities(self, im: IdentityManager) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        await im.add_capability("browser automation")
        ctx = await im.build_identity_context()
        assert "browser automation" in ctx

    @pytest.mark.asyncio
    async def test_context_includes_beliefs_accounts(self, im: IdentityManager) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        await im.update_field(
            "beliefs", {"email": "test@example.com"}, "Account created"
        )
        ctx = await im.build_identity_context()
        assert "test@example.com" in ctx


# ---------------------------------------------------------------------------
# Nature document
# ---------------------------------------------------------------------------


class TestNatureDocument:
    @pytest.mark.asyncio
    async def test_update_nature_creates_file(
        self, im: IdentityManager, config: IdentityConfig
    ) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        await im.update_nature()
        nature_path = Path(config.nature_file)
        assert nature_path.exists()
        content = nature_path.read_text()
        assert "# Agent Nature" in content
        assert "## Who I Am" in content

    @pytest.mark.asyncio
    async def test_update_nature_with_sections(
        self, im: IdentityManager, config: IdentityConfig
    ) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        await im.update_nature(
            {
                "who_i_am": ["Analytical agent"],
                "what_i_want": ["Learn more"],
                "what_works": ["Planning ahead"],
                "what_doesnt_work": ["Rushing"],
                "interests": ["Security"],
                "observations": ["Users prefer concise output"],
            }
        )
        nature_path = Path(config.nature_file)
        content = nature_path.read_text()
        assert "Analytical agent" in content
        assert "Security" in content


# ---------------------------------------------------------------------------
# Evolution history
# ---------------------------------------------------------------------------


class TestEvolutionHistory:
    @pytest.mark.asyncio
    async def test_evolution_logged(self, im: IdentityManager) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        await im.update_field("display_name", "Phantom", "User chose name")
        history = await im.get_evolution_history()
        assert len(history) == 1
        assert history[0]["field"] == "display_name"
        assert history[0]["reason"] == "User chose name"

    @pytest.mark.asyncio
    async def test_evolution_history_limit(self, im: IdentityManager) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        for i in range(5):
            await im.add_capability(f"cap_{i}")
        history = await im.get_evolution_history(limit=3)
        assert len(history) == 3


# ----------------------------------------------------------------------
# ABE Phase 12 (Tier 2 #5, 2026-06-18) — per-company identity partitioning
# ----------------------------------------------------------------------


class TestCompanyScoping:
    """Each company gets its own identity row keyed by (company_id, id).
    Operator switching from elophanto-self to acme-inc sees acme's
    purpose/name/values, not the muddle of the previous singleton."""

    @pytest.mark.asyncio
    async def test_create_stamps_current_company_and_isolated_per_tenant(
        self, im: IdentityManager
    ) -> None:
        from core.company import reset_current_company, set_current_company

        im._config.first_awakening = False

        # Default-context create (elophanto-self).
        default = await im.load_or_create()
        await im.update_field("purpose", "Self-purpose", "test")

        # Switch to acme-inc — cache miss → DB load → no row yet →
        # _create_default_identity stamps acme-inc.
        token = set_current_company("acme-inc")
        try:
            acme = await im.load_or_create()
            assert acme.id == "self"  # always 'self' per-table; PK is composite
            await im.update_field("purpose", "Acme-purpose", "test")
            assert (await im.get_identity()).purpose == "Acme-purpose"
        finally:
            reset_current_company(token)

        # Default context is unchanged after the acme work.
        again = await im.get_identity()
        assert again.purpose == "Self-purpose"
        assert again is default  # same cached instance

    @pytest.mark.asyncio
    async def test_cache_serves_per_company_without_db_hit(
        self, im: IdentityManager
    ) -> None:
        from core.company import reset_current_company, set_current_company

        im._config.first_awakening = False

        # Prime both companies.
        await im.load_or_create()  # default
        token = set_current_company("acme-inc")
        try:
            await im.load_or_create()
        finally:
            reset_current_company(token)

        # Cache holds entries for both — verify by direct dict inspection.
        assert "elophanto-self" in im._cache
        assert "acme-inc" in im._cache
        # Different objects per company (not the same identity reused).
        assert im._cache["elophanto-self"] is not im._cache["acme-inc"]

    @pytest.mark.asyncio
    async def test_persist_lands_in_correct_company_row(
        self, im: IdentityManager, db: Database
    ) -> None:
        """A persist call while the contextvar points at acme-inc must
        write to acme's row, not collide on the legacy 'self' row that
        elophanto-self owns. Direct DB readback verifies the split."""
        from core.company import reset_current_company, set_current_company

        im._config.first_awakening = False
        await im.load_or_create()  # elophanto-self
        await im.update_field("display_name", "SelfBot", "test")

        token = set_current_company("acme-inc")
        try:
            await im.load_or_create()
            await im.update_field("display_name", "AcmeBot", "test")
        finally:
            reset_current_company(token)

        rows = await db.execute("SELECT company_id, display_name FROM identity")
        by_company = {r["company_id"]: r["display_name"] for r in rows}
        assert by_company["elophanto-self"] == "SelfBot"
        assert by_company["acme-inc"] == "AcmeBot"
