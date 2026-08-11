"""Judge panels and the refine-until-good loop.

The rules under test are the ones that separate a quality gate from
theatre. A loop that always accepts is a delay; a loop that can never
accept is a hang; a panel that agrees with itself is one reviewer.
"""

from __future__ import annotations

import pytest

from core.panel import (
    Lens,
    QualityBar,
    Verdict,
    assess,
    converge,
    parse_verdict,
    resolve_lenses,
    run_panel,
)

_LENS = Lens("correctness", "logic errors")


def _v(lens: str, score: float, passed: bool, findings=None, **kw) -> Verdict:
    return Verdict(lens=lens, score=score, passed=passed, findings=findings or [], **kw)


_REAL_FINDING = "the retry loop never resets the counter, so it stops at 3"


class TestFindingQuality:
    """Rule 2: a rejection must cite something actionable."""

    def test_specific_finding_is_actionable(self) -> None:
        assert _v("x", 2, False, [_REAL_FINDING]).actionable_findings

    @pytest.mark.parametrize(
        "vague",
        ["could be better", "needs work", "improve this", "unclear", "meh", "-"],
    )
    def test_vague_findings_are_discarded(self, vague: str) -> None:
        assert _v("x", 2, False, [vague]).actionable_findings == []

    def test_too_short_is_discarded(self) -> None:
        assert _v("x", 2, False, ["bad"]).actionable_findings == []

    def test_rejection_without_a_defect_does_not_count(self) -> None:
        """The anti-hang rule: no evidence, no veto."""
        assert not _v("x", 2, False, ["could be better"]).counts_as_rejection

    def test_rejection_with_a_defect_counts(self) -> None:
        assert _v("x", 2, False, [_REAL_FINDING]).counts_as_rejection

    def test_an_errored_verdict_is_not_a_rejection(self) -> None:
        assert not _v(
            "x", 0, False, [_REAL_FINDING], error="timeout"
        ).counts_as_rejection


class TestAssess:
    def test_all_pass_above_bar_accepts(self) -> None:
        ok, reason, mean = assess(
            [_v("a", 5, True), _v("b", 4, True)], QualityBar(min_score=4.0)
        )
        assert ok and mean == 4.5

    def test_mean_below_bar_rejects(self) -> None:
        ok, reason, _ = assess(
            [_v("a", 3, True), _v("b", 3, True)], QualityBar(min_score=4.0)
        )
        assert not ok and "below bar" in reason

    def test_blocking_rejection_beats_a_high_average(self) -> None:
        """Rule 3: 4.6/5 with a real defect is not a pass."""
        verdicts = [
            _v("style", 5, True),
            _v("style2", 5, True),
            _v("security", 4, False, ["secret is logged in plaintext at line 40"]),
        ]
        ok, reason, mean = assess(verdicts, QualityBar(min_score=4.0))
        assert mean > 4.0
        assert not ok
        assert "security" in reason

    def test_non_blocking_lens_cannot_veto(self) -> None:
        verdicts = [
            _v("correctness", 5, True),
            _v("concision", 3, False, [_REAL_FINDING], blocking=False),
        ]
        ok, _, _ = assess(verdicts, QualityBar(min_score=4.0))
        assert ok

    def test_vague_blocking_rejection_does_not_block(self) -> None:
        verdicts = [_v("a", 5, True), _v("b", 4, False, ["could be better"])]
        ok, _, _ = assess(verdicts, QualityBar(min_score=4.0))
        assert ok

    def test_no_usable_verdicts_is_not_an_accept(self) -> None:
        """Silence must never read as approval."""
        ok, reason, _ = assess(
            [_v("a", 0, False, error="boom"), _v("b", 0, False, error="boom")],
            QualityBar(),
        )
        assert not ok and "usable verdict" in reason


