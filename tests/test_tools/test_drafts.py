"""Draft tools (ABE Phase 9 — Trust Ladder).

Locks in:
- email_draft / outreach_draft / post_draft write Markdown files
  under companies/<slug>/drafts/<kind>/pending/
- draft_approve moves pending → approved with a resolution footer
- draft_reject moves pending → rejected (requires reason)
- company_trust_set promotes the ladder
- All draft tools refuse on missing project_root / company_manager
"""

from __future__ import annotations

import pytest

from core.company import CompanyManager
from core.database import Database
from tools.drafts.draft_tools import (
    CompanyTrustSetTool,
    DraftApproveTool,
    DraftRejectTool,
    EmailDraftTool,
    OutreachDraftTool,
    PostDraftTool,
)


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()
    return db


@pytest.fixture
async def company_mgr(db: Database, tmp_path) -> CompanyManager:
    mgr = CompanyManager(db=db, project_root=tmp_path)
    # Seed a non-default company so we exercise the new-company path
    await mgr.create("acme-inc", "Acme Inc")
    return mgr


def _make(cls, *, project_root=None, company_mgr=None):
    t = cls()
    if hasattr(t, "_project_root"):
        t._project_root = project_root
    if hasattr(t, "_company_manager"):
        t._company_manager = company_mgr
    return t


class TestEmailDraft:
    @pytest.mark.asyncio
    async def test_writes_markdown_to_pending(self, tmp_path, company_mgr) -> None:
        tool = _make(EmailDraftTool, project_root=tmp_path)
        result = await tool.execute(
            {
                "to": "petr@example.com",
                "subject": "Test outreach v1",
                "body": "Hello — exploring a fit.",
                "company_id": "acme-inc",
            }
        )
        assert result.success
        path = tmp_path / "companies" / "acme-inc" / "drafts" / "email" / "pending"
        files = list(path.glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "Test outreach v1" in content
        assert "petr@example.com" in content
        assert "Hello — exploring a fit." in content
        # Must include resolution instructions
        assert "draft_approve" in content
        assert "draft_reject" in content

    @pytest.mark.asyncio
    async def test_empty_body_fails(self, tmp_path) -> None:
        tool = _make(EmailDraftTool, project_root=tmp_path)
        result = await tool.execute({"to": "x@y.com", "subject": "X", "body": "   "})
        assert not result.success
        assert "non-empty" in result.error

    @pytest.mark.asyncio
    async def test_uninitialized_fails(self) -> None:
        tool = EmailDraftTool()  # no project_root
        result = await tool.execute({"to": "x@y.com", "subject": "X", "body": "body"})
        assert not result.success


class TestOutreachDraft:
    @pytest.mark.asyncio
    async def test_writes_to_outreach_dir(self, tmp_path, company_mgr) -> None:
        tool = _make(OutreachDraftTool, project_root=tmp_path)
        result = await tool.execute(
            {
                "prospect_id": "p_test_1",
                "channel": "email",
                "body": "Saw your post about X — would love to chat.",
                "company_id": "acme-inc",
            }
        )
        assert result.success
        path = tmp_path / "companies" / "acme-inc" / "drafts" / "outreach" / "pending"
        files = list(path.glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "p_test_1" in content


class TestPostDraft:
    @pytest.mark.asyncio
    async def test_writes_to_post_dir_with_char_count(
        self, tmp_path, company_mgr
    ) -> None:
        tool = _make(PostDraftTool, project_root=tmp_path)
        body = "Shipping ABE Phase 9: trust ladder for outreach."
        result = await tool.execute({"content": body, "company_id": "acme-inc"})
        assert result.success
        assert result.data["char_count"] == len(body)
        path = tmp_path / "companies" / "acme-inc" / "drafts" / "post" / "pending"
        files = list(path.glob("*.md"))
        assert len(files) == 1


class TestDraftResolution:
    @pytest.mark.asyncio
    async def test_approve_moves_to_approved(self, tmp_path, company_mgr) -> None:
        draft_tool = _make(EmailDraftTool, project_root=tmp_path)
        write_result = await draft_tool.execute(
            {
                "to": "p@x.com",
                "subject": "Hello",
                "body": "body",
                "company_id": "acme-inc",
            }
        )
        draft_id = write_result.data["draft_id"]

        approve = _make(DraftApproveTool, project_root=tmp_path)
        approve_result = await approve.execute(
            {"draft_id": draft_id, "note": "voice approved"}
        )
        assert approve_result.success
        # Pending file is gone
        pending = (
            tmp_path
            / "companies"
            / "acme-inc"
            / "drafts"
            / "email"
            / "pending"
            / f"{draft_id}.md"
        )
        assert not pending.exists()
        # Approved file exists with the resolution footer
        approved = (
            tmp_path
            / "companies"
            / "acme-inc"
            / "drafts"
            / "email"
            / "approved"
            / f"{draft_id}.md"
        )
        assert approved.exists()
        body = approved.read_text(encoding="utf-8")
        assert "Resolution (approved)" in body
        assert "voice approved" in body

    @pytest.mark.asyncio
    async def test_reject_requires_reason(self, tmp_path, company_mgr) -> None:
        draft_tool = _make(EmailDraftTool, project_root=tmp_path)
        write_result = await draft_tool.execute(
            {
                "to": "p@x.com",
                "subject": "Hello",
                "body": "body",
                "company_id": "acme-inc",
            }
        )
        draft_id = write_result.data["draft_id"]

        reject = _make(DraftRejectTool, project_root=tmp_path)
        # Empty reason fails
        bad = await reject.execute({"draft_id": draft_id, "reason": "  "})
        assert not bad.success

        # Real reason succeeds, moves to rejected/, footer captures reason
        good = await reject.execute(
            {"draft_id": draft_id, "reason": "Too salesy — soften."}
        )
        assert good.success
        rejected = (
            tmp_path
            / "companies"
            / "acme-inc"
            / "drafts"
            / "email"
            / "rejected"
            / f"{draft_id}.md"
        )
        assert rejected.exists()
        body = rejected.read_text(encoding="utf-8")
        assert "Resolution (rejected)" in body
        assert "Too salesy — soften." in body

    @pytest.mark.asyncio
    async def test_approve_missing_draft_fails(self, tmp_path, company_mgr) -> None:
        approve = _make(DraftApproveTool, project_root=tmp_path)
        result = await approve.execute({"draft_id": "nonexistent"})
        assert not result.success
        assert "not found" in result.error


class TestCompanyTrustSet:
    @pytest.mark.asyncio
    async def test_promotes_trust_state(self, company_mgr) -> None:
        tool = _make(CompanyTrustSetTool, company_mgr=company_mgr)
        result = await tool.execute(
            {"slug": "acme-inc", "state": "trial", "reason": "voice approved"}
        )
        assert result.success
        assert (await company_mgr.get("acme-inc")).trust_state == "trial"

    @pytest.mark.asyncio
    async def test_rejects_invalid_state(self, company_mgr) -> None:
        tool = _make(CompanyTrustSetTool, company_mgr=company_mgr)
        result = await tool.execute({"slug": "acme-inc", "state": "bogus"})
        assert not result.success

    @pytest.mark.asyncio
    async def test_unknown_slug(self, company_mgr) -> None:
        tool = _make(CompanyTrustSetTool, company_mgr=company_mgr)
        result = await tool.execute({"slug": "no-such", "state": "trial"})
        assert not result.success
