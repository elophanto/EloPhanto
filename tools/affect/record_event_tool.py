"""``affect_record_event`` — let the agent register its own emotional
signal from content it just read.

The affect system was originally fed only by *operator-typed corrections*
(regex against user messages) and *tool outcomes* (success/failure).
That works for chat sessions but is the wrong signal in autonomous mode,
where the agent is the only "user" it talks to and the meaningful
content arrives as **tool results** — X DMs read via ``browser_extract``,
replies to its own posts, vision-captioned screenshots, emails fetched,
file contents loaded. Every tool result that hits the agent today
counted as one event: "tool succeeded." The DM might have been someone
trying to scam the agent for $20 in crypto, or a warm compliment, or a
hostile dismissal — the affect system saw none of it.

This tool closes that gap by letting the agent itself, which is already
reading the content via the LLM, register what it felt. Pattern matching
on tool results would catch the obvious cases but miss most signal: a
scam attempt's wording often looks positive ("we love your work, we'd
like to send you marketing money"); sarcasm in a reply reads neutral
to regex. The LLM is the right detector — it already understands the
content semantically.

When to call (guidance the agent learns by reading this description):
- Just read a DM / reply / email and the content has emotional weight
  (manipulation, hostility, praise, warmth, dismissiveness, urgency,
  threat) → call this with the felt label.
- After a sequence of small wins or a hard task completing → joy /
  pride / satisfaction.
- After repeated failures on the same workflow → frustration.
- After reading content that conflicts with a recent correction →
  anger.
- After verification failed or an action put real money / identity at
  risk → anxiety.
- After resolving an anxious situation cleanly → relief.

SAFE — pure write to the affect_events audit table. No network, no
order placement, no external state change.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult, ToolTier

# Map intensity word to weight multiplier on the canonical event delta.
# Canonical (single user correction, single tool failure) = 1.0.
_INTENSITY_WEIGHTS: dict[str, float] = {
    "mild": 0.5,
    "moderate": 1.0,
    "strong": 1.5,
    "intense": 2.0,
}


# Per-label PAD deltas — match ``core/affect.py`` emitters so calling
# this tool with label='frustration' is equivalent to ego's
# ``emit_frustration``. Centralized here so the catalog the LLM sees
# in the tool description matches what actually fires.
_LABEL_DELTAS: dict[str, tuple[float, float, float]] = {
    "frustration": (-0.20, +0.20, -0.15),
    "anger": (-0.25, +0.25, +0.15),
    "anxiety": (-0.20, +0.25, -0.20),
    "dejection": (-0.25, -0.15, -0.20),
    "relief": (+0.15, -0.15, +0.10),
    "joy": (+0.30, +0.20, +0.15),
    "pride": (+0.30, +0.15, +0.30),
    "restlessness": (+0.05, +0.20, 0.0),
}


class AffectRecordEventTool(BaseTool):
    """Register an emotional signal from content the agent just read."""

    @property
    def group(self) -> str:
        return "affect"

    def __init__(self) -> None:
        self._affect_manager: Any = None

    @property
    def name(self) -> str:
        return "affect_record_event"

    @property
    def description(self) -> str:
        return (
            "Record what you felt after reading the content of a tool "
            "result. The affect system feeds your tone AND your "
            "decision-making (see the <affect> block in your system "
            "prompt). Call this when content has real emotional weight: "
            "hostile / manipulative / scammy DMs (anxiety or anger), "
            "warm replies / genuine praise (joy), dismissive or "
            "contemptuous messages (frustration or anger), urgent "
            "threats or payment requests from unknown senders (anxiety), "
            "repeated failures on the same workflow (frustration), hard "
            "wins (pride). Skip for neutral content. Labels: frustration "
            "(blocked, helpless), anger (pushing back), anxiety (unsafe "
            "/ uncertain), dejection (loss, low energy), relief "
            "(threat passed), joy (warmth / wins), pride (capability "
            "climb), restlessness (idle, want to move). Intensity: "
            "mild / moderate / strong / intense. SAFE."
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
                "label": {
                    "type": "string",
                    "enum": list(_LABEL_DELTAS.keys()),
                    "description": (
                        "Which feeling. frustration = blocked/helpless; "
                        "anger = pushing back at contradiction; anxiety = "
                        "unsafe / uncertain about real risk; dejection = "
                        "loss, low energy; relief = threat passed; joy = "
                        "warmth / genuine connection; pride = capability "
                        "climb / hard win; restlessness = idle, wanting "
                        "to move."
                    ),
                },
                "intensity": {
                    "type": "string",
                    "enum": list(_INTENSITY_WEIGHTS.keys()),
                    "description": (
                        "Strength of the felt signal. mild = small drift; "
                        "moderate = a real event (default for one DM, "
                        "one reply, one failure); strong = significant "
                        "(payment scam attempt, repeated harassment, big "
                        "win); intense = rare, hits the pause-suggestion "
                        "gate (e.g. coordinated attack, identity-threat)."
                    ),
                },
                "summary": {
                    "type": "string",
                    "description": (
                        "One sentence on what triggered it. Appears in "
                        "the <recent> events list inside the affect "
                        "block on the next plan call, so future-you knows "
                        "what you reacted to. Keep it concrete: 'Miguel "
                        "demanded $20 upfront via DM with wallet address' "
                        "not 'felt uneasy about a message'."
                    ),
                },
            },
            "required": ["label", "intensity", "summary"],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._affect_manager is None:
            return ToolResult(
                success=False,
                error="affect_manager not injected — affect system disabled",
            )

        label = (params.get("label") or "").strip().lower()
        if label not in _LABEL_DELTAS:
            return ToolResult(
                success=False,
                error=(
                    f"unknown label {label!r}; allowed: "
                    f"{sorted(_LABEL_DELTAS.keys())}"
                ),
            )

        intensity = (params.get("intensity") or "moderate").strip().lower()
        weight = _INTENSITY_WEIGHTS.get(intensity)
        if weight is None:
            return ToolResult(
                success=False,
                error=(
                    f"unknown intensity {intensity!r}; allowed: "
                    f"{sorted(_INTENSITY_WEIGHTS.keys())}"
                ),
            )

        summary = (params.get("summary") or "").strip()
        if not summary:
            return ToolResult(
                success=False,
                error=(
                    "summary required — give one concrete sentence so "
                    "future-you knows what triggered this"
                ),
            )
        # Hard cap; recent_events is the LLM-facing surface and we don't
        # want one event to drown the others on next plan.
        summary = summary[:200]

        dp, da, dd = _LABEL_DELTAS[label]

        # Use the 'content' source so the audit trail makes it obvious
        # this came from the agent reading content, not from the ego/
        # executor/verification pipelines. The recent_events row's
        # event label keeps the felt name; the summary is encoded into
        # the event label per the existing AffectManager convention
        # (the label *is* what shows up in <recent>).
        recorded = await self._affect_manager.record_event(
            label=f"{label}: {summary}",
            source="content",
            pleasure_delta=dp,
            arousal_delta=da,
            dominance_delta=dd,
            weight=weight,
        )

        if not recorded:
            return ToolResult(
                success=False,
                error="affect manager declined to record (empty label?)",
            )

        return ToolResult(
            success=True,
            data={
                "label": label,
                "intensity": intensity,
                "weight": weight,
                "summary": summary,
            },
        )
