# Agent Program
#
# This is your research constitution. Read it at the start of every AutoLoop session.
# Edit this file to improve your autonomous research strategy over time.
# The agent reads it; the owner writes it. Both improve it together.
#
# See docs/47-AUTOLOOP.md for full design.

## Research Philosophy

- One change per iteration. Never modify two things at once — you can't tell which caused the result.
- Prefer deletions over additions. A simplification that holds the metric is always a win.
- Small improvement + clean code beats large improvement + complex code.
- When stuck (5+ consecutive discards): re-read the target files for fresh angles, review the
  journal for near-misses, try combining two near-misses, try the opposite of what failed,
  or make a more radical architectural change.
- A crash is information. Read the stack trace before moving on.

## Metric Interpretation

- "Better" means strictly improved, not equal.
- A 0.001 improvement with 20 lines of added complexity? Usually not worth it.
- A 0.001 improvement by deleting code? Always keep it.
- Equal metric, simpler code? Keep it — that's a simplification win.

## Iteration Protocol

1. Call experiment_status to read the current best metric and recent journal entries.
2. Form ONE hypothesis based on what has/hasn't worked. Write it in your description.
3. Implement the change — minimally and focused.
4. Call experiment_run with a clear description of what you tried and why.
5. Go to 1.

## Domain Rules

(Owner: add project-specific constraints here as you run sessions)

## What Has Worked

(Owner/agent: annotate after sessions — "Caching provider configs: -5ms latency, kept 2026-03-13")

## What Has Not Worked

(Owner/agent: annotate after sessions — "Async DNS: always race conditions in this codebase")
