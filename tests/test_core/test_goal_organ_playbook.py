"""Goal plans must name the organ's tools, not describe the work in prose.

2026-08-15, the day's defining failure: every direct request collected
evidence (2 and 8 `watch_analyze` calls), every goal-driven run collected
nothing (0 calls across 28 goal-checkpoint executions). Perfect inverse
correlation. The decomposer had never heard of `watch_analyze`, so it wrote
checkpoints like "All 48 brand-dimension cells have a documented search
result" — and the executor, handed prose with no tool anchor, improvised:
20 skill_read, 15 file_read, 10 shell_execute, and a stale CSV from a
previous run's workspace presented as this run's collection. The receipt
gate refused it three times and the goal paused.

Two prompts now carry the fix: the decomposer names the tool per checkpoint
and states criteria against the organ's register, and the executor is told
that collection means fetching from the live source in THIS run.
"""

from __future__ import annotations

import re

from core.goal_manager import _DECOMPOSE_SYSTEM
from core.goal_runner import _CHECKPOINT_PROMPT


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


class TestDecomposerKnowsTheWatchPipeline:
    def test_the_rule_is_stated(self) -> None:
        assert "USE THE ORGAN, NOT PROSE" in _DECOMPOSE_SYSTEM

    def test_collection_names_watch_analyze_with_the_right_shape(self) -> None:
        flat = _flat(_DECOMPOSE_SYSTEM)
        assert "watch_analyze subject=<brand> save=false" in flat
        assert "batch a few brands per checkpoint" in flat

    def test_deliverables_are_one_consolidated_checkpoint(self) -> None:
        flat = _flat(_DECOMPOSE_SYSTEM)
        assert "watch_scorecard format=xlsx" in flat
        assert "watch_board_report" in flat
        assert "never one deliverable per brand" in flat

    def test_criteria_anchor_to_the_register_not_files(self) -> None:
        flat = _flat(_DECOMPOSE_SYSTEM)
        assert "the register is the system of record; a file is not" in flat
        assert "watch_evidence holds rows dated today" in flat
        assert "never file counts" in flat

    def test_it_carries_the_incident(self) -> None:
        assert "zero fetches" in _flat(_DECOMPOSE_SYSTEM)
        assert "2026-08-15" in _DECOMPOSE_SYSTEM


class TestExecutorPrefersTheOrgan:
    def test_names_the_pipeline_tools(self) -> None:
        flat = _flat(_CHECKPOINT_PROMPT)
        for tool in ("watch_analyze", "watch_score", "watch_scorecard",
                     "watch_board_report", "watch_executive_deck"):
            assert tool in flat, f"{tool} missing from the checkpoint prompt"

    def test_forbids_satisfying_collection_from_old_files(self) -> None:
        flat = _flat(_CHECKPOINT_PROMPT)
        assert "fetching from the live source during this execution" in flat
        assert "prior state, not this run's evidence" in flat

    def test_explains_the_gate_so_the_model_stops_retrying_files(self) -> None:
        """The failing run read the stale CSV harder on each retry. The
        prompt now says why that can never pass."""
        flat = _flat(_CHECKPOINT_PROMPT)
        assert "receipt gate refuses" in flat
        assert "reading old artifacts harder cannot pass" in flat

    def test_validate_stage_rule_survives_the_edit(self) -> None:
        assert "party will PAY" in _CHECKPOINT_PROMPT

    def test_prompt_still_formats(self) -> None:
        out = _CHECKPOINT_PROMPT.format(
            goal="g", order=1, total=3, title="t", stage="scan",
            description="d", criteria="c", context="ctx",
        )
        assert "g" in out and "ctx" in out


class TestRevisionsObeyTheSameRules:
    """The mid-run reviser was the unguarded door.

    2026-08-15, same day as the decomposer fix: the initial plan came out
    clean (five checkpoints, all naming watch tools), then a mid-run
    revision — whose prompt carried none of the rules — replaced "collect
    the missing brands" with audit checkpoints ("Resolve the 451-versus-313
    evidence-register discrepancy") and a 216KB reconciliation CSV, while
    the missing brand stayed uncollected. Same bug, one door over.
    """

    def test_revise_carries_the_full_plan_rules(self) -> None:
        from core.goal_manager import _PLAN_RULES, _REVISE_SYSTEM

        assert _PLAN_RULES in _REVISE_SYSTEM

    def test_decompose_and_revise_share_one_rules_block(self) -> None:
        """Shared constant, not a copy — copies drift, and a drifted copy is
        how this door was left unguarded the first time."""
        from core.goal_manager import _DECOMPOSE_SYSTEM, _PLAN_RULES, _REVISE_SYSTEM

        assert _PLAN_RULES in _DECOMPOSE_SYSTEM
        assert _PLAN_RULES in _REVISE_SYSTEM

    def test_revision_fixes_the_shortfall_not_the_bookkeeping(self) -> None:
        from core.goal_manager import _REVISE_SYSTEM

        flat = _flat(_REVISE_SYSTEM)
        assert "a revision fixes the shortfall, not the bookkeeping" in flat
        assert "watch_analyze for the 3 missing brands" in flat
        assert "registers-of-the-" in flat  # no ledgers about ledgers

    def test_validate_first_rule_survives(self) -> None:
        from core.goal_manager import _REVISE_SYSTEM

        assert "paying-party signal" in _REVISE_SYSTEM


def test_plan_rules_declare_the_register_canon() -> None:
    """Regression 2026-08-15: an executor 'completing the canon' added two
    brands to the customer's register mid-goal. The register is a
    deliverable; plans must not grow it unbidden."""
    from core.goal_manager import _PLAN_RULES

    assert "THE REGISTER IS CANON" in _PLAN_RULES
    assert "Never add a new brand mid-goal" in _PLAN_RULES
