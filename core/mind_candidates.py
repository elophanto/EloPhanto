"""Candidate generators for the autonomous-mind arbiter.

Each generator is a small async function with the same signature:

    async def from_X(ctx: CandidateContext) -> list[Candidate]

The ``CandidateContext`` carries the live managers (goal, mission,
identity, affect, ego, etc.) plus the current dream-focus lens.
Generators read from those managers, score what they propose by the
intrinsic merit of the proposal (the *arbiter* applies the weights),
and return zero or more ``Candidate`` objects.

Generators must be cheap — they run every wakeup before the LLM is
called. Anything expensive (the actual dream LLM call) is gated by
the legacy code path and the arbiter just renders a "explore dream
phase" candidate referencing the existing tool.

See ``docs/75-AUTONOMOUS-MIND-V2.md`` §Phase 3.2.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core.mind_arbiter import Candidate

logger = logging.getLogger(__name__)


# Reflex cadences. Soft defaults — config can override later if needed.
_CAPABILITY_REVIEW_DAYS = 7.0
_MISSION_REBALANCE_DAYS = 7.0


@dataclass
class CandidateContext:
    """Bag of dependencies generators may read.

    Optional — every field can be None and each generator must
    degrade gracefully. The arbiter wakeup builds this once per cycle
    so generators don't make redundant DB calls.
    """

    goal_manager: Any = None
    mission_manager: Any = None
    identity_manager: Any = None
    affect_manager: Any = None
    ego_manager: Any = None
    dream_focus: str = "balanced"
    # Filled by the arbiter wakeup before generators run. Maps
    # mission_id → priority_weight; the arbiter applies the
    # mission_weight bonus from this lookup so generators don't
    # have to know about scoring.
    mission_weight_map: dict[str, float] | None = None
    # ABE Phase 2 (docs/76-ABE-FRAMEWORK.md). RoleManager handle so
    # `from_role_neglect` can rank roles by last-active staleness.
    # Optional — None disables the candidate source rather than
    # crashing the wakeup. Same shape as the other optional managers.
    role_manager: Any = None
    # ABE Phase 7 (docs/76-ABE-FRAMEWORK.md). CompanyManager handle
    # so `from_unproductized_companies` can flag companies whose
    # product.yaml is missing. Optional — None disables the source.
    # Also lets the generator read project_root for the loader.
    company_manager: Any = None
    project_root: Any = None  # Path | None
    # ABE Phase 10 (docs/76-ABE-FRAMEWORK.md). VoiceManager handle so
    # `from_voiceless_companies` can flag companies that have product
    # + exemplars but no voice.yaml — the operator dropped reference
    # material and is waiting for the agent to extract a voice. None
    # disables the source rather than crashing the wakeup.
    voice_manager: Any = None
    # ABE Phase 11 (docs/76-ABE-FRAMEWORK.md). StrategyManager handle
    # so `from_unplanned_companies`, `from_blocked_strategy_days`, and
    # `from_buildable_blockers` can read strategy state without each
    # generator re-opening the filesystem. None disables those sources.
    strategy_manager: Any = None


# ---------------------------------------------------------------------------
# Workable checkpoints
# ---------------------------------------------------------------------------


async def from_workable_checkpoints(ctx: CandidateContext) -> list[Candidate]:
    """One candidate per goal with a workable next checkpoint.

    A "workable" checkpoint matches Phase 1's
    ``_workable_goals_status`` semantics: ``status='pending'`` or
    ``status='active'`` younger than the staleness cutoff (defaults to
    12h, owned by ``AutonomousMind._STALE_CKPT_HOURS``). Stuck
    checkpoints are NOT proposed here — they appear under reflexes
    as "close this stale goal" candidates instead, so the arbiter
    can still rank closing chores against new work.

    Feasibility is set higher for shorter goals (current_checkpoint
    near total) — those are close to shipping. expected_value tracks
    the goal's place in the plan: the first checkpoint of a 15-step
    goal is worth less today than the 14th.
    """
    if not ctx.goal_manager:
        return []

    out: list[Candidate] = []
    try:
        db = ctx.goal_manager._db  # noqa: SLF001 — intentional internal
        for status in ("active", "planning"):
            goals = await ctx.goal_manager.list_goals(status=status, limit=20)
            for g in goals:
                rows = await db.execute(
                    "SELECT checkpoint_order, status, title, started_at "
                    "FROM goal_checkpoints WHERE goal_id = ? "
                    "ORDER BY checkpoint_order",
                    (g.goal_id,),
                )
                if not rows:
                    # Freshly created planning goal — propose decompose.
                    out.append(
                        Candidate(
                            source="workable_checkpoint",
                            action_spec=(
                                f"Decompose planning goal '{g.goal[:80]}' "
                                f"into checkpoints via goal_status / "
                                f"goal_decompose."
                            ),
                            expected_value=6.0,
                            feasibility=0.9,
                            lens_match=0.5,
                            cost=2.0,
                            mission_id=g.mission_id,
                            dedup_key=f"goal_decompose:{g.goal_id}",
                            metadata={"goal_id": g.goal_id, "kind": "decompose"},
                        )
                    )
                    continue
                next_workable = _pick_next_workable(rows)
                if next_workable is None:
                    continue
                progress = (
                    g.current_checkpoint / g.total_checkpoints
                    if g.total_checkpoints
                    else 0.0
                )
                # Late checkpoints are worth more (closer to shipping).
                expected = 4.0 + 4.0 * progress
                out.append(
                    Candidate(
                        source="workable_checkpoint",
                        action_spec=(
                            f"Advance goal '{g.goal[:60]}' — next checkpoint "
                            f"#{next_workable['checkpoint_order']}: "
                            f"{next_workable['title']}"
                        ),
                        expected_value=expected,
                        feasibility=0.75,
                        lens_match=0.5,
                        cost=2.5,
                        mission_id=g.mission_id,
                        dedup_key=(
                            f"goal:{g.goal_id}:ckpt:"
                            f"{next_workable['checkpoint_order']}"
                        ),
                        metadata={
                            "goal_id": g.goal_id,
                            "checkpoint_order": next_workable["checkpoint_order"],
                        },
                    )
                )
    except Exception as e:
        logger.debug("from_workable_checkpoints failed: %s", e)
    return out


def _pick_next_workable(rows: list[Any]) -> dict[str, Any] | None:
    """First ``pending`` or recent ``active`` checkpoint in order, or
    None when only completed / stale-active checkpoints remain. Keeps
    the workable definition aligned with Phase 1 so the two paths
    never disagree on what's still in play."""
    for r in rows:
        status = r["status"]
        if status == "pending":
            return {
                "checkpoint_order": r["checkpoint_order"],
                "title": r["title"],
            }
        if status == "active":
            # The arbiter is OK proposing an active checkpoint;
            # Phase 1's stale guard is the safety net for the
            # "active forever" case.
            return {
                "checkpoint_order": r["checkpoint_order"],
                "title": r["title"],
            }
    return None


