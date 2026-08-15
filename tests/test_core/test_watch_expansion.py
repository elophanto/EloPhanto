"""Executive narrative rules and search-driven source expansion.

Two complaints from the first customer-facing pack (2026-08-15):

1. "It mentions some SHA which makes zero sense. It has no design." The deck
   carried internal bookkeeping and read as a dump. The narrative prompt now
   bans machinery talk outright, and the renderer scrubs whatever slips
   through — both layers tested here.

2. "For some of the casinos it didn't spot info. It should research
   properly." The brand's own site was the only source, and for brands
   behind JS shells and bot walls that meant "not publicly observable" while
   reviews and help centers carried the facts in plain text. Expansion
   searches for third-party pages, reads them through the same verified
   exit, and holds them to the same verbatim-excerpt gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

import core.watch_observe as wo
from core.watch import WatchManager
from core.watch_deck import _clean
from tools.watch.tools import _DECK_NARRATIVE_SYSTEM


class TestNarrativeContract:
    def test_bans_internal_bookkeeping_by_name(self) -> None:
        text = _DECK_NARRATIVE_SYSTEM.lower()
        for term in ("hashes", "sha", "file paths", "manifests", "checkpoints",
                     "run ids"):
            assert term in text, f"prompt must ban {term!r}"
        assert "the room hears about the market, not about the machinery" in text

    def test_demands_action_titles(self) -> None:
        text = _DECK_NARRATIVE_SYSTEM.lower()
        assert "a sentence someone could disagree with" in text
        assert "never a label" in text

    def test_demands_en_dashes(self) -> None:
        assert "en dashes (–), never em dashes (—)" in _DECK_NARRATIVE_SYSTEM


class TestRendererScrubber:
    """The prompt is the first layer; the scrubber catches what slips."""

    def test_strips_hashes(self) -> None:
        assert "d933a396737d1868" not in _clean(
            "Verified via d933a396737d1868 capture"
        )

    def test_strips_bookkeeping_words(self) -> None:
        out = _clean("Per the SHA-256 freeze receipt and manifest, scores held.")
        assert "SHA" not in out and "manifest" not in out.lower()
        assert "freeze receipt" not in out.lower()

    def test_swaps_em_dashes(self) -> None:
        assert "—" not in _clean("Leads — but narrowly")
        assert "–" in _clean("Leads — but narrowly")

    def test_leaves_ordinary_numbers_alone(self) -> None:
        out = _clean("Revenue of 1000000 across 14 brands in 2026")
        assert "1000000" in out and "14" in out and "2026" in out

    def test_caps(self) -> None:
        assert len(_clean("x" * 999, 120)) == 120


class TestExpansionPrimitives:
    def test_queries_group_missing_dimensions(self) -> None:
        qs = wo.expansion_queries(
            "McLuck",
            ["Payment options and limits", "AMOE policy", "Loyalty programme",
             "KYC strategy"],
        )
        assert qs and all(q.startswith('"McLuck"') for q in qs)
        assert len(qs) <= 3
        assert "Payment" in qs[0]

    def test_no_missing_dimensions_no_queries(self) -> None:
        assert wo.expansion_queries("McLuck", []) == []

    def test_url_picker_dedupes_hosts_and_skips_already_fetched(self) -> None:
        results = [
            {"url": "https://reviews.example/mcluck", "title": "", "snippet": ""},
            {"url": "https://reviews.example/mcluck-2", "title": "", "snippet": ""},
            {"url": "https://www.mcluck.com/", "title": "", "snippet": ""},
            {"url": "ftp://bad.example/x", "title": "", "snippet": ""},
            {"url": "https://help.example/article#frag", "title": "", "snippet": ""},
        ]
        picked = wo.pick_expansion_urls(
            results, already_fetched={"https://www.mcluck.com/"}, limit=4
        )
        assert picked == [
            "https://reviews.example/mcluck",
            "https://help.example/article",
        ]


@dataclass
class _Resp:
    content: str


class _Router:
    """Extracts a claim only for the dimension the page supports."""

    async def complete(self, *, messages: list[dict[str, str]], **_kw: Any) -> _Resp:
        return _Resp(
            '{"claims": [{"dimension": "Payments", "subcriterion": "methods", '
            '"claim": "McLuck supports Visa and ACH withdrawals", '
            '"value_text": "Visa, ACH", '
            '"excerpt": "McLuck supports Visa and ACH withdrawals for players"}]}'
        )


class _Vault:
    def __init__(self, key: str | None) -> None:
        self._key = key

    def get(self, name: str) -> str | None:
        return self._key if name == "search_sh_api_key" else None


@pytest.fixture
async def wm(tmp_path):
    from core.database import Database

    db = Database(str(tmp_path / "exp.db"))
    await db.initialize()
    yield WatchManager(db)
    await db.close()


async def _analyze(wm, monkeypatch, *, vault_key, search_results):
    from tools.watch.tools import WatchAnalyzeTool

    await wm.upsert_dimension(
        name="Game portfolio", company_id="c1", weight_pct=50,
        subcriteria=[{"name": "range", "weight_pct": 100}],
    )
    await wm.upsert_dimension(
        name="Payments", company_id="c1", weight_pct=50,
        subcriteria=[{"name": "methods", "weight_pct": 100}],
    )
    await wm.add_subject(name="McLuck", company_id="c1", url="https://www.mcluck.com")

    # The brand's own site talks about games only — Payments stays silent.
    async def fake_collect(start_url, **kw):
        return [{
            "url": start_url,
            "text": "Play over 1,000 casino-style games at McLuck today " * 20,
            "error": None, "method": "http",
        }]

    site_claims = (
        '{"claims": [{"dimension": "Game portfolio", "subcriterion": "range", '
        '"claim": "McLuck offers over 1,000 games", "value_text": "1,000", '
        '"excerpt": "Play over 1,000 casino-style games at McLuck today"}]}'
    )

    class SiteThenExpandRouter:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, **_kw: Any) -> _Resp:
            self.calls += 1
            if self.calls == 1:
                return _Resp(site_claims)
            _kw.pop("messages", None)
            return await _Router().complete(messages=[], **_kw)

    async def fake_search(query, *, api_key, **kw):
        assert api_key == "sk-test"
        return search_results

    async def fake_fetch(url, **kw):
        return ("McLuck supports Visa and ACH withdrawals for players " * 10,
                None, "http")

    monkeypatch.setattr(wo, "collect_pages", fake_collect)
    monkeypatch.setattr(wo, "search_web", fake_search)
    # The tool imports this inside execute(), so patching the source module
    # is what its function-scope import resolves against.
    monkeypatch.setattr(wo, "fetch_page_best_effort", fake_fetch)

    t = WatchAnalyzeTool()
    t._watch_manager = wm
    t._router = SiteThenExpandRouter()
    t._config = None
    t._vault = _Vault(vault_key)
    return await t.execute({"subject": "McLuck", "company_id": "c1",
                            "save": False, "deck": False})


class TestExpansionInAnalyze:
    @pytest.mark.asyncio
    async def test_silent_dimensions_get_third_party_evidence(
        self, wm, monkeypatch
    ) -> None:
        res = await _analyze(
            wm, monkeypatch, vault_key="sk-test",
            search_results=[{"url": "https://reviews.example/mcluck",
                             "title": "McLuck review", "snippet": ""}],
        )
        assert res.success, res.error
        exp = res.data["source_expansion"]
        assert exp["attempted"] is True
        assert exp["missing_dimensions"] == ["Payments"]
        assert exp["evidence_written"] == 1

        rows = await wm.list_evidence("c1")
        third_party = [r for r in rows if r.source_type == "third_party"]
        assert len(third_party) == 1
        assert third_party[0].source_url == "https://reviews.example/mcluck"
        assert third_party[0].confidence == "low"
        assert "Visa and ACH" in third_party[0].claim

    @pytest.mark.asyncio
    async def test_no_vault_key_skips_and_says_so(self, wm, monkeypatch) -> None:
        res = await _analyze(wm, monkeypatch, vault_key=None, search_results=[])
        assert res.success, res.error
        exp = res.data["source_expansion"]
        assert exp["attempted"] is False
        assert "search_sh_api_key" in exp["note"]
        rows = await wm.list_evidence("c1")
        assert all(r.source_type == "site" for r in rows)

    @pytest.mark.asyncio
    async def test_covered_dimensions_are_not_searched(self, wm, monkeypatch) -> None:
        """Expansion targets only what the site left silent."""
        res = await _analyze(
            wm, monkeypatch, vault_key="sk-test",
            search_results=[{"url": "https://reviews.example/mcluck",
                             "title": "", "snippet": ""}],
        )
        exp = res.data["source_expansion"]
        assert "Game portfolio" not in exp["missing_dimensions"]
