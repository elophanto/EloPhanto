"""A 200 carrying no answer is a failed call, not a successful one.

2026-08-15. Asked to prompt an endpoint for an SVG, the agent sent a correct
request and got back a clean HTTP 200 whose body contained 24,164 characters
of reasoning, `content: null`, and `finish_reason: "length"` — the model had
spent its entire 8,192-token budget thinking and never emitted an answer.

The agent reported "it did not return actual SVG code" and stopped. That was
honest and useless: the response says exactly what went wrong (the budget)
and exactly what to change (raise it), and none of that reached the model as
anything it had to act on. `http_request` now fails the call and puts the
diagnosis and the fix in the error.
"""

from __future__ import annotations

from typing import Any

from tools.http.request_tool import HttpRequestTool

# The real shape returned by the endpoint, trimmed.
PELICAN: dict[str, Any] = {
    "id": "chatcmpl-HRMAjO",
    "model": "Qwen/Qwen3.8-27B",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "refusal": None,
                "reasoning": "x" * 24164,
            },
            "finish_reason": "length",
        }
    ],
    "usage": {"prompt_tokens": 61, "completion_tokens": 8192, "total_tokens": 8253},
}


class TestTheRegression:
    def test_the_real_response_is_diagnosed(self) -> None:
        d = HttpRequestTool._completion_diagnosis(PELICAN)
        assert d is not None
        assert d["empty_content"] is True
        assert d["finish_reason"] == "length"
        assert d["reasoning_chars"] == 24164
        assert d["completion_tokens"] == 8192
        assert "entire token budget on internal reasoning" in d["diagnosis"]
        assert "larger `max_tokens`" in d["suggested_fix"]

    def test_it_names_the_budget_not_just_the_absence(self) -> None:
        """'No SVG came back' is where the last attempt stopped. The useful
        sentence is why, and what to change."""
        d = HttpRequestTool._completion_diagnosis(PELICAN)
        assert d is not None
        assert "24,164" in d["diagnosis"]
        assert "reasoning_effort" in d["suggested_fix"]


class TestWhatIsNotDiagnosed:
    def test_a_real_answer_passes_through(self) -> None:
        ok = {
            "choices": [
                {"message": {"content": "<svg>…</svg>"}, "finish_reason": "stop"}
            ]
        }
        assert HttpRequestTool._completion_diagnosis(ok) is None

    def test_a_short_answer_with_length_finish_still_passes(self) -> None:
        """Truncated but non-empty is the caller's judgement, not ours."""
        truncated = {
            "choices": [
                {"message": {"content": "<svg><circle"}, "finish_reason": "length"}
            ]
        }
        assert HttpRequestTool._completion_diagnosis(truncated) is None

    def test_ordinary_api_payloads_are_untouched(self) -> None:
        for payload in (
            {"items": [1, 2, 3]},
            {"choices": "not a list"},
            {"choices": []},
            {"choices": [{"no_message": True}]},
            [1, 2, 3],
            "plain text",
            None,
        ):
            assert HttpRequestTool._completion_diagnosis(payload) is None


class TestOtherEmptyShapes:
    def test_refusal_is_named_as_a_refusal(self) -> None:
        d = HttpRequestTool._completion_diagnosis(
            {"choices": [{"message": {"content": "", "refusal": "no"},
                          "finish_reason": "content_filter"}]}
        )
        assert d is not None and "declined" in d["diagnosis"]
        assert "Rephrase" in d["suggested_fix"]

    def test_reasoning_without_length_suggests_a_field_check(self) -> None:
        d = HttpRequestTool._completion_diagnosis(
            {"choices": [{"message": {"content": None, "reasoning": "y" * 50},
                          "finish_reason": "stop"}]}
        )
        assert d is not None
        assert "no answer content" in d["diagnosis"]
        assert "non-standard field" in d["suggested_fix"]

    def test_a_bare_empty_completion_still_reports(self) -> None:
        d = HttpRequestTool._completion_diagnosis(
            {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]}
        )
        assert d is not None and "empty completion" in d["diagnosis"]

    def test_legacy_text_completions_are_covered(self) -> None:
        d = HttpRequestTool._completion_diagnosis(
            {"choices": [{"text": "", "finish_reason": "length"}]}
        )
        assert d is not None and d["finish_reason"] == "length"
