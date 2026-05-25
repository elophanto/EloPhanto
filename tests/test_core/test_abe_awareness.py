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
            "role_list",
            "role_show",
            "role_use",
            "role_sync",
        ):
            assert tool in ctx, f"awareness block must name {tool}"

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
