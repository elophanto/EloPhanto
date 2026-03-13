# EloPhanto — AutoLoop: Focus Lock, AGENT_PROGRAM.md, and Fixed Iteration Budgets

## Origin

After a deep review of Andrej Karpathy's [autoresearch](https://github.com/karpathy/autoresearch) (March 2026), three gaps in EloPhanto's autonomous loop design became clear. EloPhanto already has more sophisticated loop mechanics than autoresearch — three parallel background engines, budget controls, pause/resume on user interaction. But autoresearch is more *effective* at one specific thing: keeping the agent committed to a single objective and running it indefinitely without drifting.

The three additions in this doc address that gap directly.

---

## The Three Gaps

### Gap 1 — The Drift Problem

EloPhanto's autonomous mind evaluates its priority stack on every wakeup cycle: goals, tasks, Commune heartbeat, knowledge drift, directives. This is powerful for general-purpose autonomy but fatal for research loops. An agent running a benchmark optimization experiment will, after a few iterations, decide that checking Commune or refreshing the knowledge index is higher priority. The experiment dies mid-session.

**autoresearch's solution:** The agent is committed to one loop. The instructions literally say *"Do NOT pause... the loop runs until the human interrupts you, period."*

### Gap 2 — No Versioned Strategy Document

HEARTBEAT.md is a task queue: a list of things to do. It is not a strategy. autoresearch's `program.md` is fundamentally different — it encodes *how* the agent approaches a research session: what to try first, what constraints to respect, what "better" means, what to do when stuck. Karpathy explicitly calls it *"the research org code"* — a file the human iterates on over time to make the agent's autonomous strategy better. Over time the human shifts from prompting the agent to writing better `program.md`.

EloPhanto has no equivalent.

### Gap 3 — No Fixed Iteration Budget

autoresearch's 5-minute time budget per experiment is not just a timeout — it's a **fairness constraint**. Because every experiment runs for exactly the same wall-clock time, you can directly compare any two experiments regardless of what was changed (model depth, batch size, architecture). The agent can't accidentally compare a 30-second run against a 10-minute run.

EloPhanto's `experiment_setup` has a `timeout` parameter but no fixed budget guarantee. Experiments vary in duration, making their results incomparable.

---

## What We're Building

### 1. `AGENT_PROGRAM.md` — The Research Constitution

A new file at the project root, versioned in git, that the **owner** writes and iterates on to program the agent's autonomous research strategy.

**Different from HEARTBEAT.md:**

| | HEARTBEAT.md | AGENT_PROGRAM.md |
|---|---|---|
| **What it is** | Task queue | Research strategy |
| **Who edits it** | Owner (tasks) or agent (mark done) | Owner only |
| **Cadence** | Cleared when done, refilled as needed | Accumulated over time — gets richer |
| **Content** | "Check emails, post on Commune" | "When stuck after 5 discards, try combining near-misses. Prefer deletions over additions. Never change two things at once." |
| **Versioned** | Not meaningful to version | Intentionally versioned — git log shows strategy evolution |
| **Read by** | Heartbeat engine | Autonomous mind, at the start of every AutoLoop session |
| **Purpose** | What to do | How to think |

**Structure of `AGENT_PROGRAM.md`:**

```markdown
# Agent Program
# This file is your research constitution. Read it at the start of every
# AutoLoop session. Edit it to improve your autonomous strategy over time.

## Research Philosophy
- One change per experiment. Never change two things at once.
- Prefer deletions over additions — a simplification that holds the metric is always a win.
- When stuck (5+ discards): re-read the target files for fresh angles, review the
  journal for near-misses, try a more radical change, try the opposite of what failed.

## Metric Interpretation
- "Better" means strictly improved, not equal.
- A 1% improvement with 20 lines of complexity added is NOT worth it.
- A 0% change with 20 lines deleted IS worth it.

## Domain Rules
(Owner adds project-specific constraints here over time)
- Example: "Never change the public API surface"
- Example: "Tests must stay green — use self_run_tests after every change"
- Example: "Max memory budget: 512MB"

## What Has Worked (owner annotates over time)
- Caching provider configs: -5ms latency
- ...

## What Has Not Worked
- Async DNS: always causes race conditions in this codebase
- ...
```

