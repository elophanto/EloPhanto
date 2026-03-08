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

# ---------------------------------------------------------------------------
# Content Security Policy — blocked and warning patterns (Layer 5)
# ---------------------------------------------------------------------------

SKILL_BLOCKED_PATTERNS: list[tuple[str, str]] = [
    # Download-and-execute
    (r"curl\s.*\|\s*(bash|sh|zsh)", "download-and-execute via curl pipe"),
    (r"wget\s.*\|\s*(bash|sh|zsh)", "download-and-execute via wget pipe"),
    (r"curl\s.*-o\s+\S+\s*&&\s*(bash|sh|chmod)", "download-and-execute via curl file"),
    # Reverse shells
    (r"bash\s+-i\s+>&\s*/dev/tcp", "reverse shell via /dev/tcp"),
    (r"nc\s+-[elp].*\s+-e\s*/bin", "reverse shell via netcat"),
    (r"python.*socket.*connect.*exec", "reverse shell via Python socket"),
    # Credential theft
    (r"cat\s+~/?\.(ssh|aws|gnupg|kube)", "credential file access"),
    (r"tar\s.*~/?\.(ssh|aws|gnupg)", "credential directory archive"),
    (r"scp\s.*~/?\.(ssh|aws)", "credential exfiltration via scp"),
    # Prompt injection
    (r"ignore\s+(all\s+)?previous\s+instructions", "prompt injection attempt"),
    (r"disregard\s+(all\s+)?(prior|above)\s+instructions", "prompt injection attempt"),
    (r"you\s+are\s+now\s+(a\s+)?new\s+ai", "prompt injection / role override"),
    # Obfuscation
    (r"base64\s+-d", "base64 decode obfuscation"),
    (r"eval\s*\(\s*(atob|Buffer\.from)", "eval with decode obfuscation"),
    (r"\\x[0-9a-f]{2}.*\\x[0-9a-f]{2}.*\\x[0-9a-f]{2}", "hex-encoded payload"),
    # Destructive
    (r"rm\s+-rf\s+/(?!\w)", "destructive root deletion"),
]

SKILL_WARNING_PATTERNS: list[tuple[str, str]] = [
    (r"https?://\S+", "contains external URL"),
    (r"pip\s+install\s+", "requests pip package installation"),
    (r"npm\s+install\s+", "requests npm package installation"),
    (r"chmod\s+\+x\s+", "modifies file permissions"),
    (r"sudo\s+", "requests elevated privileges"),
]

# Invisible/confusable unicode characters that can hide malicious content
INVISIBLE_CHARS: dict[str, str] = {
    "\u200b": "zero-width space",
    "\u200c": "zero-width non-joiner",
    "\u200d": "zero-width joiner",
    "\u200e": "left-to-right mark",
    "\u200f": "right-to-left mark",
    "\u2060": "word joiner",
    "\u2061": "function application",
    "\u2062": "invisible times",
    "\u2063": "invisible separator",
    "\u2064": "invisible plus",
    "\ufeff": "zero-width no-break space (BOM)",
    "\u00ad": "soft hyphen",
    "\u034f": "combining grapheme joiner",
    "\u061c": "arabic letter mark",
    "\u115f": "hangul choseong filler",
    "\u1160": "hangul jungseong filler",
    "\u17b4": "khmer vowel inherent aq",
    "\u17b5": "khmer vowel inherent aa",
}


def _detect_invisible_chars(content: str) -> list[str]:
    """Scan for invisible unicode characters that could hide malicious content."""
    findings: list[str] = []
    for char, name in INVISIBLE_CHARS.items():
        positions = [i for i, c in enumerate(content) if c == char]
        if positions:
            # Show first occurrence with surrounding context
            pos = positions[0]
            start = max(0, pos - 20)
            end = min(len(content), pos + 20)
            context = content[start:end].replace(char, f"[{name}]")
            findings.append(
                f"Invisible character '{name}' found {len(positions)} time(s), "
                f"first at position {pos}: ...{context}..."
            )
    return findings