class TestParseVerdict:
    def test_plain_json(self) -> None:
        v = parse_verdict('{"score": 4, "passed": true, "findings": []}', _LENS)
        assert v.score == 4 and v.passed and not v.error

    def test_json_embedded_in_prose(self) -> None:
        v = parse_verdict(
            'Here is my review:\n{"score": 3, "passed": false, '
            f'"findings": ["{_REAL_FINDING}"]}}\nHope that helps.',
            _LENS,
        )
        assert v.score == 3 and not v.passed and v.actionable_findings

    def test_unparseable_is_an_error_not_a_pass(self) -> None:
        """A broken judge must not wave work through."""
        v = parse_verdict("I think it's fine honestly", _LENS)
        assert v.error and not v.passed

    def test_empty_is_an_error(self) -> None:
        assert parse_verdict("", _LENS).error

    def test_score_is_clamped(self) -> None:
        assert parse_verdict('{"score": 99, "passed": true}', _LENS).score == 5.0

    def test_string_findings_are_accepted(self) -> None:
        v = parse_verdict(
            f'{{"score": 2, "passed": false, "findings": "{_REAL_FINDING}"}}', _LENS
        )
        assert v.actionable_findings == [_REAL_FINDING]

    def test_lens_blocking_flag_is_carried_through(self) -> None:
        v = parse_verdict(
            '{"score": 1, "passed": false}', Lens("x", "y", blocking=False)
        )
        assert v.blocking is False


class TestRunPanel:
    @pytest.mark.asyncio
    async def test_judges_are_independent(self) -> None:
        """Each judge sees only its own lens — never a peer's verdict."""
        seen: list[str] = []

        async def judge(prompt: str, lens: Lens) -> str:
            seen.append(prompt)
            return '{"score": 5, "passed": true, "findings": []}'

        lenses = [Lens("a", "first"), Lens("b", "second")]
        await run_panel("artifact", lenses, judge)

        assert len(seen) == 2
        assert "first" in seen[0] and "second" not in seen[0]
        assert "second" in seen[1] and "first" not in seen[1]

    @pytest.mark.asyncio
    async def test_reference_reaches_every_judge(self) -> None:
        prompts: list[str] = []

        async def judge(prompt: str, lens: Lens) -> str:
            prompts.append(prompt)
            return '{"score": 5, "passed": true}'

        await run_panel(
            "work", [Lens("a", "x"), Lens("b", "y")], judge, reference="THE-BENCHMARK"
        )
        assert all("THE-BENCHMARK" in p for p in prompts)

    @pytest.mark.asyncio
    async def test_one_judge_raising_does_not_lose_the_others(self) -> None:
        async def judge(prompt: str, lens: Lens) -> str:
            if lens.name == "b":
                raise RuntimeError("model timeout")
            return '{"score": 5, "passed": true}'

        verdicts = await run_panel("x", [Lens("a", "1"), Lens("b", "2")], judge)
        assert len(verdicts) == 2
        assert any(v.error for v in verdicts)
        assert any(v.passed for v in verdicts)

    @pytest.mark.asyncio
    async def test_no_lenses_is_no_verdicts(self) -> None:
        async def judge(prompt: str, lens: Lens) -> str:  # pragma: no cover
            raise AssertionError("should not be called")

        assert await run_panel("x", [], judge) == []


