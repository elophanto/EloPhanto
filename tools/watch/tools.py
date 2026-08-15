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
            return ToolResult(success=False, error=f"{self.name} not initialized (watch_manager)")
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
            return ToolResult(success=True, data={"subject_id": sub.subject_id, "name": sub.name})

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
                return ToolResult(success=False, error="subject and dimension are both required")
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
            return ToolResult(success=False, error="subject and dimension are both required")
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
                return ToolResult(success=False, error="path is required for format='xlsx'")
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
            # A provisional score is marked at the number itself. A footnote
            # is not enough — the figure gets quoted on its own.
            if r.get("provisional") and o["normalized_pct"] is not None:
                score += "†"
            cp = r["views"].get("customer_proposition", {}).get("normalized_pct")
            tp = r["views"].get("transition_priority", {}).get("normalized_pct")
            lines.append(
                f"| {r['rank'] or '—'} | {r['name']}{' *(us)*' if r['is_self'] else ''} "
                f"| {r['group']} | {score} | {'—' if cp is None else f'{cp:.1f}'} "
                f"| {'—' if tp is None else f'{tp:.1f}'} "
                f"| {o['coverage_pct']:.0f}% | {o['confidence']} |"
            )
        provisional = [
            r
            for r in card["rows"]
            if r.get("provisional") and r["overall"]["normalized_pct"] is not None
        ]
        if provisional:
            lines += ["", "**† Provisional — not ranked:**"]
            lines += [
                f"- {r['name']}: {r.get('provisional_reason', 'insufficient evidence')}"
                for r in provisional
            ]
        note = (
            "\nScores are normalised to the weight actually scored; '—' means no "
            "evidence yet, never a weak result. Coverage shows the evidence gap."
        )
        if not card["weights_valid"]:
            note += f"\n⚠️  Dimension weights sum to {card['weight_total_pct']}%, not 100%."
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
            return ToolResult(success=True, data={"count": len(snaps), "snapshots": snaps})

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


_DECK_NARRATIVE_SYSTEM = """You write the words for an executive competitor
board deck. The room is a leadership team deciding how to respond in their
market; they care about competitors and their moves, not about how the
analysis was produced. You are given FACTS only: current standings, our
position, observed facts per key brand, the material changes this period,
the judged implications, and the evidence gaps.

Return STRICT JSON:
{"headline": str,
 "bullets": [str, ...],
 "exec": {"findings": [str, ...], "threats": [str, ...], "watch": [str, ...]},
 "titles": {"standings": str, "versus": str, "changes": str, "coverage": str},
 "commentary": {"standings": str, "versus": str, "changes": str,
                "coverage": str, "glance": str},
 "profiles": [{"brand": str, "title": str,
               "observations": [str, ...], "implications": [str, ...]}],
 "next_steps": [str, ...]}

- headline: one sentence, at most 14 words – the single thing the room must
  take away. Lead with the so-what for US, not a description of the market.
- bullets: 3 to 5, each at most 20 words, priority order.
- exec: what the room reads first, three columns –
  findings: 3-4 market findings (what competitors are doing, who moved);
  threats: 2-3 competitive threats to US, sharpest first;
  watch: 2-3 things to watch or act on next period.
  Each entry at most 18 words, grounded only in the facts given.
- titles: an ACTION TITLE per slide – a sentence someone could disagree with
  ("High 5 leads a thin field"), never a label ("Standings overview").
  At most 10 words each.
- commentary: one line per slide (max 22 words) telling the room what to take
  from that slide. "glance" covers the headline-numbers slide.
- profiles: one per brand listed in brand_facts EXCEPT ours, in the given
  order. For each brand:
  title – an action title about THAT brand's market position, max 10 words;
  observations – 2-4 lines on what the brand actually does in the market
  (offers, promotions, payments, product, terms), drawn from its observed
  facts, each max 20 words;
  implications – 1-2 lines on what that means for US, each max 18 words.
- next_steps: 2 to 4 concrete actions, each at most 16 words.

Rules:
- Use ONLY the facts given. Never invent a number, a move, a brand, a source.
- Talk about the MARKET and the BRANDS, never about the analysis. Words like
  evidence, coverage, dimension, scored, provisional or snapshot belong only
  in titles.coverage and commentary.coverage; everywhere else say what the
  brand does, not how well we measured it.
- If our brand is provisional or unscored, say so plainly; do not rank it.
- If there is no material change, say so; do not manufacture urgency.
- NEVER mention internal bookkeeping: no hashes, SHA, file names, file paths,
  manifests, ledgers, registers, corpora, checkpoints, run IDs, snapshots or
  tool names. The room hears about the MARKET, not about the machinery.
- Punctuation: en dashes (–), never em dashes (—).
- No filler, no preamble, no restating the method."""


