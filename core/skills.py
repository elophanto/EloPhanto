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

# Default payload diets — full SKILL.md files routinely run 10–45KB.
# Auto-inject and default skill_read use excerpts; callers opt into full.
_AUTO_SKILL_MAX_CHARS = 2500
_CRITICAL_SKILL_AUTO_CHARS = 9000
_SKILL_READ_SUMMARY_MAX_CHARS = 6000

# Workflow / playbook skills where amputating PATH trees breaks autonomy.
# Auto-inject uses a larger budget so weaker models still see the decision tree.
_CRITICAL_AUTO_SKILLS = frozenset(
    {
        "drive-business",
        "strategy-pipeline",
        "trust-ladder-workflow",
        "voice-extraction-workflow",
        "strategy-foundations",
        "b2c-marketing-voice",
        "browser-automation",
    }
)

_SKIP_EXCERPT_SECTIONS = frozenset(
    {
        "triggers",
        "description",
        "notes",
        "verify",
        "metadata",
        "license",
    }
)


def _skill_section_toc(content: str, limit: int = 24) -> str:
    heads = re.findall(r"^##\s+(.+)$", content, flags=re.MULTILINE)
    if not heads:
        return ""
    shown = [h.strip() for h in heads[:limit]]
    return "\nSections available via depth='full': " + "; ".join(shown)


