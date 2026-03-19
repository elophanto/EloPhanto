"""Lesson extractor: distills reusable insights from completed tasks into the KB.

After each successfully completed task, runs a lightweight LLM call to extract
1-2 concrete, generalizable lessons and writes them as scope=learned KB entries.
Lessons are merged into existing files when the same topic recurs, building up
richer knowledge over time rather than creating duplicate entries.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_LESSON_SYSTEM = """\
<lesson_extraction>
You extract reusable, generalizable lessons from completed AI agent tasks.

Given a task goal, outcome summary, and tools used, identify 0-2 concrete lessons
that are ALL of the following:
- Generalizable: applicable to future similar tasks, not just this one instance
- Actionable: tells the agent what to do, avoid, or watch for
- Novel: not obvious common knowledge or standard procedure

Return ONLY a JSON object — no markdown, no explanation:
{
  "lessons": [
    {
      "title": "short lesson title (5-8 words)",
      "when": "condition/context when this applies",
      "lesson": "the concrete insight (2-4 sentences max)",
      "tags": ["tag1", "tag2"]
    }
  ]
}

Return {"lessons": []} if:
- The task was routine with no novel discovery
- The lesson is too specific to generalize (e.g., a one-off file path)
- The lesson is obvious (e.g., "use browser_navigate to open pages")
- The task outcome was incomplete or errored
</lesson_extraction>"""

_COMPRESS_SYSTEM = """\
Compress the following knowledge document to be dense and factual.
Rules:
- Keep ALL factual content, procedures, steps, and key details
- Remove filler prose, redundant phrasing, and verbose explanations
- Use concise sentences and bullet points where appropriate
- Target 40% of the original length
- Preserve any code, commands, URLs, and specific values exactly

Return ONLY the compressed markdown content, no frontmatter, no preamble."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(text: str, max_len: int = 50) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug[:max_len].strip("-")


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# LessonExtractor
# ---------------------------------------------------------------------------


class LessonExtractor:
    """Extracts generalizable lessons from task completions and stores them in KB."""

    def __init__(
        self,
        router: Any,
        knowledge_dir: Path,
        indexer: Any,
        enabled: bool = True,
    ) -> None:
        self._router = router
        self._knowledge_dir = knowledge_dir
        self._indexer = indexer
        self._enabled = enabled

    async def extract_and_store(
        self,
        goal: str,
        summary: str,
        outcome: str,
        tools_used: list[str],
    ) -> None:
        """Extract lessons and write to KB. Safe to fire-and-forget."""
        if not self._enabled:
            return
        if outcome != "completed":
            return  # Only learn from successful outcomes

        try:
            response = await self._router.complete(
                messages=[
                    {"role": "system", "content": _LESSON_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"Task: {goal}\n"
                            f"Outcome: {summary[:600]}\n"
                            f"Tools used: {', '.join(tools_used[:12])}"
                        ),
                    },
                ],
                task_type="simple",
                temperature=0.2,
            )
            data = json.loads(response.content)
            lessons = data.get("lessons", [])
        except Exception as e:
            logger.debug("Lesson extraction LLM call failed: %s", e)
            return

        for lesson in lessons[:2]:  # Cap at 2 per task
            await self._write_lesson(lesson, goal)

    async def compress_content(self, content: str) -> str:
        """Compress verbose content before KB write. Returns compressed string.

        Falls back to original content if LLM call fails or content is already short.
        """
        if _estimate_tokens(content) < 400:
            return content  # Already short — skip

        try:
            response = await self._router.complete(
                messages=[
                    {"role": "system", "content": _COMPRESS_SYSTEM},
                    {"role": "user", "content": content},
                ],
                task_type="simple",
                temperature=0.1,
            )
            compressed = response.content.strip()
            if compressed and len(compressed) < len(content):
                logger.debug(
                    "Compressed KB content: %d → %d chars",
                    len(content),
                    len(compressed),
                )
                return compressed
        except Exception as e:
            logger.debug("Content compression failed: %s", e)

        return content  # Fallback to original

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _write_lesson(self, lesson: dict[str, Any], source_goal: str) -> None:
        """Write a single lesson to knowledge/learned/lessons/<slug>.md."""
        title = lesson.get("title", "Lesson").strip()
        when = lesson.get("when", "").strip()
        text = lesson.get("lesson", "").strip()
        tags = lesson.get("tags", [])

        if not text or not title:
            return

        # Scan for prompt injection before persisting
        from core.injection_guard import scan_for_injection
        from core.pii_guard import redact_pii

        combined = f"{title} {when} {text}"
        is_suspicious, patterns = scan_for_injection(combined)
        if is_suspicious:
            logger.warning(
                "Blocked lesson with injection patterns (%s): %s",
                ", ".join(patterns),
                title,
            )
            return

        # Redact PII from lesson content
        title = redact_pii(title)
        text = redact_pii(text)
        when = redact_pii(when)

        if not text or not title:
            return

        now = datetime.now(UTC)
        date_str = now.strftime("%Y-%m-%d")
        slug = _slugify(title)
        file_path = self._knowledge_dir / f"learned/lessons/{slug}.md"

        if file_path.exists():
            # Merge: append a new observation rather than overwriting
            existing = file_path.read_text(encoding="utf-8")
            observation = (
                f"\n## Observation ({date_str})\n"
                f"*Source task: {source_goal[:200]}*\n\n"
                f"{text}\n"
            )
            updated = existing.rstrip() + "\n" + observation + "\n"
            file_path.write_text(updated, encoding="utf-8")
        else:
            tag_list = ", ".join(tags) if tags else "learned"
            content = (
                f"---\n"
                f"title: {title}\n"
                f"scope: learned\n"
                f"tags: {tag_list}\n"
                f"created: {date_str}\n"
                f"updated: {date_str}\n"
                f"---\n\n"
                f"# {title}\n\n"
                f"## When This Applies\n{when}\n\n"
                f"## Lesson\n{text}\n\n"
                f"## Source\nFirst learned from: {source_goal[:200]}\n"
            )
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        if self._indexer:
            try:
                await self._indexer.index_file(file_path)
                logger.info("Lesson stored: %s", title)
            except Exception as e:
                logger.debug("Failed to index lesson %s: %s", slug, e)
