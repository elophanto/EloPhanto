"""Shared kill-switch primitives — writes/clears the data/STOP
sentinel and optionally cancels goals + disables schedules.

Used by:
- ``cli/stop_cmd.py``       — operator CLI
- ``core/gateway.py``       — slash-command intercept in chat
- ``tools/system/stop_tool.py``  — LLM-callable agent_stop /
  agent_resume tools

The single source of truth for "what does it mean to STOP" lives
here so the three call sites can't drift. Pure side-effect
functions; the callers handle their own UI / response shapes.

The sentinel file is polled by:
- ``Agent._run_with_history`` (between rounds)
- ``AutonomousMind._run_loop`` (each wakeup)
- ``TaskScheduler._run_one`` (before dispatch)

Halts are at the next safe checkpoint, NOT mid-tool-call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_SENTINEL_BODY = "Created by stop primitive. Remove to resume.\n"


def stop_file_path(data_dir: Path) -> Path:
    """``<data_dir>/STOP``. Caller must ensure ``data_dir`` exists."""
    return data_dir / "STOP"


@dataclass(slots=True, frozen=True)
class StopResult:
    sentinel_path: str
    already_stopped: bool
    cancelled_goals: int = 0
    disabled_schedules: int = 0


@dataclass(slots=True, frozen=True)
class ResumeResult:
    sentinel_path: str
    was_stopped: bool  # False when no sentinel existed


def write_sentinel(data_dir: Path) -> StopResult:
    """Create the STOP sentinel if not already present. Idempotent."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = stop_file_path(data_dir)
    if path.exists():
        return StopResult(sentinel_path=str(path), already_stopped=True)
    path.write_text(_SENTINEL_BODY, encoding="utf-8")
    return StopResult(sentinel_path=str(path), already_stopped=False)


def clear_sentinel(data_dir: Path) -> ResumeResult:
    """Remove the STOP sentinel if present. Idempotent."""
    path = stop_file_path(data_dir)
    if not path.exists():
        return ResumeResult(sentinel_path=str(path), was_stopped=False)
    path.unlink()
    return ResumeResult(sentinel_path=str(path), was_stopped=True)


def is_stopped(data_dir: Path) -> bool:
    return stop_file_path(data_dir).exists()


async def cancel_active_goals(db: Any) -> int:
    """Flip every active/planning goal to cancelled. Returns count.

    ``db`` is a ``core.database.Database`` instance. Kept ``Any`` to
    avoid the import cycle (database.py is core, kill_switch is core).

    Intentionally **global** — cancels goals across every company, not
    just the active one. The kill switch is a panic-stop; an operator
    pulling it wants everything halted, not "only this tenant". Same
    semantics as ``GoalManager.delete_all_goals``. Operator confirmed
    2026-06-18 during the Tier 2 audit pass. Do NOT add company_id
    scoping here without an explicit product decision to change that
    behavior — the global sweep is load-bearing.
    """
    rows = await db.execute(
        "SELECT goal_id FROM goals WHERE status IN ('active', 'planning')"
    )
    if not rows:
        return 0
    now = datetime.now(UTC).isoformat()
    for r in rows:
        await db.execute_insert(
            "UPDATE goals SET status='cancelled', updated_at=? WHERE goal_id=?",
            (now, r["goal_id"]),
        )
    return len(rows)


async def disable_enabled_schedules(db: Any) -> int:
    """Disable every enabled cron schedule. Returns count."""
    rows = await db.execute("SELECT id FROM scheduled_tasks WHERE enabled=1")
    if not rows:
        return 0
    for r in rows:
        await db.execute_insert(
            "UPDATE scheduled_tasks SET enabled=0 WHERE id=?", (r["id"],)
        )
    return len(rows)


async def hard_stop(
    *,
    data_dir: Path,
    db: Any = None,
    cancel_goals: bool = False,
    cancel_schedules: bool = False,
) -> StopResult:
    """Write the sentinel + optionally cancel goals / disable schedules.

    Returns the merged StopResult so the caller can render a single
    confirmation line without re-running the queries.
    """
    base = write_sentinel(data_dir)
    cg = 0
    cs = 0
    if db is not None:
        try:
            if cancel_goals:
                cg = await cancel_active_goals(db)
            if cancel_schedules:
                cs = await disable_enabled_schedules(db)
        except Exception as e:
            logger.warning("kill_switch DB cancels failed: %s", e)
    return StopResult(
        sentinel_path=base.sentinel_path,
        already_stopped=base.already_stopped,
        cancelled_goals=cg,
        disabled_schedules=cs,
    )


def resolve_data_dir(config: Any) -> Path:
    """Resolve ``data_dir`` from a loaded config. Centralized so the
    CLI + gateway + tool agree."""
    db_path = Path(config.database.db_path)
    if not db_path.is_absolute():
        db_path = config.project_root / db_path
    return db_path.parent


# ── Slash-command parsing (used by gateway + CLI chat intercept) ────


_STOP_TOKENS: frozenset[str] = frozenset(
    {"/stop", "stop", "halt", "kill", "pause", "/halt", "/kill", "/pause"}
)
_RESUME_TOKENS: frozenset[str] = frozenset(
    {"/resume", "resume", "go", "continue", "/go", "/continue", "unpause"}
)


def parse_kill_command(text: str) -> tuple[str | None, dict[str, bool]]:
    """Parse a chat message for a kill-switch command.

    Returns ``(verb, flags)`` where ``verb`` ∈ {"stop", "resume", None}.
    ``flags`` contains booleans for ``cancel_goals``, ``cancel_schedules``,
    ``hard``.

    Recognized as a stop command (case-insensitive, leading/trailing
    whitespace ignored, optional leading slash):

      stop                       → soft stop
      /stop --hard               → stop + cancel goals + disable schedules
      stop --cancel-goals
      stop --cancel-schedules
      halt / kill / pause        → soft stop synonyms

    Recognized as resume:

      resume / /resume / go / continue / unpause

    Anything else returns ``(None, {})``.
    """
    if not isinstance(text, str):
        return None, {}
    raw = text.strip()
    if not raw:
        return None, {}
    parts = raw.split()
    head = parts[0].lower()
    rest = [p.lower() for p in parts[1:]]
    flags: dict[str, bool] = {
        "cancel_goals": False,
        "cancel_schedules": False,
        "hard": False,
    }
    if head in _STOP_TOKENS:
        # Only honor "stop" alone or with flags — "stop talking" is NOT a kill.
        # Allow flags only; anything else (free-form follow-up) bails out.
        for token in rest:
            if token in ("--hard", "-hard", "hard"):
                flags["hard"] = True
                flags["cancel_goals"] = True
                flags["cancel_schedules"] = True
            elif token in ("--cancel-goals", "-cancel-goals", "cancel-goals"):
                flags["cancel_goals"] = True
            elif token in (
                "--cancel-schedules",
                "-cancel-schedules",
                "cancel-schedules",
            ):
                flags["cancel_schedules"] = True
            else:
                # Free-form follow-up — operator probably wasn't asking
                # for a kill. Bail out so "stop sending those emails" or
                # "pause the X loop" don't hard-stop everything.
                return None, {}
        return "stop", flags
    if head in _RESUME_TOKENS and not rest:
        return "resume", flags
    return None, flags
