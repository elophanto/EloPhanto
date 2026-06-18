"""ABE awareness in identity context + canonical-source tool descriptions.

Locks in the fix from 2026-05-25: the agent listed historical project
mentions (Happy Girlie, Scrape.ai, Horse Polo) from scratchpad memory
when asked about 'companies' instead of calling company_list and
returning the canonical answer (elophanto-self). Two pieces:

1. ``IdentityManager.build_identity_context`` always renders an
   ``<abe_framework>`` block that names the canonical tools and
   warns against reconstructing from memory.
2. ``company_list`` / ``company_report`` / ``role_list`` descriptions
   say CANONICAL and FIRST so the LLM reaches for them.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.config import IdentityConfig
from core.database import Database
from core.identity import IdentityManager
from tools.companies.management_tools import (
    CompanyListTool,
    CompanyReportTool,
)
from tools.roles.management_tools import RoleListTool


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()
    return db


class TestAbeFrameworkAwarenessBlock:
    @pytest.mark.asyncio
    async def test_block_always_present(self, db: Database) -> None:
        # Even a minimal identity (default row, no role active) should
        # emit the ABE framework block so the LLM sees it every cycle.
        ident_cfg = IdentityConfig(enabled=True)
        router = MagicMock()
        im = IdentityManager(db=db, router=router, config=ident_cfg)
        await db.execute_insert(
            "INSERT INTO identity (id, created_at, updated_at) "
            "VALUES ('self', ?, ?)",
            ("2026-05-25", "2026-05-25"),
        )
        await im.load_or_create()

        ctx = await im.build_identity_context()
        assert "<abe_framework>" in ctx
        assert "</abe_framework>" in ctx

    @pytest.mark.asyncio
    async def test_block_names_canonical_tools(self, db: Database) -> None:
        ident_cfg = IdentityConfig(enabled=True)
        router = MagicMock()
        im = IdentityManager(db=db, router=router, config=ident_cfg)
        await db.execute_insert(
            "INSERT INTO identity (id, created_at, updated_at) "
            "VALUES ('self', ?, ?)",
            ("2026-05-25", "2026-05-25"),
        )
        await im.load_or_create()

        ctx = await im.build_identity_context()
        # Every canonical-source tool the LLM should reach for must be
        # named in the awareness block. If a new tool gets added to the
        # ABE surface, this test fails until the block is updated.
        for tool in (
            "company_list",
            "company_report",
            "company_create",
            "company_use",
            "company_pause",
            "company_resume",
            "company_set_product",
            "company_onboard",
            "role_list",
            "role_show",
            "role_use",
            "role_sync",
        ):
            assert tool in ctx, f"awareness block must name {tool}"

    @pytest.mark.asyncio
    async def test_block_points_at_workflow_skills(self, db: Database) -> None:
        """Refactored 2026-05-26: workflows that used to live inline in
        the awareness block (Sections 5-8 — Trust Ladder / Drive My
        Business / Voice / Strategy Pipeline) now live in versioned
        SKILL.md files. The awareness block must name the skill router
        as the canonical place for workflow procedure, and name the
        load-bearing skills by slug so the LLM knows to reach for them
        (the skill router auto-loads on trigger match, but the
        awareness block makes the contract explicit)."""
        ident_cfg = IdentityConfig(enabled=True)
        router = MagicMock()
        im = IdentityManager(db=db, router=router, config=ident_cfg)
        await db.execute_insert(
            "INSERT INTO identity (id, created_at, updated_at) "
            "VALUES ('self', ?, ?)",
            ("2026-05-26", "2026-05-26"),
        )
        await im.load_or_create()

        ctx = await im.build_identity_context()
        lowered = ctx.lower()
        # The four workflow skills must be named so the LLM knows
        # to read them when the matching intent appears.
        for skill in (
            "drive-business",
            "trust-ladder-workflow",
            "voice-extraction-workflow",
            "strategy-pipeline",
        ):
            assert (
                skill in lowered
            ), f"awareness block must reference workflow skill {skill}"
        # The block must also point the LLM at the canonical tool surface
        # (so it doesn't reconstruct ABE state from memory).
        assert "company_onboard" in lowered
        # Hard rules (operator-only promotion etc.) must remain in the
        # block — they can't drift to skills because they apply across
        # every workflow.
        assert "cannot promote" in lowered or "operator only" in lowered

    @pytest.mark.asyncio
    async def test_block_warns_against_memory_reconstruction(
        self, db: Database
    ) -> None:
        # The 2026-05-25 failure was the agent answering "what companies
        # do we have?" from scratchpad memory instead of calling
        # company_list. The awareness block must explicitly name this
        # failure mode so the LLM is steered away from it.
        ident_cfg = IdentityConfig(enabled=True)
        router = MagicMock()
        im = IdentityManager(db=db, router=router, config=ident_cfg)
        await db.execute_insert(
            "INSERT INTO identity (id, created_at, updated_at) "
            "VALUES ('self', ?, ?)",
            ("2026-05-25", "2026-05-25"),
        )
        await im.load_or_create()

        ctx = await im.build_identity_context()
        lowered = ctx.lower()
        # Must mention reconstruction-from-memory as a failure mode
        assert "memory" in lowered
        # Must distinguish ABE company from project mentions
        assert "project" in lowered or "different concept" in lowered


class TestPersonalityShapeDoesNotCrashContext:
    """Regression: a production DB had ``identity.personality`` as a
    string instead of a dict. The original code called
    ``personality.items()`` and crashed with AttributeError. The
    outer try/except in Agent._build_prompt swallowed the failure,
    so the system prompt landed with an EMPTY identity section —
    no <self_model>, no <abe_framework>. The agent then answered
    'what companies do we have?' from scratchpad memory because no
    awareness block ever reached the LLM. This test pins the fix:
    a string personality must NOT crash the context builder."""

    @pytest.mark.asyncio
    async def test_string_personality_does_not_crash(self, db: Database) -> None:
        from core.identity import Identity

        from core.company import current_company_id

        ident_cfg = IdentityConfig(enabled=True)
        router = MagicMock()
        im = IdentityManager(db=db, router=router, config=ident_cfg)
        # Inject a synthetic identity with personality as a STRING
        # (the production-DB shape that crashed the original code).
        # ABE Phase 12 — cache is now per-company; inject into the
        # contextvar's slot so get_identity returns this object.
        im._cache[current_company_id()] = Identity(
            id="self",
            created_at="2026-05-25",
            updated_at="2026-05-25",
            personality="thoughtful, careful",  # type: ignore[arg-type]
        )
        # Must not raise
        ctx = await im.build_identity_context()
        # And the personality should appear as-is, plus the ABE block
        # should still land (the whole point of the fix is keeping the
        # rest of the prompt intact when one field is the wrong shape).
        assert "thoughtful, careful" in ctx
        assert "<abe_framework>" in ctx


class TestCanonicalSourceToolDescriptions:
    """The LLM picks tools partly from descriptions. The descriptions
    of `company_list`, `company_report`, and `role_list` must
    explicitly say CANONICAL + steer the LLM to call them FIRST."""

    def test_company_list_is_canonical(self) -> None:
        desc = CompanyListTool().description
        assert "CANONICAL" in desc
        assert "FIRST" in desc
        # Must explicitly warn against reconstruction
        assert "memory" in desc.lower() or "reconstruct" in desc.lower()

    def test_company_report_is_canonical(self) -> None:
        desc = CompanyReportTool().description
        assert "CANONICAL" in desc
        # The 'state of X' / 'how is X doing' questions should route here
        assert "doing" in desc.lower() or "state" in desc.lower()

    def test_role_list_is_canonical(self) -> None:
        desc = RoleListTool().description
        assert "CANONICAL" in desc
        # Must warn against guessing from memory
        assert "memory" in desc.lower() or "guess" in desc.lower()
