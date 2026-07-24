"""watch_* — track a market: brands, weighted dimensions, evidence, scores.

ABE organ 2 (market model). These tools turn ad-hoc competitor research into a
standing, evidence-backed model that can be refreshed and diffed month over
month. Market-agnostic: the scoring frame is data (see ``core/watch_seeds.py``
for ready-made packs), not code.

Two behaviours are deliberately strict, because the analysis is only worth
anything if they hold:

* ``watch_score`` refuses to score a dimension with no evidence. The honest
  representation of "we don't know" is a NULL score plus its coverage gap —
  never a low score, which would report an opaque brand as a weak one.
* ``watch_evidence`` is append-only. Corrections supersede, never overwrite,
  so month-over-month change is real rather than an artefact of editing.

Design: tmp/competitive-intel-organ-spec.md
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


def _company(params: dict[str, Any]) -> str:
    """Resolve the owning company — explicit arg wins, else the active one."""
    from core.company import current_company_id

    return str(params.get("company_id") or current_company_id() or "elophanto-self")


class _WatchToolBase(BaseTool):
    """Shared plumbing: injected manager + company resolution."""

    def __init__(self) -> None:
        self._watch_manager: Any = None

    @property
    def group(self) -> str:
        return "watch"

    def _guard(self) -> ToolResult | None:
        if self._watch_manager is None:
            return ToolResult(
                success=False, error=f"{self.name} not initialized (watch_manager)"
            )
        return None


class WatchSubjectTool(_WatchToolBase):
    """Add / list the brands being tracked."""

    @property
    def name(self) -> str:
        return "watch_subject"

    @property
    def description(self) -> str:
        return (
            "Manage the brands tracked in a competitive analysis. "
            "action='add' registers a brand (name, group, url); action='list' "
            "returns all tracked brands; action='archive' stops tracking one. "
            "Use this before recording evidence about a competitor."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "list", "archive"],
                    "description": "What to do. Default 'list'.",
                },
                "name": {"type": "string", "description": "Brand name."},
                "group_name": {
                    "type": "string",
                    "description": "Parent group / operator (e.g. 'VGW', 'B2S').",
                },
                "url": {"type": "string", "description": "Brand homepage URL."},
                "product_offering": {"type": "string"},
                "market_share_est": {"type": "string"},
                "is_self": {
                    "type": "boolean",
                    "description": "True for our own brands (excluded from competitor rollups).",
                },
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        action = str(params.get("action") or "list").lower()
        cid = _company(params)
        wm = self._watch_manager

        if action == "list":
            subs = await wm.list_subjects(cid)
            return ToolResult(
                success=True,
                data={
                    "count": len(subs),
                    "subjects": [
                        {
                            "subject_id": s.subject_id,
                            "name": s.name,
                            "group": s.group_name,
                            "url": s.url,
                            "is_self": s.is_self,
                        }
                        for s in subs
                    ],
                },
            )

        name = str(params.get("name") or "").strip()
        if not name:
            return ToolResult(success=False, error="name is required")

        if action == "add":
            sub = await wm.add_subject(
                name=name,
                company_id=cid,
                group_name=str(params.get("group_name") or ""),
                url=str(params.get("url") or ""),
                product_offering=str(params.get("product_offering") or ""),
                market_share_est=str(params.get("market_share_est") or ""),
                is_self=bool(params.get("is_self")),
            )
            return ToolResult(
                success=True, data={"subject_id": sub.subject_id, "name": sub.name}
            )

        if action == "archive":
            sub = await wm.get_subject_by_name(name, cid)
            if sub is None:
                return ToolResult(success=False, error=f"no such subject: {name!r}")
            await wm.archive_subject(sub.subject_id)
            return ToolResult(success=True, data={"archived": name})

        return ToolResult(success=False, error=f"unknown action: {action!r}")


class WatchDimensionTool(_WatchToolBase):
    """Define the weighted scoring frame, or load a ready-made pack."""

    @property
    def name(self) -> str:
        return "watch_dimension"

    @property
    def description(self) -> str:
        return (
            "Manage the scoring dimensions of a competitive analysis — the "
            "weighted parameters brands are scored on. action='seed' loads a "
            "ready-made pack (e.g. 'social_casino_t1' = the 12-dimension "
            "sweepstakes-casino frame plus its brands); action='list' shows the "
            "current frame; action='upsert' adds or edits one dimension with its "
            "weight, sub-criteria and refresh cadence."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "upsert", "seed", "packs"],
                    "description": "What to do. Default 'list'.",
                },
                "pack": {
                    "type": "string",
                    "description": "Seed pack name for action='seed'.",
                },
                "name": {"type": "string", "description": "Dimension name."},
                "description_text": {"type": "string"},
                "weight_pct": {
                    "type": "number",
                    "description": "Weight of this dimension; all should sum to 100.",
                },
                "refresh_cadence": {
                    "type": "string",
                    "enum": ["weekly", "monthly", "quarterly"],
                },
                "subcriteria": {
                    "type": "array",
                    "description": "[{name, weight_pct}] summing to 100.",
                    "items": {"type": "object"},
                },
                "view_weights": {
                    "type": "object",
                    "description": "Alternative-view weights, e.g. {'customer_proposition': 18}.",
                },
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        action = str(params.get("action") or "list").lower()
        cid = _company(params)
        wm = self._watch_manager

        if action == "packs":
            from core.watch_seeds import list_packs

            return ToolResult(success=True, data={"packs": list_packs()})

        if action == "list":
            dims = await wm.list_dimensions(cid)
            total = round(sum(d.weight_pct for d in dims), 2)
            return ToolResult(
                success=True,
                data={
                    "count": len(dims),
                    "weight_total_pct": total,
                    "weights_valid": abs(total - 100.0) < 0.01 if dims else False,
                    "dimensions": [
                        {
                            "name": d.name,
                            "weight_pct": d.weight_pct,
                            "cadence": d.refresh_cadence,
                            "subcriteria": [s.get("name") for s in d.subcriteria],
                        }
                        for d in dims
                    ],
                },
            )

        if action == "seed":
            from core.watch_seeds import get_pack

            pack_name = str(params.get("pack") or "").strip()
            pack = get_pack(pack_name)
            if pack is None:
                from core.watch_seeds import list_packs

                return ToolResult(
                    success=False,
                    error=(
                        f"unknown pack {pack_name!r}. Available: "
                        f"{[p['name'] for p in list_packs()]}"
                    ),
                )
            dims_added = 0
            for i, d in enumerate(pack["dimensions"]):
                await wm.upsert_dimension(
                    name=d["name"],
                    company_id=cid,
                    description=d.get("description", ""),
                    weight_pct=d.get("weight_pct", 0),
                    subcriteria=d.get("subcriteria", []),
                    refresh_cadence=d.get("refresh_cadence", "monthly"),
                    view_weights=d.get("view_weights", {}),
                    sort_order=i,
                )
                dims_added += 1
            subs_added = 0
            for s in pack.get("subjects", []):
                await wm.add_subject(
                    name=s["name"],
                    company_id=cid,
                    group_name=s.get("group_name", ""),
                    url=s.get("url", ""),
                    is_self=bool(s.get("is_self")),
                )
                subs_added += 1
            return ToolResult(
                success=True,
                data={
                    "pack": pack_name,
                    "dimensions_seeded": dims_added,
                    "subjects_seeded": subs_added,
                    "next": (
                        "Collect evidence with watch_evidence, then score with "
                        "watch_score. Scores without evidence are refused by design."
                    ),
                },
            )

        if action == "upsert":
            name = str(params.get("name") or "").strip()
            if not name:
                return ToolResult(success=False, error="name is required")
            try:
                dim = await wm.upsert_dimension(
                    name=name,
                    company_id=cid,
                    description=str(params.get("description_text") or ""),
                    weight_pct=float(params.get("weight_pct") or 0),
                    subcriteria=params.get("subcriteria") or [],
                    refresh_cadence=str(params.get("refresh_cadence") or "monthly"),
                    view_weights=params.get("view_weights") or {},
                )
            except ValueError as e:
                return ToolResult(success=False, error=str(e))
            return ToolResult(
                success=True,
                data={"dimension_id": dim.dimension_id, "name": dim.name},
            )

        return ToolResult(success=False, error=f"unknown action: {action!r}")


class WatchEvidenceTool(_WatchToolBase):
    """Record and query the evidence register (append-only)."""

    @property
    def name(self) -> str:
        return "watch_evidence"

    @property
    def description(self) -> str:
        return (
            "The evidence register for a competitive analysis. action='add' "
            "records ONE observed fact about a brand with full provenance "
            "(source URL, geo/state, customer state, date, confidence); "
            "action='list' queries it. Evidence is append-only — pass "
            "'supersedes' with an evidence_id to correct or refresh a prior "
            "observation instead of overwriting it. Authenticated observations "
            "(verified/purchaser/redeemer/vip) are operator-collected: pass "
            "collector='human'."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "list"]},
                "subject": {"type": "string", "description": "Brand name."},
                "dimension": {"type": "string", "description": "Dimension name."},
                "subcriterion": {
                    "type": "string",
                    "description": "Which sub-criterion this fact covers (drives coverage %).",
                },
                "claim": {
                    "type": "string",
                    "description": "The observed fact, stated plainly.",
                },
                "value_text": {"type": "string"},
                "value_num": {"type": "number"},
                "source_url": {"type": "string"},
                "source_type": {
                    "type": "string",
                    "enum": [
                        "site",
                        "terms",
                        "ad_library",
                        "trust_site",
                        "filing",
                        "shop",
                        "press",
                        "other",
                    ],
                },
                "geo_state": {
                    "type": "string",
                    "description": "US state code the observation was made from, or 'n/a'.",
                },
                "customer_state": {
                    "type": "string",
                    "enum": [
                        "logged_out",
                        "registered",
                        "verified",
                        "purchaser",
                        "redeemer",
                        "vip",
                    ],
                },
                "journey_stage": {"type": "string"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "excerpt": {
                    "type": "string",
                    "description": "Verbatim supporting quote.",
                },
                "screenshot_path": {"type": "string"},
                "collector": {"type": "string", "enum": ["agent", "human"]},
                "supersedes": {
                    "type": "string",
                    "description": "evidence_id this observation replaces.",
                },
                "include_superseded": {"type": "boolean"},
                "limit": {"type": "integer"},
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        action = str(params.get("action") or "list").lower()
        cid = _company(params)
        wm = self._watch_manager

        subject_id = None
        if params.get("subject"):
            sub = await wm.get_subject_by_name(str(params["subject"]), cid)
            if sub is None:
                return ToolResult(
                    success=False,
                    error=(
                        f"no tracked brand named {params['subject']!r} — add it "
                        "with watch_subject first"
                    ),
                )
            subject_id = sub.subject_id

        dimension_id = None
        if params.get("dimension"):
            dim = await wm.get_dimension_by_name(str(params["dimension"]), cid)
            if dim is None:
                return ToolResult(
                    success=False,
                    error=(
                        f"no dimension named {params['dimension']!r} — see "
                        "watch_dimension action='list'"
                    ),
                )
            dimension_id = dim.dimension_id

        if action == "list":
            rows = await wm.list_evidence(
                cid,
                subject_id=subject_id,
                dimension_id=dimension_id,
                include_superseded=bool(params.get("include_superseded")),
                limit=int(params.get("limit") or 50),
            )
            return ToolResult(
                success=True,
                data={
                    "count": len(rows),
                    "evidence": [
                        {
                            "evidence_id": e.evidence_id,
                            "claim": e.claim,
                            "subcriterion": e.subcriterion,
                            "source_url": e.source_url,
                            "geo_state": e.geo_state,
                            "customer_state": e.customer_state,
                            "observed_at": e.observed_at,
                            "confidence": e.confidence,
                            "collector": e.collector,
                        }
                        for e in rows
                    ],
                },
            )

        if action == "add":
            if not subject_id or not dimension_id:
                return ToolResult(
                    success=False, error="subject and dimension are both required"
                )
            claim = str(params.get("claim") or "").strip()
            if not claim:
                return ToolResult(success=False, error="claim is required")
            try:
                ev = await wm.add_evidence(
                    company_id=cid,
                    subject_id=subject_id,
                    dimension_id=dimension_id,
                    claim=claim,
                    subcriterion=str(params.get("subcriterion") or ""),
                    value_text=str(params.get("value_text") or ""),
                    value_num=params.get("value_num"),
                    source_url=str(params.get("source_url") or ""),
                    source_type=str(params.get("source_type") or "site"),
                    geo_state=str(params.get("geo_state") or "n/a"),
                    customer_state=str(params.get("customer_state") or "logged_out"),
                    journey_stage=str(params.get("journey_stage") or ""),
                    confidence=str(params.get("confidence") or "medium"),
                    excerpt=str(params.get("excerpt") or ""),
                    screenshot_path=str(params.get("screenshot_path") or ""),
                    collector=str(params.get("collector") or "agent"),
                    supersedes=params.get("supersedes"),
                )
            except ValueError as e:
                return ToolResult(success=False, error=str(e))
            return ToolResult(
                success=True,
                data={"evidence_id": ev.evidence_id, "observed_at": ev.observed_at},
            )

        return ToolResult(success=False, error=f"unknown action: {action!r}")


class WatchScoreTool(_WatchToolBase):
    """Score a brand on a dimension — strictly from recorded evidence."""

    @property
    def name(self) -> str:
        return "watch_score"

    @property
    def description(self) -> str:
        return (
            "Score a tracked brand on one dimension, 1-5 (1 = materially behind "
            "market, 3 = parity, 5 = market-leading). The score MUST be justified "
            "by evidence already recorded via watch_evidence — scoring a dimension "
            "with no evidence is refused. If the data genuinely isn't available, "
            "pass score=null to record the gap: coverage is reported separately so "
            "a brand is never marked down merely for being opaque."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["set", "list"]},
                "subject": {"type": "string", "description": "Brand name."},
                "dimension": {"type": "string", "description": "Dimension name."},
                "score": {
                    "type": "number",
                    "description": "1-5, or null to record an evidence gap.",
                },
                "rationale": {
                    "type": "string",
                    "description": "Why this score, referencing the evidence.",
                },
                "subcriteria_scores": {"type": "object"},
                "scored_by": {"type": "string"},
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        action = str(params.get("action") or "set").lower()
        cid = _company(params)
        wm = self._watch_manager

        if action == "list":
            scores = await wm.list_scores(cid)
            return ToolResult(
                success=True,
                data={
                    "count": len(scores),
                    "scores": [
                        {
                            "subject_id": s.subject_id,
                            "dimension_id": s.dimension_id,
                            "score": s.score,
                            "coverage_pct": s.coverage_pct,
                            "confidence": s.confidence,
                        }
                        for s in scores
                    ],
                },
            )

        subject_name = str(params.get("subject") or "").strip()
        dim_name = str(params.get("dimension") or "").strip()
        if not subject_name or not dim_name:
            return ToolResult(
                success=False, error="subject and dimension are both required"
            )
        sub = await wm.get_subject_by_name(subject_name, cid)
        if sub is None:
            return ToolResult(success=False, error=f"no such brand: {subject_name!r}")
        dim = await wm.get_dimension_by_name(dim_name, cid)
        if dim is None:
            return ToolResult(success=False, error=f"no such dimension: {dim_name!r}")

        raw = params.get("score")
        score = None if raw is None else float(raw)
        try:
            result = await wm.set_score(
                company_id=cid,
                subject_id=sub.subject_id,
                dimension_id=dim.dimension_id,
                score=score,
                rationale=str(params.get("rationale") or ""),
                subcriteria_scores=params.get("subcriteria_scores") or {},
                scored_by=str(params.get("scored_by") or "agent"),
            )
        except ValueError as e:
            return ToolResult(success=False, error=str(e))
        return ToolResult(
            success=True,
            data={
                "subject": sub.name,
                "dimension": dim.name,
                "score": result.score,
                "coverage_pct": result.coverage_pct,
                "confidence": result.confidence,
                "evidence_count": len(result.evidence_ids),
            },
        )


class WatchScorecardTool(_WatchToolBase):
    """The weighted executive scorecard, plus both alternative views."""

    @property
    def name(self) -> str:
        return "watch_scorecard"

    @property
    def description(self) -> str:
        return (
            "Render the executive scorecard: every tracked brand scored across "
            "the weighted dimensions, ranked, with the alternative views "
            "(customer proposition / transition priority) and each brand's "
            "evidence coverage and confidence shown separately from its "
            "competitive score."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["markdown", "json"],
                    "description": "Output format. Default 'markdown'.",
                },
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        cid = _company(params)
        card = await self._watch_manager.scorecard(cid)
        if str(params.get("format") or "markdown").lower() == "json":
            return ToolResult(success=True, data=card)

        lines = [
            "| # | Brand | Group | Score | Cust. prop | Transition | Coverage | Conf |",
            "|---|-------|-------|-------|-----------|------------|----------|------|",
        ]
        for r in card["rows"]:
            o = r["overall"]
            score = "—" if o["normalized_pct"] is None else f"{o['normalized_pct']:.1f}"
            cp = r["views"].get("customer_proposition", {}).get("normalized_pct")
            tp = r["views"].get("transition_priority", {}).get("normalized_pct")
            lines.append(
                f"| {r['rank'] or '—'} | {r['name']}{' *(us)*' if r['is_self'] else ''} "
                f"| {r['group']} | {score} | {'—' if cp is None else f'{cp:.1f}'} "
                f"| {'—' if tp is None else f'{tp:.1f}'} "
                f"| {o['coverage_pct']:.0f}% | {o['confidence']} |"
            )
        note = (
            "\nScores are normalised to the weight actually scored; '—' means no "
            "evidence yet, never a weak result. Coverage shows the evidence gap."
        )
        if not card["weights_valid"]:
            note += (
                f"\n⚠️  Dimension weights sum to {card['weight_total_pct']}%, not 100%."
            )
        return ToolResult(
            success=True,
            data={"markdown": "\n".join(lines) + note, "rows": len(card["rows"])},
        )


def create_watch_tools() -> list[BaseTool]:
    """All competitive-intelligence tools."""
    return [
        WatchSubjectTool(),
        WatchDimensionTool(),
        WatchEvidenceTool(),
        WatchScoreTool(),
        WatchScorecardTool(),
    ]
