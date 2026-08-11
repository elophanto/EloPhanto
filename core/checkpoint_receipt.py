"""Tool-grounded checkpoint receipt verification (fail closed).

A checkpoint may only complete when claims in ``success_criteria`` are
grounded in (a) the checkpoint's tool trail, or (b) an optional
system-of-record snippet. Quantitative claims without evidence fail.
This is NOT LLM-judges-LLM with zero tools.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Numbers that look like counts / money / percents in criteria.
_QUANT_RE = re.compile(
    r"(?i)(?:\d+\s*%|\$\s*\d|\b\d{1,6}\b.*(?:pre-?order|signup|user|sale|lead|"
    r"customer|commit|loi|pilot|order|click|star|follower))"
)
_NUMBER_RE = re.compile(r"\b(\d{1,7})\b")
# A percentage is a *proportion*, not a count, and cannot be checked by
# looking for its digits in the evidence. "A manifest covers 100% of
# discovered files" is satisfied by a trail reading "found 37 files, wrote
# 37 entries" — the digits 100 never appear anywhere. Counting percentages
# as counts made any criterion whose only number was a percentage
# unsatisfiable, so the checkpoint could never pass however well the agent
# did the work. Observed 2026-08-11: one goal spent three hours failing the
# same receipt, and escaped only by rewriting the criterion to drop the
# "100%" wording — routing around the gate rather than satisfying it.
_PERCENT_RE = re.compile(r"\d{1,3}(?:\.\d+)?\s*%")


@dataclass(frozen=True)
class ReceiptVerdict:
    ok: bool
    reason: str
    evidence: str = ""


def _flatten_tool_trail(tool_trace: list[dict[str, Any]] | None) -> str:
    if not tool_trace:
        return ""
    parts: list[str] = []
    for row in tool_trace:
        parts.append(str(row.get("tool") or ""))
        parts.append(str(row.get("status") or ""))
        parts.append(str(row.get("summary") or "")[:500])
        data = row.get("data")
        if data is not None:
            parts.append(str(data)[:1500])
        err = row.get("error")
        if err:
            parts.append(str(err)[:300])
    return "\n".join(parts).lower()


def verify_checkpoint_receipt(
    success_criteria: str,
    *,
    tool_trace: list[dict[str, Any]] | None = None,
    sor_text: str | None = None,
    assistant_summary: str | None = None,
) -> ReceiptVerdict:
    """Fail closed when quantitative criteria lack tool/SoR grounding.

    Soft / qualitative criteria still require *some* non-empty tool
    trail or SoR text — an empty trail with only an LLM summary is
    rejected (that was the soft-complete bug).
    """
    criteria = (success_criteria or "").strip()
    trail = _flatten_tool_trail(tool_trace)
    sor = (sor_text or "").strip().lower()
    grounded = f"{trail}\n{sor}".strip()

    if not criteria:
        # No criteria declared — require at least one successful tool.
        if tool_trace and any(
            (t.get("status") or "") == "ok" and not t.get("error") for t in tool_trace
        ):
            return ReceiptVerdict(
                True, "no criteria; tool trail present", grounded[:200]
            )
        return ReceiptVerdict(
            False,
            "no success_criteria and no successful tool trail — refusing soft complete",
        )

    if not grounded:
        return ReceiptVerdict(
            False,
            "success_criteria present but tool trail and system-of-record are empty "
            "(LLM summary alone is not evidence)",
        )

    # Quantitative: every number mentioned in criteria should appear in
    # grounded evidence (or a clearly larger/equal count for "at least N").
    if _QUANT_RE.search(criteria) or (
        "pre-order" in criteria.lower()
        or "paying" in criteria.lower()
        or re.search(r"\b\d+\b", criteria)
    ):
        # Take percentages out before reading counts, so "100%" never
        # becomes a demand for the literal digits 100 in the evidence.
        percents = _PERCENT_RE.findall(criteria)
        counts = [int(n) for n in _NUMBER_RE.findall(_PERCENT_RE.sub(" ", criteria))]
        # Ignore years / huge IDs.
        counts = [n for n in counts if 1 <= n <= 100_000]

        if counts:
            # Deliberately lenient: one grounded count is enough. This is a
            # smell test for soft-completion, not a proof of the claim, and
            # a stricter rule would refuse honest work over phrasing —
            # which is the failure that produced the three-hour loop.
            if not any(re.search(rf"\b{n}\b", grounded) for n in counts):
                return ReceiptVerdict(
                    False,
                    f"quantitative criteria {criteria!r} not grounded in tool/SoR "
                    f"evidence (no count from {counts} appears)",
                )
        if percents and not counts:
            # A proportion over a set can only be claimed by someone who
            # enumerated the set, and enumerating leaves a number in the
            # trail. Require that, or the proportion stated literally.
            if not re.search(r"\d", grounded):
                return ReceiptVerdict(
                    False,
                    f"proportion criteria {criteria!r} not grounded — evidence "
                    f"contains no counts at all, so nothing was enumerated",
                )

    # Qualitative: require overlap tokens from criteria in grounded text,
    # or any successful tool when criteria are vague.
    tokens = [
        t
        for t in re.findall(r"[a-zA-Z]{4,}", criteria.lower())
        if t
        not in {
            "that",
            "this",
            "with",
            "from",
            "have",
            "will",
            "should",
            "must",
            "when",
            "after",
            "before",
            "success",
            "criteria",
            "completed",
            "verify",
            "confirmed",
        }
    ]
    if tokens:
        hits = sum(1 for t in tokens if t in grounded)
        if hits == 0 and not (
            tool_trace and any((t.get("status") or "") == "ok" for t in tool_trace)
        ):
            return ReceiptVerdict(
                False,
                "criteria keywords not found in tool/SoR evidence",
            )

    # Assistant summary is never sufficient alone — already enforced by
    # grounded emptiness check. Mention it only for debugging.
    _ = assistant_summary
    return ReceiptVerdict(
        True, "grounded in tool trail and/or system-of-record", grounded[:240]
    )
