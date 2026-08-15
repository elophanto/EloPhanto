"""The executive deck: the board pack as slides, with the organ's honesty
rules intact on every one of them.

Three rules are easiest to lose on a slide, so they are pinned here against
the actual .pptx, not the input dict:

* unscored is blank, never zero — in the heatmap and the standings chart;
* provisional brands are listed, not ranked — a bar is trusted without its
  footnote, so a brand scored on 15% of the model must not lead the chart;
* fact and judgement are labelled — the summary slide says whether a model
  wrote it, and "no decision required" never masquerades for "not evaluated".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from core.watch import WatchManager


@dataclass
class _Resp:
    content: str


class _DeckRouter:
    """Answers the judgement and the summary prompts with valid JSON."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def complete(self, *, messages: list[dict[str, str]], **_kw: Any) -> _Resp:
        system = messages[0]["content"]
        self.calls.append("summary" if "executive-summary slide" in system else "judge")
        if "executive-summary slide" in system:
            return _Resp(
                '{"headline": "We lead, but Rival One is closing on promos.", '
                '"bullets": ["OurBrand ranks #1 at 75.0.", '
                '"Rival One dropped a full point on Promos.", '
                '"Two dimensions remain unobserved for Rival Two."]}'
            )
        return _Resp(
            '{"items": [{"subject": "Rival One", "change": "Promos 5 -> 2", '
            '"implication": "Their welcome offer weakened.", '
            '"recommendation": "Hold our promo spend.", '
            '"classification": "no_regret", "decision_required": "none"}, '
            '{"subject": "Rival Two", "change": "Trust newly scored 4", '
            '"implication": "They now publish licensing.", '
            '"recommendation": "Publish ours before Q4.", '
            '"classification": "transition_requirement", '
            '"decision_required": "Approve licensing page for Q4"}]}'
        )


@pytest.fixture
async def wm(tmp_path):
    from core.database import Database

    db = Database(str(tmp_path / "deck.db"))
    await db.initialize()
    yield WatchManager(db)
    await db.close()


async def _market(wm: WatchManager, c: str = "c1") -> dict[str, Any]:
    """Five brands: us, two rivals, one provisional, one never observed;
    a baseline snapshot, then three material moves."""
    dims = []
    for name, w in [
        ("Promos", 25),
        ("Payments", 25),
        ("Game library", 20),
        ("Support", 15),
        ("Trust", 15),
    ]:
        dims.append(
            await wm.upsert_dimension(
                name=name,
                company_id=c,
                weight_pct=w,
                subcriteria=[{"name": "a", "weight_pct": 50}, {"name": "b", "weight_pct": 50}],
            )
        )
    us = await wm.add_subject(name="OurBrand", company_id=c, url="https://u.example", is_self=True)
    r1 = await wm.add_subject(name="Rival One", company_id=c, url="https://r1.example")
    r2 = await wm.add_subject(name="Rival Two", company_id=c, url="https://r2.example")
    thin = await wm.add_subject(name="Thin Brand", company_id=c, url="https://t.example")
    await wm.add_subject(name="Ghost Brand", company_id=c, url="https://g.example")

    async def sc(subj, dim, score):
        await wm.add_evidence(
            company_id=c,
            subject_id=subj.subject_id,
            dimension_id=dim.dimension_id,
            claim=f"{subj.name} {dim.name}",
            source_url="https://x.example",
        )
        await wm.set_score(
            company_id=c, subject_id=subj.subject_id, dimension_id=dim.dimension_id, score=score
        )

    for d, v in zip(dims, [3, 4, 2, 5, 3], strict=True):
        await sc(us, d, v)
    for d, v in zip(dims, [5, 3, 4, 3, 4], strict=True):
        await sc(r1, d, v)
    for d, v in zip(dims[:4], [2, 2, 3, 2], strict=True):
        await sc(r2, d, v)
    await sc(thin, dims[3], 5)  # 15% of the model → provisional at 100.0
    await wm.take_snapshot(c, label="base")
    # Five material items: two score moves, one newly-scored dimension, and
    # the two rank changes those cause (us 2→1, Rival One 1→2).
    await sc(r1, dims[0], 2)  # material drop
    await sc(us, dims[2], 4)  # we improve
    await sc(r2, dims[4], 4)  # newly scored — always material
    return {"dims": dims, "us": us, "r1": r1, "r2": r2, "thin": thin}