# ---------------------------------------------------------------------------
# Mission momentum
# ---------------------------------------------------------------------------


async def from_mission_momentum(ctx: CandidateContext) -> list[Candidate]:
    """One candidate per neglected high-weight mission.

    The mission tier already ranks by ``priority_weight × staleness``
    via ``MissionManager.list_by_neglect``. We turn each into a
    candidate with ``staleness_bonus`` proportional to how stale it
    is — that's the arbiter signal that lets neglected missions
    catch up to flashier new dreams. Caps at 5 candidates so a long
    list doesn't dominate the menu.
    """
    if not ctx.mission_manager:
        return []
    out: list[Candidate] = []
    try:
        ranked = await ctx.mission_manager.list_by_neglect(limit=5)
        for m in ranked:
            stale_h = m.staleness_hours()
            if stale_h == float("inf"):
                stale_label = "never touched"
                stale_bonus = 6.0
            else:
                stale_label = f"{stale_h:.0f}h since last touch"
                # 24h → ~1.0, 7d → ~7.0; capped at 10.
                stale_bonus = min(10.0, stale_h / 24.0)
            out.append(
                Candidate(
                    source="mission_momentum",
                    action_spec=(
                        f"Make a move toward mission '{m.title}' "
                        f"({m.mission_id}). {stale_label}. Description: "
                        f"{m.description[:160]}"
                    ),
                    expected_value=5.5,
                    feasibility=0.6,
                    lens_match=0.5,
                    cost=3.0,
                    staleness_bonus=stale_bonus,
                    mission_id=m.mission_id,
                    dedup_key=f"mission_move:{m.mission_id}",
                    metadata={"mission_id": m.mission_id},
                )
            )
    except Exception as e:
        logger.debug("from_mission_momentum failed: %s", e)
    return out


