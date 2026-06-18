# 75 — Autonomous Mind v2: Drives, Arbiter, Self-Supervision

**Status**: Proposal · **Owner**: 0xroyce + Claude · **Started**: 2026-05-20

## Why this exists

The current autonomous mind is a **task-list executor with rich decoration**.
The components are right (ego, affect, identity, knowledge, dream lenses,
scratchpad). The executive loop that wires them into action is impoverished:

```
if active_goals: work_on_them
elif planning_goals: continue planning
else: dream → create goal
```

That router has three branches. Ego/affect/identity show up only as prompt
strings — they don't change which branch fires or which candidate gets picked.
The mind's choice of action is effectively: *"is there an active goal? then
that one."* Stuck goal → infinite anchor.

**Observed symptom (2026-05-18 → 2026-05-20)**: one goal (`d413dc4e — Operator
Acceptance Handshake`) ended ckpt 9/9 with last checkpoint still `active`
because the agent built the artifact but never called `goal_status` to close
it. For ~36 hours the mind logged variants of *"bounded source-of-truth
reconciliation for the still-surfaced active goal, without duplicating
already-verified artifacts"* every ~30 min. Not a bug in one place — a
**structural attention failure**.

A real autonomous agent has **parallel motivational streams competing for
attention**, with an executive that arbitrates by score. That's BDI, it's
motivated RL, it's how Generative Agents' reflection loop works, it's what
Voyager does with its curriculum. The shape is **N candidate sources →
arbiter → one action**, not `if/elif/else`.

## The target model

```
┌─────────────────────────────────────────────────────────────┐
│ MISSIONS — durable drives (never "complete")                │
│   alphascala-launch · elophanto-growth · elo-recovery ·     │
│   capability-development · social-presence                  │
│   (last_touched_at, momentum, weight)                       │
└─────────────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│ GOALS — bounded projects (auto-close when done)             │
│   built under a mission, or one-off                         │
└─────────────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│ ACTIONS — tasks · checkpoints · posts · reflexes            │
└─────────────────────────────────────────────────────────────┘

                  ┌──────────────────┐
                  │   THE ARBITER    │  (replaces the if/elif)
                  └──────────────────┘
                         │
   ┌─────────────────────┼─────────────────────┐
   │                     │                     │
candidate            candidate              candidate
sources              sources                sources
   │                     │                     │
   ▼                     ▼                     ▼
- workable checkpoints   - mission momentum bumps   - reflexes due
- dream candidates       - external signals         - operator nudges
                                │
                                ▼
                  score = f(value, feasibility, lens_fit,
                            mission_weight, staleness,
                            affect_bias, cost)
                                │
                                ▼
                            pick top → act
```

### Why this shape

- **Missions never "complete"** — that's what makes them drives. They're the
  answer to "what do I care about." Goals roll under them; finishing a goal
  moves a mission's momentum, doesn't close the mission.
- **Arbiter generates candidates from all sources every wakeup.** One stuck
  goal can't black-hole attention; other sources still produce candidates
  and a stale-goal penalty drops its score below them.
- **Affect/ego/identity become scorer inputs**, not just decoration.
  Frustration → diversification bias. Pride after a win → continue-the-streak.
  Identity capabilities → boost underused ones.
- **Self-supervision = attractor detector** on the action log. Rolling hash
  of recent actions; if entropy collapses, inject a forced-diversification
  candidate at high score. The system notices it's stuck and recoils.

### What's right in the current design — don't throw out

- `goal_dream` with value-lens rotation is already the candidate-generator
  template. Generalize it; don't replace it.
- Affect, ego, identity, knowledge, recent-task memory — data flow exists.
  The arbiter needs to *use* it for scoring rather than letting the LLM
  ad-hoc weight everything inside a single prompt.
- `set_next_wakeup` gives cadence control. Keep.
- Scratchpad is solid working memory. Keep.
- Phase B priority system (already built) gives the executive runway to
  run parallel-yet-arbitrated.

## Phased plan

### Phase 1 — Stop the bleeding (today, ~2h)

Tactical, no architectural commitment. Restores health; buys time to design
the rest right.

- [x] **1.1** Close the wedged goal `d413dc4e` (mark ckpt 9 `completed`, goal
      `completed`) so the running mind enters dream phase next wakeup