def _check_structural_integrity(skill_dir: Path) -> list[str]:
    """Check skill directory for structural security issues."""
    findings: list[str] = []
    resolved_root = skill_dir.resolve()

    file_count = 0
    total_size = 0

    for path in skill_dir.rglob("*"):
        if path.is_symlink():
            target = path.resolve()
            if not str(target).startswith(str(resolved_root)):
                findings.append(
                    f"Symlink escape: {path.name} -> {target} "
                    f"(outside {resolved_root})"
                )

        if path.is_file():
            file_count += 1
            try:
                total_size += path.stat().st_size
            except OSError:
                pass

            # Check for binary files (outside assets/)
            if "assets" not in path.parts:
                try:
                    chunk = path.read_bytes()[:512]
                    if b"\x00" in chunk:
                        findings.append(f"Binary file detected: {path.name}")
                except OSError:
                    pass

            # Check for executable permission on non-script files
            if "scripts" not in path.parts:
                try:
                    import stat

                    mode = path.stat().st_mode
                    if mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
                        findings.append(f"Executable permission on: {path.name}")
                except OSError:
                    pass

    if file_count > 20:
        findings.append(f"Excessive file count: {file_count} files (limit: 20)")

    if total_size > 512_000:
        findings.append(f"Large skill directory: {total_size // 1024}KB (limit: 500KB)")

    return findings


