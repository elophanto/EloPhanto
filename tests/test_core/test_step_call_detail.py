"""Parallel tool calls must be distinguishable in the activity feed.

The feed rendered the step's planner *thought* against every row, but a
thought belongs to the whole step — so three concurrent `email_read` calls on
three different messages produced three byte-identical lines that read like a
duplicated log rather than three distinct reads.
"""

from __future__ import annotations

from core.mind_tool_summary import summarize_step_call


class TestParallelCallsAreDistinguishable:
    def test_three_email_reads_render_differently(self) -> None:
        ids = [
            "<20260803074304.f26f4e7f728968b2@cio129328.polymarket.com>",
            "<0100019f7c0954fa-9dc68c1d-3c6e@email.amazonses.com>",
            "<2fd821ba52ef196b2101212d9e31af47@mlsend2.com>",
        ]
        out = [summarize_step_call("email_read", {"message_id": i}) for i in ids]
        assert len(set(out)) == 3, out

    def test_three_skill_reads_render_differently(self) -> None:
        names = ["ui-design", "x-virality", "plan-review-design"]
        out = [summarize_step_call("skill_read", {"skill_name": n}) for n in names]
        assert len(set(out)) == 3, out


class TestReadability:
    def test_message_id_collapses_to_the_sending_domain(self) -> None:
        got = summarize_step_call(
            "email_read",
            {"message_id": "<20260803074304.f26f4e7f728968b2@cio129328.polymarket.com>"},
        )
        assert got == "email_read: polymarket.com"

    def test_stays_short_enough_for_the_feed(self) -> None:
        got = summarize_step_call(
            "email_read", {"message_id": "<" + "x" * 300 + "@some.very.long.example.com>"}
        )
        assert len(got) <= 60

    def test_existing_summaries_are_preserved(self) -> None:
        assert summarize_step_call("skill_read", {"skill_name": "x-virality"}) == (
            "Loaded skill x-virality"
        )
        assert "Elon" in summarize_step_call("web_search", {"query": "Elon Terafab"})

    def test_no_identifier_yields_empty_not_noise(self) -> None:
        # The feed falls back to the planner thought when there's nothing
        # per-call worth showing.
        assert summarize_step_call("email_list", {}) == ""

    def test_never_raises_on_junk_params(self) -> None:
        for params in ({}, {"message_id": None}, {"message_id": 12345}, None):
            summarize_step_call("email_read", params)  # type: ignore[arg-type]


class TestEmittersCarryDetail:
    def test_gateway_and_agent_both_send_detail(self) -> None:
        """Both STEP_PROGRESS emitters must populate it, or the chat path and
        the scheduled path disagree about what the feed shows."""
        for path in ("core/gateway.py", "core/agent.py"):
            with open(path) as fh:
                src = fh.read()
            assert '"detail": _summarize_step_call(' in src, path