- [x] **1.2** Stale-checkpoint guard in `_build_prompt`: any goal whose last
      `active` checkpoint started >12h ago gets surfaced under a
      `[STUCK-CHECKPOINTS]` section of state_snapshot naming the goal_id
      and the stale_since timestamp, with an instruction to close it via
      `goal_status` before doing anything else
- [x] **1.3** Reframe `_count_workable_goals` via new
      `_workable_goals_status() → (count, stale_list)` that counts a goal
      as workable only if it has a pending checkpoint OR an `active`
      checkpoint within the last 12h. Stuck goals no longer block dream
      phase; old shim kept for back-compat. New tests added
- [x] **1.4** Fix `llm_usage` persistence: `CostTracker.flush(db)` and
      `ProviderTracker.flush(db)` existed but had no caller. Added
      `Agent._periodic_usage_flush()` background task (60s cadence) +
      shutdown-time final drain. Regression test added pinning the
      flush → llm_usage contract
- [x] **1.5** Smoke-test against live DB: with 1.1 applied + the new
      `_workable_goals_status` logic, returns `(workable=0, stale=[])` →
      DREAM PHASE would fire next wakeup. No other stuck checkpoints
      lurking in the production state. Full restart deferred to operator
      window — running agent's old in-memory code already benefits from
      1.1 alone (goal status now `completed`)

**Exit criteria**: no more 36-hour reconciliation loops possible. Cost
visibility back. Running agent productive again.

### Phase 2 — Missions become first-class (2–3 days)

Smallest schema that supports drives. No arbiter yet.

- [x] **2.1** New `missions` table with indices on `status+priority_weight`
      and `last_touched_at`. Lives in `_SCHEMA` so fresh installs get it
      automatically; existing DBs pick it up on next `Database.initialize()`
- [x] **2.2** Migration adds `goals.mission_id` (nullable, no FK enforcement
      — informational column; cascade not relied on)
- [x] **2.3** `core/mission_manager.py` — CRUD (`create`, `get`,
      `list_missions`, `set_status`, `update`), `touch(bump)` for momentum,
      `list_by_neglect(limit)` for the dream phase. `Mission` carries
      read-side `decayed_momentum()` (7-day half-life) and
      `staleness_hours()`. 19 focused tests
- [x] **2.3-PATCH** (ABE Phase 12, Tier 1 #1, commit `72e2a13`,
      2026-06-18) — every `mission_manager` read defaults to
      `current_company_id()` via contextvar; `create` stamps the
      active company at INSERT; `Mission.company_id` field; `get`
      and `list_missions` accept `ALL_COMPANIES` sentinel for admin
      cross-company queries. Same pattern applied to
      `goal_manager`. Was previously global (single-tenant
      assumption); now correct under multi-company operation
- [x] **2.4** Tools: `mission_list`, `mission_create`, `mission_status`
      (read+set in one), `mission_touch`, `mission_update`. All in
      `tools/missions/tools.py` sharing a `_MissionToolBase`. Registry
      wires them; `Agent._inject_mission_deps` injects the manager
- [x] **2.5** `Identity.missions` field added (list of dicts:
      `{id, title, description, priority_weight}`). When non-empty on
      first run, `_seed_default_missions` materializes them. Seed call
      runs AFTER identity init so this works. Setup wizard also
      prompts (opt-in) to define 0–8 missions during `elophanto init`,
      saving them under `identity.missions`
- [x] **2.6** Built-in default mission seeds: **none**. EloPhanto is a
      generic agent; the codebase ships ZERO operator-specific
      missions. Operators define their own via the wizard,
      `identity.missions` config, or `elophanto mission create`. The
      mind handles "no missions yet" cleanly via the Phase 1
      FORCE-DREAM gate. (Earlier draft of §2.6 incorrectly hardcoded
      five operator-specific drives — removed 2026-05-20.)
- [x] **2.7** Dream phase reads `list_by_neglect(limit=5)` and renders a
      MISSIONS block ranked by `weight × staleness`, telling the LLM to
      prefer candidates that touch high-weight stale missions and to set
      the candidate's `mission_id` to the slug. `Goal.mission_id` threaded
      through `create_goal` → `_persist_goal` → `_row_to_goal`;
      `goal_create` tool accepts optional `mission_id` param
- [x] **2.8** Goal-completion → mission-touch hook registered via
      `goal_manager.add_completion_hook`. Bumps the parent mission's
      momentum by 1.0 when a goal with `mission_id` completes. Hook
      failures are swallowed per the goal_manager contract
