"""The receipt gate must see what a tool ANSWERED, and a retry must know why
the last attempt failed.

Observed 2026-08-16 on the social-casino baseline goal: checkpoint 1
analysed all four brands, then failed its receipt three times over

    quantitative criteria '… the register still contains exactly 14
    subjects …' not grounded in tool/SoR evidence (no count from [14] appears)

because the trace carried only tool *parameters* — the register listing
that says "14" was a tool *result*, which nothing recorded — and each retry
was told nothing about the failure, so it failed the same way.
"""

from __future__ import annotations

from core.checkpoint_receipt import verify_checkpoint_receipt
from core.goal_runner import GoalRunner

CRITERIA = (
    "For all four subjects, watch_evidence contains fresh append-only rows "
    "dated during this run; the register still contains exactly 14 subjects."
)


def test_count_in_a_tool_output_grounds_the_criteria() -> None:
    trail = [
        {"tool": "watch_analyze", "status": "ok", "summary": "analyze Chumba",
         "data": {"subject": "Chumba Casino"}},
        {"tool": "watch_list", "status": "ok", "summary": "list subjects",
         "data": {}, "output": "{'success': True, 'count': 14, 'subjects': [...]}"},
    ]
    assert verify_checkpoint_receipt(CRITERIA, tool_trace=trail).ok


def test_the_same_trail_without_outputs_still_fails_closed() -> None:
    trail = [
        {"tool": "watch_analyze", "status": "ok", "summary": "analyze Chumba",
         "data": {"subject": "Chumba Casino"}},
        {"tool": "watch_list", "status": "ok", "summary": "list subjects", "data": {}},
    ]
    v = verify_checkpoint_receipt(CRITERIA, tool_trace=trail)
    assert not v.ok and "14" in v.reason


def test_retry_note_carries_the_reason_and_the_cure() -> None:
    note = GoalRunner._retry_note(
        2, "Attempt 1 failed: receipt_gate: quantitative criteria … not grounded "
        "in tool/SoR evidence (no count from [14] appears)"
    )
    assert "Why the last attempt failed" in note
    assert "no count from [14]" in note
    assert "TOOL RESULT" in note and "Restating them in prose does not count" in note
    # a timeout retry says why too, but does not lecture about receipts
    plain = GoalRunner._retry_note(2, "Attempt 1 failed: checkpoint timed out after 1800s")
    assert "timed out" in plain and "TOOL RESULT" not in plain
    assert GoalRunner._retry_note(1, "anything") == ""


def test_tool_output_lands_on_its_trace_row() -> None:
    from core.goal_runner import _attach_tool_output
    from tools.base import ToolResult

    trace = [
        {"tool": "watch_analyze", "status": "ok"},
        {"tool": "watch_list", "status": "ok"},
    ]
    _attach_tool_output(trace, "watch_list", ToolResult(success=True, data={"count": 14}))
    assert "14" in trace[1]["output"] and "output" not in trace[0]
    # a second call of the same tool gets its own row, not the first one's
    trace.append({"tool": "watch_list", "status": "ok"})
    _attach_tool_output(trace, "watch_list", ToolResult(success=True, data={"count": 15}))
    assert "15" in trace[2]["output"] and "14" in trace[1]["output"]
    assert verify_checkpoint_receipt(CRITERIA, tool_trace=trace).ok
