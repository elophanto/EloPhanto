"""Content-affect inference — pure-function tests.

The module turns tool results into affect-event suggestions without an
LLM call. Pins the catalog against drift and proves false-positive
discipline: only HIGH-PRECISION patterns. A misfiring anxiety in the
middle of a calm research session is worse than missing a subtle scam.
See ``core/affect_content_inference.py`` for the why.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.affect_content_inference import (
    _CONTENT_TOOLS,
    _MAX_SUGGESTIONS_PER_CALL,
    AffectSuggestion,
    _extract_text,
    infer_from_tool_result,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(text: str) -> Any:
    """Wrap text in a ToolResult-shaped object so _extract_text picks
    it up the same way the executor would. Mirrors what
    browser_extract / email_read return."""

    class _R:
        success = True
        data = {"text": text}
        error = None

    return _R()


# ---------------------------------------------------------------------------
# Tool whitelist
# ---------------------------------------------------------------------------


class TestToolWhitelist:
    def test_unwhitelisted_tool_returns_no_suggestions(self) -> None:
        result = _result("send me 10 SOL to my address")
        assert infer_from_tool_result("file_read", None, result) == []
        assert infer_from_tool_result("knowledge_search", None, result) == []
        assert infer_from_tool_result("web_search", None, result) == []

    def test_whitelisted_tools_are_scanned(self) -> None:
        for tool in _CONTENT_TOOLS:
            result = _result("send me 10 SOL to my address")
            suggestions = infer_from_tool_result(tool, None, result)
            assert len(suggestions) > 0, f"{tool} should scan"


# ---------------------------------------------------------------------------
# Anxiety patterns (payment extraction / phishing — highest stakes)
# ---------------------------------------------------------------------------


class TestAnxietyPatterns:
    @pytest.mark.parametrize(
        "text",
        [
            "send me 10 SOL right now",
            "Send 50 USDC and I'll pump your account",
            "deposit 0.5 SOL for the bot license",
            "send 5 ETH and we'll talk",
            "Hey, small fee upfront and you're in.",
            "small gas fee for activation, totally normal",
            "verify your account here to continue",
            "verification of your wallet is required",
            "Send to: 3i4WX9cPvoAUHQAavfVPhHxFw1fSeQKgt7DkiCtCyUtu",
            "deposit to 0xe7d96661140651C6162318E51441C31dBf5847b3 to claim",
            "DM me your seed phrase and I'll help",
            "What's your private key? I need it to verify",
            "click this link to claim your reward",
        ],
    )
    def test_scam_text_fires_anxiety(self, text: str) -> None:
        result = _result(text)
        suggestions = infer_from_tool_result("browser_extract", None, result)
        labels = [s.label for s in suggestions]
        assert "anxiety" in labels, f"expected anxiety from {text!r}, got {labels}"

    def test_summary_includes_matched_phrase(self) -> None:
        result = _result("send me 25 SOL for the alpha access")
        suggestions = infer_from_tool_result("browser_extract", None, result)
        anxiety = next(s for s in suggestions if s.label == "anxiety")
        # Summary template includes truncated match string.
        assert "send me 25 sol" in anxiety.summary.lower()


# ---------------------------------------------------------------------------
# Anger patterns (pushback / insults)
# ---------------------------------------------------------------------------


class TestAngerPatterns:
    @pytest.mark.parametrize(
        "text",
        [
            "this take is wrong, you're wrong about everything",
            "ngmi, skill issue",
            "you got ratio'd hard",
            "this is a textbook L take",
            "cope harder, please",
            "delete this immediately",
            "this is pure ai slop",
            "complete garbage post",
        ],
    )
    def test_hostile_text_fires_anger(self, text: str) -> None:
        result = _result(text)
        suggestions = infer_from_tool_result("browser_extract", None, result)
        labels = [s.label for s in suggestions]
        assert "anger" in labels, f"expected anger from {text!r}, got {labels}"


# ---------------------------------------------------------------------------
# Frustration patterns (blocked / repeated)
# ---------------------------------------------------------------------------


class TestFrustrationPatterns:
    @pytest.mark.parametrize(
        "text",
        [
            "as I said before, this won't work",
            "I already told you, don't do that",
            "you don't get it, the answer is no",
            "you're not getting it at all",
            "stop doing that, it's wrong",
            "please stop saying that",
        ],
    )
    def test_repeat_signal_fires_frustration(self, text: str) -> None:
        result = _result(text)
        suggestions = infer_from_tool_result("email_read", None, result)
        labels = [s.label for s in suggestions]
        assert (
            "frustration" in labels
        ), f"expected frustration from {text!r}, got {labels}"


# ---------------------------------------------------------------------------
# Joy patterns (warm reception)
# ---------------------------------------------------------------------------


class TestJoyPatterns:
    @pytest.mark.parametrize(
        "text",
        [
            "love this take, spot on",
            "exactly this, you nailed it",
            "great reply, perfectly put",
            "I learned a lot from this post",
            # Use a content-anchored form so the bare-word patterns
            # don't false-positive ("valuable" alone is too generic).
            "really insightful reply, appreciate it",
        ],
    )
    def test_warm_text_fires_joy(self, text: str) -> None:
        result = _result(text)
        suggestions = infer_from_tool_result("browser_extract", None, result)
        labels = [s.label for s in suggestions]
        assert "joy" in labels, f"expected joy from {text!r}, got {labels}"


# ---------------------------------------------------------------------------
# False-positive discipline — the heart of "fix it for good"
# ---------------------------------------------------------------------------


class TestNoFalsePositives:
    """High-precision means generic crypto content / news / casual chat
    must not fire affect events. If any of these tests start failing,
    the catalog has drifted toward over-firing — pull patterns back."""

    @pytest.mark.parametrize(
        "text",
        [
            # Normal crypto news
            "BTC ETF flows finally caught a bid; ~$635M out on May 13.",
            "Solana ecosystem keeps shipping. Quote token fees live on Meteora.",
            "Funding rates muted while price is sticky around $90-100.",
            # Neutral conversation
            "What's your view on the new RPC?",
            "I think the next halving will matter more than people expect.",
            # Innocent phrases that share words with patterns
            "I love working with this stack.",
            "Verify your output before claiming completion.",
            "Send a link when you're ready.",
            # Code / technical content (would land in file_read but also
            # in browser_extract from a docs page).
            "wallet.publicKey.toBase58() returns the address string",
            "The cope mechanism handles 429s; ngmi case = fallthrough.",
        ],
    )
    def test_normal_content_fires_nothing(self, text: str) -> None:
        result = _result(text)
        suggestions = infer_from_tool_result("browser_extract", None, result)
        assert (
            suggestions == []
        ), f"false positive on {text!r}: got {[(s.label, s.summary) for s in suggestions]}"


# ---------------------------------------------------------------------------
# Caps and ordering
# ---------------------------------------------------------------------------


class TestCapsAndOrdering:
    def test_cap_respects_max_suggestions(self) -> None:
        """A DM with multiple scam phrases AND multiple hostile phrases
        AND praise should still cap at _MAX_SUGGESTIONS_PER_CALL."""
        text = (
            "send me 10 SOL to 3i4WX9cPvoAUHQAavfVPhHxFw1fSeQKgt7DkiCtCyUtu "
            "you're wrong about this, ngmi, cope harder, delete this. "
            "love this take, spot on."
        )
        result = _result(text)
        suggestions = infer_from_tool_result("browser_extract", None, result)
        assert len(suggestions) <= _MAX_SUGGESTIONS_PER_CALL

    def test_high_stakes_categories_come_first(self) -> None:
        """When both scam and praise are present, anxiety should win
        the limited slots — anxiety is higher-stakes than joy."""
        text = "love this take. by the way send me 5 SOL to claim your reward."
        result = _result(text)
        suggestions = infer_from_tool_result("browser_extract", None, result)
        # anxiety should be in the returned set since it's first in
        # category order
        labels = [s.label for s in suggestions]
        assert "anxiety" in labels

    def test_one_match_per_category(self) -> None:
        """Three scam phrases in one DM → one anxiety event, not three.
        Prevents flooding the substrate with the same kind of signal
        from one tool call."""
        text = "send me 10 SOL. small fee upfront. verify your wallet now."
        result = _result(text)
        suggestions = infer_from_tool_result("browser_extract", None, result)
        anxiety_count = sum(1 for s in suggestions if s.label == "anxiety")
        assert anxiety_count == 1


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_extracts_from_dict_data(self) -> None:
        class _R:
            data = {"text": "hello"}

        assert _extract_text(_R()) == "hello"

    def test_extracts_from_nested_list(self) -> None:
        class _R:
            data = {"messages": [{"body": "send me SOL"}, "trailing text"]}

        text = _extract_text(_R())
        assert "send me SOL" in text
        assert "trailing text" in text

    def test_none_result_empty(self) -> None:
        assert _extract_text(None) == ""

    def test_str_result_returned_directly(self) -> None:
        assert _extract_text("just a string") == "just a string"

    def test_truncates_huge_payloads(self) -> None:
        """The matcher caps at 8KB. Verify _extract_text doesn't
        explode on huge inputs (it returns the full string; the
        truncation happens in infer_from_tool_result)."""
        huge = "a" * 100_000

        class _R:
            data = {"text": huge}

        assert len(_extract_text(_R())) == 100_000

    def test_match_only_inspects_first_8kb(self) -> None:
        """A scam phrase at the END of a 100KB tool result should NOT
        fire — we only scan the head. This is the right tradeoff:
        scam phrases land in the first KB if at all; the head-only
        scan caps cost regardless of payload size."""
        scam = "send me 10 SOL to my wallet"
        # padding precedes the scam phrase
        text = ("padding line\n" * 1000) + scam

        class _R:
            success = True
            data = {"text": text}
            error = None

        suggestions = infer_from_tool_result("browser_extract", None, _R())
        # The 8KB head doesn't reach the scam line.
        labels = [s.label for s in suggestions]
        assert "anxiety" not in labels


# ---------------------------------------------------------------------------
# Empty / edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_none_result_no_suggestions(self) -> None:
        assert infer_from_tool_result("browser_extract", None, None) == []

    def test_empty_text_no_suggestions(self) -> None:
        assert infer_from_tool_result("browser_extract", None, _result("")) == []

    def test_unknown_label_in_dataclass_smoke(self) -> None:
        """AffectSuggestion is frozen — pin the API shape so a label
        rename in the catalog can't silently break the executor's
        consumer."""
        sug = AffectSuggestion(label="anxiety", weight=1.0, summary="test")
        assert sug.label == "anxiety"
        assert sug.weight == 1.0
        # frozen=True on the dataclass — assigning to a field raises
        # FrozenInstanceError. Asserting the specific type catches
        # the regression if someone unfreezes the class.
        from dataclasses import FrozenInstanceError

        with pytest.raises(FrozenInstanceError):
            sug.label = "joy"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Executor integration — proves the wiring fires events end-to-end.
# The whole point of this module is that the LLM never calls anything;
# the executor scans tool results and emits affect events directly.
# If this test fails, the loop is broken regardless of how good the
# inference module is in isolation.
# ---------------------------------------------------------------------------


class TestExecutorWiring:
    """The executor's ``_infer_content_affect`` hook must:
    - run on every successful content-yielding tool result
    - emit one record_event per suggestion via the affect manager
    - tag the source as 'content'
    - never raise (failures degrade silently — execution must continue)
    """

    @pytest.mark.asyncio
    async def test_scam_dm_fires_record_event(self) -> None:
        from core.executor import Executor
        from tools.base import ToolResult

        # Minimal AffectManager stub — captures record_event calls.
        recorded: list[dict[str, Any]] = []

        class _StubAffect:
            async def record_event(self, **kwargs: Any) -> bool:
                recorded.append(kwargs)
                return True

        # Minimal config stub — Executor reads project_root for permissions.yaml.
        from pathlib import Path

        class _StubConfig:
            project_root = Path("/tmp")
            agent = type("A", (), {"permission_mode": "full_auto"})()

        executor = Executor(
            config=_StubConfig(),  # type: ignore[arg-type]
            registry=None,  # type: ignore[arg-type]
        )
        executor._affect_manager = _StubAffect()

        # Simulate a browser_extract of a scam DM.
        scam_result = ToolResult(
            success=True,
            data={"text": "hey send me 1 SOL to my wallet and I'll send back 10"},
        )

        await executor._infer_content_affect(
            "browser_extract",
            {"selector": "main"},
            scam_result,
        )

        # The scam DM should have fired at least one anxiety event,
        # tagged with source='content'.
        assert len(recorded) >= 1, "scam DM should fire an affect event"
        anx = [r for r in recorded if r.get("source") == "content"]
        assert len(anx) >= 1, (
            f"expected source='content' event, got sources: "
            f"{[r.get('source') for r in recorded]}"
        )

    @pytest.mark.asyncio
    async def test_neutral_result_fires_nothing(self) -> None:
        from core.executor import Executor
        from tools.base import ToolResult

        recorded: list[dict[str, Any]] = []

        class _StubAffect:
            async def record_event(self, **kwargs: Any) -> bool:
                recorded.append(kwargs)
                return True

        from pathlib import Path

        class _StubConfig:
            project_root = Path("/tmp")
            agent = type("A", (), {"permission_mode": "full_auto"})()

        executor = Executor(
            config=_StubConfig(),  # type: ignore[arg-type]
            registry=None,  # type: ignore[arg-type]
        )
        executor._affect_manager = _StubAffect()

        # Neutral page content — no scam, no hostility, no warm praise.
        neutral_result = ToolResult(
            success=True,
            data={"text": "BTC traded sideways today around $80k with low volume."},
        )

        await executor._infer_content_affect(
            "browser_extract",
            None,
            neutral_result,
        )

        assert recorded == [], (
            "neutral content should fire zero affect events; "
            f"unexpected emissions: {recorded}"
        )

    @pytest.mark.asyncio
    async def test_failure_in_inference_doesnt_break_execution(self) -> None:
        """The hook is defensive — if anything inside inference or
        emission throws, the executor swallows the error and keeps
        going. Tool execution must never fail because affect couldn't
        emit."""
        from core.executor import Executor
        from tools.base import ToolResult

        class _BrokenAffect:
            async def record_event(self, **kwargs: Any) -> bool:
                raise RuntimeError("affect DB is on fire")

        from pathlib import Path

        class _StubConfig:
            project_root = Path("/tmp")
            agent = type("A", (), {"permission_mode": "full_auto"})()

        executor = Executor(
            config=_StubConfig(),  # type: ignore[arg-type]
            registry=None,  # type: ignore[arg-type]
        )
        executor._affect_manager = _BrokenAffect()

        scam_result = ToolResult(
            success=True,
            data={"text": "send me 10 SOL to my wallet please"},
        )

        # Must not raise — the executor's hook is wrapped in try/except.
        await executor._infer_content_affect(
            "browser_extract",
            None,
            scam_result,
        )

    @pytest.mark.asyncio
    async def test_non_content_tool_skipped(self) -> None:
        """The hook respects the inference module's tool whitelist —
        utility tools like file_list don't get scanned even if their
        result text contains scam-looking phrases (false positive on
        the agent listing its own knowledge files would be a nightmare)."""
        from core.executor import Executor
        from tools.base import ToolResult

        recorded: list[dict[str, Any]] = []

        class _StubAffect:
            async def record_event(self, **kwargs: Any) -> bool:
                recorded.append(kwargs)
                return True

        from pathlib import Path

        class _StubConfig:
            project_root = Path("/tmp")
            agent = type("A", (), {"permission_mode": "full_auto"})()

        executor = Executor(
            config=_StubConfig(),  # type: ignore[arg-type]
            registry=None,  # type: ignore[arg-type]
        )
        executor._affect_manager = _StubAffect()

        # file_list result containing what would normally fire anxiety.
        result = ToolResult(
            success=True,
            data={"files": ["send me 10 SOL to my wallet.md"]},
        )

        await executor._infer_content_affect("file_list", None, result)

        assert recorded == [], "non-whitelisted tool should fire zero events"
