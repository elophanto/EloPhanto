"""skill_promote — turn a cluster of related lessons into a reusable SKILL.md.

The lesson-extraction layer (``core/learner.py``) automatically writes
``knowledge/learned/lessons/<slug>.md`` files when goal checkpoints
complete. After a week of autonomous work the agent typically
accumulates 100s of micro-lessons, all retrievable via
``knowledge_search`` — but they never crystallize into the higher-
abstraction *skills* the dream tool surfaces to the LLM. Effectively
the agent learns micro-patterns and forgets them between cycles
because nothing promotes "I've done this 7 times, here is the
playbook" to a named reusable skill.

This tool closes that gap. Given a list of lesson file paths the
operator (or the autonomous mind) believes cluster on a theme, it
asks the LLM to distill them into a SKILL.md (frontmatter +
triggers + steps) and writes it to ``skills/<slug>/SKILL.md``.

Boundaries:
- Does NOT auto-cluster. Caller passes the lesson list explicitly.
  Auto-clustering is a v2 add — needs embeddings + threshold tuning;
  out of scope here.
- Does NOT overwrite existing skills. If ``skills/<slug>/`` already
  exists, refuse with an error. Skill authorship is high-trust; we
  do not silently mutate established skills.
- Reads up to 30 lessons per call. More than that, the resulting
  skill would be incoherent.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


_PROMOTE_SYSTEM = """\
You are the skill-promotion layer. You receive 2-30 individual lesson
files (each a markdown snippet describing a pattern the agent learned
mid-execution) and synthesize them into ONE reusable SKILL.md.

A skill is NOT a lesson digest. It is a playbook the agent will reach
for next time it faces a similar task. Skills are read BEFORE the task
starts, not after. Write accordingly:

- Skip individual story details from lessons. Promote the underlying
  pattern. If 5 lessons say "I checked recent X before posting" promote
  "Verify dedup against recent X before posting" — not 5 anecdotes.
- Triggers: list 3-7 concrete situations where this skill applies.
  "X post" not "communication". The dream tool greps these.
- Steps: 5-12 numbered, imperative, concrete actions. Each step is one
  decision or one tool call. "Call x_style_preflight" not "ensure quality."
- Anti-patterns: 3-5 things the lessons say NOT to do. This is high-
  leverage signal because it's negative space the agent will not
  otherwise discover.

Return ONLY a YAML+markdown SKILL.md document with this structure:

---
name: <slug-name-kebab-case>
description: <one sentence — the dream tool surfaces this; must read crisp>
---

## Triggers

- <situation 1>
- <situation 2>
- ...

## Steps

1. <imperative step>
2. ...

## Anti-patterns

- <thing not to do>
- ...

## Why this skill exists

