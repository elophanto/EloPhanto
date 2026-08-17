"""Voice collectors and reading (docs/87, step 2): hygiene, verbatim quotes,
Reddit / App Store parsing, and the collect tool filing rows beside — never
inside — the evidence register."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio

from core.watch import WatchManager
from core.watch_voice import (
    VoicePost,
    brand_aliases,
    dimension_for_theme,
    is_affiliate,
    parse_app_store_feed,
    parse_reddit_comments,
    parse_reddit_listing,
    quote_is_verbatim,
    read_posts,
    strip_pii,
)


@pytest_asyncio.fixture
async def wm(tmp_path):
    from core.database import Database

    db = Database(str(tmp_path / "vc.db"))
    await db.initialize()
    yield WatchManager(db)
    await db.close()


class TestHygiene:
    def test_pii_and_links_are_stripped_before_reading(self) -> None:
        raw = "u/slotsguy87 said @crownfan check https://x.co/abc or mail me at a.b@mail.com — slow payouts"
        out = strip_pii(raw)
        assert "slotsguy87" not in out and "@crownfan" not in out and "x.co" not in out
        assert "a.b@mail.com" not in out and "slow payouts" in out

    def test_affiliate_posts_are_recognised(self) -> None:
        assert is_affiliate("Sign up with my link and use my code CROWN50 for extra coins")
        assert is_affiliate("https://crowncoins.com/?ref=abc")
        assert not is_affiliate("Redemption took 9 days, support kept saying 'in review'.")

    def test_brand_aliases_cover_what_players_type(self) -> None:
        assert brand_aliases("Crown Coins Casino", "https://www.crowncoinscasino.com") == [
            "Crown Coins Casino", "Crown Coins", "CrownCoinsCasino"
        ]
        assert brand_aliases("Pulsz Bingo", "https://www.pulszbingo.com") == ["Pulsz Bingo", "PulszBingo"]

    def test_quote_must_be_verbatim_and_not_trivial(self) -> None:
        text = "Honestly the redemption took nine days and support just said in review."
        assert quote_is_verbatim("redemption took nine days", text)
        assert quote_is_verbatim("REDEMPTION   took nine days", text)
        assert not quote_is_verbatim("redemption took 9 days", text)  # paraphrase
        assert not quote_is_verbatim("took", text)  # too short


class TestParsers:
    def test_reddit_listing_keeps_brand_posts_in_window_and_drops_affiliates(self) -> None:
        now = datetime.now(UTC).timestamp()
        payload = {"data": {"children": [
            {"kind": "t3", "data": {"name": "t3_a", "title": "Crown Coins redemption slow?", "selftext": "Took 9 days for me. u/someone agrees.",
                                    "permalink": "/r/sweepstakescasinos/comments/a/x/", "created_utc": now - 3600, "score": 12, "num_comments": 15, "subreddit": "sweepstakescasinos"}},
            {"kind": "t3", "data": {"name": "t3_b", "title": "Best promo!", "selftext": "Crown Coins — sign up with my link ref=zz", "permalink": "/r/x/comments/b/y/", "created_utc": now - 60, "score": 1}},
            {"kind": "t3", "data": {"name": "t3_c", "title": "Crown Coins was great last year", "selftext": "", "permalink": "/r/x/comments/c/z/", "created_utc": now - 90 * 86400, "score": 3}},
            {"kind": "t3", "data": {"name": "t3_d", "title": "Chumba is fine", "selftext": "no mention", "permalink": "/r/x/comments/d/", "created_utc": now - 60}},
        ]}}
        posts = parse_reddit_listing(payload, aliases=["Crown Coins"], since_utc=now - 30 * 86400)
        assert [p.post_id for p in posts] == ["t3_a"]
        p = posts[0]
        assert p.url == "https://www.reddit.com/r/sweepstakescasinos/comments/a/x/"
        assert "u/someone" not in p.text and "Took 9 days" in p.text
        assert p.weight > 0.7 and p.meta["subreddit"] == "sweepstakescasinos"

    def test_reddit_comments_from_a_thread(self) -> None:
        now = datetime.now(UTC).timestamp()
        payload = [{"data": {}}, {"data": {"children": [
            {"kind": "t1", "data": {"id": "c1", "body": "Same here, redemption took over a week and support was useless.", "created_utc": now - 100, "score": 30}},
            {"kind": "t1", "data": {"id": "c2", "body": "lol", "created_utc": now - 100}},
            {"kind": "more", "data": {}},
        ]}}]
        got = parse_reddit_comments(payload, aliases=["Crown Coins"], post_url="https://www.reddit.com/r/x/comments/a/x/", since_utc=now - 86400)
        assert [c.post_id for c in got] == ["t1_c1"] and got[0].url.endswith("/comment/c1/")
        assert got[0].weight == 0.9

    def test_app_store_feed(self) -> None:
        recent = datetime.now(UTC).isoformat()
        payload = {"feed": {"entry": [
            {"title": {"label": "Crown Coins"}, "id": {"label": "app"}},  # the app entry itself
            {"id": {"label": "r1"}, "title": {"label": "Redemptions"}, "content": {"label": "Took forever to verify my ID, then paid out fine."},
             "im:rating": {"label": "3"}, "updated": {"label": recent}, "im:version": {"label": "2.1"}},
            {"id": {"label": "r2"}, "title": {"label": "Developer Response"}, "content": {"label": "Thanks for the feedback."},
             "im:rating": {"label": "5"}, "updated": {"label": recent}},
            {"id": {"label": "r3"}, "title": {"label": "old"}, "content": {"label": "Was great in 2024 when I first played it."},
             "im:rating": {"label": "5"}, "updated": {"label": "2024-01-01T00:00:00-07:00"}},
        ]}}
        since = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        got = parse_app_store_feed(payload, app_id="123", since_iso=since)
        assert [g.post_id for g in got] == ["as_r1"]
        assert got[0].rating == 3.0 and got[0].source == "app_store" and "id123" in got[0].url


class _Router:
    """Returns whatever the test says, per batch."""

    def __init__(self, items):
        self.items = items
        self.calls = 0

    async def complete(self, **kw):
        self.calls += 1
        return SimpleNamespace(content=json.dumps({"items": self.items}))


class TestReading:
    @pytest.mark.asyncio
    async def test_reading_validates_vocabulary_and_verbatim_quotes(self) -> None:
        posts = [
            VoicePost("p1", "reddit", "u1", "Redemption took nine days and support just said in review."),
            VoicePost("p2", "reddit", "u2", "Games are fun but the app crashes on every spin lately."),
            VoicePost("p3", "reddit", "u3", "anyone know the daily bonus?"),
        ]
        router = _Router([
            {"id": "p1", "theme": "redemption_speed", "sentiment": "negative", "quote": "Redemption took nine days", "dimension": "", "geo_hint": "Florida"},
            {"id": "p2", "theme": "app_stability", "sentiment": "negative", "quote": "the app crashes constantly", "dimension": "Nope", "geo_hint": ""},  # paraphrased → dropped
            {"id": "p9", "theme": "support", "sentiment": "negative", "quote": "x", "dimension": ""},  # unknown id
        ])
        items, dropped = await read_posts(
            router, brand="Crown Coins", posts=posts,
            dimension_names=["KYC strategy and customer journey", "Game portfolio and category range"],
        )
        assert len(items) == 1
        it = items[0]
        assert it["post"].post_id == "p1" and it["geo_hint"] == "Florida"
        # empty dimension → deterministic hint (redemption → KYC/journey)
        assert it["dimension"] == "KYC strategy and customer journey"
        assert dropped["unverified_quote"] == 1 and dropped["model_skip"] == 1

    @pytest.mark.asyncio
    async def test_no_router_means_nothing_read_never_invented(self) -> None:
        items, dropped = await read_posts(None, brand="X", posts=[VoicePost("p", "reddit", "", "text")], dimension_names=[])
        assert items == [] and dropped["no_router"] == 1

    def test_dimension_hint_fallback(self) -> None:
        dims = ["Loyalty programme and proposition", "Promotional proposition and generosity"]
        assert dimension_for_theme("vip_treatment", dims) == dims[0]
        assert dimension_for_theme("promo_value", dims) == dims[1]
        assert dimension_for_theme("other", dims) == ""


class TestCollectTool:
    async def _tool(self, wm, monkeypatch, *, router):
        import core.watch_voice as V
        from tools.watch import tools as T

        async def fake_reddit(brand, aliases, **kw):
            return [VoicePost("t3_a", "reddit", "https://www.reddit.com/r/x/comments/a/",
                              "Redemption took nine days and support just said in review.",
                              posted_at=datetime.now(UTC).isoformat(), weight=0.85)], []

        async def fake_find(brand, aliases, **kw):
            return "555"

        async def fake_store(app_id, **kw):
            return [VoicePost("as_1", "app_store", "https://apps.apple.com/us/app/id555",
                              "Love the games, huge selection and new ones weekly.",
                              posted_at=datetime.now(UTC).isoformat(), rating=5.0, weight=0.8)], []

        monkeypatch.setattr(V, "collect_reddit", fake_reddit)
        monkeypatch.setattr(V, "find_app_store_id", fake_find)
        monkeypatch.setattr(V, "collect_app_store", fake_store)
        t = T.WatchVoiceCollectTool()
        t._watch_manager = wm
        t._router = router
        t._config = None
        return t

    @pytest.mark.asyncio
    async def test_collect_files_voice_rows_and_leaves_the_pack_alone(self, wm, monkeypatch) -> None:
        await wm.upsert_dimension(name="KYC strategy and customer journey", company_id="c1", weight_pct=50,
                                  subcriteria=[{"name": "kyc", "weight_pct": 100}])
        await wm.upsert_dimension(name="Game portfolio and category range", company_id="c1", weight_pct=50,
                                  subcriteria=[{"name": "range", "weight_pct": 100}])
        await wm.add_subject(company_id="c1", name="Crown Coins", url="https://crowncoins.example")
        router = _Router([
            {"id": "t3_a", "theme": "redemption_speed", "sentiment": "negative", "quote": "Redemption took nine days", "dimension": "", "geo_hint": ""},
            {"id": "as_1", "theme": "game_selection", "sentiment": "positive", "quote": "huge selection and new ones weekly", "dimension": "Game portfolio and category range", "geo_hint": ""},
        ])
        t = await self._tool(wm, monkeypatch, router=router)
        res = await t.execute({"subject": "Crown Coins", "company_id": "c1"})
        assert res.success, res.error
        assert res.data["kept_total"] == 2
        b = res.data["brands"][0]
        assert b["sources"]["app_store"]["app_id"] == "555" and b["duplicates"] == 0
        rows = await wm.list_voice("c1")
        assert {r.source for r in rows} == {"reddit", "app_store"}
        kyc = next(r for r in rows if r.theme == "redemption_speed")
        dims = {d.dimension_id: d.name for d in await wm.list_dimensions("c1")}
        assert dims[kyc.dimension_id] == "KYC strategy and customer journey"
        # the app id is cached on the subject for next time
        subj2 = await wm.get_subject_by_name("Crown Coins", "c1")
        assert "app_store:555" in subj2.tags
        # and the pack is untouched: no evidence, no scores
        assert await wm.list_evidence("c1") == [] and await wm.list_scores("c1") == []
        # a second run is all duplicates
        res2 = await t.execute({"subject": "Crown Coins", "company_id": "c1"})
        assert res2.data["kept_total"] == 0 and res2.data["brands"][0]["duplicates"] == 2

    @pytest.mark.asyncio
    async def test_register_is_canon_and_dry_run_saves_nothing(self, wm, monkeypatch) -> None:
        await wm.add_subject(company_id="c1", name="Crown Coins")
        t = await self._tool(wm, monkeypatch, router=_Router([
            {"id": "t3_a", "theme": "redemption_speed", "sentiment": "negative", "quote": "Redemption took nine days", "dimension": "", "geo_hint": ""}]))
        bad = await t.execute({"subject": "Fortune Coins", "company_id": "c1"})
        assert not bad.success and "register is canon" in bad.error
        dry = await t.execute({"subject": "Crown Coins", "company_id": "c1", "save": False})
        assert dry.success and dry.data["kept_total"] == 1 and await wm.list_voice("c1") == []
