"""goal_note — record working state for the goal being executed.

Writes to the run ledger (core/run_ledger.py). Everything noted here is
shown to every later checkpoint of the goal — after a retry, a preemption
or a restart — so it is the place for what the next run must not have to
rediscover: what exists, what is known, what was decided and why, what is
still open.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

_MODEL_KINDS = ("artifact", "fact", "decision", "question", "plan", "failure")


class GoalNoteTool(BaseTool):
    """Append a note to the current goal's run ledger."""

    def __init__(self) -> None:
        self._goal_manager: Any = None
        self._ledger: Any = None

    @property
    def group(self) -> str:
        return "goals"

    @property
    def name(self) -> str:
        return "goal_note"

    @property
    def description(self) -> str:
        return (
            "Record working state for the goal you are executing, so later "
            "checkpoints, retries and restarts start from it instead of "
            "rediscovering it. kind: artifact (something you produced; ref = "
            "path/URL/id), fact (something you established; ref = its source), "
            "decision (what you chose, why, what you rejected), question (an "
            "open question or blocker), plan (how you will do this checkpoint "
            "and how you will verify it), failure (an approach that did not "
            "work and why). Close a question with close_question_id."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(_MODEL_KINDS)},
                "content": {"type": "string", "description": "The note itself."},
                "ref": {
                    "type": "string",
                    "description": "Path, URL or id the note is about (artifacts, facts).",
                },
                "goal_id": {
                    "type": "string",
                    "description": "Only needed outside a goal checkpoint.",
                },
                "close_question_id": {
                    "type": "integer",
                    "description": "Ledger id of an open question to mark closed.",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._ledger is None:
            return ToolResult(success=False, error="Run ledger not initialized")

        from core.execution_context import current_context

        goal_id = str(params.get("goal_id") or current_context().goal_id or "").strip()
        if not goal_id:
            return ToolResult(
                success=False,
                error=(
                    "No goal in scope. goal_note records state for a goal "
                    "checkpoint; pass goal_id when calling it from elsewhere."
                ),
            )

        close_id = params.get("close_question_id")
        if close_id:
            ok = await self._ledger.close_question(int(close_id))
            return ToolResult(success=ok, data={"closed": int(close_id)})

        kind = str(params.get("kind") or "").strip()
        content = str(params.get("content") or "").strip()
        if kind not in _MODEL_KINDS:
            return ToolResult(
                success=False, error=f"kind must be one of {_MODEL_KINDS}"
            )
        if not content:
            return ToolResult(success=False, error="content is required")

        order: int | None = None
        attempt = 0
        if self._goal_manager is not None:
            try:
                rows = await self._goal_manager._db.execute(
                    "SELECT checkpoint_order, attempts FROM goal_checkpoints "
                    "WHERE goal_id = ? AND status = 'active' "
                    "ORDER BY checkpoint_order LIMIT 1",
                    (goal_id,),
                )
                if rows:
                    order = int(rows[0]["checkpoint_order"])
                    attempt = int(rows[0]["attempts"] or 0)
            except Exception:
                pass

        entry_id = await self._ledger.add(
            goal_id,
            kind,
            content,
            ref=str(params.get("ref") or ""),
            checkpoint_order=order,
            attempt=attempt,
            source="model",
        )
        if not entry_id:
            return ToolResult(success=False, error="Could not write the note")
        return ToolResult(
            success=True,
            data={
                "id": entry_id,
                "goal_id": goal_id,
                "kind": kind,
                "checkpoint": order,
            },
        )
