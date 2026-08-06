"""twitter_post must click the composer submit button, not sidebar Post.

Regression for the operator-visible failure: draft is typed, then a
`browser_click_text('Post')` hits the sidebar nav, which opens a NEW
empty compose (looks like a refresh) and forces a full re-draft.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tools.publishing.twitter_tool import TwitterPostTool


class _FakeBrowser:
    """Scripted bridge: records calls and returns canned eval results."""

    def __init__(self, script: list[Any]) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._script = list(script)
        self._i = 0

    async def call_tool(self, name: str, params: dict[str, Any]) -> Any:
        self.calls.append((name, params))
        if name == "browser_wait":
            return {"ok": True}
        if name in ("browser_navigate", "browser_get_elements", "browser_type_text"):
            return {"ok": True}
        if name == "browser_eval":
            if self._i >= len(self._script):
                return {"result": ""}
            val = self._script[self._i]
            self._i += 1
            return {"result": val}
        if name == "browser_click_text":
            raise AssertionError(
                "twitter_post must not use browser_click_text — " f"got {params!r}"
            )
        return {"ok": True}


def _eval_seq_happy_path() -> list[Any]:
    """Sequence of browser_eval return values for a clean text post."""
    # focus loop (first selector found)
    focus = ["found"]
    # paste
    paste = ["pasted"]
    # verify content in box
    verify = ["hello from the agent — shipping."]
    # submit click (enabled on first try)
    submit = ["clicked:tweetButton"]
    # publish evidence polls — toast after one empty/draft tick
    evidence = [
        json.dumps(
            {
                "href": "https://x.com/compose/post",
                "draft": "",
                "sent": False,
                "toast": "",
            }
        ),
        json.dumps(
            {
                "href": "https://x.com/compose/post",
                "draft": "",
                "sent": True,
                "toast": "your post was sent",
            }
        ),
    ]
    return focus + paste + verify + submit + evidence


@pytest.mark.asyncio
async def test_twitter_post_clicks_testid_not_sidebar_post() -> None:
    tool = TwitterPostTool()
    fake = _FakeBrowser(_eval_seq_happy_path())
    tool._browser_manager = fake
    tool._db = None

    result = await tool.execute({"content": "hello from the agent — shipping."})

    assert result.success is True, result.error
    assert result.data and result.data.get("evidence") == "toast"
    # Never used click_text (fake would raise). Soft check: no such call recorded.
    assert all(name != "browser_click_text" for name, _ in fake.calls)
    # Submit went through browser_eval with tweetButton selectors.
    submit_evals = [
        params["expression"]
        for name, params in fake.calls
        if name == "browser_eval" and "tweetButton" in params.get("expression", "")
    ]
    assert submit_evals, "expected a tweetButton eval click"
    assert "browser_click_text" not in "".join(json.dumps(c) for c in fake.calls)


@pytest.mark.asyncio
async def test_twitter_post_waits_for_enabled_button() -> None:
    tool = TwitterPostTool()
    # focus, paste, verify, then disabled twice, then click, then status url
    script = [
        "found",
        "pasted",
        "hello world draft text here for match",
        "disabled",
        "disabled",
        "clicked:tweetButtonInline",
        json.dumps(
            {
                "href": "https://x.com/user/status/1234567890",
                "draft": "",
                "sent": False,
                "toast": "",
            }
        ),
    ]
    fake = _FakeBrowser(script)
    tool._browser_manager = fake
    tool._db = None

    result = await tool.execute({"content": "hello world draft text here for match"})
    assert result.success is True, result.error
    assert result.data["tweet_url"].endswith("/status/1234567890")
    assert result.data["evidence"] == "status_url"


@pytest.mark.asyncio
async def test_twitter_post_refuses_when_submit_missing() -> None:
    tool = TwitterPostTool()
    # focus, paste, verify, then 8x missing submit
    script = ["found", "pasted", "clean draft without banned phrases ok"] + (
        ["missing"] * 8
    )
    fake = _FakeBrowser(script)
    tool._browser_manager = fake
    tool._db = None

    result = await tool.execute({"content": "clean draft without banned phrases ok"})
    assert result.success is False
    assert "tweetButton" in (result.error or "")
    assert "sidebar" in (result.error or "").lower()
