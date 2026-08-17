"""Voice of customer — a second evidence class beside the pack (docs/87).

Opinion never becomes fact: rows live in watch_voice, never in
watch_evidence; nothing here moves a score. The reading is shares with n,
brands under the minimum are 'too few to read', and cycles diff by theme.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from core.watch import (
    VOICE_THEMES,
    WatchManager,
    WatchSubject,
    WatchVoice,
    diff_voice,
    summarize_voice,
    voice_dedupe_key,
)


@pytest_asyncio.fixture
async def wm(tmp_path):
    from core.database import Database

    db = Database(str(tmp_path / "voice.db"))
    await db.initialize()
    yield WatchManager(db)
    await db.close()


def _row(subject, theme, sentiment, quote, *, days_ago=1, weight=1.0, rating=None, dim=""):
    when = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    return WatchVoice(
        voice_id=f"v-{quote[:8]}", subject_id=subject, source="reddit", theme=theme,
        sentiment=sentiment, quote=quote, posted_at=when, observed_at=when,
        weight=weight, rating=rating, dimension_id=dim,
    )


def _subjects():
    return [
        WatchSubject(subject_id="us", company_id="c1", name="Us", is_self=True),
        WatchSubject(subject_id="cc", company_id="c1", name="Crown", is_self=False),
        WatchSubject(subject_id="sb", company_id="c1", name="Spin", is_self=False),
    ]


class TestManager:
    @pytest.mark.asyncio
    async def test_add_list_and_dedupe_never_touch_evidence(self, wm) -> None:
        subj = await wm.add_subject(company_id="c1", name="Crown", url="https://c.example")
        r1 = await wm.add_voice(
            company_id="c1", subject_id=subj.subject_id, source="reddit",
            theme="redemption_speed", sentiment="negative",
            quote="  Took 9 days   to get my redemption. ", source_url="https://reddit.com/x",
            posted_at="2026-08-10T00:00:00+00:00", rating=None, weight=0.8,
        )
        assert r1 is not None and r1.quote == "Took 9 days to get my redemption."
        # cross-post of the same words: one row
        again = await wm.add_voice(
            company_id="c1", subject_id=subj.subject_id, source="x",
            theme="redemption_speed", sentiment="negative",
            quote="Took 9 days to get my redemption.", source_url="https://x.com/y",
        )
        assert again is None
        rows = await wm.list_voice("c1")
        assert len(rows) == 1 and rows[0].source == "reddit" and rows[0].weight == 0.8
        # the pack's evidence register is untouched
        assert await wm.list_evidence("c1") == []
        card = await wm.scorecard("c1")
        assert card["rows"][0]["overall"]["normalized_pct"] is None

    @pytest.mark.asyncio
    async def test_vocabularies_are_enforced(self, wm) -> None:
        subj = await wm.add_subject(company_id="c1", name="Crown")
        with pytest.raises(ValueError):
            await wm.add_voice(company_id="c1", subject_id=subj.subject_id, source="tiktok",
                               theme="support", sentiment="negative", quote="q")
        with pytest.raises(ValueError):
            await wm.add_voice(company_id="c1", subject_id=subj.subject_id, source="reddit",
                               theme="vibes", sentiment="negative", quote="q")
        with pytest.raises(ValueError):
            await wm.add_voice(company_id="c1", subject_id=subj.subject_id, source="reddit",
                               theme="support", sentiment="meh", quote="q")

    @pytest.mark.asyncio
    async def test_snapshot_carries_voice_only_when_present_and_diffs_by_theme(self, wm) -> None:
        subj = await wm.add_subject(company_id="c1", name="Crown")
        # no voice yet: snapshot payload has no 'voice' key — the pack is unchanged
        sid0 = await wm.take_snapshot("c1", label="before")
        assert "voice" not in (await wm.get_snapshot(sid0))
        assert await wm.diff_voice_since_snapshot("c1") == {
            "baseline": True, "changed": [], "material_count": 0,
            "from_mentions": 0, "to_mentions": 0, "against_snapshot": sid0,
        }
        for i in range(6):
            await wm.add_voice(company_id="c1", subject_id=subj.subject_id, source="reddit",
                               theme="redemption_speed", sentiment="negative",
                               quote=f"slow redemption number {i}", weight=1.0)
        sid1 = await wm.take_snapshot("c1", label="cycle 1")
        snap = await wm.get_snapshot(sid1)
        assert snap["voice"]["mentions"] == 6
        # next cycle: praise floods in → redemption share falls
        for i in range(12):
            await wm.add_voice(company_id="c1", subject_id=subj.subject_id, source="app_store",
                               theme="game_selection", sentiment="positive",
                               quote=f"love the games {i}", rating=5)
        d = await wm.diff_voice_since_snapshot("c1")
        assert d["baseline"] is False and d["against_snapshot"] == sid1
        themes = {(c["brand"], c["theme"]): c for c in d["changed"]}
        assert themes[("Crown", "redemption_speed")]["direction"] == "falling"
        assert themes[("Crown", "game_selection")]["direction"] == "rising"


class TestSummary:
    def test_shares_with_n_and_too_few(self) -> None:
        rows = [_row("cc", "redemption_speed", "negative", f"slow {i}") for i in range(12)]
        rows += [_row("cc", "game_selection", "positive", f"games {i}", rating=5) for i in range(8)]
        rows += [_row("sb", "support", "negative", "nobody answers")]  # 1 mention
        rows += [_row("us", "promo_value", "positive", "great daily bonus", days_ago=45)]  # outside window
        s = summarize_voice(rows, _subjects(), window_days=30, min_mentions=15)
        by = {b["name"]: b for b in s["brands"]}
        assert s["mentions"] == 21 and by["Us"]["n"] == 0 and by["Us"]["too_few"]
        assert by["Spin"]["n"] == 1 and by["Spin"]["too_few"]
        crown = by["Crown"]
        assert not crown["too_few"] and crown["n"] == 20
        assert crown["themes"]["redemption_speed"]["share"] == 0.6
        assert crown["themes"]["redemption_speed"]["neg_share"] == 1.0
        assert crown["top_complaint"] == "redemption_speed" and crown["top_praise"] == "game_selection"
        assert crown["avg_rating"] == 5.0
        assert crown["quotes"][0]["sentiment"] == "negative" and "slow" in crown["quotes"][0]["quote"]
        assert "not observed product fact" in s["label"]

    def test_weight_counts_and_flags_map_to_dimensions(self) -> None:
        rows = [_row("cc", "kyc_friction", "negative", f"kyc hell {i}", weight=0.0, dim="d-kyc") for i in range(5)]
        rows += [_row("cc", "promo_value", "positive", "nice promos", weight=1.0)]
        s = summarize_voice(rows, _subjects(), min_mentions=1)
        crown = next(b for b in s["brands"] if b["name"] == "Crown")
        # zero-weight (affiliate) rows are counted in n but carry no share
        assert crown["n"] == 6 and crown["themes"]["kyc_friction"]["share"] == 0.0
        assert crown["themes"]["promo_value"]["share"] == 1.0
        assert crown["flags"] == ["d-kyc"]

    def test_diff_needs_min_n_and_reports_direction(self) -> None:
        old = {"mentions": 10, "brands": [{"name": "Crown", "themes": {
            "support": {"n": 10, "share": 0.5, "neg_share": 0.5}}}]}
        new = {"mentions": 20, "brands": [{"name": "Crown", "is_self": False, "themes": {
            "support": {"n": 10, "share": 0.5, "neg_share": 0.9},   # neg share up 0.4
            "payments": {"n": 3, "share": 0.4, "neg_share": 1.0},   # too few to report
        }}]}
        d = diff_voice(old, new)
        assert [(c["theme"], c["direction"]) for c in d["changed"]] == [("support", "rising")]
        assert diff_voice(None, new)["baseline"] is True

    def test_dedupe_key_ignores_case_and_spacing(self) -> None:
        assert voice_dedupe_key("Slow   Redemption!") == voice_dedupe_key("slow redemption!")
        assert voice_dedupe_key("", "https://a") != voice_dedupe_key("", "https://b")
        assert "other" in VOICE_THEMES
