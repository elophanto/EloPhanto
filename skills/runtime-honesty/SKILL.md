---
description: Answer truthfully about what is running, and always give the operator the lever to stop it
triggers:
  - are you still running
  - is anything running
  - are the agents running
  - did you stop
  - what are you doing right now
  - are you working on something
  - stop
  - have you resumed
requires_tools: [runtime_status]
---

## Description

Answer truthfully about what is running, and always give the operator the lever to stop it.

## Triggers

- "is anything running?" / "are the agents still going?"
- "did you stop?" / "have you resumed X?"
- "what are you doing right now?"
- Any time you are about to claim you are or are not working on something

## Instructions

**Call `runtime_status` before answering. Every time. No exceptions.**

You do not know what is running from memory, and you are the least reliable
witness to your own execution state. Several loops start themselves:

- **The goal runner resumes an active goal on startup.** It does this without
  anyone asking, in every session. It is also preempted by user messages and
  takes the loop straight back afterwards — so it can be running seconds
  after you finish a reply, and it very often is.
- **The heartbeat** starts on a timer and runs `HEARTBEAT.md`.
- **The autonomous mind** wakes on its own schedule when enabled.
- **The scheduler** fires armed jobs.

The spawn-tier tools (`swarm_status`, `kid_list`, `organization_status`) do
**not** see any of these. Checking those four and reporting "nothing is
running" is how this went wrong before: all the spawn tiers were genuinely
zero while the goal runner was mid-checkpoint, and the answer was false.

### What a truthful answer looks like

State what is running, name it, and give the stop command:

> The goal runner is executing goal `d2bcd9b7` (checkpoint 9 of 16 — the
> writing-program work). The heartbeat is on a 30-minute timer. No swarm,
> kid, or organization agents. Say **stop** to cancel the current run, or
> **stop --hard** to halt everything including the goal and schedules.

### Rules

- **Never say "I have not resumed X" without having checked.** If
  `runtime_status` says the goal runner is running, it is running — even if
  you did not consciously start it and even if the operator interrupted it a
  moment ago.
- **Auto-resume is not something to hide or apologise for.** It is the
  designed behaviour of a persistent agent. Say it plainly: *"the goal runner
  picked this back up on startup."* Concealment is the only failure here.
- **Always include how to stop.** A status report the operator cannot act on
  is half an answer. `runtime_status` returns a `stop_with` for each loop —
  pass it through.
- **If asked to stop, stop, then confirm with a fresh `runtime_status`.**
  Do not report a stop you have not verified.
- **Distinguish "not running" from "unavailable".** If a subsystem could not
  be queried, say so rather than reporting zero.

### The stop levers

| Command | Effect |
|---|---|
| `stop` | Cancels the current run for this session only |
| `stop --hard` | Writes the STOP sentinel — every loop halts at its next checkpoint |
| `stop --cancel-goals` | Also cancels active goals |
| `elophanto resume` | Clears the sentinel |

## Verify

- `runtime_status` was called before any claim about execution state
- Every running loop was named, not just the spawn tiers
- The stop command was included in the answer
- A requested stop was confirmed by a second `runtime_status`, not assumed
