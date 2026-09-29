"""Plan outcomes and lesson records — predictions, scored.

Every checkpoint attempt starts with a plan (core/deliberation.py): an
approach, steps, the assumptions it rests on, the risks it foresees, and the
recalled lessons it applies. That plan is a prediction. This module records
how each one turned out and uses the record for two things:

  * a failure the plan did not foresee is a **surprise**; the runner asks one
    post-mortem question — which assumption was false? — and that becomes the
    lesson, so lessons come from falsified predictions rather than from the
    model's own summary of a run;
  * each lesson a plan used is credited or debited with the attempt's result.
    A lesson used at least ``MIN_USES`` times that beats the overall pass
    rate by ``PROMOTE_MARGIN`` is **promoted** to a skill under
    ``skills/learned-<slug>/SKILL.md``, which the skill system already
    matches and loads. One that trails it by ``RETIRE_MARGIN`` is **retired**:
    recall stops offering it. Files are never deleted.

Nothing here may fail the work: every call is best-effort. See
docs/95-LEARNING-LOOP.md, Phases C and D.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MIN_USES = 5
PROMOTE_MARGIN = 0.15
RETIRE_MARGIN = 0.20
# The baseline is the pass rate of the most recent plan outcomes, so it
# follows the agent as it improves rather than averaging its whole history.
BASELINE_WINDOW = 500


@dataclass
class OfferedLesson:
    """A lesson recall put in front of a planner."""

    ref: str  # "knowledge:<path>" | "instinct:<id>"
    title: str
    body: str
    label: str = ""  # "L1", "L2"… — how the plan refers to it

    def render(self) -> str:
        return f"[{self.label}] {self.title}: {self.body}"


def render_offered(lessons: list[OfferedLesson]) -> str:
    """Numbered lessons for a planning prompt; labels are assigned here."""
    for i, lesson in enumerate(lessons, 1):
        lesson.label = f"L{i}"
    return "\n".join(lesson.render() for lesson in lessons)


def lessons_by_label(
    lessons: list[OfferedLesson], labels: list[str]
) -> list[OfferedLesson]:
    """The offered lessons a plan says it used. Unknown labels are ignored."""
    wanted = {str(label).strip().strip("[]").upper() for label in labels}
    return [lesson for lesson in lessons if lesson.label.upper() in wanted]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _slug(text: str) -> str:
    text = re.sub(r"^(avoid|lesson)\s*:\s*", "", text.strip(), flags=re.I)
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48].strip("-") or "lesson"


class PlanOutcomes:
    """Records plan outcomes and keeps each lesson's record."""

    def __init__(
        self,
        db: Any,
        *,
        project_root: Path | str | None = None,
        on_promote: Callable[[Path], None] | None = None,
    ) -> None:
        self._db = db
        self._root = Path(project_root) if isinstance(project_root, (str, Path)) else None
        self._on_promote = on_promote

    # ── recording ───────────────────────────────────────────────────

    async def record(
        self,
        *,
        goal_id: str,
        checkpoint_order: int,
        attempt: int,
        passed: bool,
        gate: str = "",
        steps_planned: int = 0,
        steps_used: int = 0,
        stop_reason: str = "",
        surprise: bool = False,
        broken_assumption: str = "",
        lessons_used: list[OfferedLesson] | None = None,
    ) -> None:
        used = lessons_used or []
        await self._db.execute_insert(
            "INSERT INTO plan_outcomes (goal_id, checkpoint_order, attempt, passed, "
            "gate, steps_planned, steps_used, stop_reason, surprise, "
            "broken_assumption, lessons_used, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                goal_id,
                int(checkpoint_order),
                int(attempt),
                1 if passed else 0,
                gate,
                int(steps_planned),
                int(steps_used),
                stop_reason,
                1 if surprise else 0,
                broken_assumption[:500],
                json.dumps([lesson.ref for lesson in used]),
                _now(),
            ),
        )
        for lesson in used:
            await self._credit(lesson, passed)

    async def _credit(self, lesson: OfferedLesson, passed: bool) -> None:
        await self._db.execute_insert(
            "INSERT INTO lesson_stats (lesson_ref, title, body, uses, passes, fails, last_used) "
            "VALUES (?, ?, ?, 1, ?, ?, ?) "
            "ON CONFLICT(lesson_ref) DO UPDATE SET uses = uses + 1, "
            "passes = passes + excluded.passes, fails = fails + excluded.fails, "
            "title = excluded.title, body = excluded.body, last_used = excluded.last_used",
            (
                lesson.ref,
                lesson.title[:200],
                lesson.body[:2000],
                1 if passed else 0,
                0 if passed else 1,
                _now(),
            ),
        )
        await self._review(lesson.ref)

    # ── the record ──────────────────────────────────────────────────

    async def baseline(self) -> float | None:
        """Pass rate of the most recent plan outcomes; None with too few."""
        rows = await self._db.execute(
            "SELECT passed FROM plan_outcomes ORDER BY id DESC LIMIT ?",
            (BASELINE_WINDOW,),
        )
        if len(rows) < MIN_USES:
            return None
        return sum(int(r["passed"]) for r in rows) / len(rows)

    async def stats(self, refs: list[str]) -> dict[str, dict[str, Any]]:
        if not refs:
            return {}
        marks = ",".join("?" for _ in refs)
        rows = await self._db.execute(
            f"SELECT * FROM lesson_stats WHERE lesson_ref IN ({marks})", tuple(refs)
        )
        return {r["lesson_ref"]: dict(r) for r in rows}

    async def rank(
        self, offered: list[OfferedLesson], limit: int
    ) -> list[OfferedLesson]:
        """Drop retired lessons and order the rest by their record.

        A lesson with no record keeps its relevance order; one with a record
        is scored by its smoothed pass rate against the baseline, so a
        proven lesson rises and an unproven one is not buried.
        """
        stats = await self.stats([lesson.ref for lesson in offered])
        base = await self.baseline()
        scored: list[tuple[float, int, OfferedLesson]] = []
        for i, lesson in enumerate(offered):
            st = stats.get(lesson.ref)
            if st and st.get("status") == "retired":
                continue
            score = 0.0
            if st and base is not None and int(st.get("uses") or 0) > 0:
                # Laplace smoothing toward the baseline: two uses prove little.
                rate = (int(st["passes"]) + base * 2) / (int(st["uses"]) + 2)
                score = rate - base
            scored.append((-score, i, lesson))
        scored.sort(key=lambda t: (t[0], t[1]))
        return [lesson for _, _, lesson in scored[:limit]]

    async def _review(self, ref: str) -> None:
        """Promote or retire a lesson once its record is long enough."""
        rows = await self._db.execute(
            "SELECT * FROM lesson_stats WHERE lesson_ref = ?", (ref,)
        )
        if not rows:
            return
        st = dict(rows[0])
        uses = int(st.get("uses") or 0)
        if uses < MIN_USES or st.get("status") != "active":
            return
        base = await self.baseline()
        if base is None:
            return
        rate = int(st.get("passes") or 0) / uses
        note = (
            f"{int(st['passes'])}/{uses} passed ({rate:.0%}) against {base:.0%} overall"
        )
        if rate >= base + PROMOTE_MARGIN:
            path = await self._promote(st, rate, base)
            if path is not None:
                await self._set_status(ref, "promoted", f"{note} → {path}")
                logger.info("[learning] promoted lesson %s to %s (%s)", ref, path, note)
        elif rate <= base - RETIRE_MARGIN:
            await self._set_status(ref, "retired", note)
            logger.info("[learning] retired lesson %s (%s)", ref, note)

    async def _set_status(self, ref: str, status: str, note: str) -> None:
        await self._db.execute(
            "UPDATE lesson_stats SET status = ?, status_note = ? WHERE lesson_ref = ?",
            (status, note[:500], ref),
        )

    # ── promotion ───────────────────────────────────────────────────

    def _lesson_text(self, st: dict[str, Any]) -> str:
        """The full lesson when its file can be found, else the stored body."""
        ref = str(st.get("lesson_ref") or "")
        body = str(st.get("body") or "")
        if not ref.startswith("knowledge:") or self._root is None:
            return body
        raw = Path(ref.split(":", 1)[1])
        for candidate in (raw, self._root / raw, self._root / "knowledge" / raw):
            try:
                if candidate.is_file():
                    text = candidate.read_text(encoding="utf-8")
                    if text.startswith("---"):
                        text = text.split("---", 2)[-1]
                    return text.strip()[:4000] or body
            except OSError:
                continue
        return body

    async def _triggers(self, ref: str, title: str) -> list[str]:
        """What the skill should match: the lesson's subject and the titles
        of checkpoints where plans that used it passed."""
        triggers = [
            re.sub(r"^(avoid|lesson)\s*:\s*", "", title, flags=re.I).strip().lower()
        ]
        try:
            rows = await self._db.execute(
                "SELECT DISTINCT c.title FROM plan_outcomes p JOIN goal_checkpoints c "
                "ON c.goal_id = p.goal_id AND c.checkpoint_order = p.checkpoint_order "
                "WHERE p.passed = 1 AND p.lessons_used LIKE ? LIMIT 5",
                (f"%{json.dumps(ref)[1:-1]}%",),
            )
            triggers += [str(r["title"]).strip().lower() for r in rows if r["title"]]
        except Exception as e:
            logger.debug("promotion triggers: %s", e)
        seen: list[str] = []
        for t in triggers:
            if t and t not in seen:
                seen.append(t[:80])
        return seen[:6]

    async def _promote(
        self, st: dict[str, Any], rate: float, base: float
    ) -> Path | None:
        if self._root is None:
            return None
        title = str(st.get("title") or "Learned lesson").strip()
        skill_dir = self._root / "skills" / f"learned-{_slug(title)}"
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            return skill_file  # promoted before (or a name clash) — never overwrite
        triggers = await self._triggers(str(st["lesson_ref"]), title)
        uses = int(st.get("uses") or 0)
        passes = int(st.get("passes") or 0)
        description = (
            f"Learned playbook: {title}. Plans that applied it passed "
            f"{passes} of {uses} attempts ({rate:.0%}) against {base:.0%} overall."
        )
        content = (
            "---\n"
            f"name: learned-{_slug(title)}\n"
            f"description: {json.dumps(description)}\n"
            f"triggers: {json.dumps(triggers)}\n"
            "metadata:\n"
            "  author: elophanto-learning-loop\n"
            f"  source: {json.dumps(str(st['lesson_ref']))}\n"
            f"  promoted: {datetime.now(UTC).strftime('%Y-%m-%d')}\n"
            "---\n\n"
            f"# {title}\n\n"
            "Promoted by the learning loop (docs/95 Phase D): a lesson from an "
            f"earlier run whose plans passed {passes} of {uses} attempts, against "
            f"{base:.0%} for plans overall. It stays a skill while that holds.\n\n"
            "## Triggers\n\n"
            + "".join(f"- {t}\n" for t in triggers)
            + "\n## Instructions\n\n"
            + self._lesson_text(st)
            + "\n"
        )
        try:
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_file.write_text(content, encoding="utf-8")
        except OSError as e:
            logger.warning("lesson promotion failed: %s", e)
            return None
        if self._on_promote is not None:
            try:
                self._on_promote(skill_file)
            except Exception as e:
                logger.debug("skill reload after promotion failed: %s", e)
        return skill_file


async def record_mind_outcome(
    db: Any,
    *,
    source: str,
    action_spec: str,
    deliberated: bool,
    pick: int,
    tool_uses: list[dict[str, Any]],
    stop_reason: str,
    cost_usd: float,
) -> None:
    """One mind cycle's decision and result. Best-effort."""
    try:
        await db.execute_insert(
            "INSERT INTO mind_outcomes (source, action_spec, deliberated, pick, "
            "tool_count, tool_errors, stop_reason, cost_usd, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source[:80],
                action_spec[:300],
                1 if deliberated else 0,
                int(pick),
                len(tool_uses),
                sum(
                    1
                    for t in tool_uses
                    if str(t.get("status", "")) not in ("ok", "success", "")
                ),
                stop_reason[:80],
                float(cost_usd or 0.0),
                _now(),
            ),
        )
    except Exception as e:
        logger.debug("mind outcome not recorded: %s", e)