# ---------------------------------------------------------------------------
# Role neglect (ABE Phase 2)
# ---------------------------------------------------------------------------


async def from_role_neglect(ctx: CandidateContext) -> list[Candidate]:
    """One candidate per role, ranked by how long since last_active_at.

    Mirrors ``from_mission_momentum``: roles the agent hasn't operated
    from recently get a ``staleness_bonus`` so the arbiter is biased
    toward rotating into them. Never-active roles get the strongest
    bonus (rolling out a new role should not require operator nudging).

    The candidate's action_spec is advisory — the arbiter winning this
    candidate signals the wakeup loop to call
    ``set_current_role(name)`` for the cycle, then re-run the other
    generators (or simply work on whatever the role's allowlist
    permits). See ``AutonomousMind._cycle`` wiring.

    Caps at 5 candidates so a long role roster can't drown the menu.
    """
    if not ctx.role_manager:
        return []
    out: list[Candidate] = []
    try:
        from datetime import UTC, datetime, timedelta

        # KPI-gap is computed against ledger sums over the past 7
        # days. Pre-compute the cutoff once per cycle so all roles
        # are measured against the same window. Lazy-import the
        # ledger + company so this module stays usable in tests
        # that don't bootstrap the whole stack.
        seven_days_ago = (datetime.now(UTC) - timedelta(days=7)).isoformat()
        ledger = None
        active_company = "elophanto-self"
        try:
            from core.company import current_company_id
            from core.ledger import ResourceLedger

            # The role_manager has a `_db` attribute (private but
            # stable since Phase 2 — RoleManager is db-backed).
            db = getattr(ctx.role_manager, "_db", None)
            if db is not None:
                ledger = ResourceLedger(db)
                active_company = current_company_id()
        except Exception as e:
            logger.debug("from_role_neglect: ledger unavailable: %s", e)

        ranked = await ctx.role_manager.list_by_neglect(limit=5)
        for r in ranked:
            if r.last_active_at is None:
                stale_label = "never activated"
                stale_bonus = 6.0
            else:
                # Reuse the mission-momentum scaling so the two
                # neglect signals are commensurable: 24h → ~1.0,
                # 7d → ~7.0, capped at 10.
                try:
                    t = datetime.fromisoformat(r.last_active_at)
                    stale_h = max(
                        0.0,
                        (datetime.now(UTC) - t).total_seconds() / 3600.0,
                    )
                    stale_label = f"{stale_h:.0f}h since last active"
                    stale_bonus = min(10.0, stale_h / 24.0)
                except ValueError:
                    stale_label = "unknown staleness"
                    stale_bonus = 3.0

            # ABE Phase 4: KPI gap. For each declared KPI on the
            # role, compute (target - actual) / target where actual
            # is the ledger sum of that type over the past 7d,
            # attributed to the current company. Role's gap = mean
            # across KPIs. Falls through to 0.0 if no KPIs declared
            # or ledger lookup fails. The 0.0 default keeps role
            # candidates rankable on staleness alone when product
            # config is missing.
            kpi_gap = 0.0
            if ledger is not None and r.kpi:
                gaps: list[float] = []
                for kpi_type, target in r.kpi.items():
                    try:
                        target_f = float(target)
                        if target_f <= 0:
                            continue
                        actual = await ledger.sum(
                            active_company,
                            type=kpi_type,
                            direction="in",
                            since=seven_days_ago,
                        )
                        gap = max(0.0, target_f - actual) / target_f
                        gaps.append(min(1.0, gap))
                    except Exception as e:
                        logger.debug(
                            "from_role_neglect: kpi=%s gap calc failed: %s",
                            kpi_type,
                            e,
                        )
                if gaps:
                    kpi_gap = sum(gaps) / len(gaps)

            out.append(
                Candidate(
                    source="role_neglect",
                    action_spec=(
                        f"Switch into the {r.name.upper()} role for this "
                        f"cycle ({stale_label}; kpi_gap={kpi_gap:.2f}). "
                        f"{r.description[:160]}"
                    ),
                    expected_value=4.5,
                    feasibility=0.7,
                    lens_match=0.4,
                    cost=2.0,
                    staleness_bonus=stale_bonus,
                    kpi_gap=kpi_gap,
                    dedup_key=f"role_switch:{r.name}",
                    metadata={"role_name": r.name, "kpi_gap": kpi_gap},
                )
            )
    except Exception as e:
        logger.debug("from_role_neglect failed: %s", e)
    return out