def excerpt_skill_content(
    content: str,
    max_chars: int,
    skill_name: str = "",
) -> str:
    """Truncate skill body for prompt injection while preserving a reload path.

    Prefers ``## Instructions`` when present; otherwise starts at the first
    operational ``##`` section (skipping Triggers / Description fluff) so
    ABE playbooks without an Instructions heading keep their decision trees.
    Always appends a section TOC when truncating.
    """
    if max_chars <= 0 or len(content) <= max_chars:
        return content

    toc = _skill_section_toc(content)
    pointer = (
        f"\n\n[truncated — call skill_read(skill_name='{skill_name}', "
        f"depth='full') for complete skill]"
        if skill_name
        else "\n\n[truncated — call skill_read depth='full' for complete skill]"
    )

    body = content
    instr = re.search(
        r"(^##\s+Instructions\b.*?)(?=^##\s+|\Z)",
        content,
        flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if instr:
        body = instr.group(1).strip()
        if len(body) <= max_chars:
            return body + pointer + toc

    if not instr:
        # Start at first operational ## heading (Decision tree, PATH, Workflow…)
        for m in re.finditer(r"^##\s+(.+)$", content, flags=re.MULTILINE):
            title = m.group(1).strip().lower()
            # Strip emoji / leading punctuation for skip matching
            title_key = re.sub(r"^[^a-z0-9]+", "", title)
            title_key = title_key.split()[0] if title_key else title
            if title in _SKIP_EXCERPT_SECTIONS or title_key in _SKIP_EXCERPT_SECTIONS:
                continue
            body = content[m.start() :].strip()
            break

    cut = body[:max_chars]
    # Break on a line boundary when possible to avoid mid-token cuts.
    nl = cut.rfind("\n")
    if nl >= max_chars // 2:
        cut = cut[:nl]
    return cut + pointer + toc


def tail_truncate(text: str, max_chars: int) -> str:
    """Keep the *end* of a growing log (scratchpad / recent state)."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    cut = text[-max_chars:]
    nl = cut.find("\n")
    if 0 <= nl < max_chars // 4:
        cut = cut[nl + 1 :]
    return "…[earlier truncated]\n" + cut


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
    verify_checks: list[str] = field(default_factory=list)
    # Conditional surfacing — skill hidden from catalog when prerequisites
    # are unmet. See ``is_available()`` for the gate rules and
    # ``_parse_skill`` for the frontmatter format. Both default to
    # empty (no constraint).
    requires_tools: list[str] = field(default_factory=list)
    fallback_for_tools: list[str] = field(default_factory=list)
    # Runnable-integration contract. A skill that drives an external CLI
    # or REST API is only useful when its binaries are on PATH and its
    # credentials are resolvable; declaring that here turns a prose
    # playbook into something the agent can check before promising it.
    #
    #     ---
    #     requires:
    #       bins: [curl, jq]
    #       any_bins: [gh, hub]
    #       env: [TRELLO_API_KEY, TRELLO_TOKEN]
    #       credentials: [trello]
    #     primary_env: TRELLO_API_KEY
    #     install:
    #       brew: jq
    #       npm: "@example/cli"
    #     ---
    requires_bins: list[str] = field(default_factory=list)
    requires_any_bins: list[str] = field(default_factory=list)
    requires_env: list[str] = field(default_factory=list)
    requires_credentials: list[str] = field(default_factory=list)
    primary_env: str = ""
    install: dict[str, str] = field(default_factory=dict)

    @property
    def location(self) -> str:
        return str(self.path / "SKILL.md")

    def missing_requirements(self) -> list[str]:
        """Which declared prerequisites are not satisfied on this host.

        Returns human-readable strings so the caller can tell the operator
        exactly what to install or export. Empty list means ready to run.
        """
        import os
        import shutil

        missing: list[str] = []
        for binary in self.requires_bins:
            if not shutil.which(binary):
                hint = self._install_hint(binary)
                missing.append(f"binary '{binary}' not on PATH{hint}")
        if self.requires_any_bins and not any(
            shutil.which(b) for b in self.requires_any_bins
        ):
            missing.append(
                "none of these binaries are on PATH: "
                + ", ".join(self.requires_any_bins)
            )
        for var in self.requires_env:
            if not os.environ.get(var):
                missing.append(f"environment variable '{var}' is not set")
        return missing

    def _install_hint(self, binary: str) -> str:
        if not self.install:
            return ""
        parts = [f"{mgr}: {pkg}" for mgr, pkg in self.install.items()]
        return f" (install via {'; '.join(parts)})" if parts else ""

    def is_available(
        self,
        available_tools: set[str] | None,
        *,
        check_host: bool = False,
        available_credentials: set[str] | None = None,
    ) -> bool:
        """Whether this skill should appear in the catalog right now.

        Rules (degrade open — unknown means show):
          - ``available_tools is None``: caller doesn't know the tool
            set, so don't filter. Identical to the legacy behaviour
            before conditional gating existed.
          - ``requires_tools`` non-empty: every named tool must be in
            ``available_tools``. A skill that drives polymarket is
            useless without the polymarket tools.
          - ``fallback_for_tools`` non-empty: hide if ANY named tool
            is loaded. The fallback recipe is only relevant when the
            primary tool isn't available — e.g. a "use curl to scrape
            X" skill should disappear when ``http_get`` is loaded.
          - ``check_host`` (opt-in): also hide when a declared binary or
            environment variable is absent. Off by default because the
            PATH probe costs a stat per binary and most callers only
            want the cheap tool-level filter.
          - ``available_credentials``: when supplied, hide skills whose
            declared credential slugs are not configured.
          - Otherwise: available.
        """
        if available_tools is None:
            return True
        if self.requires_tools:
            if not all(t in available_tools for t in self.requires_tools):
                return False
        if self.fallback_for_tools:
            if any(t in available_tools for t in self.fallback_for_tools):
                return False
        if available_credentials is not None and self.requires_credentials:
            if not all(c in available_credentials for c in self.requires_credentials):
                return False
        if check_host and self.missing_requirements():
            return False
        return True


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

    def read_skill(
        self,
        name: str,
        *,
        depth: str = "full",
        max_chars: int | None = None,
    ) -> str | None:
        """Read SKILL.md content for a skill.

        ``depth='summary'`` returns an excerpt (default budget
        ``_SKILL_READ_SUMMARY_MAX_CHARS``) so tool results don't balloon
        the conversation. ``depth='full'`` returns the entire file.
        """
        skill = self._skills.get(name)
        if skill is None:
            return None
        try:
            content = (skill.path / "SKILL.md").read_text(encoding="utf-8")
        except Exception:
            content = skill.content
        if content is None:
            return None
        depth_norm = (depth or "full").strip().lower()
        if depth_norm in ("full", "complete", "all"):
            return content
        budget = max_chars if max_chars is not None else _SKILL_READ_SUMMARY_MAX_CHARS
        return excerpt_skill_content(content, budget, skill_name=name)

    def match_skills(
        self,
        query: str,
        max_results: int = 5,
        available_tools: set[str] | None = None,
    ) -> list[Skill]:
        """Find skills matching the query by triggers, name, and description.

        Scoring priority:
        - Trigger phrase match: +3 (highest signal — skill author defined these)
        - Trigger word overlap: +2
        - Name word overlap: +2 (skill name is a strong signal)
        - Description word overlap: +1 per word (broad net for skills without triggers)

        ``available_tools`` filters via ``Skill.is_available`` before
        scoring — a skill that ``requires_tools: [polymarket_*]`` will
        not appear in matches when those tools aren't loaded. Pass
        ``None`` to disable filtering (legacy behaviour).

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
            if not skill.is_available(available_tools):
                continue
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

    def match_skills_with_scores(
        self,
        query: str,
        max_results: int = 5,
        available_tools: set[str] | None = None,
    ) -> list[tuple[int, Skill]]:
        """Same matching as match_skills but exposes the raw score.

        Used by callers that need to apply a confidence threshold —
        e.g. the verification-required prompt injection gates on a
        higher score than the auto-load to avoid forcing checks on
        weak matches.

        ``available_tools`` is forwarded to ``match_skills`` and gates
        out skills whose prerequisites aren't loaded.
        """
        ranked = self.match_skills(
            query, max_results=max_results * 4, available_tools=available_tools
        )
        out: list[tuple[int, Skill]] = []
        for skill in ranked:
            out.append((self._score_skill(query, skill), skill))
        out.sort(key=lambda x: x[0], reverse=True)
        return out[:max_results]

    def _score_skill(self, query: str, skill: Skill) -> int:
        """Re-score a single skill against a query using the same logic
        as match_skills. Kept private so the rules stay in one place."""
        query_lower = query.lower()
        query_words = set(re.findall(r"\w+", query_lower))
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
        keywords = query_words - stop_words
        score = 0
        for trigger in skill.triggers:
            tl = trigger.lower().strip()
            if tl in query_lower:
                score += 3
            elif any(w in keywords for w in tl.split()):
                score += 2
        name_words = set(skill.name.lower().replace("-", " ").split())
        overlap = keywords & name_words
        score += len(overlap) * 2
        if not overlap:
            for nw in name_words:
                for qw in keywords:
                    if len(nw) >= 3 and (nw in qw or qw in nw):
                        score += 1
                        break
        if skill.description and keywords:
            desc_words = set(re.findall(r"\w+", skill.description.lower()))
            score += len(keywords & desc_words)
        return score

    def format_available_skills(
        self, query: str = "", available_tools: set[str] | None = None
    ) -> str:
        """Format skills as an XML block for the system prompt.

        When a query is provided, pre-matches relevant skills and shows them
        with full detail (triggers included). Non-matching skills use a compact
        one-liner format to keep prompt size bounded.

        When nothing matches (e.g. greetings), only a brief count is injected
        so the LLM isn't slowed by irrelevant skill data.

        ``available_tools`` (when supplied) hides skills whose
        ``requires_tools`` aren't all present, and hides ``fallback_for_tools``
        skills when their primary tool IS present. Pass the registry's
        live tool-name set; pass ``None`` to disable filtering.
        """
        if not self._skills:
            return ""

        # max_results=3: prompt-size audit (2026-05-26) showed 5 matches
        # pushing the recommended XML to ~3.5KB for ABE-heavy queries
        # (drive-business + strategy-pipeline + trust-ladder + voice +
        # strategy-foundations all match). 3 keeps the most relevant +
        # cuts ~1.5KB per turn. The LLM can still skill_read others
        # from the <other_skills> one-liner list.
        matched = (
            self.match_skills(query, max_results=3, available_tools=available_tools)
            if query
            else []
        )

        # Visible universe for counts and the <other_skills> list.
        # Filtering once up here keeps the three downstream uses in sync.
        visible_skills = [
            s for s in self._skills.values() if s.is_available(available_tools)
        ]
        visible_total = len(visible_skills)

        # No matches — minimal footprint (saves ~10K chars vs full XML)
        if not matched:
            return (
                f"<available_skills>\n"
                f"<total>{visible_total} skills available. "
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
        others = [s for s in visible_skills if s.name not in matched_names]
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
            f"<total>{visible_total} skills available. "
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
        # Strip fenced code blocks — they are documentation examples,
        # not executable instructions, and should not trigger security rules.
        stripped = re.sub(r"```[^\n]*\n.*?```", "", content, flags=re.DOTALL)
        content_lower = stripped.lower()

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
        requires_tools: list[str] = []
        fallback_for_tools: list[str] = []

        def _parse_inline_list(value: str) -> list[str]:
            """Parse the inline YAML list form ``[a, b, c]`` → list of strings."""
            value = value.strip()
            if not value.startswith("["):
                return []
            return [
                t.strip().strip('"').strip("'")
                for t in value.strip("[]").split(",")
                if t.strip().strip('"').strip("'")
            ]

        requires_bins: list[str] = []
        requires_any_bins: list[str] = []
        requires_env: list[str] = []
        requires_credentials: list[str] = []
        primary_env = ""
        install: dict[str, str] = {}

        def _as_str_list(value: Any) -> list[str]:
            if isinstance(value, str):
                return [value] if value.strip() else []
            if isinstance(value, list):
                return [str(v).strip() for v in value if str(v).strip()]
            return []

        # Try YAML frontmatter first (--- block at top of file).
        fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if fm_match:
            fm_block = fm_match.group(1)
            fm: dict[str, Any] = {}
            try:
                import yaml

                loaded = yaml.safe_load(fm_block)
                if isinstance(loaded, dict):
                    fm = loaded
            except Exception as exc:
                # A malformed block must not lose the skill — fall through
                # to the line parser, which handles the flat inline forms.
                logger.debug("Skill %r frontmatter is not valid YAML: %s", name, exc)

            if fm:
                if fm.get("description"):
                    description = str(fm["description"]).strip()
                triggers.extend(_as_str_list(fm.get("triggers")))
                requires_tools = _as_str_list(fm.get("requires_tools"))
                fallback_for_tools = _as_str_list(fm.get("fallback_for_tools"))
                primary_env = str(fm.get("primary_env", "") or "").strip()
                raw_requires = fm.get("requires")
                if isinstance(raw_requires, dict):
                    requires_bins = _as_str_list(raw_requires.get("bins"))
                    requires_any_bins = _as_str_list(raw_requires.get("any_bins"))
                    requires_env = _as_str_list(raw_requires.get("env"))
                    requires_credentials = _as_str_list(raw_requires.get("credentials"))
                elif isinstance(raw_requires, list):
                    # Shorthand: `requires: [curl, jq]` means binaries.
                    requires_bins = _as_str_list(raw_requires)
                raw_install = fm.get("install")
                if isinstance(raw_install, dict):
                    install = {
                        str(k): str(v) for k, v in raw_install.items() if v is not None
                    }
            else:
                for fm_line in fm_block.splitlines():
                    fm_line = fm_line.strip()
                    if fm_line.startswith("description:"):
                        description = (
                            fm_line.split(":", 1)[1].strip().strip('"').strip("'")
                        )
                    elif fm_line.startswith("triggers:"):
                        triggers.extend(_parse_inline_list(fm_line.split(":", 1)[1]))
                    elif fm_line.startswith("requires_tools:"):
                        requires_tools = _parse_inline_list(fm_line.split(":", 1)[1])
                    elif fm_line.startswith("fallback_for_tools:"):
                        fallback_for_tools = _parse_inline_list(
                            fm_line.split(":", 1)[1]
                        )

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

        # Extract verify checks from the ## Verify section. Each non-empty
        # bullet ('- ', '* ', '+ ') becomes one post-condition. Numbered
        # lists are accepted too. Plain prose (non-bullet lines) is
        # ignored — we want machine-actionable assertions, not commentary.
        verify_checks: list[str] = []
        verify_match = re.search(
            r"##\s*Verify\s*\n+(.*?)(?=\n##|\Z)", content, re.DOTALL | re.IGNORECASE
        )
        if verify_match:
            for line in verify_match.group(1).splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                # Bullet or numbered list item
                m = re.match(r"^(?:[-*+]|\d+[.)])\s+(.*)", stripped)
                if m:
                    check = m.group(1).strip().strip('"').strip("'")
                    if check:
                        verify_checks.append(check)

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
            verify_checks=verify_checks,
            requires_tools=requires_tools,
            fallback_for_tools=fallback_for_tools,
            requires_bins=requires_bins,
            requires_any_bins=requires_any_bins,
            requires_env=requires_env,
            requires_credentials=requires_credentials,
            primary_env=primary_env,
            install=install,
        )
