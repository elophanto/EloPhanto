"""x_style_preflight — mechanical style check for X post drafts.

Pins the banned-phrase list against the operator's accumulated
corrections so future LLM-drafted replies can't smuggle consultant /
policy-memo / AI-assistant cadence past a self-graded "passed" claim.
See tools/social/x_style_preflight_tool.py for the rationale.
"""

from __future__ import annotations

import pytest

from tools.social.x_style_preflight_tool import (
    XStylePreflightTool,
    check_x_style,
)


class TestHardBansRefuse:
    """Each hard ban must produce pass=False and surface in
    hard_violations. These are phrases the operator has explicitly
    corrected — there is no legitimate use in CT voice."""

    @pytest.mark.parametrize(
        "phrase",
        [
            "is the part that matters",
            "at the end of the day",
            "from day one",
            "the future of",
            "under the hood",
            "as an ai",
            "as an agent",
            "i can help",
            "i'd recommend",
            "mainstream borrow rails",
            "robust infrastructure",
            "leverage ux",
            "teach risk",
            "sells convenience",
            "autonomous api access",
            "best practice",
        ],
    )
    def test_phrase_blocks_post(self, phrase: str) -> None:
        # Wrap the phrase in plausible-looking sentence context so the
        # test isn't just matching against a bare token — proves
        # substring search works in real-shape input.
        draft = f"yeah, {phrase} is what i always say about this."
        result = check_x_style(draft)
        assert result["pass"] is False, f"{phrase!r} should hard-fail"
        hits = [v["phrase"] for v in result["hard_violations"]]
        assert phrase in hits, f"expected {phrase!r} in hard_violations, got {hits}"

    def test_case_insensitive(self) -> None:
        """Operator might draft in mixed case; X voice rules say
        lowercase but the banned check must catch all-caps too."""
        draft = "AS AN AI, I'd recommend you reconsider."
        result = check_x_style(draft)
        assert result["pass"] is False

    def test_position_recorded(self) -> None:
        draft = "the future of crypto is decentralized."
        result = check_x_style(draft)
        assert result["pass"] is False
        # First match starts at position 0 (or close to it).
        first = result["hard_violations"][0]
        assert first["position"] == 0
        assert first["phrase"] == "the future of"


class TestSoftBansWarnButPass:
    """Soft bans flag the operator that something looks slop-y but
    don't auto-reject. 'ecosystem' is a real crypto noun, 'unlock' has
    legit uses ('unlock the wallet'). Operator chose hard rules over
    aggressive auto-block on these."""

    def test_ecosystem_warns(self) -> None:
        draft = "the solana ecosystem keeps shipping."
        result = check_x_style(draft)
        # PASS because no hard violation.
        assert result["pass"] is True
        soft = [v["phrase"] for v in result["soft_violations"]]
        assert "ecosystem" in soft

    def test_at_scale_warns(self) -> None:
        draft = "fees drop at scale, nothing surprising."
        result = check_x_style(draft)
        assert result["pass"] is True
        assert any(v["phrase"] == "at scale" for v in result["soft_violations"])

    def test_unlock_word_boundary(self) -> None:
        """Single-word soft bans use word-boundary regex so 'unlock'
        doesn't accidentally match 'unlocked' (which feels too aggressive
        for a CT-voice check)."""
        draft = "wallet finally unlocked."
        result = check_x_style(draft)
        assert result["pass"] is True
        unlocks = [
            v["phrase"] for v in result["soft_violations"] if v["phrase"] == "unlock"
        ]
        # 'unlock' should NOT match 'unlocked' — word boundary protects.
        assert unlocks == []


class TestCleanDraftPasses:
    """Real CT-voice drafts from the agent's own knowledge log that
    earned positive feedback. These must pass cleanly — otherwise the
    preflight is over-aggressive and will block legit posts."""

    @pytest.mark.parametrize(
        "draft",
        [
            (
                "btc etf flows finally coughed up a real number: "
                "~$635m out on may 13, worst day in months."
            ),
            (
                "fee token choice sounds boring until lp pnl stops "
                "arriving as a bag of leftovers."
            ),
            (
                "telegram won because crypto optimizes for chaos: "
                "fast groups, throwaway handles, and zero procurement."
            ),
            "privacy before pmf sounds like homework.",
            (
                "yeah, this is the good kind of messy. public founder "
                "arguments beat polished foundation theater every time."
            ),
        ],
    )
    def test_real_ct_draft_passes(self, draft: str) -> None:
        result = check_x_style(draft)
        assert (
            result["pass"] is True
        ), f"draft should pass but hit: {result['hard_violations']}"


class TestXStylePreflightTool:
    @pytest.mark.asyncio
    async def test_tool_returns_pass_for_clean_draft(self) -> None:
        tool = XStylePreflightTool()
        result = await tool.execute(
            {"text": "btc finally caught a bid; funding still muted."}
        )
        assert result.success is True
        assert result.data["pass"] is True
        assert result.data["hard_violations"] == []

    @pytest.mark.asyncio
    async def test_tool_returns_violation_list(self) -> None:
        tool = XStylePreflightTool()
        result = await tool.execute({"text": "as an ai, i can help you understand."})
        assert result.success is True  # tool itself succeeds
        assert result.data["pass"] is False
        hits = {v["phrase"] for v in result.data["hard_violations"]}
        assert "as an ai" in hits
        assert "i can help" in hits

    @pytest.mark.asyncio
    async def test_tool_rejects_non_string(self) -> None:
        tool = XStylePreflightTool()
        result = await tool.execute({"text": None})  # type: ignore[dict-item]
        # None coerces to "" via tool's `or ""` guard — passes empty.
        assert result.success is True
        assert result.data["pass"] is True


class TestTwitterPostHook:
    """The actual enforcement gate: twitter_post must refuse to send
    when the content contains a hard violation."""

    @pytest.mark.asyncio
    async def test_twitter_post_refuses_on_hard_violation(self) -> None:
        from tools.publishing.twitter_tool import TwitterPostTool

        tool = TwitterPostTool()
        # Stub the browser so we know any execution past the preflight
        # would fail with a different error than ours — proves the
        # preflight is what blocked it.
        tool._browser_manager = object()  # truthy non-None
        result = await tool.execute(
            {"content": "as an ai agent, i'd recommend the future of."}
        )
        assert result.success is False
        assert "x_style_preflight failed" in (result.error or "")
        assert "as an ai" in (result.error or "")
        # Data carries the structured violation list for downstream
        # tools / logs.
        assert result.data and "style_violations" in result.data

    @pytest.mark.asyncio
    async def test_twitter_post_allows_clean_draft(self) -> None:
        """A clean draft gets past preflight and fails on the next
        check (browser unavailable in this test) — proves preflight
        isn't blocking legitimate posts."""
        from tools.publishing.twitter_tool import TwitterPostTool

        tool = TwitterPostTool()
        tool._browser_manager = None  # forces the next check to fail
        result = await tool.execute(
            {"content": "btc still bleeding into the close, nothing new."}
        )
        # Preflight didn't fire; the *next* check (browser missing) did.
        assert result.success is False
        assert "Browser not available" in (result.error or "")
