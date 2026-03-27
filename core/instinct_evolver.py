"""Instinct evolution engine: promotes high-confidence instincts into skills.

When instincts cluster around a pattern and reach high confidence,
they can evolve into full SKILL.md files that the agent loads automatically.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def evolve_instincts(
    instinct_store: Any,
    router: Any,
    skills_dir: Path,
    min_confidence: float = 0.9,
    min_observations: int = 5,
    min_cluster_size: int = 3,
) -> list[dict[str, str]]:
    """Check instincts for evolution candidates and generate skills.

    Returns list of created skills: [{"name": ..., "path": ...}].
    """
    candidates = instinct_store.get_evolution_candidates(min_confidence)
    if not candidates:
        return []

    # Cluster by tag overlap
    clusters: dict[str, list[Any]] = {}
    for inst in candidates:
        for tag in inst.tags:
            clusters.setdefault(tag, []).append(inst)

    # Find clusters large enough to form a skill
    created_skills: list[dict[str, str]] = []
    processed_ids: set[str] = set()

    for tag, instincts in sorted(
        clusters.items(), key=lambda x: len(x[1]), reverse=True
    ):
        # Filter already-processed instincts
        fresh = [i for i in instincts if i.id not in processed_ids]
        if len(fresh) < min_cluster_size:
            continue

        # Generate skill from cluster
        skill_name = f"learned-{tag}"
        skill_dir = skills_dir / skill_name

        # Don't overwrite curated skills
        if skill_dir.exists() and (skill_dir / "SKILL.md").exists():
            prov = skill_dir / ".provenance.json"
            if not prov.exists():
                # Curated skill — skip
                continue

        try:
            skill_content = await _generate_skill(
                router, tag, fresh[:10]  # Cap at 10 instincts per skill
            )
            if not skill_content:
                continue

            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")

            # Write provenance
            now = datetime.now(UTC).isoformat()
            (skill_dir / ".provenance.json").write_text(
                json.dumps(
                    {
                        "source": "instinct-evolution",
                        "created_at": now,
                        "confidence": sum(i.confidence for i in fresh) / len(fresh),
                        "evidence_count": sum(i.observation_count for i in fresh),
                        "origin_instinct_ids": [i.id for i in fresh],
                        "author": "auto-evolved",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            for i in fresh:
                processed_ids.add(i.id)

            created_skills.append(
                {"name": skill_name, "path": str(skill_dir / "SKILL.md")}
            )
            logger.info(
                "[evolve] Created skill '%s' from %d instincts",
                skill_name,
                len(fresh),
            )

        except Exception as e:
            logger.warning("[evolve] Failed to create skill '%s': %s", skill_name, e)

    return created_skills


async def _generate_skill(router: Any, tag: str, instincts: list[Any]) -> str | None:
    """Use LLM to generate a SKILL.md from a cluster of instincts."""
    instinct_text = "\n".join(
        f"- WHEN: {i.trigger}\n  DO: {i.action}\n  (confidence: {i.confidence}, "
        f"seen {i.observation_count}x)"
        for i in instincts
    )

    prompt = (
        f"Generate a SKILL.md file from these learned behavioral patterns "
        f"around '{tag}':\n\n{instinct_text}\n\n"
        f"The SKILL.md must have:\n"
        f"1. YAML frontmatter with name and description\n"
        f"2. A Triggers section with trigger phrases\n"
        f"3. An Instructions section synthesizing the instincts into a "
        f"coherent workflow\n\n"
        f"Return ONLY the SKILL.md content, nothing else."
    )

    try:
        response = await router.complete(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You generate SKILL.md files for an AI agent. "
                        "Use the standard format: YAML frontmatter (name, "
                        "description), ## Triggers section, ## Instructions "
                        "section. Be concise and actionable."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            task_type="simple",
            temperature=0.3,
        )
        content = (response.content or "").strip()
        if content and "---" in content and "## " in content:
            return content
    except Exception as e:
        logger.debug("Skill generation LLM call failed: %s", e)

    return None
