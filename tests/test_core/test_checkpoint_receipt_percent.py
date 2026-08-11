"""A percentage is a proportion, not a count.

The receipt gate extracted every number from the success criteria and
demanded each appear literally in the tool evidence. `100%` yielded `100`,
and a goal that genuinely covered 100% of 37 files produced evidence saying
"37" — never "100". Any criterion whose only number was a percentage was
therefore unsatisfiable, and the checkpoint could never pass however well
the work was done.

Observed 2026-08-11 on two goals:

    16:59:00  Checkpoint 1 receipt failed for goal a98d7c91-30f:
      'A saved manifest covers 100% of discovered files, …'
      not grounded in tool/SoR evidence (missing counts [100])

That goal spent three hours failing the same receipt, and escaped only by
rewriting the criterion to drop the "100%" wording — routing around the
gate rather than satisfying it.
"""

from __future__ import annotations

from core.checkpoint_receipt import verify_checkpoint_receipt

# The real criterion from the log.
MANIFEST = (
    "A saved manifest covers 100% of discovered files, every evaluation "
    "candidate has a hash and exposure classification, and access controls "
    "or separate paths isolate diagnosis and confirmation sets."
)
LEDGER = (
    "A ledger covers 100% of relevant discovered artifacts, cites their "
    "paths and verification evidence, and identifies the exact next "
    "unfinished step without rerunning completed work."
)


def _trail(summary: str) -> list[dict[str, object]]:
    return [{"tool": "file_list", "status": "ok", "summary": summary}]


class TestTheRegression:
    def test_full_coverage_of_37_files_now_passes(self) -> None:
        """Honest evidence names the set size, not the percentage."""
        verdict = verify_checkpoint_receipt(
            MANIFEST,
            tool_trace=_trail(
                "discovered 37 files; manifest saved with 37 entries, "
                "37 hashes, 0 unclassified candidates"
            ),
        )
        assert verdict.ok, verdict.reason

    def test_the_other_stuck_goals_criterion_passes_too(self) -> None:
        verdict = verify_checkpoint_receipt(
            LEDGER,
            tool_trace=_trail(
                "ledger written: 12 artifacts, 12 paths cited, next step recorded"
            ),
        )
        assert verdict.ok, verdict.reason

    def test_no_longer_demands_the_literal_digits(self) -> None:
        """The old failure mode, stated directly."""
        verdict = verify_checkpoint_receipt(
            MANIFEST, tool_trace=_trail("wrote 37 of 37 entries")
        )
        assert "missing counts" not in verdict.reason
        assert verdict.ok


class TestProportionsStillNeedEvidence:
    def test_a_proportion_with_no_counts_at_all_is_refused(self) -> None:
        """You cannot claim 100% of a set you never enumerated."""
        verdict = verify_checkpoint_receipt(
            MANIFEST,
            tool_trace=_trail("looked at the files and they all seem fine"),
        )
        assert not verdict.ok
        assert "nothing was enumerated" in verdict.reason

    def test_empty_evidence_is_still_refused(self) -> None:
        assert not verify_checkpoint_receipt(MANIFEST, tool_trace=[]).ok


class TestCountsAreUnchanged:
    def test_a_grounded_count_passes(self) -> None:
        verdict = verify_checkpoint_receipt(
            "The corpus contains at least 200 deduplicated examples.",
            tool_trace=_trail("corpus built: 200 unique examples after dedup"),
        )
        assert verdict.ok

    def test_an_ungrounded_count_is_refused(self) -> None:
        verdict = verify_checkpoint_receipt(
            "The corpus contains at least 200 deduplicated examples.",
            tool_trace=_trail("corpus built, looks about right"),
        )
        assert not verdict.ok
        assert "no count from [200] appears" in verdict.reason

    def test_a_percentage_does_not_mask_a_missing_count(self) -> None:
        """Mixed criteria are judged on their counts, not the proportion."""
        verdict = verify_checkpoint_receipt(
            "At least 25% of examples are held out, across 4 target contexts.",
            tool_trace=_trail("held out some examples across the contexts"),
        )
        assert not verdict.ok
        assert "[4]" in verdict.reason

    def test_substring_matches_do_not_count_as_grounding(self) -> None:
        """'10' inside '100' is not evidence for a claim of 10."""
        verdict = verify_checkpoint_receipt(
            "Exactly 10 reviewers signed off.",
            tool_trace=_trail("100 files scanned"),
        )
        assert not verdict.ok
