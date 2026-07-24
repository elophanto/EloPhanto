"""Competitive-intelligence organ — scoring math + the two integrity rules.

The rules under test are the ones that make the analysis trustworthy:

1. A missing datapoint is never a bad score (nullable score + coverage gap).
2. Evidence is append-only (corrections supersede, never overwrite).

Everything else — weighted points, alternative views, coverage, confidence
rollup — is arithmetic the scorecard and board report depend on being exact.
"""

from __future__ import annotations

import pytest

from core.watch import (
    WatchDimension,
    WatchManager,
    WatchScore,
    WatchSubject,
    build_scorecard,
    confidence_rollup,
    coverage_pct,
    score_subject,
    weighted_points,
)
from core.watch_seeds import get_pack, list_packs

# ── Pure math ───────────────────────────────────────────────────────────


class TestWeightedPoints:
    def test_sow_worked_example(self) -> None:
        # The SOW states it explicitly: 4/5 on a 10%-weighted dimension = 8.
        assert weighted_points(4, 10) == pytest.approx(8.0)

    def test_full_marks_yield_the_whole_weight(self) -> None:
        assert weighted_points(5, 12) == pytest.approx(12.0)

    def test_none_contributes_nothing_and_is_not_a_zero(self) -> None:
        # Critical: an unscored dimension must not behave like 0/5, which
        # would punish a brand for being opaque.
        assert weighted_points(None, 10) == 0.0
        assert weighted_points(1, 10) > weighted_points(None, 10)


class TestCoverage:
    def test_partial_coverage(self) -> None:
        subs = [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}]
        assert coverage_pct(subs, {"a", "b"}) == pytest.approx(50.0)

    def test_full_and_empty(self) -> None:
        subs = [{"name": "a"}, {"name": "b"}]
        assert coverage_pct(subs, {"a", "b"}) == pytest.approx(100.0)
        assert coverage_pct(subs, set()) == pytest.approx(0.0)

    def test_dimension_without_subcriteria_is_one_datapoint(self) -> None:
        assert coverage_pct([], {"anything"}) == pytest.approx(100.0)
        assert coverage_pct([], set()) == pytest.approx(0.0)


class TestConfidenceRollup:
    def test_all_high(self) -> None:
        assert confidence_rollup(["high", "high"]) == "high"

    def test_mixed_is_conservative(self) -> None:
        assert confidence_rollup(["high", "low"]) == "medium"

    def test_all_low(self) -> None:
        assert confidence_rollup(["low", "low"]) == "low"

    def test_no_evidence_is_low_not_high(self) -> None:
        assert confidence_rollup([]) == "low"


def _dims() -> list[WatchDimension]:
    return [
        WatchDimension(
            dimension_id="d1",
            name="Games",
            weight_pct=60,
            view_weights={"customer_proposition": 90, "transition_priority": 10},
        ),
        WatchDimension(
            dimension_id="d2",
            name="KYC",
            weight_pct=40,
            view_weights={"customer_proposition": 10, "transition_priority": 90},
        ),
    ]


def _score(dim_id: str, score: float | None, cov: float = 100.0) -> WatchScore:
    return WatchScore(
        score_id=f"s_{dim_id}",
        subject_id="x",
        dimension_id=dim_id,
        score=score,
        coverage_pct=cov,
        confidence="high",
    )