def _slides(path: str) -> list[dict[str, Any]]:
    from pptx import Presentation

    out = []
    for sl in Presentation(path).slides:
        text = "\n".join(sh.text_frame.text for sh in sl.shapes if sh.has_text_frame)
        chart = next((sh.chart for sh in sl.shapes if sh.has_chart), None)
        table = next((sh.table for sh in sl.shapes if sh.has_table), None)
        out.append(
            {
                "text": text,
                "chart": chart,
                "table": table,
                "notes": sl.notes_slide.notes_text_frame.text,
            }
        )
    return out


def _slide(slides: list[dict[str, Any]], title_fragment: str) -> dict[str, Any]:
    for s in slides:
        if title_fragment in s["text"]:
            return s
    raise AssertionError(f"no slide contains {title_fragment!r}")


async def _deck(
    wm: WatchManager, tmp_path, router: Any = None, **params: Any
) -> tuple[Any, list[dict[str, Any]]]:
    from tools.watch.tools import WatchExecutiveDeckTool

    t = WatchExecutiveDeckTool()
    t._watch_manager = wm
    t._router = router
    res = await t.execute({"company_id": "c1", "path": str(tmp_path / "deck.pptx"), **params})
    assert res.success, res.error
    return res, _slides(res.data["path"])


class TestTheThreeRules:
    @pytest.mark.asyncio
    async def test_provisional_brand_is_listed_not_ranked(self, wm, tmp_path) -> None:
        """Thin Brand scores 100.0 on one 15%-weight dimension. That figure
        would lead the chart and read as 'market leader'. It must not."""
        await _market(wm)
        _res, slides = await _deck(wm, tmp_path)
        standings = _slide(slides, "Where the market stands")
        cats = list(standings["chart"].plots[0].categories)
        assert not any("Thin Brand" in c for c in cats)
        assert "Thin Brand" in standings["text"]  # named below the chart…
        assert "†" in standings["text"]  # …with the dagger and its reason
        assert "scored on 15% of total dimension weight" in standings["text"]

    @pytest.mark.asyncio
    async def test_unscored_is_blank_never_zero(self, wm, tmp_path) -> None:
        await _market(wm)
        _res, slides = await _deck(wm, tmp_path)
        # Chart: Ghost Brand has no scores — it gets no bar, not a 0 bar.
        standings = _slide(slides, "Where the market stands")
        vals = list(standings["chart"].plots[0].series[0].values)
        assert 0.0 not in vals
        assert not any("Ghost" in c for c in standings["chart"].plots[0].categories)
        assert "Not yet observed" in standings["text"] and "Ghost Brand" in standings["text"]
        # Heatmap: Rival Two's unscored cell is empty text, not "0".
        heat = _slide(slides, "Scores by dimension")
        tbl = heat["table"]
        header = [tbl.cell(0, c).text for c in range(len(tbl.columns))]
        rows = {
            tbl.cell(r, 0).text: [tbl.cell(r, c).text for c in range(len(tbl.columns))]
            for r in range(1, len(tbl.rows))
        }
        ghost = rows["Ghost Brand"]
        assert ghost[1] == "—" and all(v == "" for v in ghost[2:])
        thin = rows["Thin Brand"]
        assert thin[1] == "100.0†"
        assert thin[header.index("Support")] == "5"
        assert thin[header.index("Promos")] == ""

    @pytest.mark.asyncio
    async def test_our_bar_is_in_the_chart_and_ranked_order_holds(self, wm, tmp_path) -> None:
        await _market(wm)
        _res, slides = await _deck(wm, tmp_path)
        chart = _slide(slides, "Where the market stands")["chart"]
        cats = list(chart.plots[0].categories)
        vals = list(chart.plots[0].series[0].values)
        # python-pptx draws bar categories bottom-up, so #1 is last.
        assert cats[-1].startswith("OurBrand") and "(us)" in cats[-1]
        assert vals == sorted(vals)


