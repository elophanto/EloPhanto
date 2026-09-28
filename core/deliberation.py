"""Deliberation — the thinking steps that run before acting.

The acting loop is told to act: "state your plan in one or two sentences",
"no prose preamble, begin with the first tool call". That is right for a
chat reply and wrong as the only mode for work that runs for hours, where a
wrong approach costs a whole checkpoint attempt and a repeated one costs
three. These calls sit *outside* the acting loop, at the moments where a
wrong call is expensive:

  * before a checkpoint attempt — plan it: approach, steps, assumptions,
    risks, how the success criteria will be shown by tool outputs, and on a
    retry, a diagnosis of why the last attempt failed;
  * before the mind acts — weigh the arbiter's top candidates and commit to
    one, with why, the expected outcome, and when it is done;
  * before a CRITICAL tool runs unattended — state what it should do, and
    whether it is warranted.

Each returns structured data or None. None means "carry on without it":
thinking must never be the reason work does not happen. See
docs/94-LONG-RUN-AUTONOMY-REVIEW.md §10.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_TIMEOUT_S = 120.0


def _loads(raw: str) -> Any:
    from core.goal_manager import _loads_json_lenient

    return _loads_json_lenient(raw or "")


async def _ask(
    router: Any,
    system: str,
    user: str,
    *,
    effort: str = "",
    max_tokens: int = 1500,
    timeout: float = _TIMEOUT_S,
) -> tuple[Any, str, float]:
    """One thinking call → (parsed JSON or None, reasoning text, cost)."""
    try:
        resp = await asyncio.wait_for(
            router.complete(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                task_type="planning",
                temperature=0.3,
                max_tokens=max_tokens,
                reasoning_effort=effort or None,
            ),
            timeout=timeout,
        )
    except Exception as e:
        logger.warning("deliberation call failed: %s", e)
        return None, "", 0.0
    return (
        _loads(resp.content or ""),
        str(getattr(resp, "reasoning", "") or ""),
        float(getattr(resp, "cost_estimate", 0.0) or 0.0),
    )


def _str_list(value: Any, limit: int = 8) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()][:limit]


# ---------------------------------------------------------------------------
# Checkpoint plan
# ---------------------------------------------------------------------------

_PLAN_SYSTEM = """\
You are the planning step of an autonomous agent. It runs BEFORE the agent
executes one checkpoint of a long-running goal. You do not act — you think,
so that the acting step does not have to improvise.

Return ONLY a JSON object:
{
  "diagnosis": "<on a retry: why the previous attempt failed, from the ledger, and what will be different this time; empty on a first attempt>",
  "approach": "<the approach in 2-4 sentences, naming the tools>",
  "steps": ["<concrete step>", "..."],
  "assumptions": ["<what must be true for this to work>"],
  "risks": ["<what could go wrong — and the fallback>"],
  "verification": "<how the success criteria will be shown by what tools RETURN; the completion gate accepts tool outputs, never prose>",
  "reuse": ["<artifacts or facts from the ledger this attempt builds on>"]
}

Rules:
- Build on the ledger. Never plan to recreate an artifact that exists, and
  never repeat an approach the ledger lists as failed.
- If the ledger says where the last run of this checkpoint stopped, the
  first step continues from there (after checking it).
- Use the dedicated tool for the domain; name tools, paths, URLs, counts.
- 2-8 steps. Specific beats thorough."""


@dataclass
class CheckpointPlan:
    approach: str
    steps: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    verification: str = ""
    reuse: list[str] = field(default_factory=list)
    diagnosis: str = ""
    reasoning: str = ""
    cost: float = 0.0

    def render(self) -> str:
        parts: list[str] = []
        if self.diagnosis:
            parts.append(f"DIAGNOSIS OF THE LAST ATTEMPT: {self.diagnosis}")
        parts.append(f"APPROACH: {self.approach}")
        if self.steps:
            parts.append(
                "STEPS:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(self.steps, 1))
            )
        if self.reuse:
            parts.append("BUILDS ON: " + "; ".join(self.reuse))
        if self.assumptions:
            parts.append("ASSUMPTIONS: " + "; ".join(self.assumptions))
        if self.risks:
            parts.append("RISKS / FALLBACKS: " + "; ".join(self.risks))
        if self.verification:
            parts.append(f"VERIFY BY: {self.verification}")
        return "\n".join(parts)


async def plan_checkpoint(
    router: Any,
    *,
    goal: str,
    order: int,
    total: int,
    title: str,
    description: str,
    criteria: str,
    stage: str,
    ledger_text: str,
    attempt: int,
    last_failure: str = "",
    effort: str = "",
    lessons: str = "",
) -> CheckpointPlan | None:
    """Plan one checkpoint attempt before it runs. None if planning failed."""
    retry = ""
    if attempt > 1 or last_failure:
        retry = (
            f"\nTHIS IS ATTEMPT {attempt}. The last attempt ended with: "
            f"{(last_failure or 'see ledger')[:800]}\n"
            "Diagnose it before planning.\n"
        )
    user = (
        f"GOAL: {goal}\n\n"
        f"CHECKPOINT {order} of {total}: {title}\n"
        f"Stage: {stage}\nDescription: {description}\n"
        f"Success criteria: {criteria}\n{retry}\n"
        f"RUN LEDGER:\n{ledger_text or '(empty — first run of this goal)'}"
    )
    if lessons:
        user += f"\n\nLEARNED FROM EARLIER RUNS (apply what is relevant):\n{lessons}"
    data, reasoning, cost = await _ask(router, _PLAN_SYSTEM, user, effort=effort)
    if not isinstance(data, dict) or not str(data.get("approach") or "").strip():
        return None
    return CheckpointPlan(
        approach=str(data.get("approach")).strip()[:800],
        steps=_str_list(data.get("steps")),
        assumptions=_str_list(data.get("assumptions"), 6),
        risks=_str_list(data.get("risks"), 6),
        verification=str(data.get("verification") or "").strip()[:600],
        reuse=_str_list(data.get("reuse"), 8),
        diagnosis=str(data.get("diagnosis") or "").strip()[:800],
        reasoning=reasoning[:2000],
        cost=cost,
    )


# ---------------------------------------------------------------------------
# Mind decision
# ---------------------------------------------------------------------------

_PICK_SYSTEM = """\
You are the decision step of an autonomous agent's background mind. An
arbiter has scored candidate actions from real state. Weigh the top ones
and commit to exactly one BEFORE anything is done. Consider: which moves a
real outcome (not bookkeeping), which is feasible right now, what it costs,
and what you already did recently. The top score is usually right; deviate
only for a reason you can state.

