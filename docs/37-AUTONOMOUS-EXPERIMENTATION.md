# EloPhanto — Autonomous Experimentation

## Origin

This capability is inspired by Andrej Karpathy's [autoresearch](https://github.com/karpathy/autoresearch) (MIT license, March 2026). autoresearch gives an AI agent a small LLM training setup and lets it experiment autonomously overnight: it modifies a training script, runs a 5-minute experiment, checks if the validation loss (val_bpb) improved, keeps or discards the change, and repeats — roughly 100 experiments while you sleep.

The key insight from autoresearch is not the ML part — it's the **experiment loop pattern**: a tight cycle of hypothesize → implement → measure → keep/discard → log → repeat, running indefinitely without human intervention. We took this pattern and generalized it into an EloPhanto skill that works for any measurable optimization target.

## What We Took from autoresearch

| Concept | autoresearch | EloPhanto adaptation |
|---------|-------------|---------------------|
| **Experiment loop** | Infinite loop: modify `train.py` → run → measure → keep/discard | Generalized: modify any target file → run any command → measure any metric → keep/discard |
| **Single metric** | `val_bpb` (validation bits per byte) | User-defined: latency, throughput, test count, binary size, memory, benchmark scores |
| **Git-based versioning** | Keep = advance branch. Discard = `git reset --hard HEAD~1` | Same pattern, on `experiment/<tag>` branches |
| **Experiment journal** | `results.tsv` with commit, metric, status, description | `experiments.tsv` with same schema |
| **Fixed time budget** | 5-minute training runs | User-defined timeout per experiment |
| **Simplicity criterion** | "A small improvement that adds ugly complexity is not worth it" | Adopted as-is |
| **Never stop** | "Do NOT pause to ask the human... run indefinitely until manually stopped" | Same philosophy, integrated with autonomous mind |
| **program.md as a skill** | Karpathy calls it "a super lightweight skill" — markdown instructions for the agent | Implemented as `skills/autonomous-experimentation/SKILL.md` |
| **Crash handling** | Fix simple bugs, skip fundamentally broken ideas | Same: quick-fix typos, log and move on for broken hypotheses |

## What We Did NOT Take

- **ML-specific code** — autoresearch's `train.py`, `prepare.py`, GPT model, Muon optimizer, tokenizer, dataloader — none of this is relevant to EloPhanto. We took the pattern, not the implementation.
- **Single-file constraint** — autoresearch restricts the agent to modifying one file. Our skill allows multiple target files (though one is recommended).
- **NVIDIA GPU requirement** — autoresearch requires a single NVIDIA GPU. Our generalized pattern has no hardware requirements.
- **Fixed dependencies** — autoresearch forbids installing new packages. Our skill inherits EloPhanto's normal dependency management.

## How It Works in EloPhanto

### Architecture

The autonomous experimentation skill sits at the intersection of three existing EloPhanto systems:

```
┌─────────────────────────────────────────────────┐
│           Autonomous Mind (background)          │
│         Triggers experiment loop wakeups         │
├─────────────────────────────────────────────────┤
│         Experiment Loop (this skill)            │
│  hypothesize → implement → measure → decide     │
├──────────┬──────────────┬───────────────────────┤
│ Self-Dev │   Goals      │    Knowledge          │
│ modify   │ track long-  │ store insights        │
│ test     │ running      │ from successful       │
│ rollback │ experiments  │ experiments           │
└──────────┴──────────────┴───────────────────────┘
```

Three dedicated tools manage the experiment lifecycle:

- **`experiment_setup`** — Initialize a session: create a git branch (`experiment/<tag>`), run the baseline measurement, create the experiment journal (`experiments.tsv`), and save the experiment config (`.experiment.json`). Validates target files exist, checks branch uniqueness, and cleans up on baseline failure.
- **`experiment_run`** — Execute one iteration: commit current changes, run the measurement command, extract the metric, compare to the best, and keep (advance branch) or discard (`git reset --hard HEAD~1`). Handles crashes with automatic revert. Appends every attempt to the journal.
- **`experiment_status`** — View session state: config, best metric, baseline, total experiments, keep/discard/crash counts, and the last N journal entries.

These integrate with existing tools for richer workflows:

- **`self_modify_source`** / **`self_run_tests`** — For experiments on EloPhanto's own code (ensures tests still pass)
- **`goal_create`** / **`goal_manage`** — Track experiment sessions as long-running goals
- **`knowledge_write`** — Save insights from successful experiments
- **`set_next_wakeup`** — Schedule experiment iterations in the autonomous mind