# ---------------------------------------------------------------------------
# Unproductized companies (ABE Phase 7)
# ---------------------------------------------------------------------------


async def from_unproductized_companies(
    ctx: CandidateContext,
) -> list[Candidate]:
    """One candidate per company whose product.yaml is missing or
    empty.

    Closes the read-only/write-only asymmetry from Phase 4 — when
    the dream phase sees no PRODUCT block for a company, the arbiter
    sees a high-expected-value candidate "draft a product for
    <slug>: propose what_we_sell, then call company_set_product".
    The LLM, when this wins arbitration, calls the Phase 7 tool to
    write the YAML (subject to operator approval).

    Caps at the first 3 unproductized companies so a workspace with
    a dozen empty ABEs doesn't drown the menu — the arbiter picks
    one, the agent fixes one, next cycle the menu shrinks.
    """
    if not ctx.company_manager or not ctx.project_root:
        return []
    out: list[Candidate] = []
    try:
        from core.product import load_product

        companies = await ctx.company_manager.list()
        for c in companies:
            if c.status != "active":
                continue
            if load_product(ctx.project_root, c.id) is not None:
                continue  # already has a product
            out.append(
                Candidate(
                    source="unproductized_company",
                    action_spec=(
                        f"Company '{c.id}' has no product config — draft "
                        f"a 1-3 sentence what_we_sell naming a real "
                        f"external consumer and concrete deliverable, "
                        f"then call company_set_product(slug='{c.id}', "
                        f"what_we_sell=...). Without a product the dream "
                        f"phase has no business to anchor against."
                    ),
                    expected_value=7.0,
                    feasibility=0.8,
                    lens_match=0.5,
                    cost=2.0,
                    staleness_bonus=4.0,
                    dedup_key=f"draft_product:{c.id}",
                    metadata={"company_id": c.id},
                )
            )
            if len(out) >= 3:
                break
    except Exception as e:
        logger.debug("from_unproductized_companies failed: %s", e)
    return out