class TestScoreSubject:
    def test_weighted_total_and_normalisation(self) -> None:
        out = score_subject(_dims(), {"d1": _score("d1", 5), "d2": _score("d2", 5)})
        assert out["raw_points"] == pytest.approx(100.0)
        assert out["normalized_pct"] == pytest.approx(100.0)
        assert out["scored_weight_pct"] == pytest.approx(100.0)

    def test_unscored_dimension_excluded_from_denominator(self) -> None:
        # Only Games (60%) scored, at 5/5. Raw is 60 — but normalised is 100,
        # because the brand is perfect *on what we actually know*. The thin
        # evidence shows up as scored_weight_pct, not as a depressed score.
        out = score_subject(_dims(), {"d1": _score("d1", 5)})
        assert out["raw_points"] == pytest.approx(60.0)
        assert out["scored_weight_pct"] == pytest.approx(60.0)
        assert out["normalized_pct"] == pytest.approx(100.0)
        assert out["unscored_dimensions"] == ["KYC"]

    def test_null_score_is_not_a_one(self) -> None:
        null_out = score_subject(
            _dims(), {"d1": _score("d1", 5), "d2": _score("d2", None)}
        )
        low_out = score_subject(_dims(), {"d1": _score("d1", 5), "d2": _score("d2", 1)})
        assert null_out["normalized_pct"] > low_out["normalized_pct"]

    def test_views_reweight_the_same_scores(self) -> None:
        scores = {"d1": _score("d1", 5), "d2": _score("d2", 1)}
        cp = score_subject(_dims(), scores, view="customer_proposition")
        tp = score_subject(_dims(), scores, view="transition_priority")
        # Strong on games, weak on KYC → looks good to a customer, poor as a
        # transition benchmark. Same scores, different question.
        assert cp["normalized_pct"] > tp["normalized_pct"]

    def test_nothing_scored_yields_none_not_zero(self) -> None:
        out = score_subject(_dims(), {})
        assert out["normalized_pct"] is None
        assert out["raw_points"] == 0.0


class TestBuildScorecard:
    def test_ranks_and_sorts_unscored_last(self) -> None:
        subjects = [
            WatchSubject(subject_id="a", name="Alpha"),
            WatchSubject(subject_id="b", name="Beta"),
            WatchSubject(subject_id="c", name="Gamma"),
        ]
        card = build_scorecard(
            subjects,
            _dims(),
            {
                "a": {"d1": _score("d1", 3), "d2": _score("d2", 3)},
                "b": {"d1": _score("d1", 5), "d2": _score("d2", 5)},
                # c has nothing
            },
        )
        names = [r["name"] for r in card["rows"]]
        assert names[0] == "Beta" and names[1] == "Alpha"
        assert names[2] == "Gamma"
        assert card["rows"][2]["rank"] is None  # unscored is unranked, not last-place
        assert card["weights_valid"] is True

    def test_flags_invalid_weight_total(self) -> None:
        dims = [WatchDimension(dimension_id="d1", name="Only", weight_pct=70)]
        card = build_scorecard([WatchSubject(subject_id="a", name="A")], dims, {})
        assert card["weights_valid"] is False
        assert card["weight_total_pct"] == pytest.approx(70.0)


# ── Seed pack integrity ─────────────────────────────────────────────────


class TestSeedPack:
    def test_pack_is_listed(self) -> None:
        assert any(p["name"] == "social_casino_t1" for p in list_packs())

    def test_sow_shape(self) -> None:
        pack = get_pack("social_casino_t1")
        assert pack is not None
        assert len(pack["dimensions"]) == 12
        assert len(pack["subjects"]) == 14

    def test_every_weight_vector_sums_to_100(self) -> None:
        dims = get_pack("social_casino_t1")["dimensions"]
        assert sum(d["weight_pct"] for d in dims) == pytest.approx(100.0)
        for view in ("customer_proposition", "transition_priority"):
            total = sum(d["view_weights"][view] for d in dims)
            assert total == pytest.approx(100.0), f"{view} sums to {total}"

    def test_subcriteria_sum_to_100_each(self) -> None:
        for d in get_pack("social_casino_t1")["dimensions"]:
            total = sum(s["weight_pct"] for s in d["subcriteria"])
            assert total == pytest.approx(100.0), f"{d['name']} sums to {total}"

    def test_cadences_follow_the_sow_refresh_rule(self) -> None:
        dims = {
            d["name"]: d["refresh_cadence"]
            for d in get_pack("social_casino_t1")["dimensions"]
        }
        assert dims["Promotional proposition and generosity"] == "weekly"
        assert dims["Marketing proposition"] == "weekly"
        assert dims["Available P&L, accounts and financial strength"] == "quarterly"
        assert dims["State availability and variation"] == "quarterly"

    def test_our_own_brands_are_flagged(self) -> None:
        subs = get_pack("social_casino_t1")["subjects"]
        assert {s["name"] for s in subs if s.get("is_self")} == {"Pulsz", "Pulsz Bingo"}


