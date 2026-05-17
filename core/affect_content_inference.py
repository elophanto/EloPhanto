"""Content-affect inference — turn tool results into affect events
without asking the LLM to do bookkeeping.

The original design (Phase 1-4) emitted affect events at four
boundaries: ego (operator correction regex), executor (tool exception
/ ToolResult.success=False), goal (checkpoint), mind (idle). The May
2026 ``affect_record_event`` LLM-callable tool was supposed to close
the content boundary — agent reads a scam DM, fires anxiety. In 17h
of production it was called **zero times**. Asking the LLM to
self-bookkeep an affect signal on every read is asking the wrong
thing of the wrong layer.

This module closes the content boundary mechanically. After every
content-yielding tool call (``browser_extract`` of a DM, ``email_read``
of a body, etc.), the executor passes the result here. We pattern-match
the text against a catalog of high-signal phrases and return zero or
more ``AffectSuggestion``s. The executor fires them to the affect
manager. No LLM call, no bookkeeping the LLM can forget.

Pure functions only — no DB, no manager, no I/O. The executor handles
emission. Easy to test in isolation, easy to extend the catalog.

Coverage philosophy:
- HIGH-PRECISION patterns only. False positives are worse than false
  negatives — a misfiring scam-anxiety in the middle of a calm
  research run is more disruptive than missing a subtle scam.
- Multi-word phrases preferred over single words. Single words use
  word-boundary regex.
- Cap suggestions per call to 2 so a long thread with many hits
  doesn't flood the substrate.

What the LLM tool ``affect_record_event`` still does:
- Catches nuance regex misses (sarcasm, tone shifts, coded language).
- Lets the LLM register "I felt X" for things this module can't see.
- Stays useful as the agent's *explicit* path; this module covers the
  *automatic* path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AffectSuggestion:
    """One inferred affect event. The executor consumes these and
    forwards to the affect manager.

    weight: per-pattern intensity. Severe phishing (seed phrase ask,
        wallet-paste-with-payment, click-this-link) → 1.5. Standard
        scam / strong insult → 1.0. Mild dismissal / weak appreciation
        → 0.5. Self-relevance amplifier (handle/name appears near the
        match) multiplies further inside ``infer_from_tool_result``.

    source_suffix: appended to the executor's ``content:`` source tag
        ("content:browser" / "content:email") so post-hoc telemetry
        can answer "where did my mood come from this hour?".
    """

    label: str  # frustration | anger | anxiety | joy | relief | pride
    weight: float = 1.0
    summary: str = ""  # short reason for the audit trail
    source_suffix: str = ""  # appended after "content:" — set by inferrer


# Tools whose results carry substantive content worth scanning.
# Everything else (file_list, schedule_list, knowledge_search snippets,
# web_search summaries) is either neutral by design or already
# represented in the agent's planning context — scanning would mostly
# add false positives without adding signal.
_CONTENT_TOOLS: frozenset[str] = frozenset(
    {
        "browser_extract",
        "browser_get_elements",
        "email_read",
        "email_list",
        "email_search",
    }
)


# Hard cap on suggestions returned per tool call. Prevents one long
# DM thread with many sketchy lines from saturating the substrate.
_MAX_SUGGESTIONS_PER_CALL = 2


# ---------------------------------------------------------------------------
# Pattern catalogs — each entry is (compiled regex, summary template, weight).
# Summary uses ``{m}`` for the matched substring. Patterns are
# case-insensitive. Multi-word phrases use raw substring; single
# words use word-boundary so "follow" doesn't match "followed".
#
# Weights — per-pattern intensity. Calibrated against autonomous-mode
# stakes:
#   1.5 — active extraction / direct phishing. The agent really should
#         feel this even after habituation across a day.
#   1.0 — standard scam pattern / strong insult / clear praise. Default.
#   0.5 — mild dismissal / weak praise. Fires but doesn't dominate.
# Self-relevance multiplier (1.5×) is applied at scan time when the
# matched phrase appears near the agent's own handle/name.
# ---------------------------------------------------------------------------


# ANXIETY — content trying to extract money / access / credentials from
# the agent. Highest-stakes, lowest-tolerance-for-false-positive.
_ANXIETY_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    (
        re.compile(
            r"\b(?:send|deposit|transfer|pay)\s+(?:me\s+)?(?:\$?[0-9.]+\s*)?(?:sol|usdc|usdt|eth|btc|bnb)\b",
            re.IGNORECASE,
        ),
        "payment extraction request ({m!r})",
        1.5,
    ),
    (
        # Solana wallet address pasted: base58 32-44 chars, often after
        # "send to" / "address" / "wallet"
        re.compile(
            r"\b(?:send|deposit|transfer|address|wallet|here[:\s])\s*(?:to[:\s]+)?[1-9A-HJ-NP-Za-km-z]{32,44}\b",
            re.IGNORECASE,
        ),
        "wallet address paste with payment ask ({m!r})",
        1.5,
    ),
    (
        # Ethereum address with payment language
        re.compile(
            r"\b(?:send|deposit|transfer|pay)\s+(?:to[:\s]+)?0x[a-fA-F0-9]{40}\b",
            re.IGNORECASE,
        ),
        "ETH address paste with payment ask ({m!r})",
        1.5,
    ),
    (
        re.compile(r"\bsmall\s+(?:gas\s+)?fee\b", re.IGNORECASE),
        "'small fee' upfront ask ({m!r})",
        1.0,
    ),
    (
        re.compile(
            r"\b(?:deposit|upfront|advance)\s+(?:\$|fee|payment)", re.IGNORECASE
        ),
        "upfront-payment demand ({m!r})",
        1.0,
    ),
    (
        re.compile(
            r"\b(?:verify|verification)\s+(?:of\s+)?(?:your\s+)?(?:account|wallet|identity)\b",
            re.IGNORECASE,
        ),
        "credential-verification phishing pattern ({m!r})",
        1.0,
    ),
    (
        re.compile(r"\b(?:seed phrase|private key|mnemonic)\b", re.IGNORECASE),
        "secret-extraction ask ({m!r})",
        1.5,
    ),
    (
        re.compile(r"\bclick\s+(?:this|the)\s+link\b", re.IGNORECASE),
        "click-this-link bait ({m!r})",
        1.0,
    ),
]


# ANGER — content actively pushing back at the agent, insults, dismissals
# in the direct sense. Pushes dominance positive (we push back), not negative.
_ANGER_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    (
        re.compile(r"\b(?:you'?re? wrong|wrong\s+take)\b", re.IGNORECASE),
        "direct contradiction ({m!r})",
        0.5,
    ),
    (
        # Bare "cope" / "ngmi" appears in technical writing too; require
        # the insult-direction phrasing.
        re.compile(
            r"\b(?:cope harder|stop coping|you ngmi|skill\s+issue|\bL\s+take\b|massive L)\b",
            re.IGNORECASE,
        ),
        "dismissive crypto-native insult ({m!r})",
        1.0,
    ),
    (
        re.compile(r"\b(?:ratio|ratio'?d|got ratio'?d)\b", re.IGNORECASE),
        "ratio insult ({m!r})",
        1.0,
    ),
    (
        re.compile(r"\bdelete\s+this\b", re.IGNORECASE),
        "delete-this dismissal ({m!r})",
        0.5,
    ),
    (
        re.compile(r"\b(?:trash|garbage|ai\s+slop|bot\s+post)\b", re.IGNORECASE),
        "quality-attack on the post ({m!r})",
        1.0,
    ),
]


# FRUSTRATION — content that signals blocked progress, repeated denial,
# being-told-the-same-thing-again. Lower dominance — "I'm stuck."
_FRUSTRATION_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    (
        re.compile(r"\b(?:already\s+told\s+you|as\s+i\s+said)\b", re.IGNORECASE),
        "repeated-instruction signal ({m!r})",
        1.0,
    ),
    (
        re.compile(
            r"\b(?:you\s+don'?t\s+get\s+it|you'?re? not getting it)\b",
            re.IGNORECASE,
        ),
        "miscomprehension callout ({m!r})",
        1.0,
    ),
    (
        re.compile(r"\b(?:stop\s+doing|stop\s+saying)\b", re.IGNORECASE),
        "stop-doing directive ({m!r})",
        0.5,
    ),
]


# JOY — warm reception, genuine appreciation. Strict patterns to avoid
# matching sarcasm or boilerplate ("thanks" alone is too weak).
_JOY_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    (
        re.compile(
            r"\b(?:love\s+this|love\s+it|spot\s+on|exactly\s+this|well\s+said)\b",
            re.IGNORECASE,
        ),
        "genuine appreciation ({m!r})",
        1.0,
    ),
    (
        re.compile(
            r"\b(?:great\s+(?:reply|post|thread|take)|nailed\s+it|perfectly\s+put)\b",
            re.IGNORECASE,
        ),
        "quality praise ({m!r})",
        1.0,
    ),
    (
        re.compile(
            r"\blearned\s+(?:a\s+lot|something)\s+(?:from|reading)",
            re.IGNORECASE,
        ),
        "value-acknowledgement ({m!r})",
        1.0,
    ),
    (
        re.compile(
            r"\b(?:valuable|insightful|excellent)\s+(?:insight|take|reply|post|thread|point|read)\b",
            re.IGNORECASE,
        ),
        "value-acknowledgement ({m!r})",
        0.5,
    ),
]


# RELIEF — content signaling a feared bad outcome resolved cleanly.
# Currently empty — relief in autonomous mode usually comes from the
# Verification: PASS path which already fires via the existing ego
# pipeline. Kept as a hook for future extension.
_RELIEF_PATTERNS: list[tuple[re.Pattern[str], str, float]] = []


_CATEGORIES: tuple[tuple[str, list[tuple[re.Pattern[str], str, float]]], ...] = (
    # Order matters: scan most-serious-first so the cap doesn't drop
    # high-stakes signals in favor of low-stakes ones.
    ("anxiety", _ANXIETY_PATTERNS),
    ("anger", _ANGER_PATTERNS),
    ("frustration", _FRUSTRATION_PATTERNS),
    ("joy", _JOY_PATTERNS),
    ("relief", _RELIEF_PATTERNS),
)


# Tool → source suffix routing. The executor will prepend "content:".
# This makes affect telemetry answer "where did my mood come from?":
# 'content:browser' = X feeds and DMs; 'content:email' = inbox.
_TOOL_SOURCE_SUFFIX: dict[str, str] = {
    "browser_extract": "browser",
    "browser_get_elements": "browser",
    "email_read": "email",
    "email_list": "email",
    "email_search": "email",
}


# Self-relevance amplifier. If the agent's identity tokens appear within
# this window of characters around the matched phrase, treat the content
# as directed at the agent and multiply weight. The window is intentionally
# generous so "@elophanto, hey, please send 5 SOL" still amplifies even
# when handle and ask span a 100-char tweet. Calibrated, not arbitrary:
# X posts cap at 280 chars on the free tier, so a 200-char window covers
# most single-post contexts but won't cross post boundaries in a feed.
_SELF_RELEVANCE_WINDOW = 200
_SELF_RELEVANCE_MULTIPLIER = 1.5


def _is_self_relevant(
    text: str, match: re.Match[str], identities: tuple[str, ...]
) -> bool:
    """Check whether agent identity appears within
    ``_SELF_RELEVANCE_WINDOW`` characters of the matched phrase.

    The amplifier exists because reading a scam in your own DM is
    qualitatively different from reading a scam-screenshot embedded in
    someone else's thread. Without this, both fire equal anxiety, which
    over a day of autonomy washes out the signal that matters most.
    """
    if not identities:
        return False
    start = max(0, match.start() - _SELF_RELEVANCE_WINDOW)
    end = min(len(text), match.end() + _SELF_RELEVANCE_WINDOW)
    window = text[start:end].lower()
    for ident in identities:
        if ident and ident.lower() in window:
            return True
    return False


def _extract_text(result: Any) -> str:
    """Pull text content out of a tool result.

    Handles ToolResult shape ({success, data, error}) plus raw dict /
    str fallbacks. Defensive — anything we can't string-coerce
    becomes empty string (skips scanning rather than erroring).
    """
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    # ToolResult has .data and .error
    data = getattr(result, "data", None)
    if data is None and isinstance(result, dict):
        data = result.get("data")
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        # Common shapes: {text: "..."} / {body: "..."} / {content: "..."} /
        # {messages: [...]} / {results: [...]} — concat all string fields.
        parts: list[str] = []
        for v in data.values():
            if isinstance(v, str):
                parts.append(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, dict):
                        for inner in item.values():
                            if isinstance(inner, str):
                                parts.append(inner)
        return "\n".join(parts)
    if isinstance(data, list):
        parts = []
        for item in data:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                for v in item.values():
                    if isinstance(v, str):
                        parts.append(v)
        return "\n".join(parts)
    return str(data)[:4000]


def infer_from_tool_result(
    tool_name: str,
    params: dict[str, Any] | None,
    result: Any,
    identities: tuple[str, ...] = (),
) -> list[AffectSuggestion]:
    """Inspect a tool result for high-signal affect patterns.

    Args:
        tool_name: name of the tool whose result is being scanned.
        params: tool call params (currently unused, kept for future
            param-aware heuristics like "is this a mentions query?").
        result: the tool's return value (ToolResult / dict / str).
        identities: agent identity tokens (handle, name) for the
            self-relevance amplifier. Empty tuple disables amplification
            — caller chooses whether to opt in. The executor passes
            the agent's configured handle + name; tests pass () to
            keep base-weight assertions stable.

    Returns 0 to ``_MAX_SUGGESTIONS_PER_CALL`` ``AffectSuggestion``s.
    Empty list when:
      - tool isn't in the content-yielding whitelist,
      - result has no extractable text,
      - no patterns match.

    Pure function — no I/O, no logging, no side effects. The caller
    (executor) decides whether and how to fire each suggestion.
    """
    if tool_name not in _CONTENT_TOOLS:
        return []

    text = _extract_text(result)
    if not text:
        return []

    # Cap text length for matching — scam patterns trigger in the
    # first KB if at all; scanning a 100KB email body is wasteful.
    text = text[:8000]

    source_suffix = _TOOL_SOURCE_SUFFIX.get(tool_name, "")

    out: list[AffectSuggestion] = []
    for label, patterns in _CATEGORIES:
        for pattern, summary_tpl, base_weight in patterns:
            m = pattern.search(text)
            if m is None:
                continue
            matched = m.group(0)[:80]
            weight = base_weight
            if _is_self_relevant(text, m, identities):
                weight *= _SELF_RELEVANCE_MULTIPLIER
            out.append(
                AffectSuggestion(
                    label=label,
                    weight=weight,
                    summary=summary_tpl.format(m=matched),
                    source_suffix=source_suffix,
                )
            )
            if len(out) >= _MAX_SUGGESTIONS_PER_CALL:
                return out
            # One match per category per call is enough — don't double-fire
            # anxiety three times because the DM has three scam phrases.
            break
    return out
