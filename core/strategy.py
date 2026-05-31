"""Strategy artifact + Blocker model + StrategyManager (ABE Phase 11).

ABE (Autonomous Business Entity) is a concept originated by Petr
Royce in 2023. See ``docs/76-ABE-FRAMEWORK.md`` §Phase 11.

Strategies live under
``data/companies/<slug>/strategy/{proposed,active,archive}/``.

- ``proposed/<ISO_timestamp>.yaml`` — fresh LLM output from
  ``company_plan``; not yet approved.
- ``active/strategy.yaml`` — the in-force strategy. Read by the
  autonomous mind, the report, the candidate generators.
- ``archive/<ISO_timestamp>.yaml`` — superseded prior strategies.

Each ``company_plan`` call writes a new proposal. ``company_plan_apply``
copies a chosen proposal to ``active/`` and moves the prior active
strategy to ``archive/``. Strategies COMPOSE over time — the operator's
note: "job does not end in 14 days; new strategy will appear."

The schema mirrors ``tmp/strategy.js`` 1:1 (operator's other app)
plus 5 EloPhanto-specific extensions:
``vault_requirements``, ``tool_requirements``, ``voice_seed``,
``agent_role_assignments``, ``execution_priority``.

The loader is fail-soft: missing strategy → ``None``; malformed
YAML → ``None`` with a logged warning. Companies without a
strategy operate exactly as they did pre-Phase-11.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Tool-name alias map for blocker resolution.
#
# Strategy YAMLs are written by an LLM (``company_plan``) that often
# hallucinates capability names that don't exist in the registry:
# ``x_post_and_reply`` instead of ``twitter_post`` + ``twitter_reply``,
# ``utm_builder`` instead of ``link_compose``, etc. Without this map
# the autonomous mind kept burning cycles on
# ``self_create_plugin(goal='build x_post_and_reply')`` even though
# the capability already shipped under a different name.
#
# Entry shape: ``"author_side_name": {"<registry_name>", ...}``.
# A blocker requiring the author-side name is treated as resolved
# when ALL registry-side names in the set are present in the live
# tool registry. Use ``frozenset()`` (empty) for an alias that maps
# to "any registered tool is enough" — not currently used.
#
# Add aliases here as the strategy LLM keeps inventing the same
# missing names; alternatively fix it upstream by validating tool
# names at ``company_plan`` write time. Both are valid; the alias
# map is the cheap layer that catches what slips through.
_TOOL_ALIASES: dict[str, frozenset[str]] = {
    "x_post_and_reply": frozenset({"twitter_post", "twitter_reply"}),
    "x_post": frozenset({"twitter_post"}),
    "x_reply": frozenset({"twitter_reply"}),
    "twitter_post_and_reply": frozenset({"twitter_post", "twitter_reply"}),
}


# ── Blocker model ───────────────────────────────────────────────────


_VALID_BLOCKER_TYPES: tuple[str, ...] = (
    "missing_vault_credential",
    "missing_tool",
    "missing_skill",
    "voice_conflict",
    "budget_constraint",
)

_VALID_RESOLUTIONS: tuple[str, ...] = ("ask", "build", "defer")


@dataclass(slots=True)
class Blocker:
    id: str
    type: str  # one of _VALID_BLOCKER_TYPES
    description: str
    affected_tactics: list[str] = field(default_factory=list)
    resolution_proposal: str = "ask"  # one of _VALID_RESOLUTIONS
    build_method: str | None = None  # "self_create_plugin" | "skill_promote"
    build_hint: str = ""
    resolved_at: str | None = None
    resolved_by: str | None = None
    resolved_method: str | None = None

    def is_resolved(self) -> bool:
        return self.resolved_at is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "description": self.description,
            "affected_tactics": list(self.affected_tactics),
            "resolution_proposal": self.resolution_proposal,
            "build_method": self.build_method,
            "build_hint": self.build_hint,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
            "resolved_method": self.resolved_method,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Blocker:
        return cls(
            id=str(d.get("id") or ""),
            type=str(d.get("type") or "missing_tool"),
            description=str(d.get("description") or ""),
            affected_tactics=list(d.get("affected_tactics") or []),
            resolution_proposal=str(d.get("resolution_proposal") or "ask"),
            build_method=d.get("build_method"),
            build_hint=str(d.get("build_hint") or ""),
            resolved_at=d.get("resolved_at"),
            resolved_by=d.get("resolved_by"),
            resolved_method=d.get("resolved_method"),
        )


# ── Strategy artifact ──────────────────────────────────────────────


@dataclass(slots=True)
class Strategy:
    """Loaded strategy.yaml. Mirrors tmp/strategy.js output schema
    1:1 with 5 EloPhanto extensions. Everything optional — strategies
    arrive in various levels of completeness from the LLM."""

    # Provenance
    source_path: str = ""
    created_at: str = ""

    # Direct port of tmp/strategy.js
    assumptions: list[str] = field(default_factory=list)
    inputs_to_confirm: list[str] = field(default_factory=list)
    strategy_name: str = ""
    tagline: str = ""
    strategic_insight: str = ""
    overview: str = ""
    core_message: str = ""
    positioning_statement: str = ""
    audience_segments: list[dict[str, Any]] = field(default_factory=list)
    offer_and_funnel: dict[str, Any] = field(default_factory=dict)
    tactics: list[dict[str, Any]] = field(default_factory=list)
    content_ideas: list[dict[str, Any]] = field(default_factory=list)
    creative_directions: list[dict[str, Any]] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    risks: list[dict[str, str]] = field(default_factory=list)
    experiment_roadmap: list[dict[str, Any]] = field(default_factory=list)
    measurement_plan: dict[str, Any] = field(default_factory=dict)
    timeline: dict[str, list[str]] = field(default_factory=dict)
    budget_allocation: dict[str, str] = field(default_factory=dict)
    resource_allocation: dict[str, str] = field(default_factory=dict)
    quick_wins: list[str] = field(default_factory=list)
    long_term_plays: list[str] = field(default_factory=list)
    projected_roi: dict[str, str] = field(default_factory=dict)

    # EloPhanto extensions
    vault_requirements: list[dict[str, Any]] = field(default_factory=list)
    tool_requirements: list[dict[str, Any]] = field(default_factory=list)
    voice_seed: dict[str, Any] = field(default_factory=dict)
    agent_role_assignments: dict[str, list[str]] = field(default_factory=dict)
    execution_priority: str = "staged"  # immediate | staged | experimental

    def tactic_by_id(self, tactic_id: str) -> dict[str, Any] | None:
        """Tactic id convention: 't<priority>' for ports from
        tmp/strategy.js (priority is the array index 1-N). Apply
        accepts either explicit 'id' or derives from priority."""
        for t in self.tactics:
            tid = str(t.get("id") or f"t{t.get('priority', '?')}")
            if tid == tactic_id:
                return t
        return None


# ── Loader ─────────────────────────────────────────────────────────


def active_path(project_root: Path, company_id: str) -> Path:
    return (
        project_root
        / "data"
        / "companies"
        / company_id
        / "strategy"
        / "active"
        / "strategy.yaml"
    )


def proposed_dir(project_root: Path, company_id: str) -> Path:
    return project_root / "data" / "companies" / company_id / "strategy" / "proposed"


def archive_dir(project_root: Path, company_id: str) -> Path:
    return project_root / "data" / "companies" / company_id / "strategy" / "archive"


def blockers_yaml_path(project_root: Path, company_id: str) -> Path:
    return project_root / "data" / "companies" / company_id / "blockers.yaml"


_PORT_MAP: dict[str, str] = {
    # tmp/strategy.js (camelCase) → Strategy dataclass attr (snake_case)
    "assumptions": "assumptions",
    "inputsToConfirm": "inputs_to_confirm",
    "strategyName": "strategy_name",
    "tagline": "tagline",
    "strategicInsight": "strategic_insight",
    "overview": "overview",
    "coreMessage": "core_message",
    "positioningStatement": "positioning_statement",
    "audienceSegments": "audience_segments",
    "offerAndFunnel": "offer_and_funnel",
    "tactics": "tactics",
    "contentIdeas": "content_ideas",
    "creativeDirections": "creative_directions",
    "metrics": "metrics",
    "risks": "risks",
    "experimentRoadmap": "experiment_roadmap",
    "measurementPlan": "measurement_plan",
    "timeline": "timeline",
    "budgetAllocation": "budget_allocation",
    "resourceAllocation": "resource_allocation",
    "quickWins": "quick_wins",
    "longTermPlays": "long_term_plays",
    "projectedROI": "projected_roi",
    # EloPhanto extensions (snake_case on both sides)
    "vault_requirements": "vault_requirements",
    "tool_requirements": "tool_requirements",
    "voice_seed": "voice_seed",
    "agent_role_assignments": "agent_role_assignments",
    "execution_priority": "execution_priority",
}


def load_strategy(
    project_root: Path,
    company_id: str,
    *,
    override_path: Path | None = None,
) -> Strategy | None:
    """Load the active strategy.yaml for a company. Fail-soft.

    Returns ``None`` when the file is missing, unparseable, or not
    a mapping. Never raises.
    """
    path = override_path or active_path(project_root, company_id)
    if not path.is_file():
        logger.debug("strategy: no active strategy at %s", path)
        return None
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("strategy yaml %s parse failed: %s", path, e)
        return None
    if not isinstance(data, dict):
        logger.warning("strategy yaml %s: top-level must be a mapping", path)
        return None

    s = Strategy(source_path=str(path), created_at=str(data.get("_created_at") or ""))
    for src_key, attr in _PORT_MAP.items():
        if src_key in data:
            try:
                setattr(s, attr, data[src_key])
            except (TypeError, ValueError) as e:
                logger.warning(
                    "strategy yaml %s: bad value for %s (%s)", path, src_key, e
                )
    return s


def load_blockers(project_root: Path, company_id: str) -> list[Blocker]:
    """Load the structured blockers.yaml. Returns empty list when
    missing — companies without an active strategy have no blockers."""
    path = blockers_yaml_path(project_root, company_id)
    if not path.is_file():
        return []
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("blockers yaml %s parse failed: %s", path, e)
        return []
    if not isinstance(data, dict):
        return []
    rows = data.get("blockers") or []
    if not isinstance(rows, list):
        return []
    return [Blocker.from_dict(r) for r in rows if isinstance(r, dict)]


def auto_resolve_blockers(
    project_root: Path,
    *,
    registry: Any = None,
    skills_dir: Path | None = None,
) -> dict[str, int]:
    """Sweep every company's ``blockers.yaml``. For each unresolved
    blocker, check whether the underlying gap is closed now and mark
    it resolved if so.

    Closes the autonomy loop: when `self_create_plugin` succeeds and
    registers a new tool (or `skill_promote` writes a new SKILL.md),
    the corresponding ``missing_tool`` / ``missing_skill`` blocker in
    ``blockers.yaml`` would otherwise sit open until the operator
    runs ``elophanto strategy blockers resolve`` manually. This
    function detects current registry / filesystem state and updates
    the blocker rows to ``resolved_at=<now>, resolved_by='auto',
    resolved_method='registry_check'``.

    Called from two sites:
    1. Top of ``from_buildable_blockers`` candidate generator —
       defensive sweep on every arbiter wakeup. Eventually consistent.
    2. After successful ``self_create_plugin`` / ``skill_promote``
       — immediate sweep so the operator sees the resolution without
       waiting for the next autonomous cycle.

    Returns ``{company_id: resolved_count}`` for observability.
    Failures in one company never abort the rest — each is wrapped
    in its own try/except, the operator just doesn't see a sweep
    for that one until next pass.
    """
    out: dict[str, int] = {}
    if project_root is None:
        return out

    # Build the set of currently-known tool names (cheap — registry
    # is in-memory) and installed skill slugs (filesystem walk).
    known_tools: set[str] = set()
    if registry is not None:
        try:
            for t in registry.all_tools():
                known_tools.add(t.name)
        except Exception:
            pass
    known_skills: set[str] = set()
    skills_root = skills_dir if skills_dir is not None else (project_root / "skills")
    if skills_root.is_dir():
        try:
            for entry in skills_root.iterdir():
                if entry.is_dir() and (entry / "SKILL.md").is_file():
                    known_skills.add(entry.name)
        except Exception:
            pass

    # Iterate per-company blockers files
    data_companies = project_root / "data" / "companies"
    if not data_companies.is_dir():
        return out
    for company_dir in data_companies.iterdir():
        if not company_dir.is_dir():
            continue
        company_id = company_dir.name
        try:
            blockers = load_blockers(project_root, company_id)
        except Exception:
            continue
        if not blockers:
            continue

        resolved_now = 0
        now_iso = datetime.now(UTC).isoformat()
        for b in blockers:
            if b.is_resolved():
                continue
            closed = False
            if b.type == "missing_tool":
                # Build hints carry the tool name in `description` like
                # "Strategy needs tool `linkedin_post` — ...". We don't
                # parse the description; the apply tool wrote the
                # `build_method` and the metadata. For now match
                # against the description text — backticks-wrapped tool
                # name is the convention.
                # Cleaner: explicit `target_tool_name` field — TODO if
                # this proves fragile. For now, accept either pattern.
                hit = next(
                    (
                        name
                        for name in known_tools
                        if f"`{name}`" in b.description or name in (b.build_hint or "")
                    ),
                    None,
                )
                if hit:
                    closed = True
                # Alias fallback: the strategy LLM frequently invents
                # author-side capability names (``x_post_and_reply``)
                # that map to a set of existing registry tools
                # (``twitter_post`` + ``twitter_reply``). Without this
                # check the blocker sits open forever even though the
                # capability already ships. See _TOOL_ALIASES for the
                # mapping; add entries there when a new alias is
                # observed in production.
                if not closed:
                    for alias, required in _TOOL_ALIASES.items():
                        if f"`{alias}`" in b.description or alias in (
                            b.build_hint or ""
                        ):
                            if required and required.issubset(known_tools):
                                closed = True
                                break
            elif b.type == "missing_skill":
                hit = next(
                    (
                        name
                        for name in known_skills
                        if name in b.description or name in (b.build_hint or "")
                    ),
                    None,
                )
                if hit:
                    closed = True
            if closed:
                b.resolved_at = now_iso
                b.resolved_by = "auto"
                b.resolved_method = "registry_check"
                resolved_now += 1

        if resolved_now > 0:
            try:
                save_blockers(project_root, company_id, blockers)
                logger.info(
                    "auto_resolve_blockers: %s — %d blocker(s) closed",
                    company_id,
                    resolved_now,
                )
            except Exception as e:
                logger.warning(
                    "auto_resolve_blockers: %s save failed: %s", company_id, e
                )
            out[company_id] = resolved_now

    return out


def save_blockers(project_root: Path, company_id: str, blockers: list[Blocker]) -> Path:
    import yaml

    path = blockers_yaml_path(project_root, company_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"blockers": [b.as_dict() for b in blockers]}
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


# ── Manager ────────────────────────────────────────────────────────


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")


class StrategyManager:
    """Versioned strategy artifact manager.

    Not thread-safe across processes; safe within a single async
    event loop. Cache invalidates on ``reload(slug)`` so callers
    that mutate the active strategy on disk can pick up the change.
    """

    def __init__(self, project_root: Path | None) -> None:
        self._project_root = project_root
        self._cache: dict[str, Strategy | None] = {}

    @property
    def project_root(self) -> Path | None:
        return self._project_root

    def active_path(self, company_id: str) -> Path | None:
        if self._project_root is None:
            return None
        return active_path(self._project_root, company_id)

    def proposed_dir(self, company_id: str) -> Path | None:
        if self._project_root is None:
            return None
        return proposed_dir(self._project_root, company_id)

    def archive_dir(self, company_id: str) -> Path | None:
        if self._project_root is None:
            return None
        return archive_dir(self._project_root, company_id)

    def get_active(self, company_id: str) -> Strategy | None:
        if self._project_root is None:
            return None
        if company_id not in self._cache:
            self._cache[company_id] = load_strategy(self._project_root, company_id)
        return self._cache[company_id]

    def reload(self, company_id: str) -> Strategy | None:
        self._cache.pop(company_id, None)
        return self.get_active(company_id)

    def list_proposed(self, company_id: str) -> list[Path]:
        d = self.proposed_dir(company_id)
        if d is None or not d.is_dir():
            return []
        return sorted(d.glob("*.yaml"))

    def list_archive(self, company_id: str) -> list[Path]:
        d = self.archive_dir(company_id)
        if d is None or not d.is_dir():
            return []
        return sorted(d.glob("*.yaml"))

    def write_proposal(self, company_id: str, payload: dict[str, Any]) -> Path:
        """Write a fresh LLM strategy proposal as a versioned YAML."""
        import yaml

        d = self.proposed_dir(company_id)
        if d is None:
            raise RuntimeError("strategy: no project_root configured")
        d.mkdir(parents=True, exist_ok=True)
        stamp = _utc_stamp()
        path = d / f"{stamp}.yaml"
        # Embed provenance so the load step can read it back
        payload_with_meta = {"_created_at": stamp, **payload}
        path.write_text(
            yaml.safe_dump(payload_with_meta, sort_keys=False),
            encoding="utf-8",
        )
        return path

    def promote_proposal(
        self, company_id: str, proposal_path: Path
    ) -> tuple[Path, Path | None]:
        """Promote a proposed/<ts>.yaml to active/strategy.yaml.

        Archives the prior active (if any) to archive/<ts>.yaml.
        Returns ``(new_active_path, archived_prior_path_or_None)``.
        Invalidates the cache so callers reading get_active() see
        the new state immediately.
        """
        if self._project_root is None:
            raise RuntimeError("strategy: no project_root configured")
        if not proposal_path.is_file():
            raise FileNotFoundError(proposal_path)
        active = active_path(self._project_root, company_id)
        active.parent.mkdir(parents=True, exist_ok=True)

        archived: Path | None = None
        if active.is_file():
            arch = archive_dir(self._project_root, company_id)
            arch.mkdir(parents=True, exist_ok=True)
            archived = arch / f"{_utc_stamp()}.yaml"
            shutil.move(str(active), str(archived))

        shutil.copy2(str(proposal_path), str(active))
        self._cache.pop(company_id, None)
        return active, archived

    def has_active(self, company_id: str) -> bool:
        p = self.active_path(company_id)
        return p is not None and p.is_file()

    def blocker_count(self, company_id: str) -> int:
        """Cheap read for the state snapshot — counts unresolved
        blockers. Returns 0 when blockers.yaml is absent."""
        if self._project_root is None:
            return 0
        blockers = load_blockers(self._project_root, company_id)
        return sum(1 for b in blockers if not b.is_resolved())
