"""Tests for the mind tool-summary humanizer.

Pins the contract that the autonomous-mind dashboard depends on:
- Known tools render verb-first ("Wrote X").
- Unknown tools fall back to raw name (don't invent a verb).
- Paths shorten to `…/parent/leaf` past 48 chars.
- Write tools surface an artifact preview; read tools don't.
- Markdown frontmatter / code fences are skipped when picking the
  "first meaningful line".
"""

from __future__ import annotations

from core.mind_tool_summary import (
    PREVIEW_MAX_CHARS,
    extract_artifact_preview,
    summarize_call,
)


class TestSummarizeCall:
    def test_file_write_with_path(self) -> None:
        out = summarize_call("file_write", {"path": "/tmp/notes.md", "content": "..."})
        assert out == "Wrote /tmp/notes.md"

    def test_long_path_shortened(self) -> None:
        path = "/Users/0xroyce/agents/elophanto/workspace/research/audience-brief.md"
        out = summarize_call("file_write", {"path": path})
        assert out.startswith("Wrote …/")
        assert out.endswith("audience-brief.md")

    def test_knowledge_search_uses_query(self) -> None:
        out = summarize_call("knowledge_search", {"query": "recent X reply lessons"})
        assert out == "Searched memory for: recent X reply lessons"

    def test_role_use_name(self) -> None:
        assert summarize_call("role_use", {"name": "sales"}) == "Switched to role sales"

    def test_unknown_tool_falls_through(self) -> None:
        # No verb in the table → raw name, optionally with object.
        assert summarize_call("custom_tool", {}) == "custom_tool"
        assert summarize_call("custom_tool", {"path": "x"}) == "custom_tool: x"

    def test_no_object_returns_verb_alone(self) -> None:
        assert summarize_call("role_list", {}) == "Listed roles"
        assert summarize_call("skill_list", {}) == "Listed skills"

    def test_skips_empty_params(self) -> None:
        assert summarize_call("file_write", {"path": "", "content": "x"}) == "Wrote x"


class TestExtractArtifactPreview:
    def test_short_content_returned_whole(self) -> None:
        out = extract_artifact_preview("twitter_post", {"content": "hi from the agent"})
        assert out == "hi from the agent"

    def test_long_content_truncated_with_headline(self) -> None:
        body = "# Audience research\n\n" + ("paragraph content. " * 50)
        out = extract_artifact_preview("file_write", {"content": body})
        assert out.startswith("# Audience research\n")
        assert out.endswith("…")
        # Must respect the cap (with small slack for the headline + ellipsis).
        assert len(out) <= PREVIEW_MAX_CHARS + 10

    def test_skips_yaml_frontmatter_in_headline(self) -> None:
        # Force the headline path by giving content long enough to
        # exceed PREVIEW_MAX_CHARS — short content returns whole.
        body = "---\nname: brief\nstatus: draft\n---\n\n" "## What we learned\n\n" + (
            "body paragraph. " * 30
        )
        out = extract_artifact_preview("file_write", {"content": body})
        # The first rendered line should be the H2 headline, not the
        # YAML frontmatter delimiter or the `name:` line.
        first_line = out.splitlines()[0]
        assert first_line == "## What we learned"

    def test_skips_code_fences_for_headline(self) -> None:
        # Force the headline path with long-enough content; same
        # short-vs-long rationale as the frontmatter test.
        body = "```\ncode here\n```\n\n# Real title\n\n" + ("body. " * 60)
        out = extract_artifact_preview("file_write", {"content": body})
        first_line = out.splitlines()[0]
        # The headline picker should land on the H1, not the fence.
        assert first_line == "# Real title"

    def test_read_tools_have_no_preview(self) -> None:
        # No `content`/`body`/`text`/`message` key → empty
        assert extract_artifact_preview("file_read", {"path": "/tmp/x"}) == ""
        assert extract_artifact_preview("role_use", {"name": "ops"}) == ""

    def test_empty_content_returns_empty(self) -> None:
        assert extract_artifact_preview("file_write", {"content": ""}) == ""
        assert extract_artifact_preview("file_write", {"content": "   "}) == ""

    def test_message_key_also_works(self) -> None:
        out = extract_artifact_preview(
            "email_send", {"to": "x@y.com", "message": "Hi there"}
        )
        assert out == "Hi there"