class TestConverge:
    @pytest.mark.asyncio
    async def test_accepts_on_the_first_good_round(self) -> None:
        rounds: list[int] = []

        async def produce(n: int, findings: list[str]) -> str:
            rounds.append(n)
            return "good work"

        async def judge(prompt: str, lens: Lens) -> str:
            return '{"score": 5, "passed": true, "findings": []}'

        result = await converge(
            produce=produce, judge=judge, lenses=[Lens("a", "x")], bar=QualityBar()
        )
        assert result.converged and rounds == [1]

    @pytest.mark.asyncio
    async def test_revises_against_specific_findings(self) -> None:
        """The reviser must receive the defects, not 'try again'."""
        handed: list[list[str]] = []

        async def produce(n: int, findings: list[str]) -> str:
            handed.append(findings)
            return "v2" if n > 1 else "v1"

        async def judge(prompt: str, lens: Lens) -> str:
            if "v1" in prompt:
                return (
                    f'{{"score": 2, "passed": false, "findings": ["{_REAL_FINDING}"]}}'
                )
            return '{"score": 5, "passed": true, "findings": []}'

        result = await converge(
            produce=produce, judge=judge, lenses=[Lens("correctness", "x")]
        )
        assert result.converged
        assert handed[0] == []
        assert any(_REAL_FINDING in f for f in handed[1])
        assert "[correctness]" in handed[1][0]  # lens-tagged

    @pytest.mark.asyncio
    async def test_gives_up_honestly_at_the_round_cap(self) -> None:
        """Rule 5: never claim success it did not earn."""

        async def produce(n: int, findings: list[str]) -> str:
            return "still bad"

        async def judge(prompt: str, lens: Lens) -> str:
            return f'{{"score": 1, "passed": false, "findings": ["{_REAL_FINDING}"]}}'

        result = await converge(
            produce=produce,
            judge=judge,
            lenses=[Lens("a", "x")],
            bar=QualityBar(max_rounds=2),
        )
        assert not result.converged
        assert result.rounds_used == 2
        assert "cap" in result.reason
        assert result.outstanding

    @pytest.mark.asyncio
    async def test_stops_early_when_rejection_cites_nothing(self) -> None:
        """No actionable defect means nothing to revise against — stop."""
        calls: list[int] = []

        async def produce(n: int, findings: list[str]) -> str:
            calls.append(n)
            return "work"

        async def judge(prompt: str, lens: Lens) -> str:
            return '{"score": 1, "passed": false, "findings": ["meh"]}'

        result = await converge(
            produce=produce,
            judge=judge,
            lenses=[Lens("a", "x")],
            bar=QualityBar(max_rounds=5, min_score=4.0),
        )
        assert not result.converged
        assert len(calls) == 1  # did not spin
        assert "without citing a defect" in result.reason

    @pytest.mark.asyncio
    async def test_production_failure_is_reported_not_raised(self) -> None:
        async def produce(n: int, findings: list[str]) -> str:
            raise RuntimeError("model down")

        async def judge(prompt: str, lens: Lens) -> str:  # pragma: no cover
            raise AssertionError("unreachable")

        result = await converge(produce=produce, judge=judge, lenses=[Lens("a", "x")])
        assert not result.converged and "model down" in result.reason

    @pytest.mark.asyncio
    async def test_empty_production_is_not_judged(self) -> None:
        async def produce(n: int, findings: list[str]) -> str:
            return "   "

        async def judge(prompt: str, lens: Lens) -> str:  # pragma: no cover
            raise AssertionError("should not judge nothing")

        result = await converge(produce=produce, judge=judge, lenses=[Lens("a", "x")])
        assert not result.converged and "produced nothing" in result.reason

    @pytest.mark.asyncio
    async def test_summary_is_honest_about_outcome(self) -> None:
        async def produce(n: int, findings: list[str]) -> str:
            return "work"

        async def judge(prompt: str, lens: Lens) -> str:
            return f'{{"score": 1, "passed": false, "findings": ["{_REAL_FINDING}"]}}'

        result = await converge(
            produce=produce,
            judge=judge,
            lenses=[Lens("a", "x")],
            bar=QualityBar(max_rounds=1),
        )
        summary = result.summary()
        assert summary["converged"] is False
        assert summary["rounds_used"] == 1
        assert summary["outstanding_findings"]


class TestLensPacks:
    @pytest.mark.parametrize("pack", ["code", "writing", "analysis"])
    def test_packs_have_distinct_blocking_lenses(self, pack: str) -> None:
        lenses = resolve_lenses(pack=pack)
        assert len(lenses) >= 3
        names = [lens.name for lens in lenses]
        assert len(names) == len(set(names)), "lenses must be distinct, not rewordings"
        assert any(lens.blocking for lens in lenses)

    def test_every_pack_compares_against_the_reference(self) -> None:
        for pack in ("code", "writing", "analysis"):
            assert any(lens.name == "fidelity" for lens in resolve_lenses(pack=pack))

    def test_custom_lenses_combine_with_a_pack(self) -> None:
        lenses = resolve_lenses(
            pack="code", custom=[{"name": "licensing", "brief": "licence headers"}]
        )
        assert any(lens.name == "licensing" for lens in lenses)

    def test_malformed_custom_lenses_are_skipped(self) -> None:
        assert resolve_lenses(custom=[{"name": "x"}, {"brief": "y"}, {}]) == []

    def test_unknown_pack_is_empty_not_an_error(self) -> None:
        assert resolve_lenses(pack="nope") == []
