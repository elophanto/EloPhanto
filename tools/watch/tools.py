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
            "competitive score. format='xlsx' writes the client-facing workbook "
            "(scorecard + weights + full evidence register + gaps)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["markdown", "json", "xlsx"],
                    "description": "Output format. Default 'markdown'.",
                },
                "path": {
                    "type": "string",
                    "description": "Output file for format='xlsx'.",
                },
                "title": {"type": "string", "description": "Workbook title."},
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
        wm = self._watch_manager
        card = await wm.scorecard(cid)
        fmt = str(params.get("format") or "markdown").lower()

        if fmt == "json":
            return ToolResult(success=True, data=card)

        if fmt == "xlsx":
            path = str(params.get("path") or "").strip()
            if not path:
                return ToolResult(
                    success=False, error="path is required for format='xlsx'"
                )
            try:
                from core.watch_xlsx import render_scorecard_xlsx
            except ImportError as e:  # openpyxl missing
                return ToolResult(success=False, error=f"xlsx export unavailable: {e}")
            written = render_scorecard_xlsx(
                card,
                dimensions=await wm.list_dimensions(cid),
                evidence=await wm.evidence_with_names(cid),
                staleness=await wm.staleness(cid),
                path=path,
                title=str(params.get("title") or "Competitive Scorecard"),
            )
            return ToolResult(
                success=True,
                data={
                    "path": written,
                    "sheets": ["Scorecard", "Weights", "Evidence", "Gaps"],
                    "rows": len(card["rows"]),
                },
            )

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


