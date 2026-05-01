"""Agent ego — evaluative self-image, computed from outcomes.

Identity is descriptive (who I claim to be).
Ego is evaluative (how reality has graded that claim).

Design choices baked in here:

1. **Reflective, not defensive.** No code path lets ego "defend" the self-image
   against user correction. Confidence is moved by measured pass/fail, never
   by LLM rationalization.
2. **Outcome-driven.** Confidence is an exponentially-smoothed estimate of
   per-capability success rate. The LLM only writes the *prose* (self_image,
   self_critique). It never writes the numbers.
3. **Bounded humility.** Humbling events cap at 5; confidence floors at 0.05
   (no learned helplessness) and ceils at 0.95 (no overconfidence either).
4. **Asymmetric updates.** Failures move confidence faster than successes —
   one bad outcome shouldn't be erased by the next routine win.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.config import IdentityConfig
from core.database import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Exponential smoothing weights. Failure weight > success weight.
_ALPHA_SUCCESS = 0.10
_ALPHA_FAILURE = 0.20

# Confidence bounds.
_CONF_FLOOR = 0.05
_CONF_CEIL = 0.95

# Default starting confidence for an unseen capability.
_CONF_DEFAULT = 0.50

# How many humbling events to retain and inject into context.
_HUMBLING_CAP = 5

# Recompute self_image / self_critique every N recorded outcomes.
_RECOMPUTE_EVERY = 25


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class HumblingEvent:
    capability: str
    claimed: str
    actual: str
    task_goal: str = ""
    created_at: str = ""


@dataclass
class Ego:
    """Evaluative self-image, computed from outcomes."""

    self_image: str = ""
    confidence: dict[str, float] = field(default_factory=dict)
    humbling_events: list[HumblingEvent] = field(default_factory=list)
    coherence_score: float = 1.0
    last_self_critique: str = ""
    tasks_since_recompute: int = 0
    updated_at: str = ""


# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

_RECOMPUTE_SYSTEM = """\
<self_perception_recompute>
You are writing a brief, honest self-perception for an AI agent based on
*measured outcomes*, not aspirations.

You will receive:
- The agent's declared identity (what it claims to be)
- Per-capability confidence scores (0.0-1.0) measured from actual task outcomes
- Recent "humbling events" — moments where reality contradicted the self-image

Your job:
1. Write a one-paragraph self_image (3-5 sentences) that integrates the
   humbling events. The self-image must NOT contradict the confidence numbers
   or pretend the humbling events didn't happen.
2. Write a one-line self_critique pointing at the single most important gap
   between declared identity and measured behavior.

Rules:
- Be honest, not flattering. Calibration > comfort.
- If a humbling event contradicts a declared value or capability, name it.
- Do not invent capabilities. Only describe what the data supports.

