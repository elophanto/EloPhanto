"""Autonomy health — what unattended work did, and where it is stuck.

Every stall the goal loop has had was found the same way: a person read a
multi-hour log. This digest computes the same signals from the database —
the run ledger, checkpoints, goal usage and task memory — so they reach the
operator as a morning glance: `elophanto goals health`, the
``autonomy_health`` tool, and a daily broadcast from the goal runner.
See docs/94-LONG-RUN-AUTONOMY-REVIEW.md §5.7.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

_STOP_RE = re.compile(r"^Stopped \(([^)]*)\)")


def _since(hours: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()


def _classify_failure(text: str) -> str:
    t = text.lower()
    if t.startswith("final verification"):
        return "final verification: not met"
    if "receipt gate" in t or "receipt_gate" in t:
        return "receipt gate"
    if "verification" in t or "panel review" in t:
        return "checkpoint check"
    if "budget" in t and "ran out" in t:
        return "time budget"
    if t.startswith("error"):
        return "runner error"
    return "other"


def _stop_kind(summary: str) -> str:
    m = _STOP_RE.match(summary or "")
    if not m:
        return "unknown"
    reason = m.group(1)
    for key in (
        "preempted",
        "time limit",
        "consecutive errors",
        "loop detected",
        "repeating",
        "LLM repeating",
        "budget",
        "STOP",
        "safety limit",
    ):
        if key.lower() in reason.lower():
            return key
    return reason[:40]


async def collect(
    db: Any, *, hours: float = 24.0, runner: Any = None
) -> dict[str, Any]:
    """Gather the digest's numbers. Never raises for a missing table."""
    since = _since(hours)
    report: dict[str, Any] = {
        "hours": hours,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    async def rows(sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
        try:
            return list(await db.execute(sql, params) or [])
        except Exception:
            return []

    goals = await rows("SELECT goal_id, goal, status, context_summary FROM goals")
    report["goals_by_status"] = dict(Counter(g["status"] for g in goals))

    stalled: list[str] = []
    stalled_ids: set[str] = set()
    paused: list[str] = []
    for g in goals:
        if g["status"] == "active":
            pending = await rows(
                "SELECT COUNT(*) AS c FROM goal_checkpoints "
                "WHERE goal_id = ? AND status IN ('pending', 'active')",
                (g["goal_id"],),
            )
            if not pending or int(pending[0]["c"]) == 0:
                stalled.append(f"{g['goal_id']} {g['goal'][:60]}")
                stalled_ids.add(g["goal_id"])
        elif g["status"] in ("paused", "budget_paused", "awaiting_approval"):
            first = (g["context_summary"] or "").split("\n", 1)[0][:140]
            tag = "" if first.startswith(f"[{g['status']}]") else f"[{g['status']}] "
            paused.append(f"{g['goal_id']} {tag}{first}")
    report["active_without_work"] = stalled
    report["paused"] = paused[:10]

    running = getattr(runner, "current_goal_id", None) if runner is not None else None
    report["runner"] = running or ("idle" if runner is not None else "unknown")
    report["active_goals_waiting"] = [
        g["goal_id"]
        for g in goals
        if g["status"] == "active" and g["goal_id"] not in stalled_ids and g["goal_id"] != running
    ]

    ledger = await rows(
        "SELECT kind, content, thread_id, checkpoint_order FROM run_ledger WHERE created_at >= ?",
        (since,),
    )
    failures = [r for r in ledger if r["kind"] == "failure"]
    report["failures"] = dict(
        Counter(_classify_failure(r["content"]) for r in failures)
    )
    repeat = Counter((r["thread_id"], r["checkpoint_order"]) for r in failures)
    report["repeated_failures"] = [
        f"{gid} checkpoint {order}: {n} failures"
        for (gid, order), n in repeat.items()
        if n >= 3
    ]
    handoffs = [r for r in ledger if r["kind"] == "handoff"]
    report["interruptions"] = dict(
        Counter(
            (re.match(r"^\[([^\]]+)\]", r["content"]) or [None, "unknown"])[1]
            for r in handoffs
        )
    )
    report["plans_made"] = sum(1 for r in ledger if r["kind"] == "plan")
    report["automatic_recoveries"] = sum(
        1
        for r in ledger
        if r["kind"] == "decision" and r["content"].startswith("Automatic recovery")
    )
    report["final_verifications_met"] = sum(
        1
        for r in ledger
        if r["kind"] == "decision"
        and r["content"].startswith("Final verification: met")
    )

    done = await rows(
        "SELECT COUNT(*) AS c FROM goal_checkpoints WHERE status = 'completed' AND completed_at >= ?",
        (since,),
    )
    report["checkpoints_completed"] = int(done[0]["c"]) if done else 0

    memory = await rows(
        "SELECT outcome, task_summary FROM memory WHERE created_at >= ?", (since,)
    )
    report["runs_by_outcome"] = dict(Counter(m["outcome"] for m in memory))
    report["stops_by_reason"] = dict(
        Counter(
            _stop_kind(m["task_summary"]) for m in memory if m["outcome"] != "completed"
        )
    )

    day = datetime.now(UTC).strftime("%Y-%m-%d")
    usage = await rows(
        "SELECT SUM(cost_usd) AS c, SUM(seconds) AS s FROM goal_usage WHERE day = ?",
        (day,),
    )
    report["goal_spend_today_usd"] = round(
        float((usage[0]["c"] if usage else 0) or 0), 4
    )
    report["goal_work_seconds_today"] = int(float((usage[0]["s"] if usage else 0) or 0))

    # Plans as predictions, and the lessons' record (docs/95 Phases C, D).
    outcomes = await rows(
        "SELECT attempt, passed, surprise FROM plan_outcomes WHERE created_at >= ?", (since,)
    )
    first = [o for o in outcomes if int(o["attempt"]) == 1]
    report["plans_scored"] = len(outcomes)
    report["first_attempt_passed"] = sum(int(o["passed"]) for o in first)
    report["first_attempts"] = len(first)
    report["surprises"] = sum(int(o["surprise"]) for o in outcomes)
    lessons = await rows("SELECT status, COUNT(*) AS n FROM lesson_stats GROUP BY status")
    report["lessons_by_status"] = {str(r["status"]): int(r["n"]) for r in lessons}

    # The benchmark (docs/95 Phase E): the latest score and the one before.
    report["bench"] = [
        {k: r[k] for k in ("score", "passed", "cases", "fingerprint", "created_at")}
        for r in await rows(
            "SELECT score, passed, cases, fingerprint, created_at FROM bench_runs "
            "ORDER BY id DESC LIMIT 2"
        )
    ]
    return report


def alerts(report: dict[str, Any]) -> list[str]:
    """The lines that need the operator."""
    out: list[str] = []
    for g in report.get("active_without_work", []):
        out.append(f"active with nothing to run: {g}")
    for r in report.get("repeated_failures", []):
        out.append(f"failing repeatedly — {r}")
    if report.get("runner") == "idle" and report.get("active_goals_waiting"):
        out.append(
            f"{len(report['active_goals_waiting'])} active goal(s) waiting while the runner is idle"
        )
    if report.get("failures", {}).get("final verification: not met"):
        out.append("a goal failed its final verification — see its ledger")
    for p in report.get("paused", []):
        if "awaiting_approval" in p:
            out.append(f"waiting for your approval: {p}")
    return out


def render(report: dict[str, Any]) -> str:
    """Plain-text digest."""
    lines = [f"Autonomy health — last {int(report.get('hours', 24))}h"]
    problems = alerts(report)
    if problems:
        lines.append("NEEDS YOU:")
        lines += [f"  - {p}" for p in problems]
    else:
        lines.append("Nothing needs you.")
    gb = report.get("goals_by_status", {})
    lines.append(
        "Goals: " + (", ".join(f"{k} {v}" for k, v in sorted(gb.items())) or "none")
    )
    lines.append(f"Runner: {report.get('runner')}")
    lines.append(
        f"Checkpoints completed: {report.get('checkpoints_completed', 0)} · plans made: "
        f"{report.get('plans_made', 0)} · automatic recoveries: "
        f"{report.get('automatic_recoveries', 0)} · goals verified complete: "
        f"{report.get('final_verifications_met', 0)}"
    )
    if report.get("failures"):
        lines.append(
            "Failed attempts: "
            + ", ".join(f"{k} {v}" for k, v in report["failures"].items())
        )
    if report.get("interruptions"):
        lines.append(
            "Interrupted runs: "
            + ", ".join(f"{k} {v}" for k, v in report["interruptions"].items())
        )
    if report.get("stops_by_reason"):
        lines.append(
            "Unfinished runs by reason: "
            + ", ".join(f"{k} {v}" for k, v in report["stops_by_reason"].items())
        )
    if report.get("plans_scored"):
        first = int(report.get("first_attempts", 0))
        rate = (
            f"{report.get('first_attempt_passed', 0)}/{first} first attempts passed"
            if first
            else "no first attempts"
        )
        lines.append(
            f"Plans scored: {report['plans_scored']} · {rate} · surprises "
            f"(failures no plan foresaw): {report.get('surprises', 0)}"
        )
    lessons = report.get("lessons_by_status") or {}
    if lessons:
        lines.append(
            "Lessons with a record: "
            + ", ".join(f"{k} {v}" for k, v in sorted(lessons.items()))
        )
    bench = report.get("bench") or []
    if bench:
        latest = bench[0]
        line = (
            f"Benchmark: {latest['passed']}/{latest['cases']} "
            f"({float(latest['score']):.0%}, {latest['fingerprint']})"
        )
        if len(bench) > 1:
            delta = float(latest["score"]) - float(bench[1]["score"])
            line += f" · {delta:+.0%} vs previous"
            if bench[1]["fingerprint"] != latest["fingerprint"]:
                line += " (setup changed)"
        lines.append(line)
    lines.append(
        f"Goal spend today: ${report.get('goal_spend_today_usd', 0):.2f} · work time: "
        f"{report.get('goal_work_seconds_today', 0) // 60} min"
    )
    for p in report.get("paused", []):
        if "awaiting_approval" not in p:
            lines.append(f"Paused: {p}")
    return "\n".join(lines)
