# 95 — Smarter where it counts, and learning that is measured

**Status**: Built (Phases A–G) · **Date**: 2026-09-29 · **Follows**: [94](94-LONG-RUN-AUTONOMY-REVIEW.md)

docs/94 gave long runs a spine: a run ledger, resumable stops, deliberation,
verification, scheduling. It did not make the agent smarter or make it
learn. Two facts, verified in config and data on 2026-09-29, say why:

1. **The thinking ran on the smallest model.** Every task type routed to
   Z.ai `GLM-5.3-Flash` first; `gpt-6-astra` on the flat-rate Codex
   subscription was a fallback. The operator has since made Codex first.
2. **It records, it does not learn.** Lessons are written and recalled,
   but nothing measures whether a recalled lesson helped, and nothing
   measures whether the agent is getting better at all.

Learning, here, means: behaviour changes *and* a measured result improves.
Each phase below builds one link of that loop, and each was verified
against the code before being specced.

---

## Phase A — model hygiene (verified 2026-09-29) — **built**

| Finding | Evidence | Fix |
| --- | --- | --- |
| `browser.vision_model: zai/GLM-5.3-Flash` goes to OpenRouter as an invalid model | `_infer_provider` sends any `a/b` to OpenRouter (`router.py:835-863`); 40 `BadRequest … not a valid model` in logs | Recognise `zai/` and `kimi/` prefixes (stripped like `codex/`); case-insensitive `glm-`. Operator config: `codex/gpt-6-astra`. |
| Codex `usage_limit_reached` is treated as a 60 s rate limit | 429 bodies carry `"type":"usage_limit_reached"` and `resets_at` (logs 2026-09-11); router cooldown is 60 s | Park the provider until `resets_at` (capped at 6 h), logged as a quota stop. |
| `gpt-5.5` is the default in the wizard, demo config, adapter and hosted config — it **retires on 2026-10-14** | learn.chatgpt.com/docs/models: current Codex models are `gpt-6-astra` (most capable), `gpt-6-sol` (agentic/coding), `gpt-6-luna` (efficient); `gpt-5.5` is legacy | Defaults move to `gpt-6-astra`; `elophanto config migrate` gains a *rewrite* migration that replaces Codex `gpt-5.5` with `gpt-6-astra` (update.sh runs it). |
| Effort levels differ per GPT-6 model | Astra lists Light / Medium / Extra High / Max (no High); Sol Low…Max; Luna High / Max | `_EFFORT_CLAMP` entries per model, and one retry without the effort field if Codex rejects it — the exact API strings cannot be confirmed without spending quota. |
| Z.ai model list and prices are stale in the wizard and adapter | docs.z.ai pricing: `glm-5.3` $1.40/$4.40, `glm-5.3-flash` $0.15/$0.50, free `glm-4.7-flash`, vision `glm-4.6v` | Wizard choices, demo config and `ZAI_COSTS` updated. |
| New settings from docs/94 are not in the demo config or migrations | — | Added to `config.demo.yaml`, the wizard's written config, and additive migrations. |

**Update, same day:** GPT-6.1 Sol (`gpt-6.1-sol`) was released — near-Astra
performance at a fifth of Astra's API price ($2 / $10 per 1M tokens against
$10 / $50), accepting `low` … `max` effort (no `none` / `minimal`). It is now
the Codex default in place of `gpt-6-astra`, and Codex routes reason harder:
planning `high`, coding and analysis `xhigh`, deliberation `max`; `simple`
stays on `gpt-6-luna`. The retired-`gpt-5.5` rewrite now lands on
`gpt-6.1-sol`. Existing `gpt-6-astra` settings are not rewritten — Astra is
not retiring.

Operator config (gitignored, edited in place, secrets untouched):
`browser.vision_model → codex/gpt-6-astra`, a `deliberation` route on
`gpt-6-astra` at `xhigh`, and `simple` on `gpt-6-luna` — the Pro plan hit its
Codex usage limit on 2026-09-11, and summaries, classifications and handoffs
do not need the most capable model.

## Phase B — intelligence where the thinking is (doc 94 #1) — **built**