class TestFactAndJudgementAreLabelled:
    @pytest.mark.asyncio
    async def test_without_a_model_the_summary_says_facts_only(self, wm, tmp_path) -> None:
        await _market(wm)
        res, slides = await _deck(wm, tmp_path)
        assert res.data["summary_source"] == "facts"
        summary = _slide(slides, "Executive summary")
        assert "Facts only" in summary["text"]
        assert "OurBrand ranks #1" in summary["text"]
        assert "5 material changes" in summary["text"]

    @pytest.mark.asyncio
    async def test_without_a_model_decisions_are_not_evaluated_not_none(self, wm, tmp_path) -> None:
        """'No decision required' and 'nobody judged it' must not look alike."""
        await _market(wm)
        _res, slides = await _deck(wm, tmp_path)
        decisions = _slide(slides, "Decisions required")
        assert "Not yet evaluated" in decisions["text"]
        assert "No board decision is required" not in decisions["text"]
        implications = _slide(slides, "Implications and recommendations")
        assert "no model was available" in implications["text"]

    @pytest.mark.asyncio
    async def test_with_a_model_summary_and_implications_are_labelled_as_judgement(
        self, wm, tmp_path
    ) -> None:
        await _market(wm)
        router = _DeckRouter()
        res, slides = await _deck(wm, tmp_path, router=router)
        assert res.data["summary_source"] == "model"
        assert res.data["judged_items"] == 2
        assert router.calls.count("judge") == 1 and router.calls.count("summary") == 1

        summary = _slide(slides, "Executive summary")
        assert "We lead, but Rival One is closing on promos." in summary["text"]
        assert "written by the model" in summary["text"]

        implications = _slide(slides, "Implications and recommendations")
        tbl = implications["table"]
        classes = [tbl.cell(r, 4).text for r in range(1, len(tbl.rows))]
        assert classes == ["No-regret", "Transition requirement"]  # ordered by class
        assert "written by the model" in implications["text"]

        decisions = _slide(slides, "Decisions required")
        assert "Approve licensing page for Q4" in decisions["text"]
        assert "Rival One" not in decisions["text"]  # its decision was "none"

    @pytest.mark.asyncio
    async def test_a_broken_model_degrades_to_facts_and_says_so(self, wm, tmp_path) -> None:
        class Broken:
            async def complete(self, **_kw: Any) -> _Resp:
                return _Resp("not json at all")

        await _market(wm)
        res, slides = await _deck(wm, tmp_path, router=Broken())
        assert res.data["summary_source"] == "facts"
        assert "Facts only" in _slide(slides, "Executive summary")["text"]


class TestVersusTheLeader:
    @pytest.mark.asyncio
    async def test_compares_us_to_the_top_ranked_peer_dimension_by_dimension(
        self, wm, tmp_path
    ) -> None:
        await _market(wm)
        _res, slides = await _deck(wm, tmp_path)
        vs = _slide(slides, "Where we win, where we lose")
        # After the moves: us Promos 3 vs Rival One 2 → ahead; Trust 3 vs 4 → behind.
        assert "Promos  (3 vs 2" in vs["text"]
        assert "Trust  (3 vs 4" in vs["text"]
        assert "Rival One (#2)" in vs["text"]

    @pytest.mark.asyncio
    async def test_no_self_brand_says_so_instead_of_guessing(self, wm, tmp_path) -> None:
        d = await wm.upsert_dimension(
            name="Promos",
            company_id="c1",
            weight_pct=100,
            subcriteria=[{"name": "a", "weight_pct": 100}],
        )
        s = await wm.add_subject(name="Rival", company_id="c1", url="https://r.example")
        await wm.add_evidence(
            company_id="c1", subject_id=s.subject_id, dimension_id=d.dimension_id, claim="x"
        )
        await wm.set_score(
            company_id="c1", subject_id=s.subject_id, dimension_id=d.dimension_id, score=3
        )
        _res, slides = await _deck(wm, tmp_path)
        assert "No brand is marked as ours" in _slide(slides, "Where we win")["text"]