- [x] **2.9** `elophanto mission` CLI: `list` (ranked by neglect by
      default; `--all` includes paused/retired), `show <id>`, `touch <id>
      [bump]`, `pause`, `resume`, `retire`. Wired into `cli/main.py`

**Exit criteria**: alphascala-GTM, elophanto-growth, $ELO-recovery,
capability-development are *named persistent drivers*. Dream phase produces
goals biased toward neglected missions instead of inventing from scratch.

### Phase 3 — The arbiter (3–5 days)

Replace the if/elif decision tree with a scored candidate model.

- [x] **3.1** [core/mind_arbiter.py](core/mind_arbiter.py) with:
  - [x] `Candidate` frozen dataclass (source, action_spec,
        expected_value, feasibility, lens_match, cost, staleness_bonus,
        affect_bias, mission_id?, dedup_key?, metadata)
  - [x] `score_candidate(c, weights, mission_weights)` — linear
        inspectable combiner
  - [x] `arbitrate(candidates, weights, *, mission_weights, top_k)`
        — score, dedup, sort, truncate. Highest-scoring wins per
        dedup_key
  - [x] `render_menu(scored, max_chars)` — compact LLM-facing menu
        with always-include-first-candidate guarantee
  - [x] `ArbiterWeights.from_config_dict` honoring unknown keys
- [x] **3.2** Candidate sources in
      [core/mind_candidates.py](core/mind_candidates.py):
  - [x] `from_workable_checkpoints` — propose decompose for empty-plan
        planning goals; advance for goals with workable next checkpoint
  - [x] `from_mission_momentum` — one per neglected mission via
        `MissionManager.list_by_neglect`; `staleness_bonus` scales with
        hours since last touch (never-touched = 6.0)
  - [x] `from_dream` — single placeholder steering the LLM at
        `goal_dream`; `expected_value` decays with workable_count so
        full plates don't get more dreams
  - [x] `from_reflexes` — capability-review + mission-rebalance
        candidates; rebalance triggered by max-mission-staleness
  - [x] `from_external_signals` — stub returning [] (Phase 3.5)
  - [x] `collect_all(ctx)` runs each generator, swallows per-generator
        failures
- [x] **3.3** Wakeup flow gated by `config.autonomous_mind.arbiter.enabled`.
      When on: build `CandidateContext`, `collect_all`, `arbitrate`,
      render menu, format `_ARBITER_PROMPT`. Side-channel
      `[arbiter]` log lines record menu + scores for audit. Falls back
      to legacy `_build_prompt` if generators return zero candidates
- [x] **3.4** `_ARBITER_PROMPT` template replaces the wall-of-context
      with a scored menu (3000-char cap on state_snapshot + scratchpad;
      menu is the primary payload). Rules collapsed to 7 from 11
- [x] **3.5** `MindArbiterConfig` (enabled, top_k, weights dict) under
      `autonomous_mind.arbiter`. Defaults disabled so rollout is
      reversible. Per-key override in YAML, unknown weights silently
      ignored
- [x] **3.6** 31 arbiter/candidate tests covering: stable dedup hash,
      scoring monotonicity per signal, dedup-keeps-highest, top_k
      truncation, mission_weight bonus, partial-config defaults,
      render-menu truncation behaviour, every generator degrades
      gracefully without managers, end-to-end stuck-state never
      produces empty menu

**Exit criteria**: actual multi-stream autonomous behavior. A stuck goal
can't monopolize because other sources still produce candidates. The
prompt is smaller, the decision is grounded in scored state, and the LLM's
job is *picking + reasoning*, not generating from a wall of context.

### Phase 3.5 — External signals (deferred but designed)

Bolted onto the arbiter once the loop is healthy. **Not blocking Phase 4.**

- [ ] **3.5.1** Mention scanner (X, Discord) → candidates when EloPhanto or
      $ELO is being discussed
- [ ] **3.5.2** Market deltas (Polymarket, $ELO price) → candidates when
      meaningful move
- [ ] **3.5.3** Schedule-run failures → candidates to investigate
- [ ] **3.5.4** News headlines matching identity interests → candidates

### Phase 4 — Self-supervision + reflexes (1–2 days, on top of Phase 3)

The pieces that make it feel alive.

- [ ] **4.1** **Attractor detector**: rolling hash of last N action
      descriptions in `_recent_actions`. If entropy < threshold, inject
      high-score "force-diversification" candidate. Targets the exact
      failure mode observed in the 36h reconciliation loop