Return ONLY a JSON object — no markdown:
{
  "self_image": "...",
  "self_critique": "..."
}
</self_perception_recompute>"""


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class EgoManager:
    """Manages the agent's ego state — confidence, humbling events, self-image."""

    def __init__(
        self, db: Database, router: Any, config: IdentityConfig | None = None
    ) -> None:
        self._db = db
        self._router = router
        self._config = config
        self._ego: Ego | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def load_or_create(self) -> Ego:
        rows = await self._db.execute("SELECT * FROM ego_state WHERE id = 'self'")
        if rows:
            self._ego = self._row_to_ego(rows[0])
            await self._load_humbling_events(self._ego)
            logger.info("Ego loaded (coherence=%.2f)", self._ego.coherence_score)
            return self._ego

        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            """INSERT INTO ego_state
               (id, self_image, confidence_json, coherence_score,
                last_self_critique, tasks_since_recompute, updated_at)
               VALUES ('self', '', '{}', 1.0, '', 0, ?)""",
            (now,),
        )
        self._ego = Ego(updated_at=now)
        return self._ego

    async def get_ego(self) -> Ego:
        if self._ego is None:
            await self.load_or_create()
        assert self._ego is not None
        return self._ego

    # ------------------------------------------------------------------
    # Outcome recording — the only way confidence moves
    # ------------------------------------------------------------------

    async def record_outcome(
        self,
        capability: str,
        success: bool,
        task_goal: str = "",
        notes: str = "",
    ) -> None:
        """Record a task outcome against a capability. Updates confidence
        immediately; does not call the LLM. The LLM only runs on recompute."""
        if not capability:
            return

        ego = await self.get_ego()
        now = datetime.now(UTC).isoformat()

        # Persist outcome row (audit trail)
        await self._db.execute_insert(
            """INSERT INTO ego_outcomes
               (capability, success, task_goal, notes, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (capability, 1 if success else 0, task_goal[:500], notes[:500], now),
        )

        # Update confidence with asymmetric exponential smoothing.
        prior = ego.confidence.get(capability, _CONF_DEFAULT)
        target = 1.0 if success else 0.0
        alpha = _ALPHA_SUCCESS if success else _ALPHA_FAILURE
        new = prior + alpha * (target - prior)
        new = max(_CONF_FLOOR, min(_CONF_CEIL, new))
        ego.confidence[capability] = round(new, 4)

        ego.tasks_since_recompute += 1
        ego.updated_at = now
        await self._persist_state(ego)

    async def record_humbling(
        self,
        capability: str,
        claimed: str,
        actual: str,
        task_goal: str = "",
    ) -> None:
        """Pin a moment where reality contradicted the self-image. Append-only
        in DB; in-memory list capped at _HUMBLING_CAP (newest kept)."""
        ego = await self.get_ego()
        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            """INSERT INTO ego_humbling_events
               (capability, claimed, actual, task_goal, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (capability, claimed[:300], actual[:300], task_goal[:500], now),
        )
        event = HumblingEvent(
            capability=capability,
            claimed=claimed[:300],
            actual=actual[:300],
            task_goal=task_goal[:500],
            created_at=now,
        )
        ego.humbling_events.append(event)
        if len(ego.humbling_events) > _HUMBLING_CAP:
            ego.humbling_events = ego.humbling_events[-_HUMBLING_CAP:]
        ego.updated_at = now
        # Coherence drops when a humbling event lands; recompute will reset
        # it based on the LLM's read of declared-vs-actual alignment.
        ego.coherence_score = max(0.0, ego.coherence_score - 0.10)
        await self._persist_state(ego)
        await self.update_markdown()
        logger.info(
            "Ego: humbling event recorded for '%s' (claimed='%s')",
            capability,
            claimed[:60],
        )

    # ------------------------------------------------------------------
    # Recompute self_image / self_critique
    # ------------------------------------------------------------------

    async def maybe_recompute(self, identity_summary: str) -> bool:
        """Recompute self_image if enough outcomes have accrued. Returns True
        if a recompute happened."""
        ego = await self.get_ego()
        if ego.tasks_since_recompute < _RECOMPUTE_EVERY:
            return False
        await self.recompute(identity_summary)
        return True

    async def recompute(self, identity_summary: str) -> None:
        """Force a self_image / self_critique recompute via the LLM. The LLM
        is given the *measured* confidence and humbling events and is forbidden
        from contradicting them."""
        ego = await self.get_ego()

        confidence_block = (
            "\n".join(f"  {k}: {v:.2f}" for k, v in sorted(ego.confidence.items()))
            or "  (no measured outcomes yet)"
        )
        humbling_block = (
            "\n".join(
                f"  - capability='{e.capability}' "
                f"claimed='{e.claimed}' actual='{e.actual}'"
                for e in ego.humbling_events[-_HUMBLING_CAP:]
            )
            or "  (none recorded)"
        )

        user_msg = (
            f"Declared identity:\n{identity_summary}\n\n"
            f"Measured per-capability confidence:\n{confidence_block}\n\n"
            f"Recent humbling events:\n{humbling_block}\n"
        )

        try:
            response = await self._router.complete(
                messages=[
                    {"role": "system", "content": _RECOMPUTE_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                task_type="simple",
                temperature=0.4,
            )
            data = json.loads(response.content)
            ego.self_image = str(data.get("self_image", ""))[:1500]
            ego.last_self_critique = str(data.get("self_critique", ""))[:500]
        except Exception as e:
            logger.warning("Ego recompute failed: %s — keeping previous state", e)
            return

        # Coherence climbs back when recompute integrates reality cleanly.
        if ego.humbling_events:
            ego.coherence_score = max(0.3, min(1.0, ego.coherence_score + 0.20))
        else:
            ego.coherence_score = 1.0

        ego.tasks_since_recompute = 0
        ego.updated_at = datetime.now(UTC).isoformat()
        await self._persist_state(ego)
        await self.update_markdown()
        logger.info(
            "Ego recomputed: coherence=%.2f, critique='%s'",
            ego.coherence_score,
            ego.last_self_critique[:80],
        )

    # ------------------------------------------------------------------
    # Markdown mirror — same pattern as IdentityManager.update_nature
    # ------------------------------------------------------------------

    async def update_markdown(self) -> None:
        """Write a human-readable mirror of the ego state to the configured
        markdown path. DB is the source of truth; this file is for humans
        and for knowledge-base retrieval."""
        if not self._config:
            return
        path_str = getattr(self._config, "ego_file", "")
        if not path_str:
            return
        ego = await self.get_ego()
        path = Path(path_str)
        path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC).strftime("%Y-%m-%d")

        def _bullets(items: list[str]) -> str:
            return (
                "\n".join(f"- {item}" for item in items) if items else "- (nothing yet)"
            )

        confidence_lines = [
            f"{cap}: {conf:.2f}"
            for cap, conf in sorted(
                ego.confidence.items(), key=lambda kv: kv[1], reverse=True
            )
        ]
        humbling_lines = [
            f"**{e.capability}** — claimed: _{e.claimed}_ · actual: _{e.actual}_"
            for e in ego.humbling_events[-_HUMBLING_CAP:]
        ]

        content = f"""\
---
scope: identity
tags: [self, ego, self-perception]
updated: {now}
---

# Agent Ego

How reality has graded the declared identity.

## Self-image
{ego.self_image or "_(not yet computed — needs more outcomes)_"}

## Last self-critique
{ego.last_self_critique or "_(not yet computed)_"}

## Coherence
{ego.coherence_score:.2f} (1.0 = behavior aligned with declared identity; drops on humbling events, recovers on recompute)

## Measured confidence
{_bullets(confidence_lines)}

## Where reality has disagreed
{_bullets(humbling_lines)}

*Last updated: {now}*
"""
        path.write_text(content, encoding="utf-8")
        logger.info("Ego document updated: %s", path)

    # ------------------------------------------------------------------
    # Read-side: planner hook + system-prompt context
    # ------------------------------------------------------------------

    async def should_attempt(self, capability: str, difficulty: float = 0.5) -> str:
        """Return 'yes', 'ask', or 'decline' based on confidence vs difficulty.

        difficulty: 0.0 = trivial, 1.0 = at the limit of what the agent claims.
        """
        ego = await self.get_ego()
        conf = ego.confidence.get(capability, _CONF_DEFAULT)
        margin = conf - difficulty
        if margin >= 0.15:
            return "yes"
        if margin >= -0.15:
            return "ask"
        return "decline"

    async def build_self_perception_context(self) -> str:
        """XML block injected into the system prompt after identity."""
        ego = await self.get_ego()
        if not ego.self_image and not ego.confidence and not ego.humbling_events:
            return ""

        parts = ["<self_perception>"]
        if ego.self_image:
            parts.append(f"  <self_image>{ego.self_image}</self_image>")
        if ego.confidence:
            top = sorted(ego.confidence.items(), key=lambda kv: kv[1])
            # Show the 3 lowest (where reality is most pessimistic) and
            # the 3 highest (declared strengths) — calibration over comfort.
            shown: list[tuple[str, float]] = []
            shown.extend(top[:3])
            for cap, conf in reversed(top):
                if (cap, conf) not in shown:
                    shown.append((cap, conf))
                if len(shown) >= 6:
                    break
            conf_str = ", ".join(f"{k}={v:.2f}" for k, v in shown)
            parts.append(f"  <measured_confidence>{conf_str}</measured_confidence>")
        if ego.humbling_events:
            parts.append("  <where_reality_disagreed>")
            for e in ego.humbling_events[-_HUMBLING_CAP:]:
                parts.append(
                    f'    <event capability="{e.capability}">'
                    f"claimed: {e.claimed} | actual: {e.actual}"
                    f"</event>"
                )
            parts.append("  </where_reality_disagreed>")
        if ego.last_self_critique:
            parts.append(
                f"  <last_self_critique>{ego.last_self_critique}</last_self_critique>"
            )
        parts.append(f"  <coherence>{ego.coherence_score:.2f}</coherence>")
        parts.append("</self_perception>")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _persist_state(self, ego: Ego) -> None:
        await self._db.execute_insert(
            """UPDATE ego_state
               SET self_image = ?,
                   confidence_json = ?,
                   coherence_score = ?,
                   last_self_critique = ?,
                   tasks_since_recompute = ?,
                   updated_at = ?
               WHERE id = 'self'""",
            (
                ego.self_image,
                json.dumps(ego.confidence),
                ego.coherence_score,
                ego.last_self_critique,
                ego.tasks_since_recompute,
                ego.updated_at,
            ),
        )

    async def _load_humbling_events(self, ego: Ego) -> None:
        rows = await self._db.execute(
            """SELECT capability, claimed, actual, task_goal, created_at
               FROM ego_humbling_events
               ORDER BY id DESC LIMIT ?""",
            (_HUMBLING_CAP,),
        )
        ego.humbling_events = [
            HumblingEvent(
                capability=r["capability"],
                claimed=r["claimed"],
                actual=r["actual"],
                task_goal=r["task_goal"] or "",
                created_at=r["created_at"],
            )
            for r in reversed(rows)
        ]

    @staticmethod
    def _row_to_ego(row: Any) -> Ego:
        try:
            confidence = json.loads(row["confidence_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            confidence = {}
        return Ego(
            self_image=row["self_image"] or "",
            confidence=confidence,
            humbling_events=[],
            coherence_score=float(row["coherence_score"] or 1.0),
            last_self_critique=row["last_self_critique"] or "",
            tasks_since_recompute=int(row["tasks_since_recompute"] or 0),
            updated_at=row["updated_at"] or "",
        )