async def from_voiceless_companies(
    ctx: CandidateContext,
) -> list[Candidate]:
    """One candidate per company that has exemplars but no voice.yaml.

    Phase 10 closes the half-built case: operator dropped reference
    posts/emails at data/companies/<slug>/exemplars/<channel>/*.md
    but never asked the agent to extract a voice — so the draft tools
    aren't lint-gated and the autonomous mind is one cycle away from
    producing AI-slop. This generator surfaces a high-leverage
    "run voice_extract for <slug>" candidate so the arbiter picks it
    before the mind drifts into outreach.

    Skips when:
      - no VoiceManager (test fixtures, missing project_root)
      - company already has voice.yaml (the contract is the gate)
      - fewer than 2 exemplar files (voice_extract needs ≥2)

    Caps at the first 3 voiceless companies — same shape as
    `from_unproductized_companies` to avoid menu drowning.
    """
    if not ctx.company_manager or not ctx.voice_manager or not ctx.project_root:
        return []
    out: list[Candidate] = []
    try:
        companies = await ctx.company_manager.list()
        for c in companies:
            if c.status != "active":
                continue
            voice_path = ctx.voice_manager.voice_path(c.id)
            if voice_path is None or voice_path.is_file():
                continue  # already has a voice contract
            exemplars_root = voice_path.parent / "exemplars"
            if not exemplars_root.is_dir():
                continue  # operator hasn't dropped exemplars yet
            exemplar_count = sum(
                1
                for ch_dir in exemplars_root.iterdir()
                if ch_dir.is_dir()
                for _ in ch_dir.glob("*.md")
            )
            if exemplar_count < 2:
                continue
            out.append(
                Candidate(
                    source="voiceless_company",
                    action_spec=(
                        f"Company '{c.id}' has {exemplar_count} "
                        f"operator-curated exemplars but no voice "
                        f"contract — call voice_extract(company_id="
                        f"'{c.id}') to propose a voice.yaml from "
                        f"the exemplars. Without it the draft tools "
                        f"have no lint gate and any outreach the "
                        f"mind generates is one cycle from AI-slop."
                    ),
                    expected_value=8.0,
                    feasibility=0.9,
                    lens_match=0.5,
                    cost=1.5,
                    staleness_bonus=5.0,
                    dedup_key=f"voice_extract:{c.id}",
                    metadata={
                        "company_id": c.id,
                        "exemplar_count": exemplar_count,
                    },
                )
            )
            if len(out) >= 3:
                break
    except Exception as e:
        logger.debug("from_voiceless_companies failed: %s", e)
    return out


async def from_unplanned_companies(
    ctx: CandidateContext,
) -> list[Candidate]:
    """One candidate per productized company without an active strategy.

    Phase 11: a company with a `company.yaml` but no
    `data/companies/<slug>/strategy/active/strategy.yaml` is in the
    "I know what we sell but not how to drive it" state. Surface a
    high-leverage candidate so the arbiter picks it before the mind
    drifts into dream-phase ideation. Caps at 3 to avoid menu drowning.
    """
    if not ctx.company_manager or not ctx.strategy_manager or not ctx.project_root:
        return []
    out: list[Candidate] = []
    try:
        from core.product import load_product

        companies = await ctx.company_manager.list()
        for c in companies:
            if c.status != "active":
                continue
            if load_product(ctx.project_root, c.id) is None:
                continue  # un-productized — different candidate generator handles this
            if ctx.strategy_manager.has_active(c.id):
                continue  # already planned
            out.append(
                Candidate(
                    source="unplanned_company",
                    action_spec=(
                        f"Company '{c.id}' is productized but has no "
                        f"active strategy. Sequence: "
                        f"1) `company_capabilities(company_id='{c.id}')` "
                        f"to audit what's available; "
                        f"2) ensure strategy_inputs are captured via "
                        f"`company_set_strategy_inputs`; "
                        f"3) call `company_plan(company_id='{c.id}')` "
                        f"to generate a proposal; "
                        f"4) operator runs `company_plan_apply` to "
                        f"materialize mission + goals + voice seed."
                    ),
                    expected_value=8.0,
                    feasibility=0.85,
                    lens_match=0.5,
                    cost=2.0,
                    staleness_bonus=4.0,
                    dedup_key=f"strategy_plan:{c.id}",
                    metadata={"company_id": c.id},
                )
            )
            if len(out) >= 3:
                break
    except Exception as e:
        logger.debug("from_unplanned_companies failed: %s", e)
    return out