class TestFirstCycle:
    @pytest.mark.asyncio
    async def test_no_snapshot_means_baseline_not_zero_changes(self, wm, tmp_path) -> None:
        d = await wm.upsert_dimension(
            name="Promos",
            company_id="c1",
            weight_pct=100,
            subcriteria=[{"name": "a", "weight_pct": 100}],
        )
        s = await wm.add_subject(name="Rival", company_id="c1", url="https://r.example")
        await wm.add_evidence(
            company_id="c1", subject_id=s.subject_id, dimension_id=d.dimension_id, claim="x"
        )
        await wm.set_score(
            company_id="c1", subject_id=s.subject_id, dimension_id=d.dimension_id, score=3
        )
        res, slides = await _deck(wm, tmp_path)
        assert res.data["material_count"] == 0
        assert "First reporting cycle" in _slide(slides, "Baseline established")["text"]
        assert "sets the baseline" in _slide(slides, "Executive summary")["text"]


class TestEvidenceSlide:
    @pytest.mark.asyncio
    async def test_reports_coverage_and_the_no_penalty_rule(self, wm, tmp_path) -> None:
        await _market(wm)
        _res, slides = await _deck(wm, tmp_path)
        ev = _slide(slides, "How much of this is measured")
        # 5 brands × 5 dims = 25 pairs; scored: us 5 + r1 5 + r2 5 + thin 1 = 16.
        assert "16 of 25 brand × dimension pairs" in ev["text"]
        assert "64%" in ev["text"]
        assert "Gaps are absences of evidence, not weaknesses" in ev["text"]


class TestDeckShape:
    @pytest.mark.asyncio
    async def test_ten_slides_all_within_bounds(self, wm, tmp_path) -> None:
        from pptx import Presentation

        await _market(wm)
        res, _ = await _deck(wm, tmp_path, router=_DeckRouter())
        prs = Presentation(res.data["path"])
        assert len(prs.slides) == 10
        W, H = prs.slide_width, prs.slide_height
        for sl in prs.slides:
            for sh in sl.shapes:
                assert sh.left >= 0 and sh.top >= 0
                assert sh.left + sh.width <= W and sh.top + sh.height <= H

    @pytest.mark.asyncio
    async def test_many_implications_paginate(self, wm, tmp_path) -> None:
        class Many:
            async def complete(self, *, messages, **_kw):
                if "executive-summary slide" in messages[0]["content"]:
                    return _Resp('{"headline": "h", "bullets": ["b"]}')
                items = ", ".join(
                    f'{{"subject": "S{i}", "change": "c", "implication": "i", '
                    f'"recommendation": "r", "classification": "monitor", '
                    f'"decision_required": "none"}}'
                    for i in range(12)
                )
                return _Resp(f'{{"items": [{items}]}}')

        from pptx import Presentation

        await _market(wm)
        res, slides = await _deck(wm, tmp_path, router=Many())
        titles = [s["text"] for s in slides if "Implications and recommendations" in s["text"]]
        assert len(titles) == 3  # 12 items, 5 per slide
        assert "(1/3)" in titles[0] and "(3/3)" in titles[2]
        assert len(Presentation(res.data["path"]).slides) == 12

    @pytest.mark.asyncio
    async def test_extension_is_forced_to_pptx(self, wm, tmp_path) -> None:
        await _market(wm)
        res, _ = await _deck(wm, tmp_path, path=str(tmp_path / "deck.pdf"))
        assert res.data["path"].endswith(".pptx")

    @pytest.mark.asyncio
    async def test_it_does_not_take_a_snapshot(self, wm, tmp_path) -> None:
        await _market(wm)
        before = len(await wm.list_snapshots("c1"))
        await _deck(wm, tmp_path)
        assert len(await wm.list_snapshots("c1")) == before