# ── Integrity rules against a real DB ───────────────────────────────────


@pytest.fixture
async def wm(tmp_path):
    from core.database import Database

    db = Database(str(tmp_path / "watch.db"))
    await db.initialize()
    yield WatchManager(db)
    await db.close()


async def _seeded(wm: WatchManager, company: str = "c1"):
    subj = await wm.add_subject(
        name="Rival", company_id=company, url="https://r.example"
    )
    dim = await wm.upsert_dimension(
        name="Promos",
        company_id=company,
        weight_pct=100,
        subcriteria=[
            {"name": "welcome", "weight_pct": 50},
            {"name": "ongoing", "weight_pct": 50},
        ],
    )
    return subj, dim


class TestNoEvidenceNoScore:
    @pytest.mark.asyncio
    async def test_scoring_without_evidence_is_refused(self, wm) -> None:
        subj, dim = await _seeded(wm)
        with pytest.raises(ValueError, match="no evidence"):
            await wm.set_score(
                company_id="c1",
                subject_id=subj.subject_id,
                dimension_id=dim.dimension_id,
                score=4,
            )

    @pytest.mark.asyncio
    async def test_null_score_records_the_gap_instead(self, wm) -> None:
        subj, dim = await _seeded(wm)
        s = await wm.set_score(
            company_id="c1",
            subject_id=subj.subject_id,
            dimension_id=dim.dimension_id,
            score=None,
            rationale="opaque",
        )
        assert s.score is None
        assert s.coverage_pct == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_coverage_reflects_evidence_breadth(self, wm) -> None:
        subj, dim = await _seeded(wm)
        await wm.add_evidence(
            company_id="c1",
            subject_id=subj.subject_id,
            dimension_id=dim.dimension_id,
            subcriterion="welcome",
            claim="5 SC on signup",
            confidence="high",
        )
        s = await wm.set_score(
            company_id="c1",
            subject_id=subj.subject_id,
            dimension_id=dim.dimension_id,
            score=4,
        )
        # One of two sub-criteria evidenced.
        assert s.coverage_pct == pytest.approx(50.0)
        assert s.confidence == "high"
        assert len(s.evidence_ids) == 1

    @pytest.mark.asyncio
    async def test_out_of_range_score_rejected(self, wm) -> None:
        subj, dim = await _seeded(wm)
        with pytest.raises(ValueError, match="between 1 and 5"):
            await wm.set_score(
                company_id="c1",
                subject_id=subj.subject_id,
                dimension_id=dim.dimension_id,
                score=9,
            )


class TestEvidenceIsAppendOnly:
    @pytest.mark.asyncio
    async def test_supersede_retains_history(self, wm) -> None:
        subj, dim = await _seeded(wm)
        old = await wm.add_evidence(
            company_id="c1",
            subject_id=subj.subject_id,
            dimension_id=dim.dimension_id,
            claim="min purchase $9.99",
        )
        await wm.add_evidence(
            company_id="c1",
            subject_id=subj.subject_id,
            dimension_id=dim.dimension_id,
            claim="min purchase $4.99",
            supersedes=old.evidence_id,
        )
        live = await wm.list_evidence("c1", subject_id=subj.subject_id)
        history = await wm.list_evidence(
            "c1", subject_id=subj.subject_id, include_superseded=True
        )
        assert [e.claim for e in live] == ["min purchase $4.99"]
        assert len(history) == 2  # the old observation survives for diffing

    @pytest.mark.asyncio
    async def test_invalid_enums_rejected(self, wm) -> None:
        subj, dim = await _seeded(wm)
        for kwargs, match in (
            ({"confidence": "certain"}, "confidence"),
            ({"customer_state": "whale"}, "customer_state"),
            ({"collector": "robot"}, "collector"),
        ):
            with pytest.raises(ValueError, match=match):
                await wm.add_evidence(
                    company_id="c1",
                    subject_id=subj.subject_id,
                    dimension_id=dim.dimension_id,
                    claim="x",
                    **kwargs,
                )

    @pytest.mark.asyncio
    async def test_human_collected_evidence_is_labelled(self, wm) -> None:
        # Authenticated states are operator-collected by policy; the register
        # must record who observed it so the provenance is auditable.
        subj, dim = await _seeded(wm)
        ev = await wm.add_evidence(
            company_id="c1",
            subject_id=subj.subject_id,
            dimension_id=dim.dimension_id,
            claim="VIP host assigned at $500",
            customer_state="vip",
            collector="human",
        )
        assert ev.collector == "human" and ev.customer_state == "vip"


