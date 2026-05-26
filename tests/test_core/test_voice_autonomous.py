"""Phase 10 wiring into the autonomous mind.

Locks in:
- from_voiceless_companies candidate generator surfaces companies
  with exemplars but no voice.yaml, skips companies with voice.yaml,
  skips companies with too few exemplars, caps at 3, degrades
  gracefully when voice_manager / project_root / company_manager
  are missing.
- collect_all registers from_voiceless_companies.
- CandidateContext exposes voice_manager.
"""

from __future__ import annotations

import pytest

from core.company import CompanyManager
from core.database import Database
from core.mind_candidates import (
    CandidateContext,
    collect_all,
    from_voiceless_companies,
)
from core.voice import VoiceManager


def _write(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _seed_exemplars(tmp_path, slug: str, channel: str, n: int) -> None:
    for i in range(n):
        _write(
            tmp_path / "data" / "companies" / slug / "exemplars" / channel / f"e{i}.md",
            f"exemplar {i} content for {slug}",
        )


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()
    return db


class TestVoicelessCandidateSource:
    @pytest.mark.asyncio
    async def test_yields_when_exemplars_but_no_voice(
        self, db: Database, tmp_path
    ) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        await mgr.create("acme-inc", "Acme")
        _seed_exemplars(tmp_path, "acme-inc", "twitter", 3)

        vmgr = VoiceManager(tmp_path)
        ctx = CandidateContext(
            company_manager=mgr,
            project_root=tmp_path,
            voice_manager=vmgr,
        )
        out = await from_voiceless_companies(ctx)
        slugs = {c.metadata["company_id"] for c in out}
        assert "acme-inc" in slugs
        cand = next(c for c in out if c.metadata["company_id"] == "acme-inc")
        assert cand.metadata["exemplar_count"] == 3
        assert cand.dedup_key == "voice_extract:acme-inc"

    @pytest.mark.asyncio
    async def test_skips_when_voice_yaml_present(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        await mgr.create("acme-inc", "Acme")
        _seed_exemplars(tmp_path, "acme-inc", "twitter", 3)
        _write(
            tmp_path / "data" / "companies" / "acme-inc" / "voice.yaml",
            "banned_phrases: [leverage]\n",
        )
        ctx = CandidateContext(
            company_manager=mgr,
            project_root=tmp_path,
            voice_manager=VoiceManager(tmp_path),
        )
        out = await from_voiceless_companies(ctx)
        assert all(c.metadata["company_id"] != "acme-inc" for c in out)

    @pytest.mark.asyncio
    async def test_skips_when_fewer_than_two_exemplars(
        self, db: Database, tmp_path
    ) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        await mgr.create("acme-inc", "Acme")
        _seed_exemplars(tmp_path, "acme-inc", "twitter", 1)
        ctx = CandidateContext(
            company_manager=mgr,
            project_root=tmp_path,
            voice_manager=VoiceManager(tmp_path),
        )
        out = await from_voiceless_companies(ctx)
        assert all(c.metadata["company_id"] != "acme-inc" for c in out)

    @pytest.mark.asyncio
    async def test_skips_when_no_exemplars_dir(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        await mgr.create("acme-inc", "Acme")
        # No exemplars dir at all
        ctx = CandidateContext(
            company_manager=mgr,
            project_root=tmp_path,
            voice_manager=VoiceManager(tmp_path),
        )
        out = await from_voiceless_companies(ctx)
        assert all(c.metadata["company_id"] != "acme-inc" for c in out)

    @pytest.mark.asyncio
    async def test_caps_at_three(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        for i in range(5):
            slug = f"co-{i}"
            await mgr.create(slug, slug)
            _seed_exemplars(tmp_path, slug, "twitter", 2)
        ctx = CandidateContext(
            company_manager=mgr,
            project_root=tmp_path,
            voice_manager=VoiceManager(tmp_path),
        )
        out = await from_voiceless_companies(ctx)
        assert len(out) <= 3

    @pytest.mark.asyncio
    async def test_empty_without_voice_manager(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        await mgr.create("acme-inc", "Acme")
        _seed_exemplars(tmp_path, "acme-inc", "twitter", 3)
        ctx = CandidateContext(
            company_manager=mgr, project_root=tmp_path, voice_manager=None
        )
        assert await from_voiceless_companies(ctx) == []

    @pytest.mark.asyncio
    async def test_empty_without_company_manager(self, tmp_path) -> None:
        ctx = CandidateContext(
            company_manager=None,
            project_root=tmp_path,
            voice_manager=VoiceManager(tmp_path),
        )
        assert await from_voiceless_companies(ctx) == []

    @pytest.mark.asyncio
    async def test_collect_all_includes_generator(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        await mgr.create("acme-inc", "Acme")
        _seed_exemplars(tmp_path, "acme-inc", "twitter", 3)
        ctx = CandidateContext(
            company_manager=mgr,
            project_root=tmp_path,
            voice_manager=VoiceManager(tmp_path),
        )
        out = await collect_all(ctx)
        sources = {c.source for c in out}
        assert "voiceless_company" in sources

    @pytest.mark.asyncio
    async def test_skips_paused_company(self, db: Database, tmp_path) -> None:
        mgr = CompanyManager(db=db, project_root=tmp_path)
        await mgr.create("paused-co", "Paused")
        await mgr.set_status("paused-co", "paused")
        _seed_exemplars(tmp_path, "paused-co", "twitter", 3)
        ctx = CandidateContext(
            company_manager=mgr,
            project_root=tmp_path,
            voice_manager=VoiceManager(tmp_path),
        )
        out = await from_voiceless_companies(ctx)
        assert all(c.metadata["company_id"] != "paused-co" for c in out)