Return ONLY a JSON object:
{
  "pick": <candidate number from the menu>,
  "why": "<one or two sentences: why this over the others>",
  "rejected": "<the strongest alternative and why not now>",
  "expected_outcome": "<what will exist or be true afterwards>",
  "done_when": "<the observable condition that ends this cycle>"
}"""


@dataclass
class MindDecision:
    pick: int
    why: str
    rejected: str = ""
    expected_outcome: str = ""
    done_when: str = ""
    reasoning: str = ""
    cost: float = 0.0

    def render(self, action_spec: str) -> str:
        lines = [
            f"DECISION (made before acting — execute it): candidate {self.pick}: "
            f"{action_spec[:400]}",
            f"Why: {self.why}",
        ]
        if self.rejected:
            lines.append(f"Not now: {self.rejected}")
        if self.expected_outcome:
            lines.append(f"Expected outcome: {self.expected_outcome}")
        if self.done_when:
            lines.append(f"Done when: {self.done_when} — then stop.")
        return "\n".join(lines)


async def decide_mind_action(
    router: Any,
    *,
    menu: str,
    n_candidates: int,
    state: str,
    recent: str,
    effort: str = "",
) -> MindDecision | None:
    """Commit to one arbiter candidate before the mind acts."""
    user = (
        f"CANDIDATE MENU:\n{menu}\n\n"
        f"STATE (truncated):\n{state[:2500]}\n\n"
        f"RECENT ACTIVITY:\n{recent[:1200]}"
    )
    data, reasoning, cost = await _ask(
        router, _PICK_SYSTEM, user, effort=effort, max_tokens=800
    )
    if not isinstance(data, dict):
        return None
    try:
        pick = int(data.get("pick"))
    except (TypeError, ValueError):
        return None
    if not 1 <= pick <= n_candidates:
        return None
    return MindDecision(
        pick=pick,
        why=str(data.get("why") or "").strip()[:400],
        rejected=str(data.get("rejected") or "").strip()[:300],
        expected_outcome=str(data.get("expected_outcome") or "").strip()[:300],
        done_when=str(data.get("done_when") or "").strip()[:300],
        reasoning=reasoning[:2000],
        cost=cost,
    )


# ---------------------------------------------------------------------------
# Pre-action review
# ---------------------------------------------------------------------------

_REVIEW_SYSTEM = """\
You review ONE tool call an autonomous agent is about to make with no human
watching. The tool is marked CRITICAL: it moves money, changes credentials
or the agent's own code, or cannot easily be undone.

Given the task and the recent steps, decide whether this exact call is
warranted now. Decline only for a concrete reason: it does not serve the
task, the arguments look wrong (amount, recipient, target, path), it
repeats something already done, or a safer step should come first.

Return ONLY a JSON object:
{
  "proceed": true | false,
  "expected_outcome": "<what this call should do, concretely>",
  "check": "<how the agent should confirm it worked>",
  "objection": "<if proceed is false: the specific problem>"
}"""


@dataclass
class ActionReview:
    proceed: bool
    expected_outcome: str = ""
    check: str = ""
    objection: str = ""
    cost: float = 0.0


async def review_action(
    router: Any,
    *,
    task: str,
    tool_name: str,
    args: dict[str, Any],
    recent: str,
    effort: str = "",
) -> ActionReview | None:
    """Review a CRITICAL call before it runs unattended. None = no verdict."""
    try:
        args_text = json.dumps(args, default=str)[:1500]
    except Exception:
        args_text = str(args)[:1500]
    user = (
        f"TASK: {task[:1500]}\n\nRECENT STEPS:\n{recent[:2500]}\n\n"
        f"CALL ABOUT TO RUN: {tool_name}({args_text})"
    )
    data, _reasoning, cost = await _ask(
        router, _REVIEW_SYSTEM, user, effort=effort, max_tokens=500, timeout=60.0
    )
    if not isinstance(data, dict) or "proceed" not in data:
        return None
    return ActionReview(
        proceed=bool(data.get("proceed")),
        expected_outcome=str(data.get("expected_outcome") or "").strip()[:400],
        check=str(data.get("check") or "").strip()[:300],
        objection=str(data.get("objection") or "").strip()[:400],
        cost=cost,
    )
