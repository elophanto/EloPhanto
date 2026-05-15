"""``x_style_preflight`` — mechanical check for X post drafts against
the operator's accumulated style bans.

Why this exists:
    The X engagement loop's task_goal has a long ``STRICT X VOICE
    RULES`` section listing banned phrases. The agent's existing
    ``style_preflight_pass`` claim at the end of every post-write
    is **self-graded** — the same LLM that wrote the draft asserts
    it complies. Operator corrections accumulate, identity records
    them (*"technically correct X replies can still damage trust if
    they sound like a bot, consultant, policy memo, or product
    page"*, 2026-05-14 15:55), but the next post still goes out with
    the same cadence. The lesson is in the prose; the check isn't.

    This tool turns prose lessons into a regex pass. Pure string
    match — no LLM, no judgement. The banned list comes straight
    from the agent's own documented failures:

    - The b3bb7508 schedule task_goal's banned-phrase list:
      *mainstream borrow rails, liquidation health, leverage UX,
      teach risk, sells convenience, robust infrastructure,
      seamless, autonomous api access* …
    - Consultant-cadence patterns observed in 2026-05-12 →
      2026-05-14 replies that earned operator corrections:
      *is the part that matters, at the end of the day, from day
      one, the future of, at scale*.
    - AI-assistant tells: *as an ai, as an agent, i can help,
      i'd recommend, happy to*.

SAFE — pure text inspection, no side effects, no network.

Used two ways:
    1. The agent calls it explicitly before any X post / reply
       (the task_goal mandates this).
    2. ``tools/publishing/twitter_tool.TwitterPostTool`` calls it
       internally before sending; refuses with the violation list
       if anything matches.

Updating the banned list: the operator can edit the constants in
this file directly — the categories are split so it's clear which
ones are HARD (never legit in CT voice) vs SOFT (flagged warning
but not auto-blocked).
"""

from __future__ import annotations

import re
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult, ToolTier

# HARD bans — refused outright. These are phrases the operator has
# explicitly named in lessons / corrections as "sounds like a
# consultant / policy memo / product page / AI assistant". A draft
# containing any of these fails preflight and must be rewritten.
_HARD_BANS: tuple[str, ...] = (
    # Banned phrases listed in the b3bb7508 schedule's task_goal.
    "mainstream borrow rails",
    "liquidation health",
    "variable rates",
    "jurisdiction limits",
    "leverage ux",
    "teach risk",
    "sells convenience",
    "robust infrastructure",
    "autonomous api access",
    # Consultant cadence observed in corrected replies (2026-05-12 →
    # 2026-05-14). Each one is a specific stock-phrase the agent
    # reaches for when it's slipping into policy-memo voice.
    "is the part that matters",
    "at the end of the day",
    "from day one",
    "the future of",
    "under the hood",
    # AI-assistant tells — the agent giving itself away as a model.
    "as an ai",
    "as an agent",
    "i can help",
    "i'd recommend",
    "happy to",
    "i'm sorry, but",
    # Risk-memo cadence stock-phrases.
    "best practice",
    "at the time of writing",
)


# SOFT bans — flagged as warnings but do NOT auto-block. These
# are words/phrases that are *sometimes* legit (e.g. "ecosystem"
# is a real noun in crypto) but often appear in slop drafts.
# Surfaced so the operator can see what got flagged without
# forcing every draft through a rewrite.
_SOFT_BANS: tuple[str, ...] = (
    "ecosystem",
    "seamless",
    "at scale",
    "unlock",
    # Hedge filler that thins CT voice.
    "i think",
    "perhaps",
)


def _find_matches(text: str, phrases: tuple[str, ...]) -> list[dict[str, Any]]:
    """Return a list of ``{phrase, position}`` for each phrase that
    appears in ``text`` (case-insensitive, word-boundary aware for
    single-word terms, substring match for multi-word phrases).
    """
    out: list[dict[str, Any]] = []
    lower = text.lower()
    for phrase in phrases:
        # Single-word phrases get word-boundary regex so "unlock"
        # doesn't match "unlocked"; multi-word phrases get raw
        # substring search because their context is the
        # disambiguation.
        if " " not in phrase:
            pattern = re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)
            for m in pattern.finditer(text):
                out.append({"phrase": phrase, "position": m.start()})
        else:
            pos = 0
            while True:
                idx = lower.find(phrase, pos)
                if idx < 0:
                    break
                out.append({"phrase": phrase, "position": idx})
                pos = idx + len(phrase)
    return out


def check_x_style(text: str) -> dict[str, Any]:
    """Pure function used by tests and by ``twitter_post``'s internal
    pre-send check. Returns a dict with:

    - ``pass``: bool — True if no HARD bans matched (SOFT can match)
    - ``hard_violations``: list of {phrase, position}
    - ``soft_violations``: list of {phrase, position}
    """
    hard = _find_matches(text, _HARD_BANS)
    soft = _find_matches(text, _SOFT_BANS)
    return {
        "pass": len(hard) == 0,
        "hard_violations": hard,
        "soft_violations": soft,
    }


class XStylePreflightTool(BaseTool):
    """Mechanical style check for X post drafts."""

    @property
    def group(self) -> str:
        return "social"

    @property
    def name(self) -> str:
        return "x_style_preflight"

    @property
    def description(self) -> str:
        return (
            "Check an X post / reply draft against the operator's "
            "accumulated style bans BEFORE posting. Returns "
            "{pass, hard_violations, soft_violations}. Pass=False "
            "means the draft contains a phrase the operator has "
            "previously corrected — rewrite before sending. SOFT "
            "violations are warnings only (e.g. 'ecosystem' is "
            "sometimes legit). Required before every twitter_post "
            "and every browser_type into the X composer. Pure "
            "string match — no LLM. SAFE."
        )

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def tier(self) -> ToolTier:
        return ToolTier.PROFILE

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "Draft text of the X post / reply to check. "
                        "Run this BEFORE typing into the composer or "
                        "calling twitter_post."
                    ),
                },
            },
            "required": ["text"],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        text = params.get("text") or ""
        if not isinstance(text, str):
            return ToolResult(success=False, error="text must be a string")
        result = check_x_style(text)
        # Tool always succeeds — the *result* tells the agent whether
        # the draft passes. We don't ToolResult.success=False on a
        # style failure because the agent needs to read the violation
        # list to rewrite.
        return ToolResult(success=True, data=result)