- [ ] **4.2** **Capability-review reflex**: every 7d, candidate appears:
      *"audit recent uses of tool category X; what's broken, what's
      underused?"*
- [ ] **4.3** **Mission rebalance reflex**: every 7d, candidate appears:
      *"review missions; should any pause, any be added?"*
- [ ] **4.4** **Affect → arbiter coupling**: frustration spike biases
      cost-down candidates; restlessness biases creation lens; pride biases
      continue-the-streak. Already in the prompt; now in the scorer
- [ ] **4.5** **Ego correction → mission staleness reset**: a fresh
      correction event on a mission's recent work bumps that mission's
      `last_touched_at` artificially so the mind doesn't pile new work on
      a broken foundation
- [ ] **4.6** Dashboard / `mind status` shows the candidate menu the
      arbiter saw on the last wakeup + the pick + the score — full
      observability into "why did the agent do X"

**Exit criteria**: the agent maintains itself. Operator does not need to
notice 36-hour rumination loops; they don't happen.

## Cross-cutting concerns

- [ ] **C1** Migration scripts for `missions` table + `goals.mission_id`
- [ ] **C2** Backfill: existing completed goals stay unparented (null
      `mission_id`); operator can re-parent via tool
- [ ] **C3** Docs update — `02-ARCHITECTURE.md`, `13-GOAL-LOOP.md`,
      `17-IDENTITY.md` reference v2
- [ ] **C4** Memory: feedback note that "active goal first" is wrong as
      stated; the rule is "workable checkpoint first, otherwise arbiter"
- [ ] **C5** Keep Phase B priority system intact — the arbiter runs at
      MIND priority; nothing about scheduler/preemption changes

## Anti-goals (explicitly **not** doing)

- ❌ Full rewrite. The bones are good. v2 is surgical promotion of an
      implicit structure to first-class.
- ❌ Replace LLM choice with hard rules. The arbiter scores; the LLM still
      picks from top-K with reasoning. We constrain *the menu*, not the
      mind.
- ❌ Add a workflow engine / state machine on top. Arbiter every wakeup is
      the loop. Period.
- ❌ External-signal ingestion before the internal loop is healthy. That's
      Phase 3.5 for a reason.

## The single sentence

**Promote missions to first-class durable drives, replace the mind's
if/elif with a scored arbiter that pulls candidates from missions + goals
+ reflexes + dreams + signals, and add an attractor detector so the
system can notice when it's stuck.** Everything else falls out of that.

## Working notes — append as we build

- 2026-05-20: doc created. Phase 1 starts next.
- 2026-05-20: **Phase 1 complete**. Wedged goal `d413dc4e` closed;
  `_workable_goals_status` replaces the brittle active-count gate (back-compat
  shim kept); `[STUCK-CHECKPOINTS]` section surfaces stale goals in the mind
  prompt; periodic `llm_usage` flush wired with shutdown drain; regression
  tests cover all four paths. Live-DB smoke test shows the running agent will
  enter DREAM PHASE on next wakeup once the new code is loaded.
- 2026-05-20: **Phase 3 complete**. Arbiter (`core/mind_arbiter.py`)
  with `Candidate` / `ArbiterWeights` / `arbitrate` / `render_menu`; five
  candidate sources (`core/mind_candidates.py`); opt-in wakeup gate via
  `autonomous_mind.arbiter.enabled`. Side-channel `[arbiter]` log lines
  surface menu + scores for audit. 31 new tests; 239 focused tests green.
  Live-DB smoke-test ranks `dream` and `alphascala-launch` mission moves
  at the top — exactly what the operator described as the desired
  behavior. Default remains disabled until you flip the flag.
- 2026-05-20: **Phase 2 complete**. Missions table + `goals.mission_id`
  migration; `MissionManager` with 7-day-half-life momentum decay and
  neglect-ranked listing; 5 tools (`mission_list/create/status/touch/update`);
  `Identity.missions` field with optional wizard prompt at `elophanto init`;
  **no built-in mission seeds** — operators define their own (initial draft
  hardcoded five operator-specific drives, removed); dream phase renders
  missions block and steers candidates via `mission_id`; goal-completion hook
  bumps mission momentum; `elophanto mission` CLI. 19 mission_manager tests
  added (208 focused tests green). Live CLI smoke-tested.
