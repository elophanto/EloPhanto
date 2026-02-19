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
    async def test_first_awakening(self, im: IdentityManager, router: AsyncMock) -> None:
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
        ok = await im.update_field("creator", "NotEloPhanto", "Trying to change creator")
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
    async def test_reflect_on_task_no_updates(self, im: IdentityManager, router: AsyncMock) -> None:
        im._config.first_awakening = False
        await im.load_or_create()
        router.complete.return_value = FakeLLMResponse(content=json.dumps({"updates": []}))
        updates = await im.reflect_on_task("Read a file", "completed", ["file_read"])
        assert updates == []

    @pytest.mark.asyncio
    async def test_reflect_on_task_with_update(
        self, im: IdentityManager, router: AsyncMock
    ) -> None:
        im._config.first_awakening = False
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
        updates = await im.reflect_on_task("Organize files", "completed", ["file_write"])
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
    async def test_reflect_llm_failure(self, im: IdentityManager, router: AsyncMock) -> None:
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
        router.complete.return_value = FakeLLMResponse(content=json.dumps({"updates": []}))

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
        await im.update_field("beliefs", {"email": "test@example.com"}, "Account created")
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