class TestCompanyScoping:
    @pytest.mark.asyncio
    async def test_subjects_do_not_leak_across_companies(self, wm) -> None:
        await wm.add_subject(name="Rival", company_id="c1")
        await wm.add_subject(name="Other", company_id="c2")
        assert [s.name for s in await wm.list_subjects("c1")] == ["Rival"]
        assert [s.name for s in await wm.list_subjects("c2")] == ["Other"]

    @pytest.mark.asyncio
    async def test_archived_subject_hidden_but_retained(self, wm) -> None:
        subj, _ = await _seeded(wm)
        await wm.archive_subject(subj.subject_id)
        assert await wm.list_subjects("c1") == []
        assert len(await wm.list_subjects("c1", include_archived=True)) == 1


# ── P2: change detection, staleness, exports ────────────────────────────


def _card(rows: list[dict], generated_at: str = "2026-01-01T00:00:00+00:00") -> dict:
    """Minimal scorecard payload shaped like build_scorecard's output."""
    return {
        "generated_at": generated_at,
        "dimensions": [{"name": "Promos", "weight_pct": 100, "cadence": "monthly"}],
        "weight_total_pct": 100,
        "weights_valid": True,
        "rows": rows,
    }


def _row(name: str, score, rank=1, cov=100.0, group="G") -> dict:
    return {
        "subject_id": name.lower(),
        "name": name,
        "group": group,
        "is_self": False,
        "rank": rank,
        "overall": {"normalized_pct": None if score is None else score * 20},
        "views": {},
        "dimensions": {
            "Promos": {"score": score, "coverage_pct": cov, "confidence": "high"}
        },
    }


class TestDiffScorecards:
    def test_material_score_move_detected(self) -> None:
        from core.watch import diff_scorecards

        d = diff_scorecards(_card([_row("A", 3)]), _card([_row("A", 5)]))
        kinds = [i["kind"] for c in d["changed"] for i in c["items"]]
        assert "score" in kinds
        assert d["material_count"] >= 1

    def test_sub_threshold_move_is_not_material(self) -> None:
        from core.watch import diff_scorecards

        # A monthly report that surfaces every wobble gets ignored.
        d = diff_scorecards(
            _card([_row("A", 3)]), _card([_row("A", 3.5)]), min_score_delta=1.0
        )
        assert d["changed"] == []
        assert d["material_count"] == 0

    def test_newly_scored_is_always_material(self) -> None:
        from core.watch import diff_scorecards

        d = diff_scorecards(_card([_row("A", None)]), _card([_row("A", 2)]))
        kinds = [i["kind"] for c in d["changed"] for i in c["items"]]
        assert "newly_scored" in kinds  # new knowledge, never noise

    def test_score_withdrawn_is_material(self) -> None:
        from core.watch import diff_scorecards

        d = diff_scorecards(_card([_row("A", 4)]), _card([_row("A", None)]))
        kinds = [i["kind"] for c in d["changed"] for i in c["items"]]
        assert "score_withdrawn" in kinds

    def test_rank_change_detected(self) -> None:
        from core.watch import diff_scorecards

        d = diff_scorecards(
            _card([_row("A", 3, rank=1), _row("B", 2, rank=2)]),
            _card([_row("A", 3, rank=2), _row("B", 5, rank=1)]),
        )
        kinds = [i["kind"] for c in d["changed"] for i in c["items"]]
        assert "rank" in kinds

    def test_coverage_shift_detected(self) -> None:
        from core.watch import diff_scorecards

        d = diff_scorecards(
            _card([_row("A", 3, cov=20.0)]), _card([_row("A", 3, cov=90.0)])
        )
        kinds = [i["kind"] for c in d["changed"] for i in c["items"]]
        assert "coverage" in kinds

    def test_entrants_and_exits(self) -> None:
        from core.watch import diff_scorecards

        d = diff_scorecards(_card([_row("A", 3)]), _card([_row("A", 3), _row("B", 4)]))
        assert d["added_subjects"] == ["B"]
        d2 = diff_scorecards(_card([_row("A", 3), _row("B", 4)]), _card([_row("A", 3)]))
        assert d2["removed_subjects"] == ["B"]

    def test_identical_scorecards_are_quiet(self) -> None:
        from core.watch import diff_scorecards

        rows = [_row("A", 3), _row("B", 4, rank=2)]
        d = diff_scorecards(_card(rows), _card(rows))
        assert d["material_count"] == 0


