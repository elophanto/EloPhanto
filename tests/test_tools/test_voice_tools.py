"""Voice tools (ABE Phase 10): extract / show / lint + draft integration.

Locks in:
- voice_show returns has_voice=False when no voice.yaml exists
- voice_show surfaces all parsed fields when a contract is loaded
- voice_lint returns structured violations + always-pass on empty contract
- voice_extract refuses on missing dep, missing exemplars dir, < 2 exemplars
- voice_extract writes voice_proposed.yaml from LLM output
- email_draft / outreach_draft / post_draft refuse to persist when lint fails
- Same draft tools succeed when no voice.yaml is present (fail-soft)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import yaml

from core.voice import VoiceManager
from tools.drafts.draft_tools import (
    EmailDraftTool,
    OutreachDraftTool,
    PostDraftTool,
)
from tools.voice.extract_tool import VoiceExtractTool
from tools.voice.lint_tool import VoiceLintTool
from tools.voice.show_tool import VoiceShowTool


def _write(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@dataclass
class FakeResponse:
    content: str


class FakeRouter:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    async def complete(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return FakeResponse(content=self.payload)


@pytest.fixture
def voice_mgr(tmp_path) -> VoiceManager:
    return VoiceManager(tmp_path)


class TestVoiceShow:
    @pytest.mark.asyncio
    async def test_no_contract(self, voice_mgr) -> None:
        tool = VoiceShowTool()
        tool._voice_manager = voice_mgr
        r = await tool.execute({"company_id": "co"})
        assert r.success is True
        assert r.data["has_voice"] is False
        assert "voice_extract" in r.data["next"]

    @pytest.mark.asyncio
    async def test_loaded_contract(self, tmp_path, voice_mgr) -> None:
        _write(
            tmp_path / "data" / "companies" / "co" / "voice.yaml",
            "persona: founder\nbanned_phrases: [leverage]\n"
            "length_target: {min_chars: 80, max_chars: 240}\n",
        )
        tool = VoiceShowTool()
        tool._voice_manager = voice_mgr
        r = await tool.execute({"company_id": "co"})
        assert r.success is True
        assert r.data["has_voice"] is True
        assert r.data["persona"] == "founder"
        assert r.data["banned_phrases"] == ["leverage"]
        assert r.data["length_target"]["min_chars"] == 80

    @pytest.mark.asyncio
    async def test_uninitialized(self) -> None:
        tool = VoiceShowTool()
        r = await tool.execute({"company_id": "co"})
        assert r.success is False
        assert "voice_manager" in (r.error or "")


class TestVoiceLintTool:
    @pytest.mark.asyncio
    async def test_passes_with_empty_contract(self, voice_mgr) -> None:
        tool = VoiceLintTool()
        tool._voice_manager = voice_mgr
        r = await tool.execute({"text": "anything", "company_id": "co"})
        assert r.success is True
        assert r.data["passed"] is True

    @pytest.mark.asyncio
    async def test_returns_violations(self, tmp_path, voice_mgr) -> None:
        _write(
            tmp_path / "data" / "companies" / "co" / "voice.yaml",
            "banned_phrases: [leverage]\n",
        )
        tool = VoiceLintTool()
        tool._voice_manager = voice_mgr
        r = await tool.execute({"text": "We leverage AI", "company_id": "co"})
        assert r.success is True  # tool succeeded
        assert r.data["passed"] is False  # but the lint failed
        assert any("leverage" in v for v in r.data["violations"])


class TestVoiceExtract:
    @pytest.mark.asyncio
    async def test_refuses_without_router(self, voice_mgr) -> None:
        tool = VoiceExtractTool()
        tool._voice_manager = voice_mgr
        r = await tool.execute({"company_id": "co"})
        assert r.success is False
        assert "router" in (r.error or "")

    @pytest.mark.asyncio
    async def test_refuses_when_no_exemplars_dir(self, voice_mgr, tmp_path) -> None:
        tool = VoiceExtractTool()
        tool._voice_manager = voice_mgr
        tool._router = FakeRouter("{}")
        r = await tool.execute({"company_id": "co"})
        assert r.success is False
        assert "exemplars" in (r.error or "")

    @pytest.mark.asyncio
    async def test_refuses_when_fewer_than_two(self, voice_mgr, tmp_path) -> None:
        _write(
            tmp_path / "data" / "companies" / "co" / "exemplars" / "twitter" / "a.md",
            "POV: just one exemplar",
        )
        tool = VoiceExtractTool()
        tool._voice_manager = voice_mgr
        tool._router = FakeRouter("{}")
        r = await tool.execute({"company_id": "co"})
        assert r.success is False
        assert "at least 2" in (r.error or "")

    @pytest.mark.asyncio
    async def test_writes_proposed_yaml(self, voice_mgr, tmp_path) -> None:
        _write(
            tmp_path / "data" / "companies" / "co" / "exemplars" / "twitter" / "a.md",
            "POV: agent shipped 4 tickets overnight",
        )
        _write(
            tmp_path / "data" / "companies" / "co" / "exemplars" / "twitter" / "b.md",
            "My dad didn't believe me until I showed him the diff",
        )
        payload = (
            '{"persona": "founder", "tone": ["direct"], '
            '"length_target": {"min_chars": 80, "max_chars": 240}, '
            '"allowed_hooks": ["POV: <x>"], '
            '"banned_phrases": ["leverage"], '
            '"banned_patterns": [{"regex": "^We help", "reason": "x"}], '
            '"cta_style": "soft"}'
        )
        tool = VoiceExtractTool()
        tool._voice_manager = voice_mgr
        tool._router = FakeRouter(payload)
        r = await tool.execute({"company_id": "co"})
        assert r.success is True
        assert r.data["exemplar_count"] == 2
        prop_path = tmp_path / "data" / "companies" / "co" / "voice_proposed.yaml"
        assert prop_path.is_file()
        loaded = yaml.safe_load(prop_path.read_text())
        assert loaded["banned_phrases"] == ["leverage"]
        assert loaded["allowed_hooks"] == ["POV: <x>"]

    @pytest.mark.asyncio
    async def test_strips_code_fence(self, voice_mgr, tmp_path) -> None:
        _write(
            tmp_path / "data" / "companies" / "co" / "exemplars" / "twitter" / "a.md",
            "exemplar a",
        )
        _write(
            tmp_path / "data" / "companies" / "co" / "exemplars" / "twitter" / "b.md",
            "exemplar b",
        )
        fenced = '```json\n{"persona": "x"}\n```'
        tool = VoiceExtractTool()
        tool._voice_manager = voice_mgr
        tool._router = FakeRouter(fenced)
        r = await tool.execute({"company_id": "co"})
        assert r.success is True

    @pytest.mark.asyncio
    async def test_handles_non_json_output(self, voice_mgr, tmp_path) -> None:
        _write(
            tmp_path / "data" / "companies" / "co" / "exemplars" / "twitter" / "a.md",
            "a",
        )
        _write(
            tmp_path / "data" / "companies" / "co" / "exemplars" / "twitter" / "b.md",
            "b",
        )
        tool = VoiceExtractTool()
        tool._voice_manager = voice_mgr
        tool._router = FakeRouter("not json at all")
        r = await tool.execute({"company_id": "co"})
        assert r.success is False
        assert "non-JSON" in (r.error or "")


class TestDraftVoiceIntegration:
    @pytest.mark.asyncio
    async def test_email_draft_passes_without_voice(self, tmp_path, voice_mgr) -> None:
        tool = EmailDraftTool()
        tool._project_root = tmp_path
        tool._voice_manager = voice_mgr
        r = await tool.execute(
            {
                "to": "p@e.com",
                "subject": "Hi",
                "body": "Anything goes when no voice contract",
                "company_id": "co",
            }
        )
        assert r.success is True

    @pytest.mark.asyncio
    async def test_email_draft_fails_on_voice_violation(
        self, tmp_path, voice_mgr
    ) -> None:
        _write(
            tmp_path / "data" / "companies" / "co" / "voice.yaml",
            "banned_phrases: [leverage]\n",
        )
        tool = EmailDraftTool()
        tool._project_root = tmp_path
        tool._voice_manager = voice_mgr
        r = await tool.execute(
            {
                "to": "p@e.com",
                "subject": "Hi",
                "body": "We leverage AI to deliver value",
                "company_id": "co",
            }
        )
        assert r.success is False
        assert "voice lint failed" in (r.error or "")
        assert "leverage" in (r.error or "")
        # No draft file was written
        pending = tmp_path / "companies" / "co" / "drafts" / "email" / "pending"
        assert not pending.exists() or not any(pending.iterdir())

    @pytest.mark.asyncio
    async def test_outreach_draft_voice_gated(self, tmp_path, voice_mgr) -> None:
        _write(
            tmp_path / "data" / "companies" / "co" / "voice.yaml",
            "banned_phrases: [unlock]\n",
        )
        tool = OutreachDraftTool()
        tool._project_root = tmp_path
        tool._voice_manager = voice_mgr
        r = await tool.execute(
            {
                "prospect_id": "p1",
                "body": "Let me help you unlock value",
                "company_id": "co",
            }
        )
        assert r.success is False
        assert "unlock" in (r.error or "")

    @pytest.mark.asyncio
    async def test_post_draft_voice_gated(self, tmp_path, voice_mgr) -> None:
        _write(
            tmp_path / "data" / "companies" / "co" / "voice.yaml",
            "length_target: {min_chars: 0, max_chars: 20}\n",
        )
        tool = PostDraftTool()
        tool._project_root = tmp_path
        tool._voice_manager = voice_mgr
        r = await tool.execute(
            {
                "content": ("this is way too long for the configured max bound"),
                "company_id": "co",
            }
        )
        assert r.success is False
        assert "too long" in (r.error or "")

    @pytest.mark.asyncio
    async def test_revise_succeeds_after_fail(self, tmp_path, voice_mgr) -> None:
        _write(
            tmp_path / "data" / "companies" / "co" / "voice.yaml",
            "banned_phrases: [leverage]\n",
        )
        tool = EmailDraftTool()
        tool._project_root = tmp_path
        tool._voice_manager = voice_mgr
        # First try: violates
        r1 = await tool.execute(
            {
                "to": "p@e.com",
                "subject": "Hi",
                "body": "We leverage AI",
                "company_id": "co",
            }
        )
        assert r1.success is False
        # Second try: clean body
        r2 = await tool.execute(
            {
                "to": "p@e.com",
                "subject": "Hi",
                "body": "We help with X by doing Y",
                "company_id": "co",
            }
        )
        assert r2.success is True
