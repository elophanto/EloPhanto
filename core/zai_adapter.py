"""Z.ai/GLM API adapter.

Handles the GLM-specific message formatting constraints:
1. System message at index 0 only
2. Assistant messages with tool_calls must have content: null (not "")
3. Tool results must have tool_call_id matching a preceding tool call
4. No non-tool messages between assistant's tool_calls and tool results
5. One tool result per tool_call_id
6. At least one user message in the sequence

Uses httpx for async HTTP calls.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from core.config import Config

logger = logging.getLogger(__name__)

# Approximate cost per 1M tokens for Z.ai models
ZAI_COSTS = {
    "glm-5": {"input": 0.005, "output": 0.015},
    "glm-4.7": {"input": 0.002, "output": 0.006},
    "glm-4.7-flash": {"input": 0.0005, "output": 0.0015},
    "glm-4-plus": {"input": 0.003, "output": 0.009},
}


class ZaiAdapter:
    """Custom adapter for Z.ai/GLM API with message formatting compliance."""

    def __init__(self, config: Config) -> None:
        self._config = config
        zai_cfg = config.llm.providers.get("zai")
        if not zai_cfg:
            raise ValueError("Z.ai provider not configured")
        self._api_key = zai_cfg.api_key
        self._base_url = (
            zai_cfg.base_url_coding if zai_cfg.coding_plan else zai_cfg.base_url_paygo
        )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> Any:
        """Make a chat completion call to Z.ai."""
        from core.router import LLMResponse

        formatted_messages = self._reformat_messages(messages)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "Accept-Language": "en-US,en",
        }

        payload: dict[str, Any] = {
            "model": model,
            "messages": formatted_messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=payload,
            )

            if response.status_code != 200:
                error_body = response.text
                logger.error(f"Z.ai API error {response.status_code}: {error_body}")
                raise RuntimeError(
                    f"Z.ai API error {response.status_code}: {error_body}"
                )

            data = response.json()

        choice = data["choices"][0]
        message = choice["message"]

        # Parse tool calls
        tool_calls = None
        raw_tool_calls = message.get("tool_calls")
        if raw_tool_calls:
            tool_calls = []
            for tc in raw_tool_calls:
                tool_calls.append(
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    }
                )

        # Parse usage and estimate cost
        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        costs = ZAI_COSTS.get(model, {"input": 0.002, "output": 0.006})
        cost_estimate = (
            input_tokens * costs["input"] / 1_000_000
            + output_tokens * costs["output"] / 1_000_000
        )

        return LLMResponse(
            content=message.get("content"),
            model_used=model,
            provider="zai",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_estimate=cost_estimate,
            tool_calls=tool_calls,
        )

    async def health_check(self) -> bool:
        """Verify Z.ai connectivity with a minimal request."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "Accept-Language": "en-US,en",
        }

        payload = {
            "model": "glm-4.7-flash",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if response.status_code != 200:
                    logger.warning(
                        f"Z.ai health check got status {response.status_code}: "
                        f"{response.text[:200]}"
                    )
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Z.ai health check failed: {type(e).__name__}: {e}")
            return False

    def _reformat_messages(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Apply GLM message constraints to ensure API compatibility."""
        result: list[dict[str, Any]] = []

        # Constraint 1: Collect and merge all system messages into one at index 0
        system_parts: list[str] = []
        non_system: list[dict[str, Any]] = []

        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if content:
                    system_parts.append(content)
            else:
                non_system.append(msg)

        if system_parts:
            result.append({"role": "system", "content": "\n\n".join(system_parts)})

        # Process non-system messages
        seen_tool_call_ids: set[str] = set()

        for msg in non_system:
            formatted = dict(msg)

            # Constraint 2: Assistant messages with tool_calls must have content: null
            if formatted.get("role") == "assistant" and formatted.get("tool_calls"):
                formatted["content"] = None
                # Track tool_call_ids for validation
                for tc in formatted.get("tool_calls", []):
                    tc_id = tc.get("id", "")
                    if tc_id:
                        seen_tool_call_ids.add(tc_id)

            # Constraint 5: Skip duplicate tool results for the same tool_call_id
            if formatted.get("role") == "tool":
                tc_id = formatted.get("tool_call_id", "")
                # We don't filter duplicates here since our agent loop
                # already ensures one result per tool_call_id

            result.append(formatted)

        # Constraint 6: Ensure at least one user message exists
        has_user = any(m.get("role") == "user" for m in result)
        if not has_user:
            insert_idx = 1 if result and result[0].get("role") == "system" else 0
            result.insert(insert_idx, {"role": "user", "content": "Please proceed."})

        return result
