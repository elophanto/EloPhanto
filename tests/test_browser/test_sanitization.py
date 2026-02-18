"""Tests for content sanitization in browser utils."""

from __future__ import annotations

import pytest

from tools.browser.utils import sanitize_content


class TestSanitizeContent:
    def test_strips_script_tags(self) -> None:
        html = '<div>Hello</div><script>alert("xss")</script><p>World</p>'
        result = sanitize_content(html)
        assert "<script" not in result
        assert "alert" not in result
        assert "<div>Hello</div>" in result
        assert "<p>World</p>" in result

    def test_strips_style_tags(self) -> None:
        html = "<style>body { color: red; }</style><p>Text</p>"
        result = sanitize_content(html)
        assert "<style" not in result
        assert "color: red" not in result
        assert "<p>Text</p>" in result

    def test_strips_event_handlers_double_quotes(self) -> None:
        html = '<button onclick="doEvil()">Click</button>'
        result = sanitize_content(html)
        assert "onclick" not in result
        assert "<button" in result

    def test_strips_event_handlers_single_quotes(self) -> None:
        html = "<div onmouseover='hack()'>Hover</div>"
        result = sanitize_content(html)
        assert "onmouseover" not in result

    def test_redacts_password_values(self) -> None:
        html = '<input type="password" value="secret123" name="pwd">'
        result = sanitize_content(html)
        assert "secret123" not in result
        assert "[REDACTED]" in result

    def test_replaces_large_data_uris(self) -> None:
        large_b64 = "A" * 200000
        html = f'<img src="data:image/png;base64,{large_b64}">'
        result = sanitize_content(html)
        assert "[LARGE_DATA_URI]" in result
        assert large_b64 not in result

    def test_preserves_small_data_uris(self) -> None:
        small_b64 = "A" * 100
        html = f'<img src="data:image/png;base64,{small_b64}">'
        result = sanitize_content(html)
        assert small_b64 in result

    def test_case_insensitive_script_removal(self) -> None:
        html = "<SCRIPT>evil()</SCRIPT><Script>also_evil()</Script>"
        result = sanitize_content(html)
        assert "evil" not in result

    def test_multiline_script_removal(self) -> None:
        html = "<script>\n  var x = 1;\n  alert(x);\n</script><p>Safe</p>"
        result = sanitize_content(html)
        assert "<script" not in result
        assert "alert" not in result
        assert "<p>Safe</p>" in result

    def test_empty_string(self) -> None:
        assert sanitize_content("") == ""

    def test_no_dangerous_content(self) -> None:
        html = "<div><p>Hello World</p></div>"
        assert sanitize_content(html) == html