class TestSnapshotsAndStaleness:
    @pytest.mark.asyncio
    async def test_snapshot_roundtrip_and_diff(self, wm) -> None:
        subj, dim = await _seeded(wm)
        await wm.add_evidence(
            company_id="c1", subject_id=subj.subject_id,
            dimension_id=dim.dimension_id, subcriterion="welcome", claim="x",
        )
        await wm.set_score(
            company_id="c1", subject_id=subj.subject_id,
            dimension_id=dim.dimension_id, score=2,
        )
        snap = await wm.take_snapshot("c1", label="baseline")
        assert snap
        assert (await wm.list_snapshots("c1"))[0]["label"] == "baseline"

        await wm.set_score(
            company_id="c1", subject_id=subj.subject_id,
            dimension_id=dim.dimension_id, score=5,
        )
        diff = await wm.diff_since_snapshot("c1")
        assert diff is not None
        assert diff["against_snapshot"] == snap
        assert diff["material_count"] >= 1

    @pytest.mark.asyncio
    async def test_diff_without_snapshot_returns_none(self, wm) -> None:
        await _seeded(wm)
        assert await wm.diff_since_snapshot("c1") is None

    @pytest.mark.asyncio
    async def test_never_observed_pairs_are_reported(self, wm) -> None:
        await _seeded(wm)
        gaps = await wm.staleness("c1")
        assert len(gaps) == 1
        assert gaps[0]["status"] == "never_observed"
        assert gaps[0]["last_observed"] is None

    @pytest.mark.asyncio
    async def test_fresh_evidence_is_not_stale(self, wm) -> None:
        subj, dim = await _seeded(wm)
        await wm.add_evidence(
            company_id="c1", subject_id=subj.subject_id,
            dimension_id=dim.dimension_id, claim="just observed",
        )
        assert await wm.staleness("c1") == []

    @pytest.mark.asyncio
    async def test_evidence_older_than_cadence_is_stale(self, wm) -> None:
        from datetime import UTC, datetime, timedelta

        subj, dim = await _seeded(wm)  # dimension defaults to monthly (30d)
        old = (datetime.now(UTC) - timedelta(days=90)).isoformat()
        await wm.add_evidence(
            company_id="c1", subject_id=subj.subject_id,
            dimension_id=dim.dimension_id, claim="ancient", observed_at=old,
        )
        gaps = await wm.staleness("c1")
        assert len(gaps) == 1
        assert gaps[0]["status"] == "stale"
        assert gaps[0]["age_days"] >= 89

    @pytest.mark.asyncio
    async def test_evidence_export_resolves_names(self, wm) -> None:
        subj, dim = await _seeded(wm)
        await wm.add_evidence(
            company_id="c1", subject_id=subj.subject_id,
            dimension_id=dim.dimension_id, claim="c", source_url="https://e.example",
        )
        rows = await wm.evidence_with_names("c1")
        assert rows[0]["subject"] == "Rival" and rows[0]["dimension"] == "Promos"


