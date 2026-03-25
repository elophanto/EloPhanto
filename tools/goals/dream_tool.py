"""goal_dream — Structured goal ideation: discover, generate, critique, recommend."""

from __future__ import annotations

import json
import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_DREAM_SYSTEM = """\
You are a strategic planning advisor for an autonomous AI agent.
Your job is to generate high-quality goal candidates based on the agent's
current capabilities, identity, and context.

Follow this exact process:

STEP 1 — DISCOVER: Analyze the capabilities and context provided.
STEP 2 — GENERATE: Propose 3-5 specific, measurable, achievable goals.
  Prioritize goals that: generate revenue, grow audience, build compounding
  value, or unlock new capabilities.
STEP 3 — CRITIQUE: For each goal, evaluate:
  - Feasibility (0-10): Can the agent do this with its current tools?
  - Value (0-10): Revenue potential, audience growth, or capability gain?
  - Cost (low/medium/high): LLM calls and budget required?
  - Risk: What could go wrong?
STEP 4 — RECOMMEND: Pick the single best goal and explain why.

Return ONLY a JSON object with this structure:
{
  "candidates": [
    {
      "title": "Short goal title",
      "description": "What to achieve, specifically",
      "feasibility": 8,
      "value": 9,
      "cost": "medium",
      "risk": "Brief risk assessment",
      "reasoning": "Why this goal"
    }
  ],
  "recommendation": {
    "index": 0,
    "reasoning": "Why this is the best choice right now"
  }
}
"""


class GoalDreamTool(BaseTool):
    """Structured goal ideation — discover capabilities, generate candidates, critique, recommend."""

    def __init__(self) -> None:
        self._router: Any = None
        self._registry: Any = None
        self._identity_manager: Any = None
        self._goal_manager: Any = None

    @property
    def group(self) -> str:
        return "goals"

    @property
    def name(self) -> str:
        return "goal_dream"

    @property
    def description(self) -> str:
        return (
            "Dream up new goals. Reviews agent capabilities, identity, and "
            "current state, then generates 3-5 goal candidates with feasibility/ "
            "value/cost/risk analysis. Returns a structured recommendation. "
            "Use when the user says 'dream for me', 'suggest goals', or "
            "'what should I work on'. Does NOT auto-create — returns candidates "
            "for the user to review and approve."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "description": (
                        "Optional focus area: 'revenue', 'growth', 'capability', "
                        "'content', or any custom focus. Default: balanced."
                    ),
                },
                "count": {
                    "type": "integer",
                    "description": "Number of candidates to generate (3-5, default: 5).",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._router:
            return ToolResult(success=False, error="LLM router not available.")

        focus = params.get("focus", "balanced")
        count = min(max(params.get("count", 5), 2), 7)

        # Build context about current capabilities
        context_parts: list[str] = []

        # Tool capabilities
        if self._registry:
            tools = self._registry.list_tool_summaries()
            tool_groups: dict[str, int] = {}
            for t in tools:
                # Group tools by their first word or known categories
                name = t["name"]
                if "_" in name:
                    prefix = name.split("_")[0]
                else:
                    prefix = name
                tool_groups[prefix] = tool_groups.get(prefix, 0) + 1
            context_parts.append(
                f"TOOLS ({len(tools)} total): "
                + ", ".join(f"{k}({v})" for k, v in sorted(tool_groups.items()))
            )

        # Identity
        if self._identity_manager:
            try:
                identity = await self._identity_manager.get_identity()
                if identity.purpose:
                    context_parts.append(f"PURPOSE: {identity.purpose}")
                if identity.capabilities:
                    context_parts.append(
                        f"CAPABILITIES: {', '.join(identity.capabilities[:10])}"
                    )
            except Exception:
                pass

        # Current goals
        if self._goal_manager:
            try:
                active = await self._goal_manager.list_goals(status="active", limit=5)
                if active:
                    context_parts.append(
                        "ACTIVE GOALS: " + "; ".join(f'"{g.goal}"' for g in active)
                    )
                completed = await self._goal_manager.list_goals(
                    status="completed", limit=5
                )
                if completed:
                    context_parts.append(
                        "RECENTLY COMPLETED: "
                        + "; ".join(f'"{g.goal}"' for g in completed)
                    )
            except Exception:
                pass

        context = "\n".join(context_parts) if context_parts else "(minimal context)"

        prompt = (
            f"Generate {count} goal candidates for this autonomous AI agent.\n"
            f"Focus area: {focus}\n\n"
            f"AGENT CONTEXT:\n{context}\n\n"
            "Remember: goals should be specific, measurable, and achievable "
            "with the tools listed above. Return ONLY the JSON."
        )

        try:
            response = await self._router.complete(
                messages=[
                    {"role": "system", "content": _DREAM_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                task_type="planning",
                temperature=0.7,
            )

            content = (response.content or "").strip()
            # Clean markdown wrappers
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            result = json.loads(content)
            candidates = result.get("candidates", [])
            recommendation = result.get("recommendation", {})

            return ToolResult(
                success=True,
                data={
                    "candidates": candidates,
                    "recommendation": recommendation,
                    "count": len(candidates),
                    "focus": focus,
                    "note": (
                        "These are suggestions — use goal_create to create "
                        "the one you want, or ask for a different focus."
                    ),
                },
            )

        except json.JSONDecodeError:
            # LLM returned non-JSON — return raw as analysis
            return ToolResult(
                success=True,
                data={
                    "raw_analysis": content[:3000] if content else "",
                    "note": "LLM returned free-form analysis instead of structured JSON.",
                },
            )
        except Exception as e:
            logger.error(f"Goal dream failed: {e}")
            return ToolResult(success=False, error=f"Dream failed: {e}")