@dataclass
class Skill:
    """A loaded skill with metadata parsed from its SKILL.md."""

    name: str
    path: Path
    description: str = ""
    triggers: list[str] = field(default_factory=list)
    content: str = ""
    source: str = "local"  # "local", "hub", or "external"
    author_tier: str = ""  # publisher tier from hub
    warnings: list[str] = field(default_factory=list)
    checksum_verified: bool = False

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
                if skill is None:
                    continue  # Blocked by content security policy
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

    def match_skills(self, query: str, max_results: int = 5) -> list[Skill]:
        """Find skills matching the query by triggers, name, and description.

        Scoring priority:
        - Trigger phrase match: +3 (highest signal — skill author defined these)
        - Trigger word overlap: +2
        - Name word overlap: +2 (skill name is a strong signal)
        - Description word overlap: +1 per word (broad net for skills without triggers)

        Returns skills sorted by score, capped at max_results.
        """
        query_lower = query.lower()
        query_words = set(re.findall(r"\w+", query_lower))
        # Filter out very common words that would match too broadly
        stop_words = {
            "a",
            "an",
            "the",
            "me",
            "my",
            "i",
            "is",
            "it",
            "to",
            "for",
            "of",
            "in",
            "on",
            "and",
            "or",
            "do",
            "be",
            "this",
            "that",
            "with",
            "from",
            "can",
            "you",
            "your",
            "we",
            "our",
            "how",
            "what",
            "make",
            "build",
            "create",
            "please",
            "help",
            "want",
        }
        query_keywords = query_words - stop_words

        scored: list[tuple[int, Skill]] = []
        for skill in self._skills.values():
            score = 0

            # Triggers (highest priority — author-defined relevance signals)
            for trigger in skill.triggers:
                trigger_lower = trigger.lower().strip()
                if trigger_lower in query_lower:
                    score += 3
                elif any(w in query_keywords for w in trigger_lower.split()):
                    score += 2

            # Skill name — exact word match + substring match
            # e.g. "website" contains "web" → matches "web-design-guidelines"
            name_words = set(skill.name.lower().replace("-", " ").split())
            name_overlap = query_keywords & name_words
            score += len(name_overlap) * 2
            if not name_overlap:
                for nw in name_words:
                    for qw in query_keywords:
                        if len(nw) >= 3 and (nw in qw or qw in nw):
                            score += 1
                            break

            # Description keywords (broad matching for skills without triggers)
            if skill.description and query_keywords:
                desc_words = set(re.findall(r"\w+", skill.description.lower()))
                desc_overlap = query_keywords & desc_words
                score += len(desc_overlap)

            if score > 0:
                scored.append((score, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:max_results]]

    def format_available_skills(self, query: str = "") -> str:
        """Format skills as an XML block for the system prompt.

        When a query is provided, pre-matches relevant skills and shows them
        with full detail (triggers included). Non-matching skills use a compact
        one-liner format to keep prompt size bounded.

        When nothing matches (e.g. greetings), only a brief count is injected
        so the LLM isn't slowed by irrelevant skill data.
        """
        if not self._skills:
            return ""

        matched = self.match_skills(query, max_results=5) if query else []

        # No matches — minimal footprint (saves ~10K chars vs full XML)
        if not matched:
            return (
                f"<available_skills>\n"
                f"<total>{len(self._skills)} skills available. "
                f"Use skill_list to browse or skill_read to load by name.</total>\n"
                f"</available_skills>"
            )

        # Has matches — show recommended with MUST READ instruction
        matched_names = {s.name for s in matched}
        lines = ["<available_skills>"]
        lines.append("<recommended action='MUST skill_read BEFORE any other work'>")
        for skill in matched:
            self._format_skill_xml(skill, lines)
        lines.append("</recommended>")

        # Remaining skills — show up to 20 compact one-liners, then just count
        others = [s for s in self._skills.values() if s.name not in matched_names]
        if others:
            shown = others[:20]
            lines.append("<other_skills>")
            for skill in shown:
                desc = skill.description[:80] if skill.description else ""
                lines.append(f"  {skill.name} — {desc}")
            if len(others) > 20:
                lines.append(
                    f"  ... and {len(others) - 20} more (use skill_list to browse)"
                )
            lines.append("</other_skills>")

        lines.append(
            f"<total>{len(self._skills)} skills available. "
            "Use skill_read to load any skill by name.</total>"
        )
        lines.append("</available_skills>")
        return "\n".join(lines)

    @staticmethod
    def _format_skill_xml(skill: Skill, lines: list[str]) -> None:
        """Append a single skill's XML representation to lines."""
        warn_attr = ",".join(skill.warnings) if skill.warnings else "none"
        lines.append(
            f'<skill source="{skill.source}" tier="{skill.author_tier or "local"}"'
            f' warnings="{warn_attr}">'
        )
        lines.append(f"<name>{skill.name}</name>")
        lines.append(f"<description>{skill.description}</description>")
        if skill.triggers:
            lines.append(f"<triggers>{', '.join(skill.triggers)}</triggers>")
        lines.append("</skill>")

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
        if skill is None:
            shutil.rmtree(dest)
            raise ValueError(f"Skill '{skill_name}' blocked by content security policy")
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

    @staticmethod
    def _check_skill_safety(
        name: str, content: str, skill_dir: Path | None = None
    ) -> tuple[bool, list[str]]:
        """Scan skill content for blocked and warning patterns.

        Returns (safe, messages) where safe=False means the skill is blocked.
        """
        content_lower = content.lower()

        # Check blocked patterns
        for pattern, reason in SKILL_BLOCKED_PATTERNS:
            if re.search(pattern, content_lower):
                return False, [f"BLOCKED: {reason} (pattern: {pattern})"]

        # Check invisible unicode characters
        warnings: list[str] = []
        unicode_findings = _detect_invisible_chars(content)
        if unicode_findings:
            warnings.extend(unicode_findings)

        # Check structural integrity (if directory provided)
        if skill_dir and skill_dir.is_dir():
            struct_findings = _check_structural_integrity(skill_dir)
            symlink_escapes = [f for f in struct_findings if "Symlink escape" in f]
            if symlink_escapes:
                return False, symlink_escapes
            warnings.extend(struct_findings)

        # Check warning patterns
        for pattern, reason in SKILL_WARNING_PATTERNS:
            if re.search(pattern, content_lower):
                warnings.append(reason)

        return True, warnings

    def _parse_skill(self, name: str, skill_file: Path) -> Skill | None:
        """Parse a SKILL.md file to extract metadata.

        Returns None if the skill is blocked by content security policy.
        """
        content = skill_file.read_text(encoding="utf-8")

        # Content security scan
        safe, messages = self._check_skill_safety(name, content, skill_file.parent)
        if not safe:
            logger.error(
                "Skill '%s' blocked by content security policy: %s",
                name,
                messages[0],
            )
            return None

        description = ""
        triggers: list[str] = []

        # Try YAML frontmatter first (--- block at top of file)
        fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if fm_match:
            fm_block = fm_match.group(1)
            for fm_line in fm_block.splitlines():
                fm_line = fm_line.strip()
                if fm_line.startswith("description:"):
                    description = fm_line.split(":", 1)[1].strip().strip('"').strip("'")
                elif fm_line.startswith("triggers:"):
                    # Inline YAML list: triggers: [a, b, c]
                    val = fm_line.split(":", 1)[1].strip()
                    if val.startswith("["):
                        for t in val.strip("[]").split(","):
                            t = t.strip().strip('"').strip("'")
                            if t:
                                triggers.append(t)

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

        # Determine source from metadata.json if present
        source = "local"
        author_tier = ""
        metadata_file = skill_file.parent / "metadata.json"
        if metadata_file.exists():
            try:
                import json

                meta = json.loads(metadata_file.read_text(encoding="utf-8"))
                if meta.get("source") == "elophantohub":
                    source = "hub"
                author_tier = meta.get("author_tier", "")
            except Exception:
                pass

        return Skill(
            name=name,
            path=skill_file.parent,
            description=description,
            triggers=triggers,
            content=content,
            source=source,
            author_tier=author_tier,
            warnings=messages,
        )
