"""Instinct read-path — match text against InstinctStore for mind prompts.

``InstinctStore.find_by_trigger`` returns a single best match; this module
returns TOP-N ranked by overlap × confidence for soft prompt injection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from core.instinct import Instinct

logger = logging.getLogger(__name__)


@dataclass
class MatchedInstinct:
    instinct: Instinct
    overlap: float
    confidence: float


def match_instincts(
    store: Any,
    text: str,
    *,
    threshold: float = 0.35,
    limit: int = 5,
) -> list[MatchedInstinct]:
    """Word-overlap match against all instincts; top-N by overlap * confidence.

    Overlap uses the same ratio as ``InstinctStore.find_by_trigger``:
    ``|A ∩ B| / max(|A|, |B|)``. Returns [] when store is None or text empty.
    """
    if store is None or not text or not str(text).strip():
        return []
    try:
        instincts = store.list_all()
    except Exception:
        logger.debug("[instinct_match] list_all failed", exc_info=True)
        return []
    if not instincts:
        return []

    trigger_words = set(str(text).strip().lower().split())
    if not trigger_words:
        return []

    scored: list[MatchedInstinct] = []
    for instinct in instincts:
        inst_words = set(instinct.trigger.strip().lower().split())
        if not inst_words:
            continue
        overlap = len(trigger_words & inst_words) / max(
            len(trigger_words), len(inst_words)
        )
        if overlap < threshold:
            continue
        conf = float(getattr(instinct, "confidence", 0.0) or 0.0)
        scored.append(
            MatchedInstinct(instinct=instinct, overlap=overlap, confidence=conf)
        )

    scored.sort(key=lambda m: m.overlap * m.confidence, reverse=True)
    return scored[: max(0, int(limit))]


def format_for_prompt(matches: list[MatchedInstinct] | None) -> str:
    """Short XML-ish block for the autonomous mind prompt. Empty if none."""
    if not matches:
        return ""
    lines = ["<matched_instincts>"]
    for m in matches:
        inst = m.instinct
        lines.append(
            f'  <instinct id="{inst.id}" overlap="{m.overlap:.2f}" '
            f'confidence="{m.confidence:.2f}">'
        )
        lines.append(f"    <trigger>{_xml_escape(inst.trigger)}</trigger>")
        lines.append(f"    <action>{_xml_escape(inst.action)}</action>")
        lines.append("  </instinct>")
    lines.append("</matched_instincts>")
    return "\n".join(lines)


def _xml_escape(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