class TestXlsxExport:
    @pytest.mark.asyncio
    async def test_workbook_has_four_sheets_and_blanks_not_zeros(
        self, wm, tmp_path
    ) -> None:
        from openpyxl import load_workbook

        from core.watch_xlsx import render_scorecard_xlsx

        scored = await wm.add_subject(name="Scored", company_id="c1")
        await wm.add_subject(name="Unscored", company_id="c1")
        dim = await wm.upsert_dimension(name="Promos", company_id="c1", weight_pct=100)
        await wm.add_evidence(
            company_id="c1", subject_id=scored.subject_id,
            dimension_id=dim.dimension_id, claim="x",
        )
        await wm.set_score(
            company_id="c1", subject_id=scored.subject_id,
            dimension_id=dim.dimension_id, score=4,
        )

        out = tmp_path / "card.xlsx"
        path = render_scorecard_xlsx(
            await wm.scorecard("c1"),
            dimensions=await wm.list_dimensions("c1"),
            evidence=await wm.evidence_with_names("c1"),
            staleness=await wm.staleness("c1"),
            path=out,
        )
        wb = load_workbook(path)
        assert wb.sheetnames == ["Scorecard", "Weights", "Evidence", "Gaps"]

        ws = wb["Scorecard"]
        header = [c.value for c in ws[4]]
        col = header.index("Promos") + 1
        cells = {
            r[1].value: r[col - 1].value
            for r in ws.iter_rows(min_row=5, max_row=ws.max_row)
            if r[1].value in ("Scored", "Unscored")
        }
        assert cells["Scored"] == 4
        # The whole point: absent evidence renders blank, never 0.
        assert cells["Unscored"] is None


class TestBoardReportTool:
    """The report must be useful on day one and honest when no model is
    available — it ships facts either way."""

    async def _tool(self, wm):
        from tools.watch.tools import WatchBoardReportTool

        t = WatchBoardReportTool()
        t._watch_manager = wm
        return t

    @pytest.mark.asyncio
    async def test_first_cycle_states_the_baseline(self, wm) -> None:
        await _seeded(wm)
        t = await self._tool(wm)
        res = await t.execute({"company_id": "c1", "take_snapshot": False})
        assert res.success
        assert "First reporting cycle" in res.data["markdown"]
        assert res.data["material_count"] == 0

    @pytest.mark.asyncio
    async def test_without_router_it_ships_facts_and_says_so(self, wm) -> None:
        subj, dim = await _seeded(wm)
        await wm.add_evidence(
            company_id="c1", subject_id=subj.subject_id,
            dimension_id=dim.dimension_id, claim="x",
        )
        await wm.set_score(
            company_id="c1", subject_id=subj.subject_id,
            dimension_id=dim.dimension_id, score=2,
        )
        await wm.take_snapshot("c1", label="base")
        await wm.set_score(
            company_id="c1", subject_id=subj.subject_id,
            dimension_id=dim.dimension_id, score=5,
        )
        t = await self._tool(wm)  # no router injected
        res = await t.execute({"company_id": "c1", "take_snapshot": False})
        md = res.data["markdown"]
        assert "Material changes" in md and "2.0/5 → 5.0/5" in md
        assert res.data["judged_items"] == 0
        assert "Implications not generated" in md

    @pytest.mark.asyncio
    async def test_gaps_are_framed_as_absence_not_weakness(self, wm) -> None:
        await _seeded(wm)
        t = await self._tool(wm)
        md = (await t.execute({"company_id": "c1", "take_snapshot": False})).data[
            "markdown"
        ]
        assert "never observed" in md
        assert "not weaknesses" in md

    @pytest.mark.asyncio
    async def test_snapshot_taken_by_default(self, wm) -> None:
        await _seeded(wm)
        t = await self._tool(wm)
        res = await t.execute({"company_id": "c1"})
        assert res.data["snapshot_id"]
        assert len(await wm.list_snapshots("c1")) == 1
