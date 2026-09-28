"""Soak harness for long goal runs (docs/94 §9, §5.7).

Every stall the goal loop has had was found by a person reading a
multi-hour production log. This harness reproduces a long run in seconds:
a real ``Agent`` + ``GoalManager`` + ``GoalRunner`` + SQLite, driven by a
scripted model instead of an LLM, with the disturbances production brings —
operator chat preempting checkpoints, and the process dying mid-checkpoint.

Assertions live in the tests; the harness only records what happened.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.router import LLMResponse
from tools.base import BaseTool, PermissionLevel, ToolResult

CHECKPOINT_MARKER = "You are autonomously executing a goal checkpoint."


def _resp(
    content: str | None = None, tool_calls: list[dict[str, Any]] | None = None
) -> LLMResponse:
    return LLMResponse(
        content=content,
        model_used="scripted",
        provider="scripted",
        input_tokens=1,
        output_tokens=1,
        cost_estimate=0.0,
        tool_calls=tool_calls,
    )


class SoakReportTool(BaseTool):
    """Stands in for real work: takes a little time, produces a file path."""

    def __init__(self, out_dir: Path, delay_s: float = 0.03) -> None:
        self._out_dir = out_dir
        self._delay_s = delay_s
        self.calls: list[dict[str, Any]] = []
        # Set while a call is executing — a checkpoint is holding the loop
        # right now, so a disturbance injected then is guaranteed to land.
        self.in_flight = asyncio.Event()

    @property
    def name(self) -> str:
        return "soak_write_report"

    @property
    def group(self) -> str:
        return "system"

    @property
    def description(self) -> str:
        return "Soak harness work unit."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"path": {"type": "string"}}}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        self.in_flight.set()
        try:
            await asyncio.sleep(self._delay_s)
        finally:
            self.in_flight.clear()
        self.calls.append(dict(params))
        return ToolResult(
            success=True, data={"path": params.get("path", ""), "status": "written"}
        )


@dataclass
class ScriptedModel:
    """Answers the router the way a well-behaved model would.

    Checkpoint runs make ``work_steps`` tool calls, then finish. It also
    records every checkpoint system prompt's ``<goal_id>`` so a test can
    check each run saw its own goal's plan.
    """

    out_dir: Path
    n_checkpoints: int = 6
    work_steps: int = 3
    goal_ids_seen: list[tuple[str, str]] = field(default_factory=list)
    handoff_requests: int = 0
    chats: int = 0

    async def complete(self, messages: list[dict[str, Any]], **kw: Any) -> LLMResponse:
        task_type = kw.get("task_type", "planning")
        system = next((m["content"] for m in messages if m.get("role") == "system"), "")
        first_user = next(
            (m.get("content") for m in messages if m.get("role") == "user"), ""
        )
        first_user = first_user if isinstance(first_user, str) else ""

        if task_type != "planning":
            return self._simple(system, messages)

        if CHECKPOINT_MARKER not in first_user:
            self.chats += 1
            return _resp("All good — the goal is running in the background.")

        order_m = re.search(r"CURRENT CHECKPOINT \((\d+) of", first_user)
        order = int(order_m.group(1)) if order_m else 0
        in_prompt = re.search(r"<goal_id>([^<]+)</goal_id>", system or "")
        self.goal_ids_seen.append((str(order), in_prompt.group(1) if in_prompt else ""))

        done = sum(1 for m in messages if m.get("role") == "tool")
        if done < self.work_steps:
            path = str(self.out_dir / f"cp{order}_part{done + 1}.md")
            return _resp(
                None,
                [
                    {
                        "id": f"call_{order}_{done}",
                        "type": "function",
                        "function": {
                            "name": "soak_write_report",
                            "arguments": json.dumps({"path": path}),
                        },
                    }
                ],
            )
        return _resp(
            f"Checkpoint {order} finished: wrote {self.work_steps} report parts."
        )

    def _simple(self, system: str, messages: list[dict[str, Any]]) -> LLMResponse:
        body = " ".join(str(m.get("content") or "") for m in messages)
        if "goal_decomposition" in (system or ""):
            plan = {
                "kill_criterion": "",
                "checkpoints": [
                    {
                        "order": i,
                        "title": f"Report part {i}",
                        "description": "Write the report part with soak_write_report.",
                        "success_criteria": "report part written",
                        "stage": "build",
                    }
                    for i in range(1, self.n_checkpoints + 1)
                ],
            }
            return _resp(json.dumps(plan))
        if "goal_evaluation" in (system or ""):
            return _resp(
                json.dumps({"on_track": True, "revision_needed": False, "reason": "ok"})
            )
        if "Write a handoff" in body:
            self.handoff_requests += 1
            return _resp("DONE: some parts. IN PROGRESS: next part. NEXT: write it.")
        return _resp("Summary of progress.")
