# Self-Improvement

## Description

Improve your own playbooks against a measured score. The benchmark
(`elophanto bench`) replays checkpoints you completed and verified before:
your real prompt, planning step and model run live, and every tool call is
answered from the recording, so nothing real runs. The score is the share of
cases that pass the same gates production uses. This skill runs the
experiment loop (`experiment_setup` / `experiment_run`) with that score as the
metric, so a playbook change is kept only if it measurably helps.

You may change your playbooks: skills under `skills/`, knowledge under
`knowledge/`, and `AGENT_PROGRAM.md`. You may not change code or safety rails
in a benchmark experiment — `experiment_setup` refuses other target files and
`experiment_run` refuses a change outside the declared targets.

## Triggers

- improve yourself
- self-improvement
- get better at
- benchmark score
- "why do checkpoints keep failing"
- "the benchmark dropped"
- "tune your playbooks"

## Instructions

1. **Check there is something to measure.** Run
   `elophanto bench capture`, then `elophanto bench history`. With fewer than
   10 cases the score is noise — stop and say so; cases accumulate as goals
   complete.
2. **Read the failures before changing anything.** Run
   `elophanto bench run` once (without `--metric`) and read the `why` column:
   receipt-gate refusals, failed checks, replay misses (the model called a tool
   the recorded run did not need), stops. Also read the daily health digest's
   plan and lesson lines (`autonomy_health`), and any retired lessons.
3. **Form one hypothesis per experiment.** "Checkpoints that collect listings
   fail because the playbook never says to read every page" — tied to the
   failing cases, not a general rewrite.
4. **Set up** with `experiment_setup`:
   - `metric_command`: `.venv/bin/python -m cli.main bench run --metric > run.log 2>&1`
     (or `elophanto bench run --metric > run.log 2>&1` if it is installed)
   - `metric_extract`: `grep '^bench_score:' run.log | tail -1 | awk '{print $2}'`
   - `metric_direction`: `higher`
   - `target_files`: the one or two playbook files your hypothesis is about
   - `budget_seconds`: about `max_cases × 300`
5. **Change one thing**, in the target files only, then `experiment_run` with a
   short description. It keeps the change if the score rose and reverts it
   otherwise.
6. **Treat small gains as noise.** Model output varies between runs; a gain of
   one case out of twenty is within it. Before you report an improvement,
   confirm it holds on a second `elophanto bench run`.
7. **Report** the baseline, what you tried, what was kept, and the final
   score — with `elophanto bench history` as the evidence.

## Verify

- `elophanto bench history` shows a run after the change with a higher score
  than the baseline, and the fingerprint changed (the lesson/skill digest).
- `git diff` on the experiment branch touches only `skills/`, `knowledge/` or
  `AGENT_PROGRAM.md`.

## Notes

- Every `bench run` spends model quota: cases × (plan + acting steps).
- `bench.enabled` in config.yaml runs the benchmark nightly; the digest
  reports the score and its change.
- A lesson that proves itself in real plans is promoted to a skill
  automatically (`skills/learned-*`); this loop is for deliberate changes.