async def from_blocked_strategy_days(
    ctx: CandidateContext,
) -> list[Candidate]:
    """One candidate per company with an active strategy + unresolved
    blockers older than 3 days. Phase 11: keeps blocked strategies
    from sitting in `learning` state indefinitely — surfaces the
    operator-resolvable items + the build-able ones."""
    if not ctx.company_manager or not ctx.strategy_manager or not ctx.project_root:
        return []
    from core.strategy import load_blockers

    out: list[Candidate] = []
    try:
        now = datetime.now(UTC)
        companies = await ctx.company_manager.list()
        for c in companies:
            if c.status != "active":
                continue
            if not ctx.strategy_manager.has_active(c.id):
                continue
            blockers = load_blockers(ctx.project_root, c.id)
            unresolved = [b for b in blockers if not b.is_resolved()]
            if not unresolved:
                continue
            # Check active strategy age (proxy: archive dir if non-empty
            # else file mtime). Cheap: just read mtime of active file.
            active_path = ctx.strategy_manager.active_path(c.id)
            if active_path is None:
                continue
            try:
                mtime = datetime.fromtimestamp(active_path.stat().st_mtime, tz=UTC)
                age_days = (now - mtime).total_seconds() / 86400.0
            except OSError:
                age_days = 0.0
            if age_days < 3.0:
                continue
            out.append(
                Candidate(
                    source="blocked_strategy",
                    action_spec=(
                        f"Company '{c.id}' has {len(unresolved)} unresolved "
                        f"blocker(s) on its active strategy "
                        f"({age_days:.0f}d old). Review with `elophanto "
                        f"company blockers {c.id}`; resolve operator-"
                        f"actionable items (`resolution=ask`), or invoke "
                        f"the build path for `resolution=build` items."
                    ),
                    expected_value=7.0,
                    feasibility=0.7,
                    lens_match=0.5,
                    cost=1.5,
                    staleness_bonus=6.0,
                    dedup_key=f"blockers_review:{c.id}",
                    metadata={
                        "company_id": c.id,
                        "unresolved": len(unresolved),
                        "age_days": age_days,
                    },
                )
            )
            if len(out) >= 3:
                break
    except Exception as e:
        logger.debug("from_blocked_strategy_days failed: %s", e)
    return out


async def from_buildable_blockers(
    ctx: CandidateContext,
) -> list[Candidate]:
    """One candidate per buildable blocker — items with
    `resolution_proposal='build'` and `build_method` set. The mind
    can invoke `self_create_plugin` or `skill_promote` to fill the
    gap. CRITICAL permission gates the actual build, so operator
    still approves per invocation."""
    if not ctx.company_manager or not ctx.strategy_manager or not ctx.project_root:
        return []
    from core.strategy import load_blockers

    out: list[Candidate] = []
    try:
        companies = await ctx.company_manager.list()
        for c in companies:
            if c.status != "active":
                continue
            if not ctx.strategy_manager.has_active(c.id):
                continue
            blockers = load_blockers(ctx.project_root, c.id)
            for b in blockers:
                if b.is_resolved():
                    continue
                if b.resolution_proposal != "build" or not b.build_method:
                    continue
                action: str
                if b.build_method == "self_create_plugin":
                    hint = b.build_hint or b.description
                    action = (
                        f"Build the missing capability for blocker "
                        f"`{b.id}` ({b.description}). Call "
                        f"`self_create_plugin(goal={hint!r})`. "
                        f"Operator will approve via CRITICAL permission. "
                        f"On success the new tool registers and unblocks "
                        f"tactics: {', '.join(b.affected_tactics) or '(none)'}."
                    )
                elif b.build_method == "skill_promote":
                    action = (
                        f"Build the missing skill for blocker "
                        f"`{b.id}` ({b.description}). Identify 2-30 "
                        f"lesson files relevant to "
                        f"`{b.build_hint or 'the capability'}` and call "
                        f"`skill_promote`. Operator approves via "
                        f"MODERATE permission."
                    )
                else:
                    continue
                out.append(
                    Candidate(
                        source="buildable_blocker",
                        action_spec=action,
                        expected_value=9.0,
                        feasibility=0.6,
                        lens_match=0.5,
                        cost=4.0,
                        staleness_bonus=5.0,
                        dedup_key=f"build_blocker:{c.id}:{b.id}",
                        metadata={
                            "company_id": c.id,
                            "blocker_id": b.id,
                            "build_method": b.build_method,
                        },
                    )
                )
                if len(out) >= 3:
                    break
            if len(out) >= 3:
                break
    except Exception as e:
        logger.debug("from_buildable_blockers failed: %s", e)
    return out


