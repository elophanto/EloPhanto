"""Shared consumer filter (extracted from dream_tool in ABE Phase 7).

These tests lock in the contract that both `dream_tool` (existing)
and `company_set_product` (new) call into. Same banlist, same
agent-self detection — single source of truth.
"""

from __future__ import annotations

from core.consumer_filter import (
    is_consumerless,
    is_consumerless_text,
)


class TestIsConsumerlessText:
    def test_empty_rejected(self) -> None:
        rejected, reason = is_consumerless_text("")
        assert rejected is True
        assert "empty" in reason

    def test_whitespace_only_rejected(self) -> None:
        rejected, _ = is_consumerless_text("   \n  ")
        assert rejected is True

    def test_banned_fragment_rejected(self) -> None:
        rejected, reason = is_consumerless_text(
            "A framework for self-perception calibration"
        )
        assert rejected is True
        assert "self-perception" in reason

    def test_external_audience_passes(self) -> None:
        rejected, _ = is_consumerless_text(
            "Boutique automations for indie operators. We ship "
            "agent-built lead-gen pipelines per engagement."
        )
        assert rejected is False

    def test_label_appears_in_reason(self) -> None:
        rejected, reason = is_consumerless_text(
            "evidence garden v2", label="what_we_sell"
        )
        assert rejected is True
        assert "what_we_sell" in reason


class TestIsConsumerlessCandidate:
    """Pin the original (dict-based) entrypoint that the dream tool
    relies on. These tests guard against regressions in the
    extraction — same behaviour pre and post move."""

    def test_missing_consumer_rejected(self) -> None:
        rejected, reason = is_consumerless({"title": "Some Plan", "consumer": ""})
        assert rejected is True
        assert "consumer" in reason

    def test_agent_self_consumer_rejected(self) -> None:
        rejected, reason = is_consumerless(
            {"title": "X", "consumer": "the agent itself"}
        )
        assert rejected is True

    def test_operator_consumer_passes(self) -> None:
        rejected, _ = is_consumerless(
            {
                "title": "Ship landing page",
                "consumer": "the operator deciding next quarter's focus",
                "consumer_artifact": "public URL",
            }
        )
        assert rejected is False

    def test_internal_artifact_with_self_rejected(self) -> None:
        # The consumer-self rule short-circuits before the artifact
        # rule fires — both would reject, but consumer-self is the
        # stronger signal so its reason wins. Either rejection
        # message satisfies the contract; the assertion just pins
        # the actual short-circuit order.
        rejected, reason = is_consumerless(
            {
                "title": "X",
                "consumer": "this agent",
                "consumer_artifact": "internal rubric",
            }
        )
        assert rejected is True
        assert "agent itself" in reason

    def test_internal_artifact_with_external_consumer_passes(self) -> None:
        # Rule 3 is conjunctive: rubric to operator is fine.
        rejected, _ = is_consumerless(
            {
                "title": "Review rubric",
                "consumer": "the operator deciding which leads to pursue",
                "consumer_artifact": "rubric",
            }
        )
        assert rejected is False


class TestDreamToolReexports:
    """The dream tool re-exports the names from consumer_filter so any
    external code referencing them still works. These tests prevent
    a future refactor from accidentally breaking that contract."""

    def test_reexports_match(self) -> None:
        from core.consumer_filter import (
            _BANNED_TITLE_FRAGMENTS as cf_banned,
        )
        from core.consumer_filter import (
            _INTERNAL_ARTIFACT_HINTS as cf_hints,
        )
        from tools.goals.dream_tool import (
            _BANNED_TITLE_FRAGMENTS as dt_banned,
        )
        from tools.goals.dream_tool import (
            _INTERNAL_ARTIFACT_HINTS as dt_hints,
        )

        assert cf_banned is dt_banned
        assert cf_hints is dt_hints

    def test_dream_tool_is_consumerless_still_works(self) -> None:
        from tools.goals.dream_tool import _is_consumerless

        rejected, _ = _is_consumerless({"title": "Evidence Garden", "consumer": "X"})
        assert rejected is True
