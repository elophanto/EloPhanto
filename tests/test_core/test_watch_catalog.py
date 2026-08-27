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
        assert len(Presentation(str(b)).slides) == len(Presentation(str(a)).slides) + 4
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