# ---------------------------------------------------------------------------
# Dream
# ---------------------------------------------------------------------------


async def from_dream(ctx: CandidateContext) -> list[Candidate]:
    """One placeholder candidate that points the LLM at the dream
    pipeline.

    We intentionally do NOT call ``goal_dream`` here — it's the most
    expensive operation in the wakeup, and running it every cycle to
    produce candidates the LLM may not pick wastes budget. Instead
    the arbiter ranks "go think about new goals" as one option among
    many; if it wins, the LLM calls ``goal_dream`` and the
    existing pipeline runs.

    The candidate's ``expected_value`` decays with the number of
    workable_checkpoints already in play — when there's lots to do
    on existing goals, dreaming up new ones is worth less.
    """
    workable_count = 0
    if ctx.goal_manager:
        try:
            active = await ctx.goal_manager.list_goals(status="active", limit=20)
            planning = await ctx.goal_manager.list_goals(status="planning", limit=20)
            workable_count = len(active) + len(planning)
        except Exception as e:
            logger.debug("from_dream goal count failed: %s", e)

    expected = 7.0 - min(5.0, 1.0 * workable_count)
    feasibility = 0.85
    return [
        Candidate(
            source="dream",
            action_spec=(
                f"Dream up a new goal via goal_dream(focus='{ctx.dream_focus}'). "
                f"Today's value lens is {ctx.dream_focus}; pursue a candidate "
                f"that touches a neglected mission or an underused capability."
            ),
            expected_value=expected,
            feasibility=feasibility,
            lens_match=1.0,
            cost=3.5,
            dedup_key=f"dream:{ctx.dream_focus}",
            metadata={"dream_focus": ctx.dream_focus},
        )
    ]


# ---------------------------------------------------------------------------
# Reflexes
# ---------------------------------------------------------------------------


async def from_reflexes(ctx: CandidateContext) -> list[Candidate]:
    """Standing periodic self-checks.

    Two reflexes today:

    1. **Capability review** — every ~7d, audit which tools were
       used heavily / lightly / not at all in the recent past and
       propose pruning or learning. Reads no DB by default; the
       reflex's *execution* (when picked) does that work.
    2. **Mission rebalance** — every ~7d, propose reviewing mission
       weights and statuses. Triggered by the staleness of the
       least-recently-touched active mission.

    These are intentionally simple. Phase 4 adds the attractor
    detector + affect-coupled reflexes on top of this scaffold.
    """
    out: list[Candidate] = []
    try:
        cap_due = await _capability_review_due(ctx)
        if cap_due is not None:
            days_overdue, last_seen = cap_due
            stale_bonus = min(10.0, days_overdue * 1.4)
            out.append(
                Candidate(
                    source="reflex_capability_review",
                    action_spec=(
                        "Review your tool/capability usage. Which tools "
                        "did you lean on this week? Which are unused or "
                        "broken? Pick ONE underused capability and either "
                        "exercise it or note why it should be retired. "
                        f"Last review: {last_seen}."
                    ),
                    expected_value=5.0,
                    feasibility=0.85,
                    lens_match=0.4,
                    cost=2.0,
                    staleness_bonus=stale_bonus,
                    dedup_key="reflex:capability_review",
                    metadata={"days_overdue": days_overdue},
                )
            )
    except Exception as e:
        logger.debug("capability reflex failed: %s", e)

    try:
        miss_due = await _mission_rebalance_due(ctx)
        if miss_due is not None:
            out.append(
                Candidate(
                    source="reflex_mission_rebalance",
                    action_spec=(
                        "Review your missions. Read mission_list and "
                        "decide: should any pause, retire, or change "
                        "priority_weight? Are there missions missing that "
                        "you keep doing work outside of?"
                    ),
                    expected_value=5.5,
                    feasibility=0.85,
                    lens_match=0.4,
                    cost=2.0,
                    staleness_bonus=miss_due,
                    dedup_key="reflex:mission_rebalance",
                    metadata={"reason": "stale_missions"},
                )
            )
    except Exception as e:
        logger.debug("mission rebalance reflex failed: %s", e)

    return out


