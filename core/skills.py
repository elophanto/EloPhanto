"""Skills system — discovers, loads, and matches SKILL.md files.

Skills are best-practice guides that the agent reads before starting
specific types of tasks. Each skill lives in a directory with a SKILL.md
file containing triggers, instructions, and examples.

Three tiers:
- Bundled: ship with EloPhanto in skills/
- Installed: pulled from external repos into skills/
- User: created by the user or agent in skills/

All tiers use the same directory convention and are discovered uniformly.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """A loaded skill with metadata parsed from its SKILL.md."""

    name: str
    path: Path
    description: str = ""
    triggers: list[str] = field(default_factory=list)
    content: str = ""

    @property
    def location(self) -> str:
        return str(self.path / "SKILL.md")


class SkillManager:
    """Discovers and manages skills from the skills/ directory."""

    def __init__(self, skills_dir: Path, hub_client: Any = None) -> None:
        self._skills_dir = skills_dir
        self._skills: dict[str, Skill] = {}
        self._hub = hub_client

    @property
    def hub(self) -> Any:
        """Access the hub client (may be None if not configured)."""
        return self._hub

    @hub.setter
    def hub(self, client: Any) -> None:
        self._hub = client

    async def search_hub(self, query: str) -> list:
        """Search EloPhantoHub for matching skills."""
        if self._hub:
            return await self._hub.search(query)
        return []

    async def install_from_hub(self, name: str) -> str:
        """Install a skill from EloPhantoHub by name."""
        if not self._hub:
            raise RuntimeError("EloPhantoHub not configured")
        installed = await self._hub.install(name)
        # Re-discover to pick up the new skill
        self.discover()
        return installed

    def discover(self) -> int:
        """Scan the skills directory and load all valid skills.

        Returns the number of skills discovered.
        """
        self._skills.clear()

        if not self._skills_dir.exists():
            return 0

        for entry in sorted(self._skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith("_") or entry.name.startswith("."):
                continue

            skill_file = entry / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                skill = self._parse_skill(entry.name, skill_file)
                self._skills[skill.name] = skill
            except Exception as e:
                logger.warning(f"Failed to parse skill {entry.name}: {e}")

        logger.info(f"Discovered {len(self._skills)} skills")
        return len(self._skills)

    def list_skills(self) -> list[Skill]:
        """Return all discovered skills."""
        return list(self._skills.values())

    def get_skill(self, name: str) -> Skill | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def read_skill(self, name: str) -> str | None:
        """Read the full SKILL.md content for a skill."""
        skill = self._skills.get(name)
        if skill is None:
            return None
        try:
            return (skill.path / "SKILL.md").read_text(encoding="utf-8")
        except Exception:
            return skill.content

    def match_skills(self, query: str, max_results: int = 3) -> list[Skill]:
        """Find skills whose triggers match the query.

        Uses simple keyword matching against the trigger list.
        Returns skills sorted by match quality (number of triggers hit).
        """
        query_lower = query.lower()
        query_words = set(re.findall(r"\w+", query_lower))

        scored: list[tuple[int, Skill]] = []
        for skill in self._skills.values():
            score = 0
            for trigger in skill.triggers:
                trigger_lower = trigger.lower().strip()
                if trigger_lower in query_lower:
                    score += 2
                elif any(w in query_words for w in trigger_lower.split()):
                    score += 1
            if score > 0:
                scored.append((score, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:max_results]]

    def format_available_skills(self) -> str:
        """Format all skills as an XML block for the system prompt."""
        if not self._skills:
            return ""

        lines = ["<available_skills>"]
        for skill in self._skills.values():
            lines.append("<skill>")
            lines.append(f"<name>{skill.name}</name>")
            lines.append(f"<description>{skill.description}</description>")
            lines.append(f"<location>{skill.location}</location>")
            lines.append("</skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)

    def install_from_directory(self, source: Path, name: str | None = None) -> str:
        """Install a skill from a local directory containing SKILL.md.

        Returns the installed skill name.
        """
        skill_file = source / "SKILL.md"
        if not skill_file.exists():
            raise FileNotFoundError(f"No SKILL.md found in {source}")

        skill_name = name or source.name
        dest = self._skills_dir / skill_name
        if dest.exists():
            raise FileExistsError(f"Skill '{skill_name}' already exists")

        import shutil

        shutil.copytree(source, dest)

        skill = self._parse_skill(skill_name, dest / "SKILL.md")
        self._skills[skill_name] = skill
        logger.info(f"Installed skill: {skill_name}")
        return skill_name

    def remove_skill(self, name: str) -> bool:
        """Remove an installed skill. Returns True if removed."""
        skill = self._skills.get(name)
        if skill is None:
            return False

        import shutil

        if skill.path.exists():
            shutil.rmtree(skill.path)

        del self._skills[name]
        logger.info(f"Removed skill: {name}")
        return True

    def _parse_skill(self, name: str, skill_file: Path) -> Skill:
        """Parse a SKILL.md file to extract metadata."""
        content = skill_file.read_text(encoding="utf-8")

        description = ""
        triggers: list[str] = []

        # Extract description from the first ## Description section
        desc_match = re.search(
            r"##\s*Description\s*\n+(.*?)(?=\n##|\Z)", content, re.DOTALL
        )
        if desc_match:
            description = desc_match.group(1).strip()
            description = description.split("\n")[0].strip()

        # Extract triggers from the ## Triggers section
        trigger_match = re.search(
            r"##\s*Triggers\s*\n+(.*?)(?=\n##|\Z)", content, re.DOTALL
        )
        if trigger_match:
            trigger_block = trigger_match.group(1)
            for line in trigger_block.strip().splitlines():
                line = line.strip().lstrip("- ").strip('"').strip("'")
                if line:
                    triggers.append(line)

        return Skill(
            name=name,
            path=skill_file.parent,
            description=description,
            triggers=triggers,
            content=content,
        )
