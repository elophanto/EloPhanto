"""Catalog — the raw inventory behind the scores (docs/89).

The client asked for "game providers, coin packages, promotions and game
list, just the raw data". It is a list, not a judgement: verified against
the page, stamped with the session it was read in, never scored.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from pptx import Presentation

from core.watch import WatchManager
from core.watch_catalog import (
    catalog_page_kind,
    dedupe_key,
    extract_catalog,
    parse_price,
    rank_catalog_pages,
)


class _Router:
    def __init__(self, items):
        self.items = items

    async def complete(self, **kw):
        return SimpleNamespace(content=json.dumps({"items": self.items}))


@pytest_asyncio.fixture
async def wm(tmp_path):
    from core.database import Database

    db = Database(str(tmp_path / "cat.db"))
    await db.initialize()
    yield WatchManager(db)
    await db.close()


class TestPagePicking:
    def test_each_kind_finds_its_page_and_legal_pages_are_never_one(self) -> None:
        assert catalog_page_kind("https://b.com/store", "Buy coins") == "coin_package"
        assert catalog_page_kind("https://b.com/promotions", "") == "promotion"
        assert catalog_page_kind("https://b.com/providers", "") == "provider"
        assert catalog_page_kind("https://b.com/slots", "All slots") == "game"
        assert catalog_page_kind("https://b.com/terms", "Terms") == ""
        assert catalog_page_kind("https://b.com/sweepstakes-rules", "") == ""

    def test_pages_group_by_kind_best_first(self) -> None:
        pages = [
            {"url": "https://b.com/", "title": "Home"},
            {"url": "https://b.com/store", "title": "Store"},
            {"url": "https://b.com/shop", "title": "Shop"},
            {"url": "https://b.com/buy", "title": "Buy"},
            {"url": "https://b.com/promotions", "title": "Promotions"},
        ]
        got = rank_catalog_pages(pages, per_kind=2)
        assert [p["url"] for p in got["coin_package"]] == ["https://b.com/store", "https://b.com/shop"]
        assert [p["url"] for p in got["promotion"]] == ["https://b.com/promotions"]

    def test_price_parsing(self) -> None:
        assert parse_price("$29.99 package") == 29.99
        assert parse_price("$4,999.00") == 4999.0
        assert parse_price("Best value") is None


class TestExtraction:
    @pytest.mark.asyncio
    async def test_items_must_be_printed_on_the_page(self) -> None:
        page = "Our studios: Pragmatic Play, Hacksaw Gaming and NetEnt power the lobby."
        r = _Router([
            {"name": "Pragmatic Play", "detail": "", "index": 0},
            {"name": "NetEnt", "detail": "", "index": 2},
            {"name": "Evolution Gaming", "detail": "invented", "index": 3},  # not on the page
        ])
        got = await extract_catalog(r, kind="provider", brand="B", page_text=page)
        assert [g["name"] for g in got] == ["Pragmatic Play", "NetEnt"]

    @pytest.mark.asyncio
    async def test_packages_keep_order_price_and_grant(self) -> None:
        page = "$9.99 gets GC 100,000 + free SC 10. $29.99 gets GC 700,000 + free SC 55."
        r = _Router([
            {"name": "$9.99", "coins": "GC 100,000 + free SC 10", "detail": "starter", "index": 0},
            {"name": "$29.99", "coins": "GC 700,000 + free SC 55", "detail": "", "index": 1},
        ])
        got = await extract_catalog(r, kind="coin_package", brand="B", page_text=page)
        assert [g["price_usd"] for g in got] == [9.99, 29.99]
        assert got[0]["coins_text"] == "GC 100,000 + free SC 10"
        assert [g["sort_index"] for g in got] == [0, 1]

    @pytest.mark.asyncio
    async def test_no_router_or_bad_kind_invents_nothing(self) -> None:
        assert await extract_catalog(None, kind="game", brand="B", page_text="x") == []
        assert await extract_catalog(_Router([]), kind="nonsense", brand="B", page_text="x") == []


class TestResearchFirst:
    """Public pages and the open web first; a session is spent only on what
    they cannot answer, and the metered exit is not spent at all."""

    def test_queries_name_the_brand_and_the_kind(self) -> None:
        from core.watch_catalog import research_queries

        qs = dict(research_queries("McLuck", ["provider", "coin_package"], year=2026))
        assert any("providers" in q for k, q in research_queries("McLuck", ["provider"], year=2026))
        assert "coin packages" in " ".join(
            q for k, q in research_queries("McLuck", ["coin_package"], year=2026)
        )
        assert qs  # both kinds produced queries

    def test_the_brands_own_domain_outranks_coupon_farms(self) -> None:
        from core.watch_catalog import rank_research_urls

        got = rank_research_urls(
            [
                {"url": "https://promo-codes.example/mcluck-bonus"},
                {"url": "https://www.mcluck.com/providers"},
                {"url": "https://casinoreview.example/mcluck"},
                {"url": "https://www.mcluck.com/terms"},   # legal pages never
                {"url": "not-a-url"},
            ],
            brand_host="mcluck.com",
        )
        assert got[0] == "https://www.mcluck.com/providers"
        assert got[-1] == "https://promo-codes.example/mcluck-bonus"
        assert all("terms" not in u for u in got)

    @pytest.mark.asyncio
    async def test_research_fills_what_the_site_missed_and_marks_the_source(
        self, wm, monkeypatch
    ) -> None:
        import core.watch_observe as wo
        from tools.watch import tools as T

        await wm.add_subject(company_id="c1", name="McLuck", url="https://www.mcluck.com")

        async def fake_collect(start_url, **kw):
            # the brand's own pages say nothing about providers
            return [{"url": "https://www.mcluck.com/providers", "title": "Providers",
                     "text": "Our lobby is powered by great games.", "error": None, "method": "http"}]

        async def fake_search(query, *, api_key, **kw):
            assert api_key == "sk-test"
            return [{"url": "https://review.example/mcluck", "title": "review", "snippet": ""}]

        async def fake_fetch(url, **kw):
            assert kw.get("proxy_url") is None, "research must not spend the metered exit"
            return ("McLuck carries Pragmatic Play and Hacksaw Gaming titles.", None, "http")

        monkeypatch.setattr(wo, "collect_pages", fake_collect)
        monkeypatch.setattr(wo, "search_web", fake_search)
        monkeypatch.setattr(wo, "fetch_page_best_effort", fake_fetch)

        t = T.WatchCatalogCollectTool()
        t._watch_manager, t._config, t._browser_manager = wm, None, None
        t._vault = {"search_sh_api_key": "sk-test"}
        t._router = _Router([{"name": "Pragmatic Play", "detail": "", "index": 0},
                             {"name": "Hacksaw Gaming", "detail": "", "index": 1}])
        res = await t.execute({"company_id": "c1", "kinds": ["provider"]})
        assert res.success, res.error
        kinds = res.data["brands"][0]["kinds"]["provider"]
        assert kinds["from"] == "public research" and kinds["found"] == 2
        rows = await wm.list_catalog("c1")
        assert {r.name for r in rows} == {"Pragmatic Play", "Hacksaw Gaming"}
        assert all(r.source_type == "third_party" for r in rows)
        assert all(r.geo_state == "n/a" for r in rows)  # no geo claim, no proxy

    @pytest.mark.asyncio
    async def test_nothing_public_marks_the_kind_for_sign_in_only_when_asked(
        self, wm, monkeypatch
    ) -> None:
        import core.watch_observe as wo
        from tools.watch import tools as T

        await wm.add_subject(company_id="c1", name="McLuck", url="https://www.mcluck.com")

        async def empty_pages(start_url, **kw):
            return [{"url": "https://www.mcluck.com/store", "title": "Store",
                     "text": "Sign in to see your prices.", "error": None, "method": "http"}]

        async def no_hits(query, *, api_key, **kw):
            return []

        monkeypatch.setattr(wo, "collect_pages", empty_pages)
        monkeypatch.setattr(wo, "search_web", no_hits)

        t = T.WatchCatalogCollectTool()
        t._watch_manager, t._config, t._browser_manager = wm, None, None
        t._vault = {"search_sh_api_key": "sk-test"}
        t._router = _Router([])
        quiet = await t.execute({"company_id": "c1", "kinds": ["coin_package"]})
        assert quiet.data["needs_sign_in"] == []  # not asked, so not suggested
        loud = await t.execute({"company_id": "c1", "kinds": ["coin_package"],
                                "sign_in_if_missing": True})
        assert loud.data["needs_sign_in"] == ["McLuck:coin_package"]


class TestAttribution:
    """A page reached by searching a brand may be about ten other brands —
    or about somebody's own business (2026-08-27: a game studio's services
    page gave LuckyLand a provider it does not carry)."""

    def test_comparison_and_unrelated_pages_are_refused(self) -> None:
        from core.watch_catalog import research_page_ok
        from core.watch_voice import brand_aliases

        ll = brand_aliases("LuckyLand Slots", "https://www.luckylandslots.com")
        assert not research_page_ok(
            "https://www.wagertalk.com/sites-like/luckyland", "LuckyLand " * 9,
            "LuckyLand Slots", ll,
        )
        assert not research_page_ok(
            "https://www.juegostudio.com/game-development-services",
            "We build games for clients", "LuckyLand Slots", ll,
        )
        assert not research_page_ok("https://x.example/z", "A page about tractors", "Pulsz", ["Pulsz"])

    def test_brand_pages_and_reviews_are_accepted(self) -> None:
        from core.watch_catalog import research_page_ok
        from core.watch_voice import brand_aliases

        assert research_page_ok("https://www.mcluck.com/providers", "…", "McLuck", ["McLuck"])
        # the short name in the URL is enough — "…/reviews/modo/"
        assert research_page_ok(
            "https://time2play.com/casinos/reviews/modo/", "Modo review",
            "Modo Casino", brand_aliases("Modo Casino", "https://www.modo.us"),
        )
        # or the brand named repeatedly in the text
        assert research_page_ok(
            "https://x.example/y", "Pulsz is great. Pulsz pays. Pulsz has games.",
            "Pulsz", ["Pulsz"],
        )


class TestProvenanceIsVisible:
    def test_a_ladder_read_off_a_review_site_says_so(self, tmp_path) -> None:
        from pptx import Presentation

        from core.watch_deck import factual_narrative, render_executive_deck

        catalog = {
            "items": 2, "label": "Raw inventory…",
            "totals": {"coin_package": 2}, "third_party_only": ["Pulsz coin_package"],
            "brands": [{
                "subject_id": "s", "name": "Pulsz", "is_self": True,
                "counts": {"coin_package": 2}, "providers": [], "games_sample": [],
                "promotions": [], "customer_states": ["logged_out"], "observed_at": "2026-08-27",
                "sources": {"coin_package": ["third_party"]},
                "packages": [
                    {"name": "$1.99", "price_usd": 1.99, "coins": "30,000 Gold Coins",
                     "detail": "", "url": "https://review.example", "source_type": "third_party"},
                    {"name": "$4.99", "price_usd": 4.99, "coins": "79,500 Gold Coins",
                     "detail": "", "url": "https://www.pulsz.com/store", "source_type": "site"},
                ],
            }],
        }
        card = {"rows": [], "dimensions": []}
        out = tmp_path / "p.pptx"
        render_executive_deck(card, diff=None, judged=[], summary=factual_narrative(card, None, [], []),
                              gaps=[], evidence_count=1, path=out, catalog=catalog)
        texts = []
        for sl in Presentation(str(out)).slides:
            parts = [sh.text_frame.text for sh in sl.shapes if sh.has_text_frame]
            for sh in sl.shapes:
                if sh.has_table:
                    parts += [c.text for r in sh.table.rows for c in r.cells]
            texts.append("\n".join(parts))
        slide = next(t for t in texts if "Coin packages" in t)
        assert "review site" in slide and "the brand" in slide
        assert "reported, not observed" in slide  # the caveat is on the page, not implied


class TestLadderHygiene:
    """A price ladder read off review-site prose picks up junk rungs and
    tautologies (2026-08-27 deck: 'Card Crush 30$ → like 12 coins', and
    'Crown Coins $1.99 → $1.99')."""

    @pytest.mark.asyncio
    async def test_a_rung_without_a_readable_price_is_dropped(self) -> None:
        page = "Packages start at 30$ and you get like 12 coins. The $9.99 tier gives 25 Mystery Coins."
        r = _Router([
            {"name": "30$", "coins": "like 12 coins", "detail": "", "index": 0},
            {"name": "$9.99", "coins": "25 Mystery Coins", "detail": "", "index": 1},
        ])
        got = await extract_catalog(r, kind="coin_package", brand="B", page_text=page)
        assert [g["name"] for g in got] == ["$9.99"] and got[0]["price_usd"] == 9.99

    @pytest.mark.asyncio
    async def test_a_grant_that_only_repeats_the_price_is_blanked(self) -> None:
        page = "The $1.99 package is available."
        r = _Router([{"name": "$1.99", "coins": "$1.99", "detail": "Min. package", "index": 0}])
        got = await extract_catalog(r, kind="coin_package", brand="B", page_text=page)
        assert got[0]["coins_text"] == "" and got[0]["price_usd"] == 1.99

    def test_the_slide_shows_the_detail_instead_and_names_the_source(self, tmp_path) -> None:
        from pptx import Presentation

        from core.watch_deck import factual_narrative, render_executive_deck

        catalog = {
            "items": 1, "label": "Raw inventory…", "totals": {"coin_package": 1, "promotion": 40},
            "third_party_only": ["Crown coin_package"],
            "brands": [{
                "subject_id": "s", "name": "Crown", "is_self": False,
                "counts": {"coin_package": 1, "promotion": 2}, "providers": [], "games_sample": [],
                "sources": {"coin_package": ["third_party"]},
                "promotions": [{"name": "August Deal", "detail": "", "image": "", "url": "u"}],
                "packages": [{"name": "$1.99", "price_usd": 1.99, "coins": "",
                              "detail": "Its coin split is not published", "url": "u",
                              "source_type": "third_party"}],
                "customer_states": ["logged_out"], "observed_at": "2026-08-27",
            }],
        }
        card = {"rows": [], "dimensions": []}
        out = tmp_path / "d.pptx"
        render_executive_deck(card, diff=None, judged=[], summary=factual_narrative(card, None, [], []),
                              gaps=[], evidence_count=1, path=out, catalog=catalog)
        texts = []
        for sl in Presentation(str(out)).slides:
            parts = [sh.text_frame.text for sh in sl.shapes if sh.has_text_frame]
            for sh in sl.shapes:
                if sh.has_table:
                    parts += [c.text for r in sh.table.rows for c in r.cells]
            texts.append("\n".join(parts))
        pkg = next(t for t in texts if "Coin packages" in t)
        assert "as reported by public sources" in pkg      # not "as priced on each store"
        assert "Its coin split is not published" in pkg    # detail stands in for the grant
        assert "$1.99\n$1.99" not in pkg                   # never the price twice
        promo = next(t for t in texts if "promotions on record" in t)
        assert "40 promotions on record" in promo          # the total, not just what fits


class TestPerBrandDetail:
    """The client asked for the raw data, not a summary of it: the deck
    carries a page per brand with every provider, the whole ladder, the
    promotions and the titles (2026-08-27: the appendix showed 12 ticked
    providers and five sample games while 39 and 44 were held)."""

    def test_a_page_per_brand_lists_what_is_held_and_counts_the_rest(self, tmp_path) -> None:
        from pptx import Presentation

        from core.watch_deck import factual_narrative, render_executive_deck

        provs = [f"Studio {i}" for i in range(60)]
        games = [f"Game {i}" for i in range(70)]
        catalog = {
            "items": 140, "label": "Raw inventory…",
            "totals": {"provider": 60, "coin_package": 2, "promotion": 3, "game": 70},
            "third_party_only": [],
            "brands": [{
                "subject_id": "s", "name": "Pulsz", "is_self": True,
                "counts": {"provider": 60, "coin_package": 2, "promotion": 3, "game": 70},
                "providers": provs, "games_sample": games[:12], "games_full": games,
                "sources": {"provider": ["site"]},
                "packages": [
                    {"name": "$1.99", "price_usd": 1.99, "coins": "30,000 Gold Coins",
                     "detail": "", "url": "u", "source_type": "site"},
                    {"name": "$4.99", "price_usd": 4.99, "coins": "79,500 Gold Coins",
                     "detail": "", "url": "u", "source_type": "site"},
                ],
                "promotions": [{"name": f"Promo {i}", "detail": "terms", "image": "", "url": "u"}
                               for i in range(3)],
                "promotions_full": [{"name": f"Promo {i}", "detail": "terms", "image": "", "url": "u"}
                                    for i in range(3)],
                "customer_states": ["logged_out"], "observed_at": "2026-08-27",
            }],
        }
        card = {"rows": [], "dimensions": []}
        out = tmp_path / "d.pptx"
        render_executive_deck(card, diff=None, judged=[], summary=factual_narrative(card, None, [], []),
                              gaps=[], evidence_count=1, path=out, catalog=catalog)
        prs = Presentation(str(out))
        page = next(
            sl for sl in prs.slides
            if any(sh.has_text_frame and sh.text_frame.text.startswith("RAW DATA · PULSZ")
                   for sh in sl.shapes)
        )
        text = "\n".join(sh.text_frame.text for sh in page.shapes if sh.has_text_frame)
        assert "60 providers · 2 packages · 3 promotions · 70 titles read" in text
        assert "Studio 0" in text and "Studio 43" in text          # the list itself, not a tick
        assert "$1.99 → 30,000 Gold Coins" in text                 # the ladder, rung by rung
        assert "Promo 0" in text and "Game 0" in text
        assert "more in the workbook" in text                      # and what did not fit is counted
        # nothing runs off the page
        W, H = prs.slide_width, prs.slide_height
        assert not [
            sh for sh in page.shapes
            if sh.left is not None and (sh.left < 0 or sh.top < 0
                                        or sh.left + sh.width > W + 18288
                                        or sh.top + sh.height > H + 18288)
        ]


class TestRegister:
    @pytest.mark.asyncio
    async def test_recollection_updates_rather_than_duplicating(self, wm) -> None:
        subj = await wm.add_subject(company_id="c1", name="Crown", url="https://c.example")
        row, is_new = await wm.add_catalog_item(
            company_id="c1", subject_id=subj.subject_id, brand_name="Crown",
            kind="coin_package", name="$29.99", coins_text="GC 700", price_usd=29.99,
            sort_index=1, source_url="https://c.example/store",
        )
        assert is_new and row["catalog_id"]
        # the ladder changes: same package, new grant — one row, updated
        row2, is_new2 = await wm.add_catalog_item(
            company_id="c1", subject_id=subj.subject_id, brand_name="Crown",
            kind="coin_package", name="$29.99", coins_text="GC 900 + SC 60", price_usd=29.99,
            sort_index=1, source_url="https://c.example/store", customer_state="registered",
        )
        assert not is_new2
        rows = await wm.list_catalog("c1")
        assert len(rows) == 1 and rows[0].coins_text == "GC 900 + SC 60"
        assert rows[0].customer_state == "registered"
        # never scored, and the evidence register is untouched
        assert await wm.list_evidence("c1") == [] and await wm.list_scores("c1") == []
        assert dedupe_key("Crown", "coin_package", "$29.99") == dedupe_key("crown", "coin_package", " $29.99 ")

    @pytest.mark.asyncio
    async def test_vocabularies_are_enforced(self, wm) -> None:
        subj = await wm.add_subject(company_id="c1", name="Crown")
        with pytest.raises(ValueError):
            await wm.add_catalog_item(company_id="c1", subject_id=subj.subject_id,
                                      kind="jackpot", name="x")
        with pytest.raises(ValueError):
            await wm.add_catalog_item(company_id="c1", subject_id=subj.subject_id,
                                      kind="game", name="x", customer_state="whale")

    @pytest.mark.asyncio
    async def test_summary_reads_ladders_and_counts(self, wm) -> None:
        us = await wm.add_subject(company_id="c1", name="Us", is_self=True)
        cc = await wm.add_subject(company_id="c1", name="Crown")
        for name, price, idx in (("$49.99", 49.99, 2), ("$9.99", 9.99, 0), ("$29.99", 29.99, 1)):
            await wm.add_catalog_item(company_id="c1", subject_id=cc.subject_id, brand_name="Crown",
                                      kind="coin_package", name=name, price_usd=price, sort_index=idx)
        for prov in ("Pragmatic Play", "NetEnt"):
            await wm.add_catalog_item(company_id="c1", subject_id=cc.subject_id, brand_name="Crown",
                                      kind="provider", name=prov)
        await wm.add_catalog_item(company_id="c1", subject_id=us.subject_id, brand_name="Us",
                                  kind="game", name="Sweet Bonanza")
        s = await wm.catalog_summary("c1")
        assert s["items"] == 6 and s["totals"]["coin_package"] == 3
        assert s["brands"][0]["name"] == "Us"  # ours first
        crown = next(b for b in s["brands"] if b["name"] == "Crown")
        assert [p["price_usd"] for p in crown["packages"]] == [9.99, 29.99, 49.99]  # ladder in order
        assert crown["counts"]["provider"] == 2
        snap = await wm.get_snapshot(await wm.take_snapshot("c1"))
        assert snap["catalog"]["items"] == 6


class TestDeckAndWorkbook:
    def _catalog(self):
        return {
            "items": 8, "label": "Raw inventory as printed…",
            "totals": {"provider": 2, "coin_package": 2, "promotion": 2, "game": 2},
            "brands": [{
                "subject_id": "s", "name": "Crown", "is_self": False,
                "counts": {"provider": 2, "coin_package": 2, "promotion": 2, "game": 2},
                "providers": ["Pragmatic Play", "NetEnt"],
                "packages": [{"name": "$9.99", "price_usd": 9.99, "coins": "GC 100,000 + SC 10",
                              "detail": "starter", "url": "u"},
                             {"name": "$29.99", "price_usd": 29.99, "coins": "GC 700,000 + SC 55",
                              "detail": "", "url": "u"}],
                "promotions": [{"name": "150% Extra Coins", "detail": "first purchase, 24h",
                                "image": "", "url": "u"}],
                "games_sample": ["Sweet Bonanza", "Gates of Olympus"],
                "customer_states": ["registered"], "observed_at": "2026-08-27",
            }],
        }

    def test_appendix_slides_appear_only_with_rows(self, tmp_path) -> None:
        from core.watch_deck import factual_narrative, render_executive_deck

        card = {"rows": [{"name": "Crown", "is_self": False, "rank": 1, "provisional": False,
                          "overall": {"normalized_pct": 60.0, "coverage_pct": 70.0}, "dimensions": {}}],
                "dimensions": []}
        a, b = tmp_path / "a.pptx", tmp_path / "b.pptx"
        n = factual_narrative(card, None, [], [])
        render_executive_deck(card, diff=None, judged=[], summary=n, gaps=[], evidence_count=1, path=a)
        render_executive_deck(card, diff=None, judged=[], summary=n, gaps=[], evidence_count=1, path=b,
                              catalog=self._catalog())
        # four field-level slides + one raw-data page for the brand itself
        assert len(Presentation(str(b)).slides) == len(Presentation(str(a)).slides) + 5
        texts = []
        for sl in Presentation(str(b)).slides:
            parts = [sh.text_frame.text for sh in sl.shapes if sh.has_text_frame]
            for sh in sl.shapes:
                if sh.has_table:
                    parts += [c.text for r in sh.table.rows for c in r.cells]
            texts.append("\n".join(parts))
        assert any("Pragmatic Play" in t for t in texts)
        assert any("$29.99" in t and "GC 700,000 + SC 55" in t for t in texts)
        assert any("150% Extra Coins" in t for t in texts)
        assert any("Sweet Bonanza" in t for t in texts)

    def test_workbook_gains_one_sheet_per_kind(self, tmp_path) -> None:
        from openpyxl import load_workbook

        from core.watch_xlsx import render_scorecard_xlsx

        card = {"rows": [], "dimensions": []}
        rows = [
            {"brand": "Crown", "kind": "provider", "name": "NetEnt", "detail": "", "url": "u",
             "session": "logged_out", "observed_at": "2026-08-27", "sort_index": 0},
            {"brand": "Crown", "kind": "coin_package", "name": "$29.99", "price_usd": 29.99,
             "coins": "GC 700,000", "detail": "", "url": "u", "session": "registered",
             "observed_at": "2026-08-27", "sort_index": 1},
            {"brand": "Crown", "kind": "promotion", "name": "150% Extra", "detail": "24h",
             "image": "/shots/p.jpg", "url": "u", "session": "logged_out",
             "observed_at": "2026-08-27", "sort_index": 0},
            {"brand": "Crown", "kind": "game", "name": "Sweet Bonanza", "detail": "Pragmatic",
             "url": "u", "session": "logged_out", "observed_at": "2026-08-27", "sort_index": 0},
        ]
        plain = render_scorecard_xlsx(card, dimensions=[], evidence=[], staleness=[], path=tmp_path / "a.xlsx")
        assert "Providers" not in load_workbook(plain).sheetnames
        with_raw = render_scorecard_xlsx(card, dimensions=[], evidence=[], staleness=[],
                                         path=tmp_path / "b.xlsx", catalog_rows=rows)
        wb = load_workbook(with_raw)
        assert {"Providers", "Coin packages", "Promotions", "Games"} <= set(wb.sheetnames)
        assert wb["Coin packages"]["B4"].value == 29.99
        assert wb["Promotions"]["D4"].value == "/shots/p.jpg"
