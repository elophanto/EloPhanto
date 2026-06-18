"""SessionSearchTool — Tier 2 #4 post-audit (2026-06-18) cross-tenant
leak regression test.

Before the fix, ``session_search`` returned messages from sessions in
other companies if they shared the same channel filter (or no filter
at all). The active company filter is applied via subquery against
the now-tenant-scoped sessions table.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.company import reset_current_company, set_current_company
from core.database import Database
from core.session import SessionManager
from tools.data.session_search import SessionSearchTool


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
async def populated_db(db: Database) -> Database:
    """Seed two companies' sessions with searchable messages."""
    mgr = SessionManager(db=db)

    # elophanto-self session + message
    self_session = await mgr.get_or_create("cli", "op")
    await mgr.log_message(self_session.session_id, "user", "polymarket trade analysis")

    # acme-inc session + message (same channel, same user_id, different company)
    token = set_current_company("acme-inc")
    try:
        acme_session = await mgr.get_or_create("cli", "op")
        await mgr.log_message(
            acme_session.session_id, "user", "polymarket forecast for client"
        )
    finally:
        reset_current_company(token)

    return db


@pytest.fixture
def tool(populated_db: Database) -> SessionSearchTool:
    t = SessionSearchTool()
    t._db = populated_db
    return t


def _flatten_content(result_data: dict) -> str:
    """Concatenate every message body returned by SessionSearchTool so
    tests can assert by substring. Result shape is
    {"results": [{"excerpts": [[{"role", "content"}, ...], ...]}, ...]}."""
    out: list[str] = []
    for session in result_data.get("results", []):
        for window in session.get("excerpts", []):
            for msg in window:
                out.append(msg.get("content", ""))
    return " ".join(out)


@pytest.mark.asyncio
async def test_search_only_returns_active_company_results(
    tool: SessionSearchTool,
) -> None:
    """Operator in elophanto-self searches for 'polymarket' — must NOT
    see acme-inc's message even though both companies have one."""
    result = await tool.execute({"query": "polymarket"})
    assert result.success
    content = _flatten_content(result.data)

    # The elophanto message must be present.
    assert "trade analysis" in content
    # The acme message must NOT leak.
    assert "forecast for client" not in content
    # Exactly one session returned (elophanto's), not two.
    assert result.data["total_sessions"] == 1


@pytest.mark.asyncio
async def test_search_returns_other_company_when_context_switched(
    tool: SessionSearchTool,
) -> None:
    """The mirror test: switching to acme returns acme's message, not
    elophanto's. Pins that the filter is contextvar-driven, not
    hardcoded to elophanto-self."""
    token = set_current_company("acme-inc")
    try:
        result = await tool.execute({"query": "polymarket"})
    finally:
        reset_current_company(token)

    assert result.success
    content = _flatten_content(result.data)
    assert "forecast for client" in content
    assert "trade analysis" not in content
    assert result.data["total_sessions"] == 1
