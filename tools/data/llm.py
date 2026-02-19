"""LLM call tool — allows the agent to make sub-LLM-calls through the router."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class LLMCallTool(BaseTool):
    """Makes LLM inference calls through the router."""

    @property
    def name(self) -> str:
        return "llm_call"

    @property
    def description(self) -> str:
        return (
            "Makes an LLM inference call through the router. Use this when you need "
            "to think deeply about a subtask, generate text, summarize content, "
            "analyze data, or perform any natural language processing. The router "
            "selects the best model based on the task type."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The prompt or question to send to the LLM",
                },
                "task_type": {
                    "type": "string",
                    "enum": ["planning", "coding", "analysis", "simple"],
                    "description": "Type of task (affects model selection). Default: simple",
                },
                "system_prompt": {
                    "type": "string",
                    "description": "Optional system prompt for the LLM",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Maximum tokens in response",
                },
                "temperature": {
                    "type": "number",
                    "description": "Sampling temperature (0.0 to 1.0)",
                },
            },
            "required": ["prompt"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        # The router is injected by the agent at runtime via the _router attribute
        router = getattr(self, "_router", None)
        if router is None:
            return ToolResult(
                success=False,
                error="LLM router not available. The agent must set _router on this tool.",
            )

        prompt = params["prompt"]
        task_type = params.get("task_type", "simple")
        system_prompt = params.get("system_prompt")
        max_tokens = params.get("max_tokens")
        temperature = params.get("temperature", 0.7)

        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await router.complete(
                messages=messages,
                task_type=task_type,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            return ToolResult(
                success=True,
                data={
                    "response": response.content,
                    "model_used": response.model_used,
                    "tokens_used": {
                        "input": response.input_tokens,
                        "output": response.output_tokens,
                    },
                    "cost_estimate": response.cost_estimate,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"LLM call failed: {e}")