A `deliberation` task type. Every thinking call routes through it: the
checkpoint plan, the mind's decision, the pre-action review, decomposition and
its critique, progress evaluation, the final goal check, and panel judges.
The router falls back to the `planning` route when no `deliberation` route is
configured, so nothing breaks for existing installs — borrowing planning's
models but thinking at `high`, not planning's effort, which operators often
run low for latency. `goals.deliberation_effort` (now empty by default)
overrides the route's effort when set. Optional `llm.judge_model` (e.g.
`zai/glm-5.3`) runs the checkpoint panel's judges and the final goal check on
a different model family from the one that did the work, and falls back to the
route if that model fails. Plan revision and progress evaluation, which ran
on `simple`, now route here too. The pre-action review asks for `medium`
effort: it has a 60-second budget, and a timeout is no verdict. The
`panel_review` tool's judges are full agent runs with tools and keep the
acting route.

## Phase C — every plan is a prediction (doc 94 #2) — **built**

A checkpoint plan states its steps and how success will be shown. After the
attempt, the runner records a **plan outcome**: first-attempt pass, which
gate failed if any, steps used against steps planned, stop reason. A failed
attempt whose plan did not foresee the failure (not among its risks) is a
**surprise**; one post-mortem call compares the plan's assumptions with what
happened and names the assumption that broke. That becomes the lesson — so
lessons come from falsified predictions, not from the model's own summary.

```sql
CREATE TABLE IF NOT EXISTS plan_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id TEXT NOT NULL, checkpoint_order INTEGER NOT NULL, attempt INTEGER NOT NULL,
    passed INTEGER NOT NULL, gate TEXT NOT NULL DEFAULT '',
    steps_planned INTEGER NOT NULL DEFAULT 0, steps_used INTEGER NOT NULL DEFAULT 0,
    stop_reason TEXT NOT NULL DEFAULT '', surprise INTEGER NOT NULL DEFAULT 0,
    broken_assumption TEXT NOT NULL DEFAULT '', lessons_used TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
```

Mind decisions get the same record without an LLM call (`mind_outcomes`:
source, action, whether it was deliberated, the pick, tool calls and tool
errors, stop reason, cost) — enough for calibration statistics.

As built (`core/plan_outcomes.py`, `GoalRunner._record_outcome`): an outcome
is recorded for every attempt that had a plan — pass, receipt-gate failure,
verification failure, timeout, error. Interruptions (preemption, STOP, the
day's budget) refund the attempt and record nothing; the plan is dropped at
the start of the next attempt so a stale plan is never scored. The broken
assumption is also written to the run ledger as a fact, so the next attempt's
plan reads it. The post-mortem's lesson goes through the learner's usual
guards (injection scan, PII redaction, merge by title) with the tags
`failure` and `surprise`. The daily health digest reports plans scored,
first-attempt passes, surprises, and lessons by status.

## Phase D — lessons earn their place (doc 94 #3) — **built**

`recall_lesson_items` returns each lesson it offers with its identity
(`knowledge:<path>` or `instinct:<id>`); the planner sees them numbered
(`[L1]`, `[L2]`…) and names the ones it applies in `lessons_used`. Each plan
outcome credits or debits them in `lesson_stats (lesson_ref, title, body,
uses, passes, fails, status, status_note, last_used)`. The baseline is the
pass rate of the last 500 plan outcomes — all attempts, because lessons are
applied on retries too. A lesson used at least 5 times whose pass rate beats
the baseline by 15 points is **promoted**: written as a skill under
`skills/learned-<slug>/SKILL.md` — the full lesson as its instructions, its
measured record in the description, and as triggers its subject plus the
titles of checkpoints where plans that used it passed — and the skill list is
reloaded. An existing skill is never overwritten. A lesson used at least 5
times that trails the baseline by 20 points is **retired**: recall stops
offering it. Files are never deleted. Recall ranks the rest by their record,
smoothed toward the baseline so two lucky uses prove little; a lesson with
no record keeps its relevance order.

## Phase E — a benchmark from its own history (doc 94 #4) — **built**

Without a number, "smarter" is a feeling. The goal runner now keeps each
checkpoint attempt's tool calls and outputs (`tool_traces`, outputs capped at
4 KB). `elophanto bench capture` turns completed checkpoints into cases under
`data/bench/cases/` — the prompt inputs, the recorded tool outputs, the
success criteria and verification. `elophanto bench run` replays them: the
model runs live, but every tool call is answered from the recording by a
task-local interceptor (`core/run_hooks.py`) — **no real tool ever runs**.
Each case is scored by the same receipt gate and checks as production.
Results go to `bench_runs` with a fingerprint of the model routing and
prompt, so a change — a model, a prompt, the lesson set — shows up as a
number. `bench.enabled` (off by default: it spends model quota) runs it
nightly from the goal runner's watchdog.