The agent reads this file at the start of every AutoLoop session. The owner improves it after each session — adding domain rules, annotating what worked, refining the philosophy. Over many sessions, `AGENT_PROGRAM.md` becomes a high-quality research strategy document specific to the project.

**How it's different from a skill:** Skills are generic, reusable across agents and projects. `AGENT_PROGRAM.md` is project-specific and accumulates real experimental knowledge from this agent's own runs.

---

### 2. AutoLoop — Focus Lock in the Autonomous Mind

A new operating mode for the autonomous mind: when running an AutoLoop session, the mind locks onto the experiment and does nothing else until:
- The user interrupts (sends a message)
- A hard stop condition is reached: `max_iterations`, `max_hours`, or `target_metric` achieved
- The agent writes `AUTOLOOP_DONE` to the session log

**How it works:**

When `experiment_setup` is called with `autoloop: true`, it writes a focus lock to `data/autoloop.json`:

```json
{
  "active": true,
  "tag": "mar13",
  "branch": "experiment/mar13",
  "started_at": 1741823400,
  "max_iterations": 50,
  "max_hours": 8.0,
  "iterations_run": 0,
  "best_metric": 145.2,
  "status": "running"
}
```

On every wakeup, the autonomous mind checks for an active focus lock **before** building its priority stack. If `autoloop.json` exists and `active: true`:

1. Read `AGENT_PROGRAM.md` (if it exists) for strategy context
2. Check stop conditions (iterations, hours, target met)
3. Run one experiment iteration via `experiment_run`
4. Update `autoloop.json` with new iteration count and best metric
5. Schedule next wakeup (short interval — typically 30s for fast experiments)
6. Skip the normal priority stack entirely

The mind never drifts to Commune, goals, or other tasks while a focus lock is active. The user can always interrupt by sending a message (the normal pause mechanism), and on resume the focus lock is rechecked.

**New tool: `autoloop_control`** — manages the focus lock:
- `action: "start"` — activates focus lock (called by `experiment_setup` with `autoloop: true`)
- `action: "stop"` — deactivates focus lock, mind returns to normal priority stack
- `action: "status"` — shows active session: iterations, best metric, elapsed time, branch
- `action: "pause"` — temporarily suspend without clearing (survives restart)

---

### 3. Fixed Iteration Budget

The core fairness constraint from autoresearch: every experiment runs for exactly the same wall-clock duration, so results are directly comparable.

`experiment_setup` gains a `budget_seconds` parameter (default: `null` = no budget). When set:

- The measurement command is run with a hard wall-clock limit
- The experiment is killed at exactly `budget_seconds` (not a soft timeout — SIGTERM + SIGKILL)
- If the command exits early (success), it's evaluated normally
- The budget is written to `.experiment.json` and enforced by `experiment_run` on every iteration

```yaml
# Example: 5-minute budget like autoresearch
experiment_setup(
  tag="mar13",
  metric_command="python train.py > run.log 2>&1",
  metric_extract="grep '^val_bpb:' run.log | awk '{print $2}'",
  metric_direction="lower",
  target_files=["train.py"],
  budget_seconds=300,   # exactly 5 minutes, every time
  autoloop=true,
  max_iterations=100
)
```

**Why this matters:** Without a fixed budget, you can't tell if an improvement came from the change or from running longer. With a fixed budget, every iteration is a controlled experiment.

---

## The Full AutoLoop Flow