class TestBoardReportCanCarryTheDeck:
    @pytest.mark.asyncio
    async def test_deck_path_writes_both_from_one_period(self, wm, tmp_path) -> None:
        """Both artefacts are cut from the same diff, before the snapshot."""
        from tools.watch.tools import WatchBoardReportTool

        await _market(wm)
        t = WatchBoardReportTool()
        t._watch_manager = wm
        t._router = _DeckRouter()
        res = await t.execute(
            {
                "company_id": "c1",
                "path": str(tmp_path / "report.md"),
                "deck_path": str(tmp_path / "deck.pptx"),
                "take_snapshot": True,
            }
        )
        assert res.success
        assert res.data["material_count"] == 5
        assert res.data["deck_path"] == str(tmp_path / "deck.pptx")
        assert "deck_error" not in res.data
        slides = _slides(res.data["deck_path"])
        assert "5 material changes" in _slide(slides, "material changes this period")["text"]
        # …and the snapshot came after, so a follow-up diff is empty.
        assert (await wm.diff_since_snapshot("c1"))["material_count"] == 0

    @pytest.mark.asyncio
    async def test_report_to_disk_brings_the_deck_by_default(self, wm, tmp_path) -> None:
        """The deck is part of the pack, not an option to remember."""
        from tools.watch.tools import WatchBoardReportTool

        await _market(wm)
        t = WatchBoardReportTool()
        t._watch_manager = wm
        res = await t.execute(
            {"company_id": "c1", "path": str(tmp_path / "board-march.md"),
             "take_snapshot": False}
        )
        assert res.success
        assert res.data["deck_path"] == str(tmp_path / "board-march.pptx")
        assert (tmp_path / "board-march.pptx").exists()
        assert (tmp_path / "board-march.md").exists()

    @pytest.mark.asyncio
    async def test_deck_false_skips_it(self, wm, tmp_path) -> None:
        from tools.watch.tools import WatchBoardReportTool

        await _market(wm)
        t = WatchBoardReportTool()
        t._watch_manager = wm
        res = await t.execute(
            {"company_id": "c1", "path": str(tmp_path / "r.md"),
             "deck": False, "take_snapshot": False}
        )
        assert res.success and "deck_path" not in res.data
        assert not (tmp_path / "r.pptx").exists()

    @pytest.mark.asyncio
    async def test_inline_report_writes_nothing_so_no_deck(self, wm, tmp_path) -> None:
        """No path means the report is returned, not saved — same for the deck."""
        from tools.watch.tools import WatchBoardReportTool

        await _market(wm)
        t = WatchBoardReportTool()
        t._watch_manager = wm
        res = await t.execute({"company_id": "c1", "take_snapshot": False})
        assert res.success and "deck_path" not in res.data
        assert not list(tmp_path.glob("*.pptx"))


class TestRegistration:
    def test_tool_is_created_and_in_the_watch_group(self) -> None:
        from tools.watch.tools import create_watch_tools

        names = {t.name: t for t in create_watch_tools()}
        assert "watch_executive_deck" in names
        assert names["watch_executive_deck"].group == "watch"

    def test_analyze_ships_the_deck_by_default(self) -> None:
        from tools.watch.tools import WatchAnalyzeTool

        props = WatchAnalyzeTool().input_schema["properties"]
        assert "deck" in props
        assert "Default true" in props["deck"]["description"]
        assert "executive deck" in WatchAnalyzeTool().description
