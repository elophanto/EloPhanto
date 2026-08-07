"""Falsifiable self-accounting — personality rules, nuclear scenes, who-are-you.

Doctrine (docs/17-IDENTITY.md):
  Reality grades the self; marketing does not.
  Estimation ≠ control — no trait floats in the live system prompt.
  Who-are-you is compiled from DB rows with mechanical cite-check.
  Strong personality_rules: propose → operator confirm.
  Enforcement is personality_lint (deterministic), not prompt hope.

McAdams actor/agent/author is a docs metaphor only — never BFI/OCEAN scores.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from core.database import Database

logger = logging.getLogger(__name__)

RuntimeFactSource = Callable[[], list[str] | Awaitable[list[str]]]

_CITE_RE = re.compile(r"\b(?:rule|scene|caution)-([a-zA-Z0-9_-]+)\b")
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+|[^.!?]+$")

# Kinds with deterministic observables. custom requires measurable_observable.
_MEASURABLE_KINDS = frozenset({"brevity", "anti_hype", "deference", "custom"})

_DEFAULT_ANTI_HYPE = (
    "revolutionary",
    "game-changer",
    "game changer",
    "disrupt",
    "synergy",
    "leverage ai",
    "cutting-edge",
    "world-class",
    "thrilled to announce",
)


@dataclass
class MeasurableObservable:
    """Deterministic lint surface for a personality_rule."""

    max_sentences: int | None = None
    max_chars: int | None = None
    forbid_phrases: list[str] = field(default_factory=list)
    forbid_regex: list[str] = field(default_factory=list)
    require_ask_before_assert: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_sentences": self.max_sentences,
            "max_chars": self.max_chars,
            "forbid_phrases": list(self.forbid_phrases),
            "forbid_regex": list(self.forbid_regex),
            "require_ask_before_assert": self.require_ask_before_assert,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> MeasurableObservable:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            max_sentences=_opt_int(raw.get("max_sentences")),
            max_chars=_opt_int(raw.get("max_chars")),
            forbid_phrases=[str(p) for p in (raw.get("forbid_phrases") or []) if p],
            forbid_regex=[str(p) for p in (raw.get("forbid_regex") or []) if p],
            require_ask_before_assert=bool(raw.get("require_ask_before_assert")),
        )

    def is_lintable(self) -> bool:
        return bool(
            self.max_sentences
            or self.max_chars
            or self.forbid_phrases
            or self.forbid_regex
            or self.require_ask_before_assert
        )


@dataclass
class PersonalityRule:
    id: str
    rule: str
    kind: str
    measurable: MeasurableObservable
    evidence_ids: list[str] = field(default_factory=list)
    company_id: str = "elophanto-self"
    status: str = "proposed"  # proposed | active | retired
    miss_streak: int = 0
    created_at: str = ""
    updated_at: str = ""

    def cite_token(self) -> str:
        return f"rule-{self.id}"


@dataclass
class NuclearScene:
    id: str
    causal_link: str
    evidence_ids: list[str] = field(default_factory=list)
    company_id: str = "elophanto-self"
    status: str = "proposed"  # proposed | active | retired
    created_at: str = ""

    def cite_token(self) -> str:
        return f"scene-{self.id}"


@dataclass
class PersonalityLintResult:
    passed: bool
    violations: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    rule_ids_hit: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": list(self.violations),
            "suggestions": list(self.suggestions),
            "rule_ids_hit": list(self.rule_ids_hit),
        }


def _opt_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _short_id() -> str:
    return uuid.uuid4().hex[:12]


def default_observable_for_kind(kind: str) -> MeasurableObservable:
    if kind == "brevity":
        return MeasurableObservable(max_sentences=6, max_chars=1200)
    if kind == "anti_hype":
        return MeasurableObservable(forbid_phrases=list(_DEFAULT_ANTI_HYPE))
    if kind == "deference":
        return MeasurableObservable(require_ask_before_assert=True)
    return MeasurableObservable()


def lint_text_against_rules(
    text: str, rules: list[PersonalityRule]
) -> PersonalityLintResult:
    """Deterministic personality lint. Fail-closed on measurable violations."""
    violations: list[str] = []
    suggestions: list[str] = []
    hit: list[str] = []
    body = text or ""
    lower = body.lower()
    sentences = [s.strip() for s in _SENTENCE_RE.findall(body) if s.strip()]

    for rule in rules:
        if rule.status != "active":
            continue
        m = rule.measurable
        if not m.is_lintable():
            continue
        local: list[str] = []
        if m.max_sentences is not None and len(sentences) > m.max_sentences:
            local.append(
                f"{rule.cite_token()}: too many sentences "
                f"({len(sentences)} > {m.max_sentences})"
            )
            suggestions.append("Shorten the answer; prefer fewer sentences.")
        if m.max_chars is not None and len(body) > m.max_chars:
            local.append(
                f"{rule.cite_token()}: too long ({len(body)} > {m.max_chars} chars)"
            )
            suggestions.append("Trim the answer to the character budget.")
        for phrase in m.forbid_phrases:
            if phrase and phrase.lower() in lower:
                local.append(f"{rule.cite_token()}: banned phrase {phrase!r}")
                suggestions.append(f"Remove hype/banned phrasing: {phrase!r}")
        for rx in m.forbid_regex:
            try:
                if re.search(rx, body, flags=re.IGNORECASE | re.MULTILINE):
                    local.append(f"{rule.cite_token()}: banned pattern {rx!r}")
            except re.error as e:
                logger.warning("personality: bad regex %s: %s", rx, e)
        if m.require_ask_before_assert:
            assertive = re.search(
                r"\b(you (must|should|need to)|i (will|am going to) (post|send|pay|delete))\b",
                lower,
            )
            asking = "?" in body or re.search(
                r"\b(may i|should i|do you want|want me to)\b", lower
            )
            if assertive and not asking:
                local.append(
                    f"{rule.cite_token()}: assertive claim without asking the operator"
                )
                suggestions.append("Ask before asserting irreversible actions.")
        if local:
            hit.append(rule.id)
            violations.extend(local)

    return PersonalityLintResult(
        passed=not violations,
        violations=violations,
        suggestions=suggestions,
        rule_ids_hit=hit,
    )


def rewrite_for_brevity(text: str, max_sentences: int, max_chars: int | None) -> str:
    """Deterministic trim — no LLM. Used after lint fail for brevity rules."""
    sentences = [s.strip() for s in _SENTENCE_RE.findall(text or "") if s.strip()]
    trimmed = " ".join(sentences[:max_sentences]).strip()
    if max_chars is not None and len(trimmed) > max_chars:
        trimmed = trimmed[: max(0, max_chars - 1)].rstrip() + "…"
    return trimmed


def cite_check(text: str, allowed_tokens: set[str]) -> tuple[str, list[str]]:
    """Strip or flag invented citation tokens. Returns (text, invented)."""
    invented: list[str] = []
    out = text or ""

    def _repl(match: re.Match[str]) -> str:
        token = match.group(0)
        if token not in allowed_tokens:
            invented.append(token)
            return ""
        return token

    cleaned = _CITE_RE.sub(_repl, out)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, invented


def is_self_description_query(text: str) -> bool:
    """Heuristic: operator is asking for a self-description.

    Used to soft-mandate the who_are_you tool — not to skip the model.
    """
    t = (text or "").strip().lower()
    if not t:
        return False
    needles = (
        "who are you",
        "who you are",
        "who you really are",
        "who you truly are",
        "what are you",
        "what you are",
        "tell me about yourself",
        "describe yourself",
        "your identity",
        "who am i talking to",
    )
    return any(n in t for n in needles)


class PersonalityManager:
    """Company-scoped personality rules + nuclear scenes + who-are-you compile."""

    def __init__(
        self,
        db: Database,
        *,
        project_root: Path | None = None,
        agent_name: str = "EloPhanto",
    ) -> None:
        self._db = db
        self._project_root = project_root or Path(".")
        self._agent_name = agent_name
        # Named sources owned by live subsystems (learner, dataset, tools…).
        # who_are_you collects these — no hardcoded capability essays here.
        self._runtime_fact_sources: list[tuple[str, RuntimeFactSource]] = []

    def register_runtime_fact_source(
        self, name: str, source: RuntimeFactSource
    ) -> None:
        """Idempotent register/replace a runtime fact provider by name."""
        self._runtime_fact_sources = [
            (n, s) for n, s in self._runtime_fact_sources if n != name
        ]
        self._runtime_fact_sources.append((name, source))

    def clear_runtime_fact_sources(self) -> None:
        self._runtime_fact_sources.clear()

    async def collect_runtime_facts(self) -> list[str]:
        """Merge facts from registered subsystem sources (deduped, ordered)."""
        import inspect

        out: list[str] = []
        seen: set[str] = set()
        for name, source in self._runtime_fact_sources:
            try:
                raw = source()
                if inspect.isawaitable(raw):
                    raw = await raw
            except Exception as e:
                logger.debug("runtime fact source %s failed: %s", name, e)
                continue
            for fact in raw or []:
                text = str(fact).strip()
                if text and text not in seen:
                    seen.add(text)
                    out.append(text)
        return out

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------

    async def propose_rule(
        self,
        *,
        rule: str,
        kind: str,
        measurable: MeasurableObservable | None = None,
        evidence_ids: list[str] | None = None,
        company_id: str | None = None,
    ) -> PersonalityRule:
        from core.company import current_company_id

        cid = company_id or current_company_id()
        kind = (kind or "custom").strip().lower()
        if kind not in _MEASURABLE_KINDS:
            raise ValueError(f"unknown kind {kind!r}")
        meas = measurable or default_observable_for_kind(kind)
        if not meas.is_lintable():
            raise ValueError(
                "measurable_observable required and must be lintable "
                "(max_sentences/max_chars/forbid_phrases/forbid_regex/"
                "require_ask_before_assert)"
            )
        now = _now()
        row = PersonalityRule(
            id=_short_id(),
            rule=rule.strip(),
            kind=kind,
            measurable=meas,
            evidence_ids=list(evidence_ids or []),
            company_id=cid,
            status="proposed",
            created_at=now,
            updated_at=now,
        )
        await self._persist_rule(row)
        self._write_rule_proposal_file(row)
        return row

    async def confirm_rule(
        self, rule_id: str, *, company_id: str | None = None
    ) -> bool:
        rule = await self.get_rule(rule_id, company_id=company_id)
        if rule is None:
            return False
        rule.status = "active"
        rule.updated_at = _now()
        await self._persist_rule(rule)
        self._clear_rule_proposal_file(rule)
        return True

    async def reject_rule(self, rule_id: str, *, company_id: str | None = None) -> bool:
        rule = await self.get_rule(rule_id, company_id=company_id)
        if rule is None:
            return False
        rule.status = "retired"
        rule.updated_at = _now()
        await self._persist_rule(rule)
        self._clear_rule_proposal_file(rule)
        return True

    async def retire_rule(self, rule_id: str, *, company_id: str | None = None) -> bool:
        return await self.reject_rule(rule_id, company_id=company_id)

    async def get_rule(
        self, rule_id: str, *, company_id: str | None = None
    ) -> PersonalityRule | None:
        from core.company import current_company_id

        cid = company_id or current_company_id()
        rows = await self._db.execute(
            "SELECT * FROM personality_rules WHERE id = ? AND company_id = ?",
            (rule_id, cid),
        )
        if not rows:
            return None
        return self._row_to_rule(rows[0])

    async def list_rules(
        self,
        *,
        company_id: str | None = None,
        status: str | None = "active",
    ) -> list[PersonalityRule]:
        from core.company import current_company_id

        cid = company_id or current_company_id()
        if status:
            rows = await self._db.execute(
                "SELECT * FROM personality_rules WHERE company_id = ? AND status = ? "
                "ORDER BY created_at ASC",
                (cid, status),
            )
        else:
            rows = await self._db.execute(
                "SELECT * FROM personality_rules WHERE company_id = ? "
                "ORDER BY created_at ASC",
                (cid,),
            )
        return [self._row_to_rule(r) for r in rows]

    async def record_lint_misses(self, rule_ids: list[str]) -> list[str]:
        """Bump miss_streak; propose retire when streak >= 3. Returns retire proposals."""
        retired_proposals: list[str] = []
        for rid in rule_ids:
            rule = await self.get_rule(rid)
            if rule is None or rule.status != "active":
                continue
            rule.miss_streak += 1
            rule.updated_at = _now()
            if rule.miss_streak >= 3:
                rule.status = "proposed"  # propose retire via status flip note
                retired_proposals.append(rid)
                logger.info(
                    "personality: rule %s miss_streak=%d — propose retire",
                    rid,
                    rule.miss_streak,
                )
            await self._persist_rule(rule)
        return retired_proposals

    async def record_lint_pass(self, rule_ids: list[str]) -> None:
        for rid in rule_ids:
            rule = await self.get_rule(rid)
            if rule is None:
                continue
            if rule.miss_streak:
                rule.miss_streak = 0
                rule.updated_at = _now()
                await self._persist_rule(rule)

    # ------------------------------------------------------------------
    # Nuclear scenes
    # ------------------------------------------------------------------

    async def propose_scene(
        self,
        *,
        causal_link: str,
        evidence_ids: list[str],
        company_id: str | None = None,
        auto_activate_if_verified: bool = True,
    ) -> NuclearScene:
        from core.company import current_company_id

        cid = company_id or current_company_id()
        if not causal_link.strip():
            raise ValueError("causal_link required")
        if not evidence_ids:
            raise ValueError("evidence_ids required")
        verified = await self._verify_evidence_ids(evidence_ids, company_id=cid)
        now = _now()
        scene = NuclearScene(
            id=_short_id(),
            causal_link=causal_link.strip(),
            evidence_ids=list(evidence_ids),
            company_id=cid,
            status="active" if (auto_activate_if_verified and verified) else "proposed",
            created_at=now,
        )
        await self._persist_scene(scene)
        if scene.status == "proposed":
            self._write_scene_proposal_file(scene)
        return scene

    async def confirm_scene(
        self, scene_id: str, *, company_id: str | None = None
    ) -> bool:
        scene = await self.get_scene(scene_id, company_id=company_id)
        if scene is None:
            return False
        if not await self._verify_evidence_ids(
            scene.evidence_ids, company_id=scene.company_id
        ):
            return False
        scene.status = "active"
        await self._persist_scene(scene)
        self._clear_scene_proposal_file(scene)
        return True

    async def wipe_scenes(self, *, company_id: str | None = None) -> int:
        """Counterfactual wipe for tests / operator reset."""
        from core.company import current_company_id

        cid = company_id or current_company_id()
        rows = await self.list_scenes(company_id=cid, status=None)
        for s in rows:
            s.status = "retired"
            await self._persist_scene(s)
        return len(rows)

    async def get_scene(
        self, scene_id: str, *, company_id: str | None = None
    ) -> NuclearScene | None:
        from core.company import current_company_id

        cid = company_id or current_company_id()
        rows = await self._db.execute(
            "SELECT * FROM nuclear_scenes WHERE id = ? AND company_id = ?",
            (scene_id, cid),
        )
        if not rows:
            return None
        return self._row_to_scene(rows[0])

    async def list_scenes(
        self,
        *,
        company_id: str | None = None,
        status: str | None = "active",
    ) -> list[NuclearScene]:
        from core.company import current_company_id

        cid = company_id or current_company_id()
        if status:
            rows = await self._db.execute(
                "SELECT * FROM nuclear_scenes WHERE company_id = ? AND status = ? "
                "ORDER BY created_at ASC",
                (cid, status),
            )
        else:
            rows = await self._db.execute(
                "SELECT * FROM nuclear_scenes WHERE company_id = ? "
                "ORDER BY created_at ASC",
                (cid,),
            )
        return [self._row_to_scene(r) for r in rows]

    # ------------------------------------------------------------------
    # Lint
    # ------------------------------------------------------------------

    async def lint(
        self, text: str, *, company_id: str | None = None
    ) -> PersonalityLintResult:
        rules = await self.list_rules(company_id=company_id, status="active")
        result = lint_text_against_rules(text, rules)
        if result.rule_ids_hit:
            if result.passed:
                await self.record_lint_pass(result.rule_ids_hit)
            else:
                await self.record_lint_misses(result.rule_ids_hit)
        return result

    async def lint_and_enforce(
        self, text: str, *, company_id: str | None = None
    ) -> tuple[str, PersonalityLintResult]:
        """Lint; apply deterministic brevity rewrite; re-lint fail-closed."""
        first = await self.lint(text, company_id=company_id)
        if first.passed:
            return text, first

        rewritten = text
        rules = await self.list_rules(company_id=company_id, status="active")
        for rule in rules:
            if rule.id not in first.rule_ids_hit:
                continue
            if rule.kind == "brevity" and rule.measurable.max_sentences:
                rewritten = rewrite_for_brevity(
                    rewritten,
                    rule.measurable.max_sentences,
                    rule.measurable.max_chars,
                )
            if rule.kind == "anti_hype":
                for phrase in rule.measurable.forbid_phrases:
                    if not phrase:
                        continue
                    rewritten = re.sub(
                        re.escape(phrase),
                        "",
                        rewritten,
                        flags=re.IGNORECASE,
                    )
                rewritten = re.sub(r"[ \t]{2,}", " ", rewritten).strip()

        second = lint_text_against_rules(rewritten, rules)
        if not second.passed:
            # Fail-closed: do not return violating text
            return "", second
        return rewritten, second

    # ------------------------------------------------------------------
    # Who-are-you compiler
    # ------------------------------------------------------------------

    async def compile_who_are_you(
        self,
        *,
        company_id: str | None = None,
        felt_state: str | None = None,
        caution_rules: list[dict[str, str]] | None = None,
        runtime_facts: list[str] | None = None,
    ) -> dict[str, Any]:
        """Assemble a self-description from DB artifacts. No marketing template."""
        from core.company import current_company_id

        cid = company_id or current_company_id()
        rules = await self.list_rules(company_id=cid, status="active")
        scenes = await self.list_scenes(company_id=cid, status="active")
        # Only scars with real rule text count — bare capability tags
        # produced "- ops:" noise and falsely flipped empty_life.
        caution = [
            c
            for c in (caution_rules or [])
            if isinstance(c, dict) and str(c.get("rule") or "").strip()
        ]

        allowed: set[str] = set()
        for r in rules:
            allowed.add(r.cite_token())
        for s in scenes:
            allowed.add(s.cite_token())
        for i, c in enumerate(caution):
            tok = f"caution-{c.get('capability') or i}"
            allowed.add(tok)

        # Lived autobiography = rules + scenes. Caution/felt are weather.
        # Runtime facts come from registered subsystem sources (scalable) —
        # callers may override with an explicit list for tests.
        empty_life = not (rules or scenes)
        if runtime_facts is None:
            facts = await self.collect_runtime_facts()
        else:
            facts = [str(f).strip() for f in runtime_facts if str(f).strip()]
        if not facts:
            facts = [
                "runtime.host: local agent with tools, goals, and gated approvals."
            ]

        lines: list[str] = []
        lines.append(
            f"I am {self._agent_name}, a local autonomous agent with an "
            "evidence-backed self-model (not a questionnaire persona, not a "
            "claim of consciousness)."
        )

        if empty_life:
            lines.append(
                "Insufficient lived evidence yet — no active personality_rules "
                "or nuclear_scenes for this company hat."
            )
        else:
            if rules:
                lines.append("Active stance rules (enforced by personality_lint):")
                for r in rules:
                    lines.append(f"- [{r.cite_token()}] ({r.kind}) {r.rule}")
            if scenes:
                lines.append("Cited turning points:")
                for s in scenes:
                    lines.append(f"- [{s.cite_token()}] {s.causal_link}")

        if facts:
            lines.append("Runtime capability facts (from live subsystems):")
            for fact in facts:
                lines.append(f"- {fact}")

        if caution:
            lines.append("Competence scars (ego caution_rules):")
            for i, c in enumerate(caution):
                tok = f"caution-{c.get('capability') or i}"
                lines.append(
                    f"- [{tok}] {c.get('capability', '?')}: "
                    f"{str(c.get('rule') or '').strip()}"
                )
        if felt_state:
            lines.append(f"Current felt_state (weather, not biography): {felt_state}.")

        body = "\n".join(lines)
        cleaned, invented = cite_check(body, allowed)
        if invented:
            logger.warning("who_are_you invented citations stripped: %s", invented)
        return {
            "text": cleaned,
            "empty_life": empty_life,
            "company_id": cid,
            "citations": sorted(allowed),
            "invented_citations": invented,
            "rules": [
                asdict(r) | {"measurable": r.measurable.to_dict()} for r in rules
            ],
            "scenes": [asdict(s) for s in scenes],
            "runtime_facts": facts,
        }

    # ------------------------------------------------------------------
    # Identity proposal bridge (gated personality/values/style)
    # ------------------------------------------------------------------

    def write_identity_field_proposal(
        self,
        *,
        field_name: str,
        value: Any,
        reason: str,
        trigger: str,
        company_id: str | None = None,
    ) -> Path:
        from core.company import current_company_id

        cid = company_id or current_company_id()
        dest = self._project_root / "data" / "companies" / cid / "personality_proposals"
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"identity_{field_name}_{_short_id()}.json"
        path.write_text(
            json.dumps(
                {
                    "kind": "identity_field",
                    "field": field_name,
                    "value": value,
                    "reason": reason,
                    "trigger": trigger,
                    "company_id": cid,
                    "status": "pending",
                    "created_at": _now(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return path

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _persist_rule(self, rule: PersonalityRule) -> None:
        await self._db.execute_insert(
            "INSERT INTO personality_rules "
            "(id, company_id, rule_text, kind, measurable_json, evidence_json, "
            "status, miss_streak, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "rule_text=excluded.rule_text, kind=excluded.kind, "
            "measurable_json=excluded.measurable_json, "
            "evidence_json=excluded.evidence_json, status=excluded.status, "
            "miss_streak=excluded.miss_streak, updated_at=excluded.updated_at",
            (
                rule.id,
                rule.company_id,
                rule.rule,
                rule.kind,
                json.dumps(rule.measurable.to_dict()),
                json.dumps(rule.evidence_ids),
                rule.status,
                rule.miss_streak,
                rule.created_at,
                rule.updated_at,
            ),
        )

    async def _persist_scene(self, scene: NuclearScene) -> None:
        await self._db.execute_insert(
            "INSERT INTO nuclear_scenes "
            "(id, company_id, causal_link, evidence_json, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "causal_link=excluded.causal_link, evidence_json=excluded.evidence_json, "
            "status=excluded.status",
            (
                scene.id,
                scene.company_id,
                scene.causal_link,
                json.dumps(scene.evidence_ids),
                scene.status,
                scene.created_at,
            ),
        )

    def _row_to_rule(self, row: Any) -> PersonalityRule:
        return PersonalityRule(
            id=row["id"],
            rule=row["rule_text"],
            kind=row["kind"],
            measurable=MeasurableObservable.from_dict(
                json.loads(row["measurable_json"] or "{}")
            ),
            evidence_ids=json.loads(row["evidence_json"] or "[]"),
            company_id=row["company_id"],
            status=row["status"],
            miss_streak=int(row["miss_streak"] or 0),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_scene(self, row: Any) -> NuclearScene:
        return NuclearScene(
            id=row["id"],
            causal_link=row["causal_link"],
            evidence_ids=json.loads(row["evidence_json"] or "[]"),
            company_id=row["company_id"],
            status=row["status"],
            created_at=row["created_at"],
        )

    async def _verify_evidence_ids(
        self, evidence_ids: list[str], *, company_id: str
    ) -> bool:
        """Every evidence id must resolve to a real outcome, rule, or caution token."""
        if not evidence_ids:
            return False
        for eid in evidence_ids:
            if eid.startswith("rule-"):
                if await self.get_rule(eid[5:], company_id=company_id) is None:
                    return False
                continue
            if eid.startswith("scene-"):
                if await self.get_scene(eid[6:], company_id=company_id) is None:
                    return False
                continue
            if eid.startswith("outcome-") or eid.isdigit():
                rows = await self._db.execute(
                    "SELECT id FROM ego_outcomes WHERE id = ? AND company_id = ?",
                    (int(eid.replace("outcome-", "")), company_id),
                )
                if not rows:
                    return False
                continue
            if eid.startswith("caution-"):
                continue  # caution tokens validated at compile time from live ego
            # Unknown scheme — fail closed
            return False
        return True

    def _proposal_dir(self, company_id: str) -> Path:
        d = (
            self._project_root
            / "data"
            / "companies"
            / company_id
            / "personality_proposals"
        )
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _write_rule_proposal_file(self, rule: PersonalityRule) -> None:
        path = self._proposal_dir(rule.company_id) / f"rule_{rule.id}.json"
        path.write_text(
            json.dumps(
                {
                    "kind": "personality_rule",
                    "id": rule.id,
                    "rule": rule.rule,
                    "rule_kind": rule.kind,
                    "measurable": rule.measurable.to_dict(),
                    "evidence_ids": rule.evidence_ids,
                    "status": "pending",
                    "created_at": rule.created_at,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _clear_rule_proposal_file(self, rule: PersonalityRule) -> None:
        path = self._proposal_dir(rule.company_id) / f"rule_{rule.id}.json"
        if path.is_file():
            path.unlink()

    def _write_scene_proposal_file(self, scene: NuclearScene) -> None:
        path = self._proposal_dir(scene.company_id) / f"scene_{scene.id}.json"
        path.write_text(
            json.dumps(
                {
                    "kind": "nuclear_scene",
                    "id": scene.id,
                    "causal_link": scene.causal_link,
                    "evidence_ids": scene.evidence_ids,
                    "status": "pending",
                    "created_at": scene.created_at,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _clear_scene_proposal_file(self, scene: NuclearScene) -> None:
        path = self._proposal_dir(scene.company_id) / f"scene_{scene.id}.json"
        if path.is_file():
            path.unlink()
