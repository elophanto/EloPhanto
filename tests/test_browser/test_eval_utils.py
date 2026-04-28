"""Tests for tools.browser.eval_utils.eval_value.

Pinning down the contract because reading browser_eval results was
silently broken across multiple tools (publishing, affiliate) for a
long time — the bridge returns ``resultJson`` (JSON-encoded) but
callers were reading ``result`` (which doesn't exist) and ending up
with empty strings, then deciding "X isn't logged in" / "could not
extract product" / etc.
"""

from __future__ import annotations

from tools.browser.eval_utils import eval_value


class TestEvalValueBridgeShape:
    """The current bridge envelope: ``{success, expression, resultJson, error}``."""

    def test_string_value(self) -> None:
        assert eval_value({"success": True, "resultJson": '"found"'}) == "found"

    def test_number_value(self) -> None:
        assert eval_value({"success": True, "resultJson": "42"}) == 42

    def test_boolean_value(self) -> None:
        assert eval_value({"success": True, "resultJson": "true"}) is True
        assert eval_value({"success": True, "resultJson": "false"}) is False

    def test_null_value(self) -> None:
        assert eval_value({"success": True, "resultJson": "null"}) is None

    def test_object_value(self) -> None:
        result = {"success": True, "resultJson": '{"key": "value", "n": 7}'}
        assert eval_value(result) == {"key": "value", "n": 7}

    def test_array_value(self) -> None:
        result = {"success": True, "resultJson": "[1, 2, 3]"}
        assert eval_value(result) == [1, 2, 3]

    def test_url_extract(self) -> None:
        # The exact shape twitter_tool / youtube_tool / tiktok_tool care about
        result = {
            "success": True,
            "expression": "window.location.href",
            "resultJson": '"https://x.com/EloPhanto/status/12345"',
        }
        assert eval_value(result) == "https://x.com/EloPhanto/status/12345"


class TestEvalValueLegacyShape:
    """Tolerate the old / hand-rolled ``{"result": ...}`` envelope."""

    def test_legacy_dict_with_result_field(self) -> None:
        assert eval_value({"result": "oldstyle"}) == "oldstyle"

    def test_legacy_with_object(self) -> None:
        # If a caller passes a non-string under ``result``, return it as-is.
        assert eval_value({"result": {"nested": True}}) == {"nested": True}


class TestEvalValueDegenerateInputs:
    def test_bare_string_passthrough(self) -> None:
        assert eval_value("plain string") == "plain string"

    def test_none(self) -> None:
        assert eval_value(None) is None

    def test_empty_dict_returns_none(self) -> None:
        assert eval_value({}) is None

    def test_dict_without_relevant_fields(self) -> None:
        assert eval_value({"unrelated": "data"}) is None

    def test_malformed_json_falls_back_to_raw(self) -> None:
        # If resultJson is somehow not valid JSON, return it as a string
        # rather than crashing the whole tool.
        result = {"success": True, "resultJson": "this is not json"}
        assert eval_value(result) == "this is not json"

    def test_non_string_resultJson_returned_as_is(self) -> None:
        # Defensive: someone shoves a non-string into resultJson.
        result = {"success": True, "resultJson": 42}
        assert eval_value(result) == 42

    def test_resultJson_takes_priority_over_legacy_result(self) -> None:
        # If both fields are set, prefer the bridge's actual format.
        result = {"resultJson": '"new"', "result": "old"}
        assert eval_value(result) == "new"