<2-3 sentences. What does it compound? What went wrong before the
agent had this pattern? Reading this should make the agent *want* to
use the skill, not just know it exists.>
"""


def _slugify(name: str) -> str:
    """Convert a free-form name to a safe kebab-case directory slug.

    The agent might propose "X post quality checklist" or "Identity
    debt audit" — both need to land in a filesystem-safe directory.
    Reuses the same slug shape as the existing ``core/learner.py``
    slugifier so a human reading the skills directory cannot tell
    the difference between an operator-written skill and a promoted
    one.
    """
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")[:60]


class SkillPromoteTool(BaseTool):
    """Distil 2-30 lessons into one named, reusable SKILL.md.

    The autonomous mind has a lesson-accrual loop already; this is
    the *next* abstraction level. Without this tool, lessons exist
    but never compound — every cycle re-derives the same pattern.
    """

    def __init__(self) -> None:
        self._router: Any = None
        self._project_root: Path | None = None

    @property
    def group(self) -> str:
        return "skills"

    @property
    def name(self) -> str:
        return "skill_promote"

    @property
    def description(self) -> str:
        return (
            "Promote 2-30 related lesson files into one reusable SKILL.md. "
            "Use when knowledge_search reveals you've learned the same pattern "
            "across multiple goals — promotes those lessons to a named skill "
            "the dream tool can surface next session. Provide lesson paths and "
            "a proposed skill name. Skill is written to skills/<slug>/SKILL.md; "
            "refuses if the slug already exists."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": (
                        "Human-readable name for the skill — used as the "
                        "directory slug (kebab-cased) and the frontmatter "
                        "name field. Pick something a future-you would "
                        "search for, e.g. 'identity-audit-playbook'."
                    ),
                },
                "lesson_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Paths (relative to project root, or absolute) to "
                        "2-30 lesson markdown files to distil. Typically "
                        "knowledge/learned/lessons/*.md entries surfaced "
                        "by knowledge_search."
                    ),
                },
            },
            "required": ["skill_name", "lesson_paths"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        # MODERATE because writing to skills/ affects future dream
        # cycles. Operator may want eyes on the first few promotions
        # before granting auto-approval.
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._router:
            return ToolResult(success=False, error="LLM router not available.")
        if self._project_root is None:
            return ToolResult(success=False, error="Project root not configured.")

        skill_name = str(params.get("skill_name", "")).strip()
        lesson_paths = params.get("lesson_paths", []) or []

        if not skill_name:
            return ToolResult(success=False, error="skill_name is required.")
        if not isinstance(lesson_paths, list) or not lesson_paths:
            return ToolResult(
                success=False, error="lesson_paths must be a non-empty list."
            )
        if len(lesson_paths) > 30:
            return ToolResult(
                success=False,
                error=f"Too many lessons ({len(lesson_paths)}) — cap is 30. "
                "Larger clusters produce incoherent skills.",
            )
        if len(lesson_paths) < 2:
            return ToolResult(
                success=False,
                error="Need at least 2 lessons to justify a skill. "
                "A single lesson should stay a lesson.",
            )

        slug = _slugify(skill_name)
        if not slug:
            return ToolResult(
                success=False,
                error=f"skill_name {skill_name!r} produces an empty slug.",
            )

        # Refuse to overwrite existing skills. Skill files are high-
        # trust; mutating one silently could break behavior the operator
        # depends on.
        skill_dir = self._project_root / "skills" / slug
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            return ToolResult(
                success=False,
                error=(
                    f"Skill {slug!r} already exists at {skill_md}. "
                    "Pick a different name or delete the existing skill first."
                ),
            )

        # Collect lesson texts. Skip-silently any unreadable lesson —
        # the LLM can still produce a useful skill from the rest, and
        # one bad path shouldn't fail the whole promotion.
        lesson_texts: list[str] = []
        skipped: list[str] = []
        for raw in lesson_paths:
            p = Path(str(raw)).expanduser()
            if not p.is_absolute():
                p = self._project_root / p
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
                if len(text.strip()) < 20:
                    skipped.append(str(p))
                    continue
                # Cap each lesson to keep prompt size bounded.
                if len(text) > 3000:
                    text = text[:3000] + "\n…(truncated)"
                lesson_texts.append(f"=== {p.name} ===\n{text}")
            except OSError:
                skipped.append(str(p))

        if len(lesson_texts) < 2:
            return ToolResult(
                success=False,
                error=(
                    f"After reading, only {len(lesson_texts)} lessons remained "
                    f"(skipped: {skipped}). Need at least 2."
                ),
            )

        prompt = (
            f"Promote these {len(lesson_texts)} lessons into a SKILL.md "
            f"named '{skill_name}'. Slug: {slug}.\n\n"
            f"LESSONS:\n\n" + "\n\n".join(lesson_texts) + "\n\n"
            "Return ONLY the SKILL.md content — frontmatter then "
            "markdown body. No code fences, no commentary before or after."
        )

        try:
            response = await self._router.complete(
                messages=[
                    {"role": "system", "content": _PROMOTE_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                task_type="planning",
                temperature=0.3,
            )
        except Exception as e:
            return ToolResult(success=False, error=f"LLM call failed: {e}")

        content = (response.content or "").strip()
        # Strip accidental code fences.
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        if not content.startswith("---"):
            return ToolResult(
                success=False,
                error=(
                    "LLM returned non-frontmatter content. Refusing to "
                    "write malformed SKILL.md. First 200 chars: "
                    f"{content[:200]!r}"
                ),
            )

        try:
            skill_dir.mkdir(parents=True, exist_ok=False)
            skill_md.write_text(content, encoding="utf-8")
        except FileExistsError:
            return ToolResult(
                success=False,
                error=f"Race: skill {slug!r} created by another process.",
            )
        except OSError as e:
            return ToolResult(success=False, error=f"Failed to write SKILL.md: {e}")

        # Phase 11 autonomy-loop closer (2026-05-27): the new skill
        # may have been built specifically to resolve a `missing_skill`
        # blocker on some company's strategy. Sweep all companies'
        # blockers.yaml now so the operator sees the resolution
        # immediately. Best-effort.
        resolved_summary: dict[str, int] = {}
        try:
            from core.strategy import auto_resolve_blockers

            resolved_summary = auto_resolve_blockers(
                self._project_root,
                registry=None,
                skills_dir=self._project_root / "skills",
            )
        except Exception as e:
            logger.debug("auto_resolve_blockers post-skill sweep failed: %s", e)

        return ToolResult(
            success=True,
            data={
                "skill_path": str(skill_md),
                "slug": slug,
                "lessons_used": len(lesson_texts),
                "lessons_skipped": skipped,
                "size_bytes": skill_md.stat().st_size,
                "auto_resolved_blockers": resolved_summary,
                "note": (
                    "Skill is now visible to goal_dream next cycle. "
                    "If the synthesis looks off, you can edit SKILL.md "
                    "directly or delete the directory and re-promote."
                ),
            },
        )
