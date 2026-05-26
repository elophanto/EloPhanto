"""Voice profile + linter for ABE companies (Phase 10).

ABE (Autonomous Business Entity) is a concept originated by Petr
Royce in 2023. See ``docs/76-ABE-FRAMEWORK.md`` §Phase 10.

Each company optionally has a ``data/companies/<slug>/voice.yaml``
file declaring how the company writes — persona, tone, banned
phrases / regex patterns, length bounds, optional allowed-hooks
allowlist. Draft tools (``email_draft``, ``outreach_draft``,
``post_draft``) call ``VoiceManager.lint()`` BEFORE persisting; on
violation the draft is refused and the LLM gets the violation list
in the ToolResult error so it can revise on the next planning cycle.

**Fail-soft.** When no ``voice.yaml`` exists, ``lint()`` returns
``passed=True, violations=[]``. Companies without a voice contract
are not blocked — the operator opts in by running ``voice_extract``
or by writing the file directly.

**Pure / sync.** ``lint()`` is a deterministic string check (banned
phrases, regex, length, hook allowlist). No LLM call, no IO beyond
the cached yaml read. Cheap to call repeatedly from draft tools.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class LengthBounds:
    min_chars: int = 0
    max_chars: int = 0  # 0 = unbounded


@dataclass(slots=True, frozen=True)
class BannedPattern:
    regex: str
    reason: str = ""


@dataclass(slots=True)
class Voice:
    persona: str = ""
    tone: list[str] = field(default_factory=list)
    length_target: LengthBounds = field(default_factory=LengthBounds)
    allowed_hooks: list[str] = field(default_factory=list)
    banned_phrases: list[str] = field(default_factory=list)
    banned_patterns: list[BannedPattern] = field(default_factory=list)
    cta_style: str = ""
    source_path: str = ""


@dataclass(slots=True, frozen=True)
class LintResult:
    passed: bool
    violations: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": list(self.violations),
            "suggestions": list(self.suggestions),
        }


def _default_path(project_root: Path, company_id: str) -> Path:
    """Convention: data/companies/<slug>/voice.yaml under project root.

    Note the path is the *data* dir (generated runtime state), not
    the *source* dir under ``companies/<slug>/``. See verification
    delta #1 in docs/76 §Phase 10.
    """
    return project_root / "data" / "companies" / company_id / "voice.yaml"


def load_voice(
    project_root: Path,
    company_id: str,
    *,
    override_path: Path | None = None,
) -> Voice | None:
    """Load a company's voice YAML.

    Returns ``None`` when the file is missing, unparseable, or not a
    mapping. Never raises — a missing voice file is the normal state
    for any company that hasn't run ``voice_extract`` yet.
    """
    path = override_path or _default_path(project_root, company_id)
    if not path.is_file():
        logger.debug("voice: no yaml at %s", path)
        return None

    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("voice yaml %s parse failed: %s", path, e)
        return None

    if not isinstance(data, dict):
        logger.warning("voice yaml %s: top-level must be a mapping", path)
        return None

    length_raw = data.get("length_target") or {}
    if isinstance(length_raw, dict):
        length = LengthBounds(
            min_chars=int(length_raw.get("min_chars") or 0),
            max_chars=int(length_raw.get("max_chars") or 0),
        )
    else:
        length = LengthBounds()

    patterns: list[BannedPattern] = []
    for entry in data.get("banned_patterns") or []:
        if isinstance(entry, dict) and entry.get("regex"):
            patterns.append(
                BannedPattern(
                    regex=str(entry["regex"]),
                    reason=str(entry.get("reason") or ""),
                )
            )

    return Voice(
        persona=str(data.get("persona") or "").strip(),
        tone=[str(t) for t in (data.get("tone") or [])],
        length_target=length,
        allowed_hooks=[str(h) for h in (data.get("allowed_hooks") or [])],
        banned_phrases=[str(p) for p in (data.get("banned_phrases") or [])],
        banned_patterns=patterns,
        cta_style=str(data.get("cta_style") or "").strip(),
        source_path=str(path),
    )


def lint_text(text: str, voice: Voice, *, channel: str = "") -> LintResult:
    """Run a voice contract over ``text``. Pure function.

    Rules evaluated (each independent, all collected before return):
      1. Banned phrases (case-insensitive substring match).
      2. Banned regex patterns (case-insensitive).
      3. Length bounds (min_chars / max_chars, when set).
      4. Allowed-hooks allowlist (when non-empty): the FIRST non-empty
         line must match at least one allowed hook template. Hook
         templates are treated as substring matches against a slot-
         stripped form (``<x>`` → wildcard). This is intentionally
         permissive — it catches obvious mismatch, not stylistic edge.
    """
    violations: list[str] = []
    suggestions: list[str] = []
    body = text or ""

    # 1. Banned phrases
    lower = body.lower()
    for phrase in voice.banned_phrases:
        if not phrase:
            continue
        if phrase.lower() in lower:
            violations.append(f"banned phrase: {phrase!r}")

    # 2. Banned regex patterns
    for bp in voice.banned_patterns:
        try:
            if re.search(bp.regex, body, flags=re.IGNORECASE | re.MULTILINE):
                reason = f" — {bp.reason}" if bp.reason else ""
                violations.append(f"banned pattern {bp.regex!r}{reason}")
        except re.error as e:
            logger.warning("voice: bad regex %s: %s", bp.regex, e)

    # 3. Length bounds
    lb = voice.length_target
    if lb.min_chars > 0 and len(body) < lb.min_chars:
        violations.append(f"too short: {len(body)} chars (min {lb.min_chars})")
    if lb.max_chars > 0 and len(body) > lb.max_chars:
        violations.append(f"too long: {len(body)} chars (max {lb.max_chars})")

    # 4. Allowed hooks (only when allowlist is non-empty)
    if voice.allowed_hooks:
        first_line = next(
            (line.strip() for line in body.splitlines() if line.strip()),
            "",
        )
        if first_line and not _matches_any_hook(first_line, voice.allowed_hooks):
            violations.append("opening line matches no allowed hook template")
            suggestions.append(
                "rewrite opening line using one of: "
                + ", ".join(voice.allowed_hooks[:3])
                + ("..." if len(voice.allowed_hooks) > 3 else "")
            )

    return LintResult(
        passed=not violations,
        violations=violations,
        suggestions=suggestions,
    )


_SLOT_RE = re.compile(r"<[^>]+>")


def _matches_any_hook(line: str, hooks: list[str]) -> bool:
    """A line matches a hook template if, after replacing ``<slots>``
    with wildcards, the template's non-slot fragments all appear in
    order within the line (case-insensitive)."""
    low = line.lower()
    for hook in hooks:
        fragments = [
            frag.strip().lower() for frag in _SLOT_RE.split(hook) if frag.strip()
        ]
        if not fragments:
            # Template was effectively all slots — match anything.
            return True
        pos = 0
        ok = True
        for frag in fragments:
            idx = low.find(frag, pos)
            if idx < 0:
                ok = False
                break
            pos = idx + len(frag)
        if ok:
            return True
    return False


class VoiceManager:
    """Loads + caches per-company Voice profiles; runs lints.

    Cache is keyed by ``company_id`` and invalidated by ``reload()``.
    Not thread-safe across processes — the cache is process-local
    and tools call ``reload(slug)`` after writing a new voice.yaml
    so the next ``lint()`` picks up the change.
    """

    def __init__(self, project_root: Path | None) -> None:
        self._project_root = project_root
        self._cache: dict[str, Voice | None] = {}

    @property
    def project_root(self) -> Path | None:
        return self._project_root

    def voice_path(self, company_id: str) -> Path | None:
        if self._project_root is None:
            return None
        return _default_path(self._project_root, company_id)

    def exemplars_dir(self, company_id: str, channel: str) -> Path | None:
        if self._project_root is None:
            return None
        return (
            self._project_root
            / "data"
            / "companies"
            / company_id
            / "exemplars"
            / channel
        )

    def get(self, company_id: str) -> Voice | None:
        if self._project_root is None:
            return None
        if company_id not in self._cache:
            self._cache[company_id] = load_voice(self._project_root, company_id)
        return self._cache[company_id]

    def reload(self, company_id: str) -> Voice | None:
        self._cache.pop(company_id, None)
        return self.get(company_id)

    def lint(self, text: str, *, company_id: str, channel: str = "") -> LintResult:
        """Fail-soft lint. Returns ``passed=True`` when no voice
        contract exists for the company (the normal state until the
        operator opts in via voice_extract)."""
        voice = self.get(company_id)
        if voice is None:
            return LintResult(passed=True, violations=[], suggestions=[])
        return lint_text(text, voice, channel=channel)