As built (`core/tool_traces.py`, `core/bench.py`, `cli/bench_cmd.py`):

- **Recording.** Every attempt's calls are stored with the attempt's start
  time; parameters are redacted first (any key naming a secret; every value
  passed to a `vault_` tool); outputs are JSON, capped at 4 KB. The attempt
  that passes is marked. Failed attempts' traces are pruned after 14 days;
  passed ones are kept — they are the cases.
- **A case** holds the goal, the checkpoint and its criteria and declared
  checks, the run ledger *as it stood when the attempt started* (so it does
  not contain the answer), and the recording.
- **Replay.** `RunHooks.tool_interceptor` is consulted by the executor right
  after the arguments are parsed — before permission prompts, guards or any
  side effect. A call is answered by the unused recorded call of the same
  tool whose parameters match best; the same call made again gets the same
  answer; a call with no recorded answer gets an error naming what the case
  recorded, and counts as a miss. Screenshot paths are stripped from
  replayed outputs. `RunHooks.record_memory=False` keeps the replay out of
  long-term memory and the learner.
- **The run** uses the production prompt (`build_checkpoint_prompt`) and, when
  `goals.deliberate` is on, the production planning step with recalled
  lessons — the lesson set is part of what is measured — but records no plan
  outcome and credits no lesson.
- **Scoring**: the receipt gate, then the declared `tool_output` and
  `artifact` checks. `file_exists`, `url_ok` and `judgment` need the world or
  a panel and are skipped.
- **Fingerprint**: planning and deliberation routes (provider, model,
  effort), `judge_model`, the git revision, and digests of the learned skills,
  the lessons and `AGENT_PROGRAM.md`.
- The daily digest shows the latest score and the change from the previous
  run, flagged when the setup changed.

Cases accumulate from goal runs after this change; `bench capture` on an
older database finds none.

## Phase F — improving its own playbooks (doc 94 #5) — **built**

`elophanto bench run --metric` prints `bench_score: <x>`, which the existing
AutoLoop (`experiment_setup` / `experiment_run`, keep-or-discard against a
metric) can optimise. `experiment_setup` refuses target files outside
`skills/`, `knowledge/` and `AGENT_PROGRAM.md` when the metric is the
benchmark — the agent may rewrite its playbooks, never its code or safety
rails. A skill (`skills/self-improvement/SKILL.md`) gives the recipe.

As built: the benchmark is recognised by `bench run` in the metric command.
Because `experiment_run` stages with `git add -A`, the boundary is enforced
there too: setup records `restrict_to_targets`, and a run whose staged
changes reach outside the declared targets is refused and unstaged — the
edits stay in the working tree for the agent to revert. The skill tells the
agent to read the failing cases first, change one playbook per experiment,
and treat a one-case gain as noise until a second run confirms it.

## Phase G — training data from verified runs (doc 94 #6) — **built**

`elophanto bench export-training` writes, from the recorded traces and plan
outcomes: `sft.jsonl` — checkpoint trajectories that passed every gate, in
chat format with tool calls; `preference.jsonl` — pairs where the same
checkpoint failed and then passed (rejected, chosen). Fine-tuning itself is
not built here: it needs GPU infrastructure and a model that can be trained
(the configured Qwen on Hugging Face qualifies). The export is the part that
did not exist.

As built (`core/training_export.py`): files land under
`<agent.workspace>/training/<date>/` unless `--out` says otherwise. Each
trajectory starts from the checkpoint prompt with the ledger as it stood when
that attempt began, then one assistant tool call and one tool result per
recorded call, then the checkpoint's result. A preference pair's prompt is
the failed attempt's starting point. Parameters were redacted when stored;
all text is also passed through the PII redactor. Only checkpoints that
eventually passed are exported; failed traces are pruned after 14 days, so
pairs come from recent history.

---

## Order

A → B → C+D → E → F+G. Each phase is committed on its own after the full
suite passes.