async def _capability_review_due(ctx: CandidateContext) -> tuple[float, str] | None:
    """Look up the last capability-review memory; if older than
    ``_CAPABILITY_REVIEW_DAYS``, return (days_overdue, last_seen_iso).
    Returns None when memory is unavailable so the reflex stays
    silent rather than firing without grounding.

    Currently uses a simple proxy: the agent's recent task memory.
    Phase 4 can replace this with a dedicated `reflexes` table.
    """
    # No proper memory dimension yet; return a soft "always slightly
    # overdue" signal so the reflex appears at a modest score until
    # the operator wires it to a real source. This is deliberate —
    # we want the reflex visible in early dry-runs.
    return (1.0, "never recorded")


async def _mission_rebalance_due(ctx: CandidateContext) -> float | None:
    """If the oldest active mission's staleness exceeds the rebalance
    period, return a staleness_bonus proportional to how overdue.
    Returns None when there are no missions or none are old enough."""
    if not ctx.mission_manager:
        return None
    missions = await ctx.mission_manager.list_missions()
    if not missions:
        return None
    now = datetime.now(UTC)
    max_stale_days = 0.0
    for m in missions:
        stale_h = m.staleness_hours(now)
        if stale_h == float("inf"):
            return 6.0
        max_stale_days = max(max_stale_days, stale_h / 24.0)
    if max_stale_days < _MISSION_REBALANCE_DAYS:
        return None
    return min(10.0, (max_stale_days - _MISSION_REBALANCE_DAYS) * 1.5 + 3.0)


# ---------------------------------------------------------------------------
# External signals (stub — Phase 3.5)
# ---------------------------------------------------------------------------


async def from_external_signals(ctx: CandidateContext) -> list[Candidate]:
    """Placeholder for Phase 3.5 — mentions, market deltas, schedule
    failures, news headlines. Returns [] today so the arbiter shape
    is fixed for callers; bolt on after the internal loop is healthy.
    """
    return []


# ---------------------------------------------------------------------------
# Convenience: run every generator
# ---------------------------------------------------------------------------


async def collect_all(ctx: CandidateContext) -> list[Candidate]:
    """Run every generator, concat results. Per-generator failures
    are logged and dropped so one broken source doesn't black-hole
    the wakeup."""
    out: list[Candidate] = []
    for gen in (
        from_workable_checkpoints,
        from_mission_momentum,
        from_role_neglect,
        from_unproductized_companies,
        from_voiceless_companies,
        from_unplanned_companies,
        from_blocked_strategy_days,
        from_buildable_blockers,
        from_dream,
        from_reflexes,
        from_external_signals,
    ):
        try:
            out.extend(await gen(ctx))
        except Exception as e:
            logger.warning("candidate generator %s failed: %s", gen.__name__, e)
    return out
