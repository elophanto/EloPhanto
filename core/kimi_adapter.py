"""Kimi / Moonshot AI API adapter via Kilo Code Gateway.

OpenAI-compatible chat completions routed through the Kilo AI Gateway.
Supports Kimi K2.5 (native multimodal vision model).

Kilo Gateway docs: https://kilo.ai/docs/gateway
Base URL: https://api.kilo.ai/api/gateway
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from core.config import Config

logger = logging.getLogger(__name__)

# Approximate cost per 1M tokens (Kilo Gateway pricing)
# Keys use internal short names; mapped to gateway model IDs before API call.
KIMI_COSTS = {
    "kimi-k2.5": {"input": 0.45, "output": 2.20},
    "kimi-k2-thinking-turbo": {"input": 0.15, "output": 0.60},
}

# Map internal short model names → Kilo Gateway model IDs
KIMI_MODEL_MAP = {
    "kimi-k2.5": "moonshotai/kimi-k2.5",
    "kimi-k2-thinking-turbo": "moonshotai/kimi-k2.5",  # gateway only exposes k2.5
}


class KimiAdapter:
    """Custom adapter for Kimi via Kilo Code AI Gateway.

    The gateway is OpenAI-compatible so no special message reformatting
    is needed — unlike Z.ai/GLM which has 6 message constraints.
    """

    DEFAULT_BASE_URL = "https://api.kilo.ai/api/gateway"

    def __init__(self, config: Config) -> None:
        self._config = config
        kimi_cfg = config.llm.providers.get("kimi")
        if not kimi_cfg:
            raise ValueError("Kimi provider not configured")
        self._api_key = kimi_cfg.api_key
        self._base_url = kimi_cfg.base_url or self.DEFAULT_BASE_URL
        self._default_model = kimi_cfg.default_model or "kimi-k2.5"
        # Persistent HTTP client — reuses TCP connections across calls
        self._client = httpx.AsyncClient(timeout=180.0)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> Any:
        """Make a chat completion call to Kimi via Kilo Gateway."""
        from core.router import LLMResponse

        # Map internal name → Kilo Gateway model ID
        wire_model = KIMI_MODEL_MAP.get(model, f"moonshotai/{model}")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        payload: dict[str, Any] = {
            "model": wire_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools

        response = await self._client.post(
            f"{self._base_url}/chat/completions",
            headers=headers,
            json=payload,
        )

        if response.status_code != 200:
            error_body = response.text
            logger.error(f"Kimi API error {response.status_code}: {error_body}")
            raise RuntimeError(f"Kimi API error {response.status_code}: {error_body}")

        data = response.json()

        choice = data["choices"][0]
        message = choice["message"]
        finish_reason = choice.get("finish_reason", "stop") or "stop"

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

        costs = KIMI_COSTS.get(model, {"input": 0.60, "output": 2.50})
        cost_estimate = (
            input_tokens * costs["input"] / 1_000_000
            + output_tokens * costs["output"] / 1_000_000
        )

        from core.provider_tracker import detect_truncation

        truncated = detect_truncation(
            finish_reason, output_tokens, message.get("content")
        )

        return LLMResponse(
            content=message.get("content"),
            model_used=model,
            provider="kimi",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_estimate=cost_estimate,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            suspected_truncated=truncated,
        )

    async def health_check(self) -> bool:
        """Verify Kimi connectivity via Kilo Gateway with a minimal request."""
        wire_model = KIMI_MODEL_MAP.get(
            self._default_model, f"moonshotai/{self._default_model}"
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        payload = {
            "model": wire_model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        }

        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=10.0,
            )
            if response.status_code != 200:
                logger.warning(
                    f"Kimi health check got status {response.status_code}: "
                    f"{response.text[:200]}"
                )
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Kimi health check failed: {type(e).__name__}: {e}")
            return False