```
Owner writes/updates AGENT_PROGRAM.md
            │
            ▼
User: "Start an AutoLoop on train.py, metric: val_bpb, 5-min budget, run overnight"
            │
            ▼
Agent calls experiment_setup(tag="mar13", budget_seconds=300, autoloop=True, max_iterations=100)
  ├─ Creates branch: experiment/mar13
  ├─ Reads AGENT_PROGRAM.md (strategy context)
  ├─ Runs baseline: budget=300s exactly
  ├─ Writes .experiment.json with budget
  ├─ Writes data/autoloop.json (focus lock: active)
  └─ Confirms: "AutoLoop active. Will run ~100 experiments. Sleeping now."
            │
            ▼
Autonomous Mind wakeup cycle (every 30s):
  ├─ Checks data/autoloop.json → focus lock active
  ├─ Checks stop conditions (100 iterations? 8 hours?)
  ├─ Reads AGENT_PROGRAM.md for strategy context
  ├─ Formulates ONE hypothesis
  ├─ Implements change in train.py
  ├─ Calls experiment_run → runs for exactly 300s → extracts val_bpb
  ├─ Keep or discard (git keep/reset)
  ├─ Updates autoloop.json (iterations_run++, best_metric)
  ├─ Schedules next wakeup: 30s
  └─ Sleeps
            │
            ▼
12 iterations/hour × 8 hours = ~96 experiments overnight
            │
            ▼
Morning: User sees autoloop_status → best metric, branch, experiments journal
Owner updates AGENT_PROGRAM.md with what worked/didn't
```

---

## Implementation

### New Files
- `tools/experimentation/autoloop_tool.py` — `autoloop_control` tool
- `data/autoloop.json` — focus lock state (runtime, not committed)
- `AGENT_PROGRAM.md` — project root, owner-maintained (created by `setup.sh` with template)

### Modified Files
- `core/autonomous_mind.py` — check focus lock before priority stack evaluation
- `tools/experimentation/setup_tool.py` — add `autoloop`, `budget_seconds`, `max_iterations`, `max_hours` parameters
- `tools/experimentation/run_tool.py` — enforce `budget_seconds` with hard kill
- `core/planner.py` — read `AGENT_PROGRAM.md` into system prompt when focus lock active
- `setup.sh` — create `AGENT_PROGRAM.md` template on first install

### Config

No new config section required. AutoLoop uses existing `autonomous_mind` config:

```yaml
autonomous_mind:
  enabled: true
  wakeup_seconds: 30        # shorter wakeup for tight experiment loops
  max_rounds_per_wakeup: 3  # enough to formulate hypothesis + run + decide
```

---

## What Stays the Same

- Pause on user message — unchanged. User can always interrupt.
- Resume after user task — unchanged. Focus lock is rechecked on resume.
- Budget controls — unchanged. Per-wakeup and daily limits still apply.
- Approval system — unchanged. Tools that require approval still ask.
- The existing experiment tools (`experiment_setup`, `experiment_run`, `experiment_status`) — backward compatible. AutoLoop is opt-in via `autoloop=True`.

---

## Comparison

| | autoresearch | EloPhanto pre-AutoLoop | EloPhanto AutoLoop |
|---|---|---|---|
| **Focus lock** | Yes — single loop, never stop | No — mind drifts to other tasks | Yes — focus lock via `autoloop.json` |
| **Strategy doc** | `program.md` — human-maintained | No equivalent | `AGENT_PROGRAM.md` — human-maintained |
| **Fixed budget** | Yes — exactly 5 minutes | No — soft timeout only | Yes — hard kill at `budget_seconds` |
| **Multi-channel visibility** | No | Yes | Yes |
| **Pause on user** | No | Yes | Yes |
| **Any metric** | No (val_bpb only) | Yes | Yes |
| **Multi-file experiments** | No (train.py only) | Yes | Yes |
| **Goal integration** | No | Yes | Yes |
| **Knowledge capture** | No | Yes | Yes |
| **Background loops** | No — foreground process | 3 parallel engines | 3 parallel engines + focus lock |

---

## References

- [karpathy/autoresearch](https://github.com/karpathy/autoresearch) — Original inspiration. MIT. The `program.md`, fixed budget, and NEVER STOP patterns.
- [docs/37-AUTONOMOUS-EXPERIMENTATION.md](37-AUTONOMOUS-EXPERIMENTATION.md) — Existing experiment loop docs (tools, journal format, skill).
- [docs/26-AUTONOMOUS-MIND.md](26-AUTONOMOUS-MIND.md) — Autonomous mind architecture.
- [docs/46-PROACTIVE-ENGINE.md](46-PROACTIVE-ENGINE.md) — Heartbeat engine and HEARTBEAT.md.
- Skill file: `skills/autonomous-experimentation/SKILL.md`
- Tool files: `tools/experimentation/`
