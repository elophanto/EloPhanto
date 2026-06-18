"""SessionManager tests — focused on Tier 2 #4 (2026-06-18).

Pins the contract that two companies sharing the same (channel,
user_id) get separate sessions instead of collision. Also exercises
the basic create / get / get_or_create / list / delete surface so this
file works as a regression net for future session refactors.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.company import ALL_COMPANIES, reset_current_company, set_current_company
from core.database import Database
from core.session import SessionManager


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def mgr(db: Database) -> SessionManager:
    return SessionManager(db=db)


# ----------------------------------------------------------------------
# Basic CRUD — regression net
# ----------------------------------------------------------------------


class TestBasicLifecycle:
    @pytest.mark.asyncio
    async def test_create_persists(self, mgr: SessionManager) -> None:
        s = await mgr.create("cli", "op")
        again = await mgr.get(s.session_id)
        assert again is not None
        assert again.channel == "cli"
        assert again.user_id == "op"
        assert again.company_id == "elophanto-self"

    @pytest.mark.asyncio
    async def test_get_or_create_returns_existing(self, mgr: SessionManager) -> None:
        s1 = await mgr.get_or_create("cli", "op")
        s2 = await mgr.get_or_create("cli", "op")
        assert s1.session_id == s2.session_id

    @pytest.mark.asyncio
    async def test_delete(self, mgr: SessionManager) -> None:
        s = await mgr.create("cli", "op")
        assert await mgr.delete(s.session_id)
        assert await mgr.get(s.session_id) is None


# ----------------------------------------------------------------------
# Tier 2 #4 — per-company session isolation
# ----------------------------------------------------------------------


class TestCompanyScoping:
    """The UNIQUE constraint widened from (channel, user_id) to
    (channel, user_id, company_id). Two companies sharing the same
    channel+user_id no longer collide and no longer overwrite each
    other's conversation history."""

    @pytest.mark.asyncio
    async def test_two_companies_get_distinct_sessions(
        self, mgr: SessionManager
    ) -> None:
        # Default context: create session for ("cli", "op").
        self_session = await mgr.get_or_create("cli", "op")
        self_session.conversation_history.append(
            {"role": "user", "content": "self-only message"}
        )
        await mgr.save(self_session)

        # Switch to acme-inc; same (channel, user_id) but different
        # company → distinct session.
        token = set_current_company("acme-inc")
        try:
            acme_session = await mgr.get_or_create("cli", "op")
            assert acme_session.session_id != self_session.session_id
            assert acme_session.company_id == "acme-inc"
            assert acme_session.conversation_history == []  # fresh
            acme_session.conversation_history.append(
                {"role": "user", "content": "acme-only message"}
            )
            await mgr.save(acme_session)
        finally:
            reset_current_company(token)

        # Default-context reload: still has only the self message,
        # NOT the acme one.
        again = await mgr.get_or_create("cli", "op")
        assert again.session_id == self_session.session_id
        contents = [m["content"] for m in again.conversation_history]
        assert "self-only message" in contents
        assert "acme-only message" not in contents

    @pytest.mark.asyncio
    async def test_get_or_create_with_explicit_company_id(
        self, mgr: SessionManager
    ) -> None:
        """Explicit ``company_id=`` arg overrides the contextvar so
        admin tools / migrations can target a specific tenant without
        rewriting the operator's active context."""
        s = await mgr.get_or_create("cli", "op", company_id="acme-inc")
        assert s.company_id == "acme-inc"

    @pytest.mark.asyncio
    async def test_cache_does_not_leak_across_companies(
        self, mgr: SessionManager
    ) -> None:
        """The in-memory cache (lines 142-149 of session.py) used to
        match on (channel, user_id) only. After Tier 2 #4 the match
        includes company_id so the cache can't return a foreign
        tenant's session by accident."""
        self_session = await mgr.get_or_create("cli", "op")
        # Both sessions stay in cache.
        token = set_current_company("acme-inc")
        try:
            acme_session = await mgr.get_or_create("cli", "op")
            assert acme_session.session_id != self_session.session_id
            # Re-fetch acme inside the same context — should return the
            # acme one, not the cached elophanto-self one.
            again = await mgr.get_or_create("cli", "op")
            assert again.session_id == acme_session.session_id
        finally:
            reset_current_company(token)

    @pytest.mark.asyncio
    async def test_list_active_scopes_to_current_company(
        self, mgr: SessionManager
    ) -> None:
        # Seed sessions across two companies.
        await mgr.get_or_create("cli", "op")
        token = set_current_company("acme-inc")
        try:
            await mgr.get_or_create("cli", "op")
            await mgr.get_or_create("telegram", "op")
        finally:
            reset_current_company(token)

        # Default context — only self's session.
        listed = await mgr.list_active()
        assert {s.company_id for s in listed} == {"elophanto-self"}
        assert len(listed) == 1

        # Switch to acme — only acme's.
        token = set_current_company("acme-inc")
        try:
            listed = await mgr.list_active()
            assert {s.company_id for s in listed} == {"acme-inc"}
            assert len(listed) == 2
        finally:
            reset_current_company(token)

    @pytest.mark.asyncio
    async def test_all_companies_sentinel_lists_across_tenants(
        self, mgr: SessionManager
    ) -> None:
        await mgr.get_or_create("cli", "op")
        token = set_current_company("acme-inc")
        try:
            await mgr.get_or_create("cli", "op")
        finally:
            reset_current_company(token)

        listed = await mgr.list_active(company_id=ALL_COMPANIES)
        companies = {s.company_id for s in listed}
        assert companies == {"elophanto-self", "acme-inc"}

    @pytest.mark.asyncio
    async def test_duplicate_within_same_company_still_blocked(
        self, mgr: SessionManager, db: Database
    ) -> None:
        """The new UNIQUE still enforces the original guarantee within
        a single tenant: two sessions for (channel, user_id, company)
        cannot coexist. Manager's get_or_create returns the existing
        one; direct DB insert raises."""
        s1 = await mgr.get_or_create("cli", "op")
        s2 = await mgr.get_or_create("cli", "op")
        assert s1.session_id == s2.session_id

        # Raw insert with a new session_id but duplicate
        # (channel, user_id, company_id) must violate UNIQUE.
        import sqlite3

        with pytest.raises(sqlite3.IntegrityError):
            await db.execute_insert(
                "INSERT INTO sessions "
                "(session_id, channel, user_id, created_at, last_active, company_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("dup-id", "cli", "op", "2026-01-01", "2026-01-01", "elophanto-self"),
            )
