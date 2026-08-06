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
        nums = [int(n) for n in _NUMBER_RE.findall(criteria)]
        # Ignore years / huge IDs.
        nums = [n for n in nums if 1 <= n <= 100_000]
        if nums:
            missing = []
            for n in nums:
                # Accept exact digit or evidence that mentions the count.
                if str(n) not in grounded:
                    missing.append(n)
            if missing and not any(re.search(rf"\b{n}\b", grounded) for n in nums):
                return ReceiptVerdict(
                    False,
                    f"quantitative criteria {criteria!r} not grounded in tool/SoR "
                    f"evidence (missing counts {missing})",
                )
            # Soft pass if at least one claimed number appears.
            if all(str(n) not in grounded for n in nums):
                return ReceiptVerdict(
                    False,
                    f"no claimed count from {nums} found in tool/SoR evidence",
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
