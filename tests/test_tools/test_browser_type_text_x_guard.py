"""browser_type_text X-composer guard — refuse substantive text input on
x.com / twitter.com because the Lexical-controlled composer drops
leading chars during the focus race.

Pinned after 2026-05-16 04:28 incident: agent's draft
'clarity headline is doing more work than the bill text' landed on X
as 'e is doing more work than the bill text' (first 15 chars eaten).
twitter_post had failed (couldn't find textbox), agent fell back to
raw browser_type_text — the dangerous path. This guard removes that
foot-gun.
"""

from __future__ import annotations

from typing import Any

import pytest

from tools.base import PermissionLevel
from tools.browser.tools import BridgeBrowserTool


class _StubBrowser:
    """Simulates browser_manager. ``host`` controls what location.host
    returns when the tool queries via browser_eval."""

    def __init__(self, host: str) -> None:
        self.host = host
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, params: dict[str, Any]) -> Any:
        self.calls.append((name, params))
        if name == "browser_eval" and "location.host" in params.get("expression", ""):
            # browser_eval returns {"result": <value>} in the bridge contract
            # — eval_value extracts it.
            return {"result": self.host}
        return {"ok": True}


def _make_tool(name: str) -> BridgeBrowserTool:
    return BridgeBrowserTool(
        tool_name=name,
        tool_description="test",
        tool_schema={"type": "object"},
        tool_permission=PermissionLevel.MODERATE,
    )


class TestXComposerGuard:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "host", ["x.com", "www.x.com", "twitter.com", "mobile.twitter.com"]
    )
    async def test_long_text_refused_on_x_host(self, host: str) -> None:
        tool = _make_tool("browser_type_text")
        tool._browser_manager = _StubBrowser(host)

        result = await tool.execute(
            {"text": "clarity headline is doing more work than the bill text"}
        )

        assert result.success is False
        assert "refused" in (result.error or "").lower()
        # Tool did the host check via browser_eval but did NOT proceed
        # to the dangerous browser_type_text call.
        names = [n for (n, _) in tool._browser_manager.calls]
        assert "browser_eval" in names
        assert "browser_type_text" not in names

    @pytest.mark.asyncio
    async def test_short_text_passes_on_x(self) -> None:
        """Short input (search query, hashtag, 2FA code) still goes
        through — only the multi-paragraph drafts that hit the focus
        race are blocked."""
        tool = _make_tool("browser_type_text")
        tool._browser_manager = _StubBrowser("x.com")

        result = await tool.execute({"text": "hello"})
        assert result.success is True
        # No host check at all because length gate didn't trip.
        names = [n for (n, _) in tool._browser_manager.calls]
        assert "browser_eval" not in names
        assert "browser_type_text" in names

    @pytest.mark.asyncio
    async def test_long_text_allowed_on_other_hosts(self) -> None:
        """Same long text on a non-X host goes through normally."""
        tool = _make_tool("browser_type_text")
        tool._browser_manager = _StubBrowser("medium.com")

        result = await tool.execute(
            {"text": "clarity headline is doing more work than the bill text"}
        )
        assert result.success is True
        names = [n for (n, _) in tool._browser_manager.calls]
        # Host check happened, found it wasn't X, then proceeded.
        assert "browser_eval" in names
        assert "browser_type_text" in names

    @pytest.mark.asyncio
    async def test_host_check_failure_lets_call_through(self) -> None:
        """If browser_eval errors when probing the host, the guard
        doesn't block — we'd rather risk a truncated post (caught by
        verification downstream) than block unrelated typing work."""

        class _ErroringBrowser:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, Any]]] = []

            async def call_tool(self, name: str, params: dict[str, Any]) -> Any:
                self.calls.append((name, params))
                if name == "browser_eval":
                    raise RuntimeError("page closed mid-eval")
                return {"ok": True}

        tool = _make_tool("browser_type_text")
        tool._browser_manager = _ErroringBrowser()

        result = await tool.execute(
            {"text": "clarity headline is doing more work than the bill text"}
        )
        assert result.success is True
        names = [n for (n, _) in tool._browser_manager.calls]
        assert "browser_type_text" in names

    @pytest.mark.asyncio
    async def test_guard_only_fires_for_browser_type_text(self) -> None:
        """Other browser tools (click, navigate, eval) on x.com are
        unaffected — guard is name-specific."""
        for tool_name in ("browser_click", "browser_navigate", "browser_extract"):
            tool = _make_tool(tool_name)
            tool._browser_manager = _StubBrowser("x.com")
            result = await tool.execute(
                {"index": 1, "text": "a very long string that would otherwise trip"}
            )
            assert result.success is True, f"{tool_name} should not be guarded"
            names = [n for (n, _) in tool._browser_manager.calls]
            # No pre-call host check for non-type tools.
            assert "browser_eval" not in names
            assert tool_name in names