class WatchSnapshotTool(_WatchToolBase):
    """Freeze the scorecard so later months have something to compare against."""

    @property
    def name(self) -> str:
        return "watch_snapshot"

    @property
    def description(self) -> str:
        return (
            "Freeze the current scorecard as a snapshot. Snapshots are what "
            "watch_diff and the monthly board report compare against, so take "
            "one at the end of every reporting cycle. action='list' shows "
            "existing snapshots."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["take", "list"]},
                "label": {
                    "type": "string",
                    "description": "Human label, e.g. 'March board report'.",
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
        cid = _company(params)
        wm = self._watch_manager
        action = str(params.get("action") or "take").lower()

        if action == "list":
            snaps = await wm.list_snapshots(cid)
            return ToolResult(
                success=True, data={"count": len(snaps), "snapshots": snaps}
            )

        snap_id = await wm.take_snapshot(cid, label=str(params.get("label") or ""))
        return ToolResult(success=True, data={"snapshot_id": snap_id})


class WatchDiffTool(_WatchToolBase):
    """What materially changed since a snapshot."""

    @property
    def name(self) -> str:
        return "watch_diff"

    @property
    def description(self) -> str:
        return (
            "Compare the live scorecard against a snapshot and return only "
            "MATERIAL changes: score moves of at least a full point, rank "
            "changes, dimensions newly scored or withdrawn, big coverage "
            "shifts, and brands entering or leaving. Use this to answer 'what "
            "actually changed this month?' without re-reading everything."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "snapshot_id": {
                    "type": "string",
                    "description": "Snapshot to compare against. Default: the most recent.",
                },
                "min_score_delta": {
                    "type": "number",
                    "description": "Minimum score move to count as material. Default 1.0.",
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
        diff = await self._watch_manager.diff_since_snapshot(
            cid,
            snapshot_id=params.get("snapshot_id"),
            min_score_delta=float(params.get("min_score_delta") or 1.0),
        )
        if diff is None:
            return ToolResult(
                success=False,
                error=(
                    "no snapshot to compare against — take one with "
                    "watch_snapshot first (a diff needs a prior state)"
                ),
            )
        return ToolResult(success=True, data=diff)


_BOARD_SYSTEM = """You are preparing a monthly competitor board report.

You are given FACTS: material changes detected between two scorecards, plus the
evidence recorded this period. Convert them into board-ready judgement.

For each material change output:
- implication: what this means for US specifically, in one sentence
- recommendation: the concrete action to take
- classification: exactly one of
    no_regret            — worth doing regardless of how strategy or rankings
                           change next month; low cost, reversible, independent
                           of major platform work
    transition_requirement — must be built as part of the platform transition
    post_transition      — optimisation to do after the transition completes
    monitor              — no action yet; watch it
- decision_required: what the board must decide, or "none"

Rules:
- Use ONLY the facts given. Never invent a competitor move, number or source.
- If a change is ambiguous, say so and classify it 'monitor'.
- Be concise and concrete. No filler, no restating the change.
- The no-regret test: "would we still be pleased we did this if the transition
  plan, competitor rankings or strategic priorities changed next month?"

Return STRICT JSON: {"items":[{"subject":str,"change":str,"implication":str,
"recommendation":str,"classification":str,"decision_required":str}]}"""


class WatchBoardReportTool(_WatchToolBase):
    """Turn the month's material changes into implications and decisions."""

    def __init__(self) -> None:
        super().__init__()
        self._router: Any = None

    @property
    def name(self) -> str:
        return "watch_board_report"

    @property
    def description(self) -> str:
        return (
            "Produce the monthly competitor board report: material changes "
            "since the last snapshot, each turned into an implication, a "
            "recommendation classified as no-regret / transition-requirement / "
            "post-transition / monitor, and the decision the board must make — "
            "plus current standings and outstanding evidence gaps."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "snapshot_id": {
                    "type": "string",
                    "description": "Compare against this snapshot. Default: most recent.",
                },
                "path": {
                    "type": "string",
                    "description": "Optional file to write the markdown report to.",
                },
                "take_snapshot": {
                    "type": "boolean",
                    "description": "Snapshot the current state after reporting. Default true.",
                },
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def _judge(self, diff: dict[str, Any]) -> list[dict[str, Any]]:
        """Ask the router to turn facts into implications. Optional by design:
        with no router the report still ships the facts, clearly marked."""
        if self._router is None:
            return []
        import json as _json

        facts = [
            {"subject": c["subject"], "changes": [i["detail"] for i in c["items"]]}
            for c in diff.get("changed", [])
        ]
        if diff.get("added_subjects"):
            facts.append(
                {"subject": "(new entrants)", "changes": diff["added_subjects"]}
            )
        if not facts:
            return []
        try:
            resp = await self._router.complete(
                messages=[
                    {"role": "system", "content": _BOARD_SYSTEM},
                    {"role": "user", "content": _json.dumps(facts, indent=1)},
                ],
                task_type="analysis",
                temperature=0.2,
                max_tokens=1800,
            )
            text = (resp.content or "").strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                text = text[4:] if text.startswith("json") else text
            data = _json.loads(text)
            items = data.get("items", []) if isinstance(data, dict) else []
            return [i for i in items if isinstance(i, dict)]
        except Exception as e:  # judgement is best-effort; facts are not
            import logging

            logging.getLogger(__name__).warning("board report judgement failed: %s", e)
            return []

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        cid = _company(params)
        wm = self._watch_manager

        diff = await wm.diff_since_snapshot(cid, snapshot_id=params.get("snapshot_id"))
        card = await wm.scorecard(cid)
        gaps = await wm.staleness(cid)

        lines: list[str] = ["# Competitor board report", ""]
        if diff is None:
            lines += [
                "**First reporting cycle** — no prior snapshot, so there is "
                "nothing to compare against yet. This report establishes the "
                "baseline; next cycle will show material change.",
                "",
            ]
        else:
            lines += [
                f"Period: {diff.get('from_generated_at', '?')} → "
                f"{diff.get('to_generated_at', '?')}",
                f"Material changes: **{diff.get('material_count', 0)}**",
                "",
            ]

        # ── Standings ──
        lines += ["## Standings", ""]
        lines += [
            "| # | Brand | Overall | Cust. prop | Transition | Coverage |",
            "|---|-------|---------|-----------|------------|----------|",
        ]
        for r in card["rows"][:15]:
            o = r["overall"]
            cp = r["views"].get("customer_proposition", {}).get("normalized_pct")
            tp = r["views"].get("transition_priority", {}).get("normalized_pct")
            fmt = lambda v: "—" if v is None else f"{v:.1f}"  # noqa: E731
            lines.append(
                f"| {r['rank'] or '—'} | {r['name']}{' *(us)*' if r['is_self'] else ''} "
                f"| {fmt(o['normalized_pct'])} | {fmt(cp)} | {fmt(tp)} "
                f"| {o['coverage_pct']:.0f}% |"
            )
        lines.append("")

        # ── Material changes + judgement ──
        judged: list[dict[str, Any]] = []
        if diff and diff.get("material_count"):
            lines += ["## Material changes", ""]
            for c in diff.get("changed", []):
                lines.append(f"**{c['subject']}**")
                for item in c["items"]:
                    lines.append(f"- {item['detail']}")
                lines.append("")
            if diff.get("added_subjects"):
                lines.append(
                    f"**New in the analysis:** {', '.join(diff['added_subjects'])}"
                )
                lines.append("")
            if diff.get("removed_subjects"):
                lines.append(f"**Removed:** {', '.join(diff['removed_subjects'])}")
                lines.append("")

            judged = await self._judge(diff)
            if judged:
                lines += ["## Implications and recommendations", ""]
                lines += [
                    "| Subject | Change | Implication | Recommendation | Class | Decision required |",
                    "|---------|--------|-------------|----------------|-------|-------------------|",
                ]
                for j in judged:
                    lines.append(
                        f"| {j.get('subject', '')} | {j.get('change', '')} "
                        f"| {j.get('implication', '')} | {j.get('recommendation', '')} "
                        f"| `{j.get('classification', 'monitor')}` "
                        f"| {j.get('decision_required', 'none')} |"
                    )
                lines.append("")
            else:
                lines += [
                    "> Implications not generated (no model available). The "
                    "material changes above are the factual record; judgement "
                    "still needs to be applied.",
                    "",
                ]
        elif diff is not None:
            lines += [
                "## Material changes",
                "",
                "None this period above the materiality threshold "
                f"(score move ≥ {diff['thresholds']['min_score_delta']}, "
                f"coverage shift ≥ {diff['thresholds']['min_coverage_delta']}%).",
                "",
            ]

        # ── Evidence gaps ──
        never = [g for g in gaps if g["status"] == "never_observed"]
        stale = [g for g in gaps if g["status"] == "stale"]
        lines += ["## Evidence gaps", ""]
        lines.append(
            f"- **{len(never)}** brand × dimension pairs never observed"
            + (
                f" (e.g. {never[0]['subject']} / {never[0]['dimension']})"
                if never
                else ""
            )
        )
        lines.append(f"- **{len(stale)}** overdue a refresh against their cadence")
        lines.append("")
        lines.append(
            "> Gaps are absences of evidence, not weaknesses. No brand is "
            "scored down for being opaque."
        )

        report = "\n".join(lines)
        written = None
        if params.get("path"):
            from pathlib import Path

            p = Path(str(params["path"])).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(report, encoding="utf-8")
            written = str(p)

        snap_id = None
        if params.get("take_snapshot", True):
            snap_id = await wm.take_snapshot(cid, label="board report")

        return ToolResult(
            success=True,
            data={
                "markdown": report,
                "material_count": (diff or {}).get("material_count", 0),
                "judged_items": len(judged),
                "gaps_never_observed": len(never),
                "gaps_stale": len(stale),
                "path": written,
                "snapshot_id": snap_id,
            },
        )


class WatchObserveTool(_WatchToolBase):
    """Collect evidence from public pages — every claim proof-checked."""

    def __init__(self) -> None:
        super().__init__()
        self._router: Any = None
        self._config: Any = None

    @property
    def name(self) -> str:
        return "watch_observe"

    @property
    def description(self) -> str:
        return (
            "Collect evidence about a tracked brand automatically: fetches the "
            "brand's public pages, extracts facts for the given dimension, and "
            "files them in the evidence register. Every claim must quote the "
            "source verbatim and the quote is CHECKED against the fetched page "
            "— unverifiable claims are discarded, not saved. Public/logged-out "
            "pages only; anything behind an account is operator-collected."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Brand name."},
                "dimension": {"type": "string", "description": "Dimension name."},
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Pages to read. Defaults to the brand's homepage.",
                },
                "geo_state": {
                    "type": "string",
                    "description": (
                        "US state to observe as. Uses the matching proxy exit "
                        "from proxy.pool when configured."
                    ),
                },
                "max_claims": {
                    "type": "integer",
                    "description": "Per page. Default 8.",
                },
                "company_id": {"type": "string"},
            },
            "required": ["subject", "dimension"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        if self._router is None:
            return ToolResult(
                success=False,
                error="watch_observe needs a model to read pages (router not injected)",
            )
        from core.watch_observe import (
            extract_claims,
            fetch_page,
            filter_verified_claims,
        )

        cid = _company(params)
        wm = self._watch_manager
        subj = await wm.get_subject_by_name(str(params.get("subject") or ""), cid)
        if subj is None:
            return ToolResult(
                success=False, error=f"no such brand: {params.get('subject')!r}"
            )
        dim = await wm.get_dimension_by_name(str(params.get("dimension") or ""), cid)
        if dim is None:
            return ToolResult(
                success=False, error=f"no such dimension: {params.get('dimension')!r}"
            )

        urls = [str(u) for u in (params.get("urls") or []) if str(u).strip()]
        if not urls:
            if not subj.url:
                return ToolResult(
                    success=False,
                    error=f"{subj.name} has no URL — pass urls, or set one via watch_subject",
                )
            urls = [subj.url]

        geo_state = str(params.get("geo_state") or "n/a")
        proxy_url = None
        if self._config is not None and getattr(self._config, "proxy", None):
            proxy_url = self._config.proxy.request_proxy_url(geo_state) or None

        subcriteria = [str(s.get("name", "")) for s in dim.subcriteria if s.get("name")]
        max_claims = int(params.get("max_claims") or 8)

        written = 0
        rejected_total = 0
        page_reports: list[dict[str, Any]] = []

        for url in urls[:5]:
            text, err = await fetch_page(url, proxy_url=proxy_url)
            if err or not text:
                page_reports.append({"url": url, "error": err or "no readable text"})
                continue
            claims = await extract_claims(
                self._router,
                page_text=text,
                dimension_name=dim.name,
                subcriteria=subcriteria,
                max_claims=max_claims,
            )
            verified, rejected = filter_verified_claims(claims, text)
            rejected_total += len(rejected)
            for c in verified:
                await wm.add_evidence(
                    company_id=cid,
                    subject_id=subj.subject_id,
                    dimension_id=dim.dimension_id,
                    subcriterion=str(c.get("subcriterion") or ""),
                    claim=str(c.get("claim") or "")[:1000],
                    value_text=str(c.get("value_text") or "")[:300],
                    source_url=url,
                    source_type="site",
                    geo_state=geo_state,
                    # Agent collection is logged-out only, by policy.
                    customer_state="logged_out",
                    # Quoted from a live page and substring-verified: solid on
                    # provenance, but a marketing page is still the brand
                    # talking about itself — hence medium, not high.
                    confidence="medium",
                    excerpt=str(c.get("excerpt") or "")[:1000],
                    collector="agent",
                )
                written += 1
            page_reports.append(
                {
                    "url": url,
                    "chars": len(text),
                    "proposed": len(claims),
                    "verified": len(verified),
                    "rejected": len(rejected),
                    "rejections": [r["reason"] for r in rejected[:3]],
                }
            )

        return ToolResult(
            success=True,
            data={
                "subject": subj.name,
                "dimension": dim.name,
                "geo_state": geo_state,
                "proxied": bool(proxy_url),
                "evidence_written": written,
                "claims_rejected": rejected_total,
                "pages": page_reports,
                "note": (
                    "Claims are only saved when their verbatim excerpt is found "
                    "in the fetched page. Score with watch_score once coverage "
                    "is adequate."
                ),
            },
        )


class WatchQueueTool(_WatchToolBase):
    """What needs re-observing, and the schedules that drive it."""

    def __init__(self) -> None:
        super().__init__()
        self._scheduler: Any = None

    @property
    def name(self) -> str:
        return "watch_queue"

    @property
    def description(self) -> str:
        return (
            "The competitive-intelligence refresh queue: which brand × "
            "dimension pairs have never been observed or are overdue against "
            "their cadence (promotional weekly, operational monthly, financial "
            "quarterly), most urgent first. action='schedule' installs the "
            "recurring weekly/monthly/quarterly refresh jobs."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "schedule"]},
                "cadence": {
                    "type": "string",
                    "enum": ["weekly", "monthly", "quarterly"],
                    "description": "Only show pairs on this cadence.",
                },
                "limit": {"type": "integer", "description": "Default 25."},
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        cid = _company(params)
        action = str(params.get("action") or "list").lower()

        if action == "schedule":
            if self._scheduler is None:
                return ToolResult(
                    success=False, error="scheduler unavailable — cannot install jobs"
                )
            crons = {
                "weekly": "0 9 * * 1",
                "monthly": "0 9 1 * *",
                "quarterly": "0 9 1 1,4,7,10 *",
            }
            existing = {s.name: s.id for s in await self._scheduler.list_schedules()}
            created: list[str] = []
            for cadence, cron in crons.items():
                name = f"Competitive refresh · {cadence}"
                if name in existing:
                    await self._scheduler.delete_schedule(existing[name])
                await self._scheduler.create_schedule(
                    name=name,
                    task_goal=(
                        f"Refresh the {cadence} competitive-intelligence "
                        f"dimensions for {cid}. Call watch_queue with "
                        f"cadence={cadence} to see what is due, then "
                        f"watch_observe each pair, then watch_score the ones "
                        f"that now have enough evidence. Do not invent facts."
                    ),
                    cron_expression=cron,
                    description="Auto-created by watch_queue action=schedule",
                    company_id=cid,
                )
                created.append(f"{name} ({cron})")
            return ToolResult(success=True, data={"schedules": created})

        gaps = await self._watch_manager.staleness(cid)
        cadence = str(params.get("cadence") or "").lower()
        if cadence:
            gaps = [g for g in gaps if g.get("cadence") == cadence]
        # Never-observed first, then the most overdue.
        gaps.sort(
            key=lambda g: (
                g["status"] != "never_observed",
                -(g.get("age_days") or 0),
            )
        )
        limit = int(params.get("limit") or 25)
        return ToolResult(
            success=True,
            data={
                "due_count": len(gaps),
                "never_observed": sum(
                    1 for g in gaps if g["status"] == "never_observed"
                ),
                "stale": sum(1 for g in gaps if g["status"] == "stale"),
                "queue": gaps[:limit],
            },
        )


def create_watch_tools() -> list[BaseTool]:
    """All competitive-intelligence tools."""
    return [
        WatchSubjectTool(),
        WatchDimensionTool(),
        WatchEvidenceTool(),
        WatchScoreTool(),
        WatchScorecardTool(),
        WatchSnapshotTool(),
        WatchDiffTool(),
        WatchBoardReportTool(),
        WatchObserveTool(),
        WatchQueueTool(),
    ]