def _collect_exhibits(
    evidence: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    config: Any = None,
) -> dict[str, list[dict[str, str]]]:
    """brand -> up to 3 newest storefront exhibits ``{path, url, observed_at}``.

    Register-carried paths come first — the shot stands beside the claims
    from that page. Brands whose shots never landed on a row (an unreadable
    site rescued by third-party sources) fall back to the workspace exhibit
    directory, so a walled brand still shows its storefront."""
    from pathlib import Path

    out: dict[str, list[dict[str, str]]] = {}
    seen: set[str] = set()
    for e in evidence:
        pth = str(e.get("screenshot_path") or "")
        if not pth or pth in seen or not Path(pth).exists():
            continue
        seen.add(pth)
        out.setdefault(str(e.get("subject") or ""), []).append(
            {
                "path": pth,
                "url": str(e.get("source_url") or ""),
                "observed_at": str(e.get("observed_at") or ""),
            }
        )
    ws = str(getattr(config, "workspace", "") or "").strip()
    if ws:
        root = Path(ws).expanduser()
        if not root.is_absolute():
            root = Path(getattr(config, "project_root", Path.cwd())) / root
        base = root / "watch-screenshots"
        for r in rows:
            name = str(r.get("name") or "")
            if not name or out.get(name):
                continue
            slug = "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-") or "brand"
            d = base / slug
            if not d.is_dir():
                continue
            files = sorted(d.glob("*.jpg"), key=lambda f: f.name, reverse=True)
            if files:
                out[name] = [{"path": str(f), "url": "", "observed_at": ""} for f in files[:3]]
    return {k: v[:3] for k, v in out.items() if v}


