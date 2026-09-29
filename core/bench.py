"""A benchmark from the agent's own history (docs/95 Phase E).

"Smarter" needs a number. The goal runner keeps every checkpoint attempt's
tool calls and outputs (core/tool_traces.py). This module turns attempts that
passed every gate into **cases** and **replays** them:

  * the case holds what the attempt started from — the goal, the checkpoint,
    its success criteria and declared checks, and the run ledger as it stood
    when the attempt began — plus the recording of what its tools returned;
  * a replay runs the real prompt, the real planning step and the real model,
    but every tool call is answered from the recording by a task-local
    interceptor (core/run_hooks.py). **No real tool ever runs** — nothing is
    fetched, written, sent or paid for — and the run leaves no memory and
    teaches no lessons;
  * each case is scored by the same receipt gate production uses, and by the
    declared checks that read the trail (``tool_output``, ``artifact``).
    Checks that need the world — files on disk, live URLs — and panel
    judgement are not replayable and are skipped.

A run's score goes to ``bench_runs`` with a fingerprint of what produced it:
the model routing, the code revision, and the learned lessons and skills. A
change to any of them shows up as a number.

A replay answers a call with the recorded call of the same tool whose
parameters match best; a call the recording has no answer for gets an error
saying what the case recorded — the model can recover the way it would from
a failed tool, and the miss is counted.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPLAYABLE_CHECKS = ("tool_output", "artifact")


@dataclass
class BenchCase:
    id: str
    goal: str
    order: int
    total: int
    title: str
    stage: str
    description: str
    criteria: str
    verification: str
    ledger: str
    recording: list[dict[str, Any]] = field(default_factory=list)
    source: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> BenchCase:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), indent=2, default=str), encoding="utf-8"
        )


def cases_dir(config: Any) -> Path:
    raw = Path(
        getattr(getattr(config, "bench", None), "cases_dir", "") or "data/bench/cases"
    )
    return raw if raw.is_absolute() else Path(config.project_root) / raw


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


async def capture(
    db: Any, directory: Path, *, limit: int = 50, overwrite: bool = False
) -> list[Path]:
    """Write a case for each recent checkpoint attempt that passed every gate."""
    from core.run_ledger import RunLedger
    from core.tool_traces import attempt_trace

    attempts = await db.execute(
        "SELECT goal_id, checkpoint_order, attempt, MIN(created_at) AS started "
        "FROM tool_traces WHERE passed = 1 GROUP BY goal_id, checkpoint_order, attempt "
        "ORDER BY MAX(id) DESC LIMIT ?",
        (int(limit),),
    )
    written: list[Path] = []
    for a in attempts:
        goal_id, order = str(a["goal_id"]), int(a["checkpoint_order"])
        path = directory / f"{goal_id}-{order}.json"
        if path.exists() and not overwrite:
            continue
        goals = await db.execute("SELECT * FROM goals WHERE goal_id = ?", (goal_id,))
        cps = await db.execute(
            "SELECT * FROM goal_checkpoints WHERE goal_id = ? AND checkpoint_order = ?",
            (goal_id, order),
        )
        if not goals or not cps:
            continue
        goal, cp = dict(goals[0]), dict(cps[0])
        recording = await attempt_trace(
            db, goal_id=goal_id, checkpoint_order=order, attempt=int(a["attempt"])
        )
        if not recording:
            continue
        ledger = await RunLedger(db).render(
            goal_id, checkpoint_order=order, before=a["started"]
        )
        BenchCase(
            id=f"{goal_id}-{order}",
            goal=str(goal.get("goal") or ""),
            order=order,
            total=int(goal.get("total_checkpoints") or order),
            title=str(cp.get("title") or ""),
            stage=str(cp.get("stage") or "unknown"),
            description=str(cp.get("description") or ""),
            criteria=str(cp.get("success_criteria") or ""),
            verification=str(cp.get("verification") or ""),
            ledger=ledger,
            recording=recording,
            source={
                "goal_id": goal_id,
                "attempt": int(a["attempt"]),
                "started": a["started"],
                "captured": datetime.now(UTC).isoformat(),
            },
        ).save(path)
        written.append(path)
    return written


def load_cases(directory: Path, limit: int | None = None) -> list[BenchCase]:
    cases = []
    for path in sorted(directory.glob("*.json")):
        try:
            cases.append(BenchCase.load(path))
        except Exception as e:
            logger.warning("bench case %s unreadable: %s", path.name, e)
    return cases[:limit] if limit else cases


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


def _similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    if a == b:
        return 2.0
    keys = set(a) | set(b)
    if not keys:
        return 1.0
    return sum(1 for k in keys if str(a.get(k)) == str(b.get(k))) / len(keys)


def _as_result(rec: dict[str, Any]) -> Any:
    from tools.base import ToolResult

    text = str(rec.get("output") or "")
    ok = (rec.get("status") or "ok") == "ok"
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        data = {"output": text, "truncated": True}
    if not isinstance(data, dict):
        data = {"output": data}
    success = bool(data.pop("success", ok)) and ok
    error = data.pop("error", None) or (rec.get("error") if not ok else None)
    # A screenshot path from the recording would be read and sent to a
    # vision model; the replay has no page to look at.
    data = {k: v for k, v in data.items() if "screenshot" not in k.lower()}
    return ToolResult(success=success, data=data, error=str(error) if error else None)


class Replay:
    """Answers tool calls from one recording. Never runs a tool."""

    def __init__(self, recording: list[dict[str, Any]]) -> None:
        self._calls = list(recording)
        self._used: set[int] = set()
        self.misses: list[str] = []

    async def __call__(self, tool: str, params: dict[str, Any]) -> Any:
        from tools.base import ToolResult

        params = params if isinstance(params, dict) else {}
        # An unused recording of this tool whose parameters match best; the
        # same call made again gets the same answer as before.
        best, best_score = None, -1.0
        for i, rec in enumerate(self._calls):
            if rec.get("tool") != tool:
                continue
            score = _similarity(params, rec.get("params") or {})
            if i in self._used:
                if score < 2.0:
                    continue
            else:
                score += 0.01
            if score > best_score:
                best, best_score = i, score
        if best is None:
            self.misses.append(tool)
            recorded = sorted({str(r.get("tool")) for r in self._calls})
            return ToolResult(
                success=False,
                error=(
                    f"replay: no recorded output for this {tool} call. The recording "
                    f"has: {', '.join(recorded)}"
                ),
            )
        self._used.add(best)
        return _as_result(self._calls[best])


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


async def score(
    case: BenchCase, trace: list[dict[str, Any]], response: Any
) -> tuple[bool, str]:
    """The production gates that a replay can honestly apply."""
    from core.checkpoint_receipt import verify_checkpoint_receipt
    from core.checkpoint_verify import parse_checks, verify_checkpoint
    from core.run_ledger import extract_artifacts

    stop = str(getattr(response, "stop_reason", "") or "")
    if stop and stop != "completed":
        return False, f"stopped: {stop}"
    content = str(getattr(response, "content", "") or "")
    verdict = verify_checkpoint_receipt(
        case.criteria, tool_trace=trace, assistant_summary=content[:500]
    )
    if not verdict.ok:
        return False, f"receipt gate: {verdict.reason}"
    checks = [
        c for c in parse_checks(case.verification) if c.get("type") in REPLAYABLE_CHECKS
    ]
    if checks:
        vres = await verify_checkpoint(
            checks,
            tool_trace=trace,
            artifact_refs=[ref for ref, _ in extract_artifacts(trace)],
            workspace="",
            router=None,
            criteria=case.criteria,
            result_text=content,
        )
        if not vres.ok:
            return False, f"verification: {vres.reason}"
    return True, verdict.reason


async def run_case(
    agent: Any, case: BenchCase, *, time_budget: float = 600.0
) -> dict[str, Any]:
    """Replay one case through the agent. Returns its result row."""
    from core.execution_context import TaskSource
    from core.goal_runner import _attach_tool_output, build_checkpoint_prompt
    from core.run_hooks import run_hooks

    router = agent._router
    tracker = getattr(router, "cost_tracker", None)
    cost_before = float(getattr(tracker, "daily_total", 0.0) or 0.0)
    started = time.monotonic()
    prompt = build_checkpoint_prompt(
        goal=case.goal,
        order=case.order,
        total=case.total,
        title=case.title,
        stage=case.stage,
        description=case.description,
        criteria=case.criteria,
        context="",
        ledger=case.ledger,
    )
    goals_cfg = getattr(agent._config, "goals", None)
    if getattr(goals_cfg, "deliberate", False):
        from core.deliberation import plan_checkpoint
        from core.plan_outcomes import render_offered

        lessons = ""
        try:
            lessons = render_offered(
                list(
                    await agent.recall_lesson_items(f"{case.title}. {case.description}")
                )
            )
        except Exception as e:
            logger.debug("bench lesson recall failed: %s", e)
        plan = await plan_checkpoint(
            router,
            goal=case.goal,
            order=case.order,
            total=case.total,
            title=case.title,
            description=case.description,
            criteria=case.criteria,
            stage=case.stage,
            ledger_text=case.ledger,
            attempt=1,
            effort=str(getattr(goals_cfg, "deliberation_effort", "") or ""),
            lessons=lessons,
        )
        if plan is not None:
            prompt += (
                "\nYOUR PLAN FOR THIS ATTEMPT (made before starting — follow "
                "it; if what you find contradicts it, record a decision with "
                "goal_note and adapt):\n" + plan.render() + "\n"
            )

    trace: list[dict[str, Any]] = []

    def _on_tool(name: str, params: dict[str, Any], error: str | None) -> None:
        trace.append(
            {
                "tool": name,
                "status": "error" if error else "ok",
                "error": error,
                "data": {k: str(v)[:200] for k, v in list((params or {}).items())[:8]},
                "params": params or {},
            }
        )

    def _on_result(name: str, params: dict[str, Any], result: Any) -> None:
        _attach_tool_output(trace, name, result)

    replay = Replay(case.recording)
    response: Any = None
    error = ""
    try:
        with run_hooks(
            on_tool_executed=_on_tool,
            on_tool_result=_on_result,
            tool_interceptor=replay,
            record_memory=False,
        ):
            response = await agent.submit_task(
                TaskSource.GOAL,
                prompt,
                time_budget_seconds=time_budget,
                isolated_history=True,
                memory_label=f"Benchmark case {case.id}",
            )
        passed, reason = await score(case, trace, response)
    except Exception as e:
        passed, reason, error = False, f"error: {e}", str(e)
    return {
        "id": case.id,
        "passed": passed,
        "reason": reason[:300],
        "steps": len(trace),
        "recorded_steps": len(case.recording),
        "misses": len(replay.misses),
        "stop_reason": str(
            getattr(response, "stop_reason", "") or ("error" if error else "")
        ),
        "cost_usd": round(
            float(getattr(tracker, "daily_total", 0.0) or 0.0) - cost_before, 6
        ),
        "seconds": round(time.monotonic() - started, 1),
    }


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def _git_revision(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _tree_digest(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for path in sorted(paths):
        try:
            h.update(f"{path.name}:{path.stat().st_size}".encode())
        except OSError:
            continue
    return h.hexdigest()[:12]


def fingerprint(config: Any) -> tuple[str, dict[str, Any]]:
    """What produced a score: routing, code revision, lessons and skills."""
    root = Path(config.project_root)
    routing = {}
    for name in ("planning", "deliberation"):
        r = config.llm.routing.get(name)
        if r is not None:
            routing[name] = {
                "provider": r.preferred_provider,
                "model": r.models.get(r.preferred_provider, ""),
                "effort": r.reasoning_effort,
            }
    detail = {
        "routing": routing,
        "judge_model": getattr(config.llm, "judge_model", ""),
        "revision": _git_revision(root),
        "learned_skills": _tree_digest(list(root.glob("skills/learned-*/SKILL.md"))),
        "lessons": _tree_digest(list((root / "knowledge" / "learned").glob("**/*.md"))),
    }
    program = root / "AGENT_PROGRAM.md"
    if program.exists():
        detail["program"] = hashlib.sha256(program.read_bytes()).hexdigest()[:12]
    digest = hashlib.sha256(json.dumps(detail, sort_keys=True).encode()).hexdigest()[
        :12
    ]
    return digest, detail


@dataclass
class BenchRun:
    fingerprint: str
    detail: dict[str, Any]
    results: list[dict[str, Any]]

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r["passed"])

    @property
    def score(self) -> float:
        return self.passed / len(self.results) if self.results else 0.0

    @property
    def mean_steps(self) -> float:
        return (
            sum(r["steps"] for r in self.results) / len(self.results)
            if self.results
            else 0.0
        )


async def run_bench(
    agent: Any,
    cases: list[BenchCase],
    *,
    db: Any = None,
    time_budget: float = 600.0,
) -> BenchRun:
    """Replay ``cases`` one after another and record the run."""
    fp, detail = fingerprint(agent._config)
    results = []
    for case in cases:
        result = await run_case(agent, case, time_budget=time_budget)
        logger.info(
            "[bench] %s: %s (%s)",
            case.id,
            "pass" if result["passed"] else "fail",
            result["reason"][:120],
        )
        results.append(result)
    run = BenchRun(fingerprint=fp, detail=detail, results=results)
    if db is not None and results:
        await db.execute_insert(
            "INSERT INTO bench_runs (fingerprint, fingerprint_detail, cases, passed, score, "
            "mean_steps, cost_usd, seconds, results, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fp,
                json.dumps(detail),
                len(results),
                run.passed,
                run.score,
                run.mean_steps,
                sum(r["cost_usd"] for r in results),
                sum(r["seconds"] for r in results),
                json.dumps(results),
                datetime.now(UTC).isoformat(),
            ),
        )
    return run


async def history(db: Any, limit: int = 10) -> list[dict[str, Any]]:
    rows = await db.execute(
        "SELECT id, fingerprint, cases, passed, score, mean_steps, cost_usd, created_at "
        "FROM bench_runs ORDER BY id DESC LIMIT ?",
        (int(limit),),
    )
    return [dict(r) for r in rows]
