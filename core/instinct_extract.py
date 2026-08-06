"""Thin instinct extraction from receipt-verified checkpoint completions.

Only called after ``verify_checkpoint_receipt`` passes. Candidates are
stored via InstinctStore — never force-applied; operator-deletable.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def maybe_extract_instinct(
    *,
    project_root: Path,
    goal: Any,
    checkpoint: Any,
    summary: str,
    tool_trace: list[dict[str, Any]] | None = None,
) -> None:
    """Best-effort: record a few-shot instinct for similar decompose work."""
    stage = (getattr(checkpoint, "stage", None) or "unknown").strip()
    title = (getattr(checkpoint, "title", None) or "").strip()
    if not title:
        return
    tools_used = sorted(
        {
            str(t.get("tool") or "")
            for t in (tool_trace or [])
            if (t.get("status") or "") == "ok" and t.get("tool")
        }
    )
    if not tools_used:
        return

    from core.instinct import InstinctStore, get_project_hash

    data_dir = project_root / "data"
    store = InstinctStore(
        data_dir=data_dir, project_hash=get_project_hash(project_root)
    )
    trigger = (
        f"goal stage={stage} checkpoint like: {title[:120]} "
        f"(goal: {str(getattr(goal, 'goal', '') or '')[:80]})"
    )
    action = (
        f"Prefer tools {', '.join(tools_used[:6])}; "
        f"success pattern: {(summary or '')[:160]}"
    )
    evidence = f"verified receipt for {getattr(goal, 'goal_id', '?')}:{getattr(checkpoint, 'order', '?')}"
    try:
        store.merge_or_create(
            trigger=trigger,
            action=action,
            evidence=evidence,
            tags=["goal", "verified", stage],
            scope="project",
        )
    except Exception as e:
        logger.debug("instinct extract failed: %s", e)