def _brand_facts(card: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Observed facts per key brand, for the narrative model: the ranked
    leader and runners-up plus our brand, newest first, at most one claim
    per dimension per brand so eight lines cover the whole product."""
    rows = card.get("rows", [])
    ranked = [r for r in rows if r.get("rank") is not None]
    picks: list[str] = []
    for r in ranked:
        if not r.get("is_self"):
            picks.append(r["name"])
        if len(picks) >= 4:
            break
    us = next((r["name"] for r in rows if r.get("is_self")), None)
    if us:
        picks.append(us)
    facts: dict[str, list[str]] = {}
    for name in picks:
        seen_dims: set[str] = set()
        lines: list[str] = []
        for e in evidence:  # evidence_with_names is newest-first
            if str(e.get("subject") or "") != name:
                continue
            dim = str(e.get("dimension") or "")
            if dim in seen_dims:
                continue
            claim = str(e.get("claim") or "").strip()
            if not claim:
                continue
            seen_dims.add(dim)
            lines.append(f"[{dim}] {claim[:160]}")
            if len(lines) >= 8:
                break
        if lines:
            facts[name] = lines
    return facts


async def _narrate_for_deck(
    router: Any,
    *,
    card: dict[str, Any],
    diff: dict[str, Any] | None,
    judged: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The deck's words. Model-written from facts when a router exists;
    otherwise the computed factual fallback — and the deck labels which."""
    from core.watch_deck import factual_narrative

    fallback = factual_narrative(card, diff, judged, gaps)
    if router is None:
        return fallback
    import json as _json

    rows = card.get("rows", [])
    facts = {
        "standings": [
            {
                "rank": r.get("rank"),
                "brand": r["name"],
                "is_us": bool(r.get("is_self")),
                "overall_normalized_pct": r["overall"]["normalized_pct"],
                "provisional": bool(r.get("provisional")),
                "coverage_pct": r["overall"]["coverage_pct"],
                "unscored_dimensions": r["overall"].get("unscored_dimensions", [])[:6],
            }
            for r in rows[:14]
        ],
        "material_changes": (
            None
            if diff is None
            else {
                "count": diff.get("material_count", 0),
                "changed": [
                    {
                        "subject": c["subject"],
                        "items": [i["detail"] for i in c["items"]],
                    }
                    for c in diff.get("changed", [])
                ],
                "added_subjects": diff.get("added_subjects", []),
                "removed_subjects": diff.get("removed_subjects", []),
            }
        ),
        "implications": judged,
        "brand_facts": _brand_facts(card, evidence or []),
        "gaps": {
            "never_observed_pairs": sum(1 for g in gaps if g.get("status") == "never_observed"),
            "unobserved_brands": sorted(
                {g["subject"] for g in gaps if g.get("status") == "never_observed"}
            )[:6],
            "stale": sum(1 for g in gaps if g.get("status") == "stale"),
        },
    }
    try:
        resp = await router.complete(
            messages=[
                {"role": "system", "content": _DECK_NARRATIVE_SYSTEM},
                {"role": "user", "content": _json.dumps(facts, indent=1, default=str)},
            ],
            task_type="analysis",
            temperature=0.3,
            max_tokens=2400,
        )
        text = (resp.content or "").strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            text = text[4:] if text.startswith("json") else text
        data = _json.loads(text)
        bullets = [str(b).strip() for b in data.get("bullets", []) if str(b).strip()]
        if not bullets:
            return fallback
        known = {str(r.get("name") or "") for r in rows}
        exec_zone = data.get("exec") or {}
        profiles = [
            {
                "brand": str(pr.get("brand") or "").strip(),
                "title": str(pr.get("title") or "").strip(),
                "observations": [
                    str(o).strip() for o in (pr.get("observations") or []) if str(o).strip()
                ][:4],
                "implications": [
                    str(i).strip() for i in (pr.get("implications") or []) if str(i).strip()
                ][:2],
            }
            for pr in (data.get("profiles") or [])
            if isinstance(pr, dict) and str(pr.get("brand") or "").strip() in known
        ]
        return {
            "headline": str(data.get("headline") or "").strip(),
            "bullets": bullets[:5],
            "exec": {
                "findings": [
                    str(x).strip() for x in (exec_zone.get("findings") or []) if str(x).strip()
                ][:4],
                "threats": [
                    str(x).strip() for x in (exec_zone.get("threats") or []) if str(x).strip()
                ][:3],
                "watch": [str(x).strip() for x in (exec_zone.get("watch") or []) if str(x).strip()][
                    :3
                ],
            },
            "profiles": [pr for pr in profiles if pr["observations"]][:4],
            "titles": {
                k: str(v).strip() for k, v in (data.get("titles") or {}).items() if str(v).strip()
            },
            "commentary": {
                k: str(v).strip()
                for k, v in (data.get("commentary") or {}).items()
                if str(v).strip()
            },
            "next_steps": [
                str(b).strip() for b in (data.get("next_steps") or []) if str(b).strip()
            ][:4]
            or fallback["next_steps"],
            "source": "model",
        }
    except Exception as e:  # the deck still ships — as facts, and says so
        import logging

        logging.getLogger(__name__).warning("deck narrative failed: %s", e)
        return fallback


class WatchBoardReportTool(_WatchToolBase):
    """Turn the month's material changes into implications and decisions."""

    def __init__(self) -> None:
        super().__init__()
        self._router: Any = None
        self._config: Any = None  # workspace root, for storefront exhibits

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
            "plus current standings and outstanding evidence gaps. When written "
            "to a path, the executive deck (.pptx) is written beside it."
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
                "deck": {
                    "type": "boolean",
                    "description": (
                        "Also write the executive deck (.pptx) — the same facts "
                        "and judgement as ~10 board slides. Default true whenever "
                        "`path` is set; the deck lands beside the report."
                    ),
                },
                "deck_path": {
                    "type": "string",
                    "description": (
                        "Where to write the deck. Default: `path` with a .pptx suffix."
                    ),
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
            facts.append({"subject": "(new entrants)", "changes": diff["added_subjects"]})
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
            overall_txt = fmt(o["normalized_pct"])
            if r.get("provisional") and o["normalized_pct"] is not None:
                overall_txt += "†"
            lines.append(
                f"| {r['rank'] or '—'} | {r['name']}{' *(us)*' if r['is_self'] else ''} "
                f"| {overall_txt} | {fmt(cp)} | {fmt(tp)} "
                f"| {o['coverage_pct']:.0f}% |"
            )
        board_provisional = [
            r
            for r in card["rows"][:15]
            if r.get("provisional") and r["overall"]["normalized_pct"] is not None
        ]
        if board_provisional:
            lines += [
                "",
                "† Provisional: scored on too little of the model to hold a rank. "
                "The figure is real; the standing is not yet earned.",
            ]
            lines += [
                f"- **{r['name']}** — {r.get('provisional_reason', '')}" for r in board_provisional
            ]
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
                lines.append(f"**New in the analysis:** {', '.join(diff['added_subjects'])}")
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
            + (f" (e.g. {never[0]['subject']} / {never[0]['dimension']})" if never else "")
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

        # The deck is the same facts and the same judgement, before the
        # snapshot below — so both deliverables describe one period. It is
        # part of the pack, not an extra: whenever the report goes to disk,
        # the deck goes beside it unless deck=false.
        deck_written = None
        deck_error = None
        deck_target = str(params.get("deck_path") or "").strip()
        if not deck_target and written:
            from pathlib import Path as _P

            deck_target = str(_P(written).with_suffix(".pptx"))
        if not params.get("deck", True):
            deck_target = ""
        if deck_target:
            try:
                from core.watch_deck import render_executive_deck

                ev_rows = await wm.evidence_with_names(cid)
                summary = await _narrate_for_deck(
                    self._router,
                    card=card,
                    diff=diff,
                    judged=judged,
                    gaps=gaps,
                    evidence=ev_rows,
                )
                deck_written = render_executive_deck(
                    card,
                    diff=diff,
                    judged=judged,
                    summary=summary,
                    gaps=gaps,
                    evidence_count=len(ev_rows),
                    screenshots=_collect_exhibits(ev_rows, card.get("rows", []), self._config),
                    path=deck_target,
                )
            except Exception as e:
                deck_error = str(e)

        snap_id = None
        if params.get("take_snapshot", True):
            snap_id = await wm.take_snapshot(cid, label="board report")

        data: dict[str, Any] = {
            "markdown": report,
            "material_count": (diff or {}).get("material_count", 0),
            "judged_items": len(judged),
            "gaps_never_observed": len(never),
            "gaps_stale": len(stale),
            "path": written,
            "snapshot_id": snap_id,
        }
        if deck_target:
            data["deck_path"] = deck_written
            if deck_error:
                data["deck_error"] = deck_error
        return ToolResult(success=True, data=data)


class WatchExecutiveDeckTool(_WatchToolBase):
    """The board pack as slides: standings, our position, what moved, what to
    do, what to decide, and how much of it is actually measured."""

    def __init__(self) -> None:
        super().__init__()
        self._router: Any = None
        self._config: Any = None  # workspace root, for storefront exhibits

    @property
    def name(self) -> str:
        return "watch_executive_deck"

    @property
    def description(self) -> str:
        return (
            "Produce the executive presentation (.pptx, ~16 slides) of the "
            "competitor analysis: executive summary (findings / threats / "
            "watch next), standings chart, our brand vs the leader, a deep-"
            "dive slide per key competitor (observations → implications), "
            "storefront screenshot exhibits, market moves, implications and "
            "recommendations, decisions required, and appendix (coverage, "
            "heatmap, method). Same stored evidence as the workbook and board "
            "report — use when asked for a presentation, deck, slides or "
            "board pack. Does not snapshot; run watch_board_report to close "
            "the cycle."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Where to write the .pptx. Default ~/Desktop/competitor-deck.pptx",
                },
                "snapshot_id": {
                    "type": "string",
                    "description": "Compare against this snapshot. Default: most recent.",
                },
                "title": {
                    "type": "string",
                    "description": "Deck title. Default 'Competitive Intelligence — Executive Briefing'.",
                },
                "market_label": {
                    "type": "string",
                    "description": "Subtitle on the cover, e.g. the market or client name.",
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
        from pathlib import Path

        path = Path(str(params.get("path") or "~/Desktop/competitor-deck.pptx")).expanduser()
        if path.suffix.lower() != ".pptx":
            path = path.with_suffix(".pptx")

        diff = await wm.diff_since_snapshot(cid, snapshot_id=params.get("snapshot_id"))
        card = await wm.scorecard(cid)
        gaps = await wm.staleness(cid)
        evidence = await wm.evidence_with_names(cid)

        # Reuse the report's judgement so both artefacts say the same thing.
        judge = WatchBoardReportTool()
        judge._router = self._router
        judged = await judge._judge(diff) if diff else []
        summary = await _narrate_for_deck(
            self._router,
            card=card,
            diff=diff,
            judged=judged,
            gaps=gaps,
            evidence=evidence,
        )
        try:
            from core.watch_deck import render_executive_deck

            written = render_executive_deck(
                card,
                diff=diff,
                judged=judged,
                summary=summary,
                gaps=gaps,
                evidence_count=len(evidence),
                screenshots=_collect_exhibits(evidence, card.get("rows", []), self._config),
                path=path,
                title=str(params.get("title") or "Competitive Intelligence — Executive Briefing"),
                market_label=str(params.get("market_label") or ""),
            )
        except Exception as e:
            return ToolResult(success=False, error=f"deck export failed: {e}")

        ranked = [r for r in card["rows"] if r.get("rank") is not None]
        return ToolResult(
            success=True,
            data={
                "path": written,
                "brands": len(card["rows"]),
                "ranked": len(ranked),
                "material_count": (diff or {}).get("material_count", 0),
                "judged_items": len(judged),
                "summary_source": summary.get("source", "facts"),
                "note": (
                    "Summary and implications are model-written from the factual "
                    "record and labelled as such on the slides; standings, scores "
                    "and gaps are computed. Unscored dimensions are blank, never "
                    "zero, and provisional brands are listed, not ranked."
                    if summary.get("source") == "model"
                    else "No model available: the summary slide is factual only "
                    "and says so. Standings, scores and gaps are computed."
                ),
            },
        )


def _exit_not_verified(geo_state: str, detail: dict[str, Any]) -> ToolResult:
    """Refuse when the exit cannot be *proven* to be in the claimed state.

    Two distinct failures share this gate: the provider routed the request
    somewhere else (targeting is best-effort — observed `_state-texas`
    exiting in Virginia), or the geolocation echoes were unreachable so
    nothing could be proven either way. Both end the same: no proof, no
    stamp. "Could not verify" must never soften into "verified".
    """
    landed = [
        f"{g.get('state_code')} ({g.get('ip')})"
        for g in detail.get("landed", [])
        if isinstance(g, dict) and g.get("state_code")
    ]
    unreachable = any(isinstance(g, dict) and g.get("error") for g in detail.get("landed", []))
    if landed:
        why = f"the exit landed in {', '.join(landed)} instead"
    elif unreachable:
        why = "the geolocation services could not be reached, so nothing was proven"
    else:
        why = "the exit could not be verified"
    return ToolResult(
        success=False,
        error=(
            f"Exit verification failed for geo_state={geo_state}: {why}. "
            "State targeting is best-effort at the provider, so retrying may "
            "land correctly (each attempt re-rolls the exit). Evidence is only "
            "stamped with a state its exit provably came from."
        ),
    )


def _no_exit_for_state(geo_state: str) -> ToolResult:
    """Refuse rather than collect from the wrong place and stamp it right.

    `geo_state` on an evidence row is a provenance claim — "this is what a
    customer in Nevada sees". If no exit actually comes out in that state,
    the honest options are to route there or to say so. Fetching from the
    host's own location (or from a different state's exit) and writing "NV"
    on it is neither, so it is not offered.
    """
    return ToolResult(
        success=False,
        error=(
            f"No network exit for geo_state={geo_state}. Add a proxy.pool entry "
            f"for {geo_state}, or — if the single proxy is pinned to that state "
            f"(e.g. an IPRoyal password ending _state-…) — declare it with "
            f"`proxy.state: {geo_state}` in config.yaml. Refusing to collect from "
            "the host's own location and stamp the evidence with a state it was "
            "not observed from. Omit geo_state to observe without a state claim."
        ),
    )


class WatchObserveTool(_WatchToolBase):
    """Collect evidence from public pages — every claim proof-checked."""

    def __init__(self) -> None:
        super().__init__()
        self._router: Any = None
        self._config: Any = None
        self._browser_manager: Any = None

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
            "— unverifiable claims are discarded, not saved. Falls back to the real "
            "browser when a site is a JS app or blocks plain requests. "
            "Public/logged-out pages only; anything behind an account is "
            "operator-collected."
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
            fetch_page_best_effort,
            filter_verified_claims,
        )

        cid = _company(params)
        wm = self._watch_manager
        subj = await wm.get_subject_by_name(str(params.get("subject") or ""), cid)
        if subj is None:
            return ToolResult(success=False, error=f"no such brand: {params.get('subject')!r}")
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
        if geo_state != "n/a" and not proxy_url:
            return _no_exit_for_state(geo_state)

        # A state stamp is proven, not assumed: pin one exit and check its
        # geolocation before anything is fetched, then fetch through the
        # pinned session so the proof binds the pages it covers.
        exit_info: dict[str, Any] = {}
        if geo_state != "n/a" and proxy_url:
            from core.watch_observe import verify_exit_state

            ok, proxy_url, exit_info = await verify_exit_state(proxy_url, geo_state)
            if not ok:
                return _exit_not_verified(geo_state, exit_info)
        http_exit_ip = str(exit_info.get("ip") or "")

        subcriteria = [str(s.get("name", "")) for s in dim.subcriteria if s.get("name")]
        max_claims = int(params.get("max_claims") or 8)

        written = 0
        rejected_total = 0
        page_reports: list[dict[str, Any]] = []
        # Browser-escalated pages exit through Chrome's own credentials, not
        # the verified session — a different address. Checked once, lazily,
        # the first time a page actually escalates; None = not yet checked.
        browser_exit: dict[str, Any] | None = None

        for url in urls[:5]:
            text, fetch_err, method = await fetch_page_best_effort(
                url, browser_manager=self._browser_manager, proxy_url=proxy_url
            )
            if fetch_err or not text:
                page_reports.append({"url": url, "error": fetch_err or "no readable text"})
                continue
            page_exit_ip = http_exit_ip
            if geo_state != "n/a" and method == "browser":
                if browser_exit is None:
                    from core.watch_observe import verify_browser_exit

                    b_ok, b_detail = await verify_browser_exit(self._browser_manager, geo_state)
                    browser_exit = {"ok": b_ok, **b_detail}
                if not browser_exit.get("ok"):
                    page_reports.append(
                        {
                            "url": url,
                            "method": method,
                            "error": (
                                f"page needed the browser, but Chrome's exit is "
                                f"not verified in {geo_state} "
                                f"({browser_exit.get('state_code') or browser_exit.get('error', 'unknown')}) "
                                "— page skipped so the state stamp stays true"
                            ),
                        }
                    )
                    continue
                page_exit_ip = str(browser_exit.get("ip") or "")
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
                    exit_ip=page_exit_ip,
                )
                written += 1
            page_reports.append(
                {
                    "url": url,
                    "method": method,
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
                "exit": exit_info or None,
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


class WatchAnalyzeTool(_WatchToolBase):
    """One command: read a brand, score every dimension, save the deliverables."""

    def __init__(self) -> None:
        super().__init__()
        self._router: Any = None
        self._vault: Any = None  # for search-driven source expansion
        self._config: Any = None
        self._browser_manager: Any = None

    @property
    def group(self) -> str:
        return "watch"

    @property
    def name(self) -> str:
        return "watch_analyze"

    @property
    def description(self) -> str:
        return (
            "Run a FULL competitor analysis on one brand end to end: reads its "
            "site (landing page plus terms / promotions / payments pages, using "
            "the real browser when a site is a JS app or blocks requests), files "
            "every verifiable fact into the evidence register, scores each "
            "dimension it has evidence for, and saves the pack: scorecard "
            "workbook, board report and executive deck (.pptx). Use this when "
            "asked to 'do a competitor analysis on "
            "X' or 'analyse X and save the results'. Dimensions with no evidence "
            "are left unscored rather than guessed."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "Brand to analyse (must be tracked, or pass url).",
                },
                "url": {
                    "type": "string",
                    "description": "Homepage — needed only if the brand isn't tracked yet.",
                },
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Explicit pages to read instead of auto-discovering.",
                },
                "dimensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Limit to these dimensions. Default: all.",
                },
                "out_dir": {
                    "type": "string",
                    "description": "Where to save the workbook, report and deck. Default ~/Desktop.",
                },
                "geo_state": {
                    "type": "string",
                    "description": "Observe as this US state.",
                },
                "max_pages": {
                    "type": "integer",
                    "description": "Pages to read. Default 4.",
                },
                "save": {
                    "type": "boolean",
                    "description": "Write the deliverables to disk. Default true.",
                },
                "deck": {
                    "type": "boolean",
                    "description": (
                        "Also write the executive presentation (.pptx). Default "
                        "true — it is part of the pack. Set false to skip it."
                    ),
                },
                "expand_sources": {
                    "type": "boolean",
                    "description": (
                        "When the brand's own site leaves dimensions without "
                        "evidence, search the web for third-party sources "
                        "(reviews, help centers) and read those too. Default "
                        "true; needs the search_sh_api_key vault entry."
                    ),
                },
                "screenshots": {
                    "type": "boolean",
                    "description": (
                        "Also file clean storefront screenshots (homepage + up "
                        "to 2 key pages) as visual evidence, captured only "
                        "through a state-verified browser exit. Default true."
                    ),
                },
                "company_id": {"type": "string"},
            },
            "required": ["subject"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    def _exhibit_dir(self, brand: str) -> Any:
        """``<workspace>/watch-screenshots/<brand-slug>/`` — None when no
        workspace is configured (exhibits then simply are not filed)."""
        from pathlib import Path

        ws = str(getattr(self._config, "workspace", "") or "").strip()
        if not ws:
            return None
        root = Path(ws).expanduser()
        if not root.is_absolute():
            root = Path(getattr(self._config, "project_root", Path.cwd())) / root
        slug = "".join(ch if ch.isalnum() else "-" for ch in brand.lower()).strip("-") or "brand"
        d = root / "watch-screenshots" / slug
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        if self._router is None:
            return ToolResult(
                success=False, error="watch_analyze needs a model (router not injected)"
            )
        from core.watch_observe import (
            collect_pages,
            extract_claims_multi,
            filter_verified_claims,
            score_dimension,
        )

        cid = _company(params)
        wm = self._watch_manager
        name = str(params.get("subject") or "").strip()

        subj = await wm.get_subject_by_name(name, cid)
        if subj is None:
            url = str(params.get("url") or "").strip()
            if not url:
                known = [s.name for s in await wm.list_subjects(cid)]
                return ToolResult(
                    success=False,
                    error=(
                        f"{name!r} is not tracked. Pass url= to add it, or pick "
                        f"one of: {known[:14]}"
                    ),
                )
            subj = await wm.add_subject(name=name, company_id=cid, url=url)

        dimensions = await wm.list_dimensions(cid)
        if not dimensions:
            return ToolResult(
                success=False,
                error=(
                    "no scoring dimensions defined — seed a frame first, e.g. "
                    "watch_dimension action='seed' pack='social_casino_t1'"
                ),
            )
        wanted = {d.lower() for d in (params.get("dimensions") or [])}
        if wanted:
            dimensions = [d for d in dimensions if d.name.lower() in wanted]
            if not dimensions:
                return ToolResult(success=False, error="no matching dimensions")

        geo_state = str(params.get("geo_state") or "n/a")
        proxy_url = None
        if self._config is not None and getattr(self._config, "proxy", None):
            proxy_url = self._config.proxy.request_proxy_url(geo_state) or None
        if geo_state != "n/a" and not proxy_url:
            return _no_exit_for_state(geo_state)

        # Prove the exit before reading anything; fetch through the session
        # that passed. See watch_observe — same rule, same reasons.
        exit_info: dict[str, Any] = {}
        if geo_state != "n/a" and proxy_url:
            from core.watch_observe import verify_exit_state

            ok, proxy_url, exit_info = await verify_exit_state(proxy_url, geo_state)
            if not ok:
                return _exit_not_verified(geo_state, exit_info)
        http_exit_ip = str(exit_info.get("ip") or "")

        # ── 1. Read the site ──
        explicit = [str(u) for u in (params.get("urls") or []) if str(u).strip()]
        max_pages = int(params.get("max_pages") or 4)
        if explicit:
            pages = []
            from core.watch_observe import fetch_page_best_effort

            for u in explicit[:max_pages]:
                t, e, m = await fetch_page_best_effort(
                    u, browser_manager=self._browser_manager, proxy_url=proxy_url
                )
                pages.append({"url": u, "text": t, "error": e, "method": m})
        else:
            if not subj.url:
                return ToolResult(success=False, error=f"{subj.name} has no URL — pass url or urls")
            pages = await collect_pages(
                subj.url,
                browser_manager=self._browser_manager,
                proxy_url=proxy_url,
                max_pages=max_pages,
            )

        # Browser-escalated pages exit through Chrome's credentials, not the
        # verified session. One check covers them all; failing it drops those
        # pages from a state-stamped run rather than stamping them falsely.
        browser_exit: dict[str, Any] = {}
        if geo_state != "n/a" and any(
            str(p.get("method") or "").startswith("browser") for p in pages
        ):
            from core.watch_observe import verify_browser_exit

            b_ok, b_detail = await verify_browser_exit(self._browser_manager, geo_state)
            browser_exit = {"ok": b_ok, **b_detail}
            if not b_ok:
                dropped = [p for p in pages if str(p.get("method") or "").startswith("browser")]
                pages = [p for p in pages if not str(p.get("method") or "").startswith("browser")]
                for p_ in dropped:
                    pages.append(
                        {
                            "url": p_.get("url"),
                            "text": "",
                            "method": p_.get("method"),
                            "error": (
                                f"browser exit not verified in {geo_state} "
                                f"({b_detail.get('state_code') or b_detail.get('error', 'unknown')}) "
                                "— page dropped so the state stamp stays true"
                            ),
                        }
                    )

        readable = [p for p in pages if p.get("text")]
        # An unreadable site is not the end of the brand — it is the case
        # source expansion exists for. The early return here used to run
        # BEFORE expansion, so the brands that most needed third-party
        # sources (bot-walled, browser exit unverifiable) were exactly the
        # ones that never got them. Now the run continues into expansion
        # with every dimension missing, and only fails if that finds
        # nothing either.
        site_unreadable = not readable
        site_error = (
            f"could not read any page for {subj.name}: "
            f"{[p.get('error') for p in pages]}. The site may need the "
            "browser (is Chrome available?) or an explicit urls list."
        )

        # ── 1c. Storefront exhibits ──
        # A clean screenshot of what a visitor actually sees, filed beside
        # the claims it supports. Captured only through a browser whose exit
        # is verified in the claimed state — an out-of-state storefront is a
        # different product, not an exhibit.
        shots: dict[str, str] = {}
        shots_note = ""
        if params.get("screenshots", True) and self._browser_manager is not None:
            targets: list[str] = []
            if subj.url:
                targets.append(subj.url)
            for p_ in readable:
                u = str(p_.get("url") or "")
                if u and u not in targets:
                    targets.append(u)
            targets = targets[:3]
            if targets:
                allowed = True
                if geo_state != "n/a":
                    if not browser_exit:
                        from core.watch_observe import verify_browser_exit

                        b_ok, b_detail = await verify_browser_exit(self._browser_manager, geo_state)
                        browser_exit = {"ok": b_ok, **b_detail}
                    allowed = bool(browser_exit.get("ok"))
                    if not allowed:
                        shots_note = f"skipped — browser exit not verified in {geo_state}"
                shot_dir = self._exhibit_dir(subj.name) if allowed else None
                if allowed and shot_dir is None:
                    allowed = False
                    shots_note = "skipped — no workspace configured"
                if allowed and shot_dir is not None:
                    from core.watch_observe import (
                        capture_page_screenshot,
                        screenshot_filename,
                    )

                    for u in targets:
                        out = shot_dir / screenshot_filename(u)
                        got = await capture_page_screenshot(self._browser_manager, u, str(out))
                        if got:
                            shots[u] = got
                    if not shots and not shots_note:
                        shots_note = "capture failed on every page"

        # ── 2. Extract + verify, one model call per page across all dimensions ──
        dim_specs = [
            {
                "name": d.name,
                "subcriteria": [str(s.get("name", "")) for s in d.subcriteria if s.get("name")],
            }
            for d in dimensions
        ]
        by_name = {d.name: d for d in dimensions}
        written = 0
        rejected_total = 0
        site_covered: set[str] = set()
        page_reports: list[dict[str, Any]] = []

        for page in readable:
            page_text = page.get("text")
            if not isinstance(page_text, str) or not page_text:
                continue
            claims = await extract_claims_multi(
                self._router, page_text=page_text, dimensions=dim_specs
            )
            verified, rejected = filter_verified_claims(claims, page_text)
            rejected_total += len(rejected)
            for c in verified:
                dim = by_name.get(str(c.get("dimension")))
                if dim is None:
                    continue
                site_covered.add(dim.dimension_id)
                await wm.add_evidence(
                    company_id=cid,
                    subject_id=subj.subject_id,
                    dimension_id=dim.dimension_id,
                    subcriterion=str(c.get("subcriterion") or ""),
                    claim=str(c.get("claim") or "")[:1000],
                    value_text=str(c.get("value_text") or "")[:300],
                    source_url=page["url"],
                    source_type="site",
                    geo_state=geo_state,
                    customer_state="logged_out",
                    confidence="medium",
                    excerpt=str(c.get("excerpt") or "")[:1000],
                    screenshot_path=shots.get(str(page.get("url") or ""), ""),
                    collector="agent",
                    exit_ip=(
                        str(browser_exit.get("ip") or "")
                        if str(page.get("method") or "").startswith("browser")
                        else http_exit_ip
                    ),
                )
                written += 1
            page_reports.append(
                {
                    "url": page["url"],
                    "method": page.get("method"),
                    "chars": len(page_text),
                    "verified": len(verified),
                    "rejected": len(rejected),
                }
            )

        # ── 2b. Expand sources where the brand's own site said nothing ──
        # The site is the primary source; for dimensions it left silent, look
        # where the facts actually live — reviews, help centers, app stores —
        # found by search, fetched through the SAME verified session, held to
        # the same verbatim-excerpt gate. A brand that hides its terms is not
        # a brand we score blind; it is a brand we read about elsewhere.
        expansion_report: dict[str, Any] = {}
        if params.get("expand_sources", True):
            covered = site_covered
            evidenced = {
                e.dimension_id for e in await wm.list_evidence(cid, subject_id=subj.subject_id)
            }
            missing = [d.name for d in dimensions if d.dimension_id not in (covered | evidenced)]
            api_key = None
            if self._vault is not None:
                try:
                    api_key = self._vault.get("search_sh_api_key")
                except Exception:
                    api_key = None
            if missing and not api_key:
                expansion_report = {
                    "attempted": False,
                    "missing_dimensions": missing,
                    "note": "no search_sh_api_key in vault — expansion skipped",
                }
            elif missing:
                from core.watch_observe import (
                    expansion_queries,
                    fetch_page_best_effort,
                    pick_expansion_urls,
                    search_web,
                )

                fetched = {str(pr.get("url") or "") for pr in pages}
                results: list[dict[str, str]] = []
                queries = expansion_queries(subj.name, missing)
                search_key = str(api_key)
                for q in queries:
                    results.extend(await search_web(q, api_key=search_key))
                extra_urls = pick_expansion_urls(results, already_fetched=fetched, limit=4)
                exp_written = 0
                exp_pages: list[dict[str, Any]] = []
                for url in extra_urls:
                    text, fetch_err, method = await fetch_page_best_effort(
                        url,
                        browser_manager=self._browser_manager,
                        proxy_url=proxy_url,
                    )
                    if fetch_err or not text:
                        exp_pages.append({"url": url, "error": fetch_err})
                        continue
                    claims = await extract_claims_multi(
                        self._router,
                        page_text=text,
                        dimensions=[d for d in dim_specs if d["name"] in missing],
                    )
                    verified, _rej = filter_verified_claims(claims, text)
                    for c in verified:
                        dim = by_name.get(str(c.get("dimension")))
                        if dim is None:
                            continue
                        await wm.add_evidence(
                            company_id=cid,
                            subject_id=subj.subject_id,
                            dimension_id=dim.dimension_id,
                            subcriterion=str(c.get("subcriterion") or ""),
                            claim=str(c.get("claim") or "")[:1000],
                            value_text=str(c.get("value_text") or "")[:300],
                            source_url=url,
                            # Third-party pages: real provenance, lower
                            # authority than the brand's own words.
                            source_type="third_party",
                            geo_state=geo_state,
                            customer_state="logged_out",
                            confidence="low",
                            excerpt=str(c.get("excerpt") or "")[:1000],
                            collector="agent",
                            exit_ip=(
                                str(browser_exit.get("ip") or "")
                                if method == "browser"
                                else http_exit_ip
                            ),
                        )
                        exp_written += 1
                    exp_pages.append({"url": url, "method": method, "verified": len(verified)})
                written += exp_written
                expansion_report = {
                    "attempted": True,
                    "missing_dimensions": missing,
                    "queries": queries,
                    "pages": exp_pages,
                    "evidence_written": exp_written,
                }

        if site_unreadable and written == 0:
            exp_note = ""
            if expansion_report.get("attempted"):
                exp_note = (
                    " Source expansion searched "
                    f"{len(expansion_report.get('queries', []))} queries and "
                    "found no verifiable third-party claims either."
                )
            elif expansion_report.get("note"):
                exp_note = f" Source expansion: {expansion_report['note']}."
            return ToolResult(
                success=False,
                data={"source_expansion": expansion_report or None},
                error=site_error + exp_note,
            )

        # ── 3. Score what the evidence supports ──
        scored: list[dict[str, Any]] = []
        unscored: list[str] = []
        for dim in dimensions:
            own = await wm.list_evidence(
                cid, subject_id=subj.subject_id, dimension_id=dim.dimension_id
            )
            if not own:
                unscored.append(dim.name)
                continue
            # Peer evidence makes the 1-5 judgement comparative instead of a
            # guess in isolation; absent peers, the model is told to say so.
            peers: dict[str, list[str]] = {}
            for other in await wm.list_subjects(cid):
                if other.subject_id == subj.subject_id:
                    continue
                rows = await wm.list_evidence(
                    cid, subject_id=other.subject_id, dimension_id=dim.dimension_id
                )
                if rows:
                    peers[other.name] = [r.claim for r in rows[:10]]
            judged = await score_dimension(
                self._router,
                dimension_name=dim.name,
                subcriteria=[str(s.get("name", "")) for s in dim.subcriteria if s.get("name")],
                own_claims=[r.claim for r in own],
                peer_claims=peers,
            )
            if judged is None or judged.get("score") is None:
                await wm.set_score(
                    company_id=cid,
                    subject_id=subj.subject_id,
                    dimension_id=dim.dimension_id,
                    score=None,
                    rationale=(judged or {}).get("rationale", "evidence too thin"),
                    scored_by="agent",
                )
                unscored.append(dim.name)
                continue
            res = await wm.set_score(
                company_id=cid,
                subject_id=subj.subject_id,
                dimension_id=dim.dimension_id,
                score=judged["score"],
                rationale=judged.get("rationale", ""),
                scored_by="agent",
            )
            scored.append(
                {
                    "dimension": dim.name,
                    "score": res.score,
                    "coverage_pct": res.coverage_pct,
                    "provisional": judged.get("provisional", False),
                    "rationale": judged.get("rationale", ""),
                }
            )

        # ── 4. Save the deliverables ──
        saved: dict[str, str] = {}
        if params.get("save", True):
            from pathlib import Path

            out_dir = Path(str(params.get("out_dir") or "~/Desktop")).expanduser()
            out_dir.mkdir(parents=True, exist_ok=True)
            slug = "".join(ch if ch.isalnum() else "-" for ch in subj.name.lower()).strip("-")
            try:
                from core.watch_xlsx import render_scorecard_xlsx

                saved["scorecard"] = render_scorecard_xlsx(
                    await wm.scorecard(cid),
                    dimensions=await wm.list_dimensions(cid),
                    evidence=await wm.evidence_with_names(cid),
                    staleness=await wm.staleness(cid),
                    path=out_dir / f"competitor-scorecard-{slug}.xlsx",
                    title=f"Competitive Scorecard — {subj.name}",
                )
            except Exception as e:
                saved["scorecard_error"] = str(e)

            report_tool = WatchBoardReportTool()
            report_tool._watch_manager = wm
            report_tool._router = self._router
            report_tool._config = self._config
            rep_params: dict[str, Any] = {
                "company_id": cid,
                "path": str(out_dir / f"competitor-report-{slug}.md"),
                "take_snapshot": True,
            }
            want_deck = bool(params.get("deck", True))
            rep_params["deck"] = want_deck
            if want_deck:
                rep_params["deck_path"] = str(out_dir / f"competitor-deck-{slug}.pptx")
            rep = await report_tool.execute(rep_params)
            if rep.success:
                saved["report"] = rep.data.get("path") or ""
                if want_deck:
                    if rep.data.get("deck_path"):
                        saved["deck"] = rep.data["deck_path"]
                    if rep.data.get("deck_error"):
                        saved["deck_error"] = rep.data["deck_error"]

        return ToolResult(
            success=True,
            data={
                "subject": subj.name,
                "pages_read": len(readable),
                "exit": exit_info or None,
                "source_expansion": expansion_report or None,
                "pages": page_reports,
                "evidence_written": written,
                "claims_rejected": rejected_total,
                "dimensions_scored": len(scored),
                "dimensions_unscored": len(unscored),
                "scores": scored,
                "unscored": unscored,
                "screenshots": (
                    {
                        "captured": len(shots),
                        "paths": sorted(shots.values()),
                        **({"note": shots_note} if shots_note else {}),
                    }
                    if (shots or shots_note)
                    else None
                ),
                "saved": saved,
                "note": (
                    "Every saved fact quotes its source and was checked against "
                    "the live page. Unscored dimensions had no supporting "
                    "evidence on the pages read — that is a coverage gap, not a "
                    "weakness of the brand."
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
                "never_observed": sum(1 for g in gaps if g["status"] == "never_observed"),
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
        WatchExecutiveDeckTool(),
        WatchObserveTool(),
        WatchQueueTool(),
        WatchAnalyzeTool(),
    ]
