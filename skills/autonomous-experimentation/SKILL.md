# Autonomous Experimentation

## Description

A structured loop for autonomous, metric-driven experimentation. The agent modifies code, measures a metric, keeps improvements, discards regressions, logs everything, and repeats indefinitely. Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch), which uses this pattern to let an AI agent run ML training experiments overnight — modifying a training script, running 5-minute experiments, keeping what improves val_bpb, discarding what doesn't.

This skill generalizes that pattern beyond ML: any measurable optimization target works — code performance, binary size, test coverage, response latency, memory usage, benchmark scores, or any custom metric the user defines.

## Triggers

- experiment
- optimize
- benchmark
- "run experiments overnight"
- "try things and keep what works"
- "improve performance"
- autoresearch
- "experiment loop"
- "try different approaches"
- ablation

## Instructions

### Setup Phase

Before starting the experiment loop, establish these with the user:

1. **Metric** — What number are you optimizing? Must be machine-readable from command output.
   - Examples: `val_bpb`, `pytest --tb=no | grep passed`, `time ./benchmark`, `wc -c binary`
   - Must have a clear direction: lower is better, or higher is better

2. **Target file(s)** — What can the agent modify?
   - Keep scope narrow. One file is ideal, two or three is acceptable.
   - Everything else is read-only context.

3. **Run command** — How to measure the metric after each change.
   - Must be deterministic (or averaged over multiple runs)
   - Must complete in a bounded time (set a timeout)

4. **Constraints** — What must NOT break?
   - Tests that must still pass
   - Resource limits (memory, disk, time)
   - Code style / complexity preferences

5. **Run tag** — A label for this experiment session (e.g., `mar7-perf`).
   - Create a git branch: `experiment/<tag>`

6. **Experiment journal** — Create `experiments.tsv` with header:
   ```
   commit	metric	status	description
   ```
   Record the baseline as the first entry.

### The Experiment Loop

LOOP FOREVER:

1. **Baseline check** — Read the current best metric from the journal.

2. **Hypothesis** — Formulate ONE specific change to try. Write it down before coding.
   - Draw from: literature in code comments, prior near-misses in the journal, combining successful changes, architectural alternatives, hyperparameter sweeps, simplification (removing code that doesn't help).

3. **Implement** — Modify only the in-scope file(s). Keep changes minimal and focused.
   - One idea per experiment. Never combine multiple hypotheses.

4. **Commit** — `git commit` the change with a descriptive message.

5. **Run** — Execute the run command, redirecting output to `run.log`:
   ```
   <run_command> > run.log 2>&1
   ```
   Do NOT let output flood the context window.

6. **Extract metric** — Parse the metric from `run.log`.
   - If the run crashed: `tail -n 50 run.log` to diagnose. Try a quick fix (typo, import). If fundamentally broken, log as `crash` and revert.

7. **Decide** — Compare to baseline:
   - **Improved**: Keep the commit. Update baseline. Log as `keep`.
   - **Equal or worse**: `git reset --hard HEAD~1`. Log as `discard`.
   - **Crash**: Revert. Log as `crash`.

8. **Log** — Append to `experiments.tsv`:
   ```
   <commit>	<metric>	<keep|discard|crash>	<what was tried>
   ```

9. **Repeat** — Go to step 2. Never stop. Never ask "should I continue?"

### Simplicity Criterion

Borrowed from autoresearch: all else being equal, simpler is better.

- A small metric improvement that adds ugly complexity? Probably not worth it.
- A small metric improvement from *deleting* code? Definitely keep.
- Equal metric but much simpler code? Keep.
- Weigh complexity cost against improvement magnitude.

### When Stuck

If the last 5+ experiments all got discarded:

1. Re-read the in-scope files for new angles
2. Review the journal for patterns (what kinds of changes worked?)
3. Try more radical changes (architectural, not just parameter tweaks)
4. Try combining two previous near-misses
5. Try the opposite of what you've been doing

### Timeout and Crash Handling

- Set a timeout for each run (e.g., 2x the expected duration)
- If a run exceeds the timeout, kill it and treat as a crash
- If a crash is a simple bug (typo, missing import), fix and re-run
- If the idea itself is broken, log as crash and move on
- After 3 consecutive crashes, pause and re-evaluate approach

### Integration with EloPhanto

- Use `self_modify_source` for changes to EloPhanto's own code
- Use `self_run_tests` as the constraint checker (tests must still pass)
- Use `goal_create` for long-running experiment sessions with checkpoints
- Use the autonomous mind to run experiments in the background
- Use `knowledge_write` to save insights from successful experiments

## Examples

### Good: Performance Optimization

```
User: "Optimize the response time of the LLM router. Run experiments overnight."

Agent:
1. Establishes metric: average latency from `pytest tests/test_core/test_router.py -v --tb=no`
2. Target file: core/router.py
3. Creates branch: experiment/mar7-router-perf
4. Records baseline: 145ms average
5. Experiment 1: cache provider configs → 138ms → keep
6. Experiment 2: async DNS resolution → 135ms → keep
7. Experiment 3: connection pooling → 131ms → keep
8. Experiment 4: remove fallback retries → 130ms but tests fail → discard
9. ... continues overnight
```

### Good: ML Training (autoresearch-style)

```
User: "Run autoresearch on train.py. Optimize val_bpb."

Agent:
1. Metric: val_bpb (lower is better), extracted via `grep "^val_bpb:" run.log`
2. Target: train.py
3. Run command: `uv run train.py > run.log 2>&1` (5-min budget)
4. Experiments: architecture changes, hyperparameter sweeps, optimizer tweaks
5. Each experiment is a 5-minute training run
6. ~12 experiments/hour, ~100 overnight
```

### Bad: No Clear Metric

```
User: "Make the code better"

Agent should ask:
- Better how? Faster? Smaller? More readable? More test coverage?
- What specific metric can we measure?
- What file(s) should I modify?
```

### Bad: Too Many Changes at Once

```
Experiment: "Change the optimizer, double the learning rate, and switch to a different architecture"

This combines 3 hypotheses. If it improves, you don't know which change helped.
If it regresses, you don't know which change hurt. One change at a time.
```

## Verify

- Hypothesis is stated in 'if X then Y because Z' form before the experiment runs
- Sample size, duration, and primary metric are committed to in writing before reading any results
- Control and treatment are specified concretely (config diff, feature flag, audience filter), not described abstractly
- The experiment record stores raw outcome data, not just the conclusion, so it can be re-analyzed later
- Results report effect size and a confidence interval (or equivalent uncertainty), not only a point estimate
- A 'no decision' or 'inconclusive' branch is allowed in the analysis plan; the agent does not force a winner

## Notes

- The experiment journal (`experiments.tsv`) is the ground truth. Always log.
- Git branches keep the main branch clean. All experiments happen on `experiment/<tag>`.
- The agent should never stop to ask if it should continue. The human will interrupt when they want it to stop.
- This pattern works best with `full_auto` permission mode and the autonomous mind enabled.
- For EloPhanto self-optimization, combine with `self_run_tests` to ensure experiments don't break existing functionality.
- Original inspiration: [karpathy/autoresearch](https://github.com/karpathy/autoresearch) — autonomous ML research where an AI agent iterates on a training script overnight, keeping what improves the loss metric and discarding what doesn't.