### The Loop

```
Setup:
  1. User defines: metric, target file(s), run command, constraints, tag
  2. Agent creates branch: experiment/<tag>
  3. Agent creates experiments.tsv with baseline entry

Loop (runs indefinitely):
  1. Read current best metric from journal
  2. Formulate ONE hypothesis
  3. Implement the change (minimal, focused)
  4. Git commit
  5. Run measurement command → run.log
  6. Extract metric from run.log
  7. If improved → keep commit, update baseline, log "keep"
     If equal/worse → git reset --hard HEAD~1, log "discard"
     If crashed → revert, log "crash"
  8. Append to experiments.tsv
  9. Go to 1
```

### Experiment Journal

Tab-separated file tracking every attempt:

```
commit	metric	status	description
a1b2c3d	145.2	keep	baseline
b2c3d4e	138.7	keep	cache provider configs
c3d4e5f	139.1	discard	async DNS resolution (no improvement)
d4e5f6g	0.0	crash	connection pooling (OOM)
e5f6g7h	131.4	keep	batch provider health checks
```

This journal serves multiple purposes:
- **Audit trail** — every experiment is documented
- **Pattern recognition** — the agent can review what worked and what didn't
- **Knowledge extraction** — successful experiments become knowledge base entries
- **Reproducibility** — every attempt has a git commit hash

### Integration Points

**With the Goal System:**
A long-running experiment session maps naturally to a goal:
- Goal: "Optimize router latency to under 100ms"
- Checkpoints: "Establish baseline", "Run 10 experiments", "Run 20 experiments", "Achieve target"

**With the Autonomous Mind:**
The experiment loop runs in the background via the autonomous mind's wakeup cycle. Each wakeup runs one experiment iteration, then schedules the next wakeup after the measurement completes.

**With Self-Development:**
When experimenting on EloPhanto's own code, `self_modify_source` handles the safety guarantees: pre-change test baseline, post-change test verification, and automatic rollback on test failure.

**With Knowledge:**
Successful experiments are distilled into knowledge entries. "Caching provider configs reduced router latency by 5%" becomes a permanent insight that informs future optimization work.

## Configuration

No new configuration is required. The skill uses existing config:

- `agent.permission_mode: full_auto` — recommended for unattended experimentation
- `autonomous_mind.enabled: true` — required for background experiment loops
- `goals.enabled: true` — recommended for tracking experiment sessions

## Use Cases

### Self-Optimization
The agent experiments on its own codebase overnight. "Make the router faster" → 50 experiments on `core/router.py`, each verified against the test suite, keeping every improvement.

### ML Research (autoresearch-style)
Point the agent at a training script with a measurable metric. It runs experiments autonomously, just like autoresearch, but integrated with EloPhanto's goal tracking, knowledge system, and multi-channel notifications.

### Performance Benchmarking
"Optimize this API endpoint for throughput" → The agent tries different caching strategies, query optimizations, connection pooling configs, measuring requests/second after each change.

### Build Size Optimization
"Reduce the production bundle size" → The agent experiments with tree-shaking configs, import replacements, dependency alternatives, measuring `wc -c dist/bundle.js` after each change.

### Test Coverage
"Increase test coverage to 90%" → The agent writes tests, measures coverage after each batch, keeps what contributes meaningful coverage, discards redundant tests.

## Comparison with Existing Self-Development

| | Self-Development (existing) | Autonomous Experimentation (new) |
|---|---|---|
| **Trigger** | User asks for a specific change | User defines a metric to optimize |
| **Attempts** | Single attempt with rollback on failure | N attempts, keeping only improvements |
| **Metric** | Pass/fail (tests pass or don't) | Quantitative (how much did it improve?) |
| **Duration** | Minutes | Hours to overnight |
| **Journal** | Git commits only | TSV with metrics per attempt |
| **Human input** | Often required | Set and forget |

The two systems are complementary: self-development builds new capabilities, autonomous experimentation optimizes existing ones.

## References

- [karpathy/autoresearch](https://github.com/karpathy/autoresearch) — Original inspiration. MIT license. Autonomous ML research via experiment loop.
- [karpathy/nanochat](https://github.com/karpathy/nanochat) — Parent training codebase that autoresearch simplifies.
- Skill file: `skills/autonomous-experimentation/SKILL.md`
