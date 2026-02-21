"""LLM Router: selects provider and model, makes calls, tracks cost.

Routes LLM calls to the correct provider (Ollama, Z.ai, OpenRouter)
based on task type, user configuration, and provider availability.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

import litellm

from core.config import Config

logger = logging.getLogger(__name__)

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""

    content: str | None
    model_used: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost_estimate: float
    tool_calls: list[dict[str, Any]] | None = None


@dataclass
class CostTracker:
    """Tracks LLM spending for budget enforcement."""

    daily_total: float = 0.0
    task_total: float = 0.0
    calls: list[dict[str, Any]] = field(default_factory=list)
    _pending_records: list[dict[str, Any]] = field(default_factory=list)

    def record(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        task_type: str = "unknown",
    ) -> None:
        self.daily_total += cost
        self.task_total += cost
        record = {
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": cost,
            "task_type": task_type,
            "timestamp": time.time(),
        }
        self.calls.append(record)
        self._pending_records.append(record)

    def reset_task(self) -> None:
        self.task_total = 0.0

    def within_budget(self, daily_limit: float, task_limit: float) -> bool:
        return self.daily_total < daily_limit and self.task_total < task_limit

    async def flush(self, db: Any) -> None:
        """Persist pending records to the llm_usage table."""
        if not db or not self._pending_records:
            return
        from datetime import datetime

        for record in self._pending_records:
            try:
                await db.execute_insert(
                    "INSERT INTO llm_usage "
                    "(model, provider, input_tokens, output_tokens, "
                    "cost_usd, task_type, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        record["model"],
                        record["provider"],
                        record["input_tokens"],
                        record["output_tokens"],
                        record["cost"],
                        record["task_type"],
                        datetime.now(UTC).isoformat(),
                    ),
                )
            except Exception:
                pass  # Non-fatal
        self._pending_records.clear()


class LLMRouter:
    """Routes LLM calls to the appropriate provider and model."""

    # Seconds before a failed provider is retried
    HEALTH_RECOVERY_SECONDS = 60
    # Retry config for transient failures
    MAX_RETRIES = 3
    RETRY_DELAYS = [2, 5, 10]  # seconds between retries

    def __init__(self, config: Config) -> None:
        self._config = config
        self._cost_tracker = CostTracker()
        self._provider_health: dict[str, bool] = {}
        self._provider_failed_at: dict[str, float] = {}

    @property
    def cost_tracker(self) -> CostTracker:
        return self._cost_tracker

    def _mark_unhealthy(self, provider: str) -> None:
        """Mark a provider as unhealthy with a recovery timer."""
        self._provider_health[provider] = False
        self._provider_failed_at[provider] = time.time()

    def _is_healthy(self, provider: str) -> bool:
        """Check if a provider is healthy, recovering after cooldown."""
        if self._provider_health.get(provider, True):
            return True
        # Auto-recover after cooldown
        failed_at = self._provider_failed_at.get(provider, 0)
        if time.time() - failed_at >= self.HEALTH_RECOVERY_SECONDS:
            logger.info(f"Provider {provider} health recovered after cooldown")
            self._provider_health[provider] = True
            return True
        return False

    async def _call_with_retries(
        self,
        provider: str,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int | None,
    ) -> LLMResponse:
        """Call a provider with retries on transient failures."""
        for attempt in range(self.MAX_RETRIES):
            try:
                if provider == "zai":
                    return await self._call_zai(
                        messages, model, tools, temperature, max_tokens
                    )
                else:
                    return await self._call_litellm(
                        messages, model, provider, tools, temperature, max_tokens
                    )
            except Exception as e:
                delay = self.RETRY_DELAYS[min(attempt, len(self.RETRY_DELAYS) - 1)]
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(
                        f"{provider}/{model} attempt {attempt + 1}/{self.MAX_RETRIES} "
                        f"failed: {e}. Retrying in {delay}s..."
                    )
                    # Reset health so retry doesn't skip this provider
                    self._provider_health.pop(provider, None)
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"{provider}/{model} failed after {self.MAX_RETRIES} attempts: {e}"
                    )
                    raise
        raise RuntimeError("Unreachable")  # pragma: no cover

    async def complete(
        self,
        messages: list[dict[str, Any]],
        task_type: str = "simple",
        model_override: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Route an LLM call to the appropriate provider.

        Each provider is retried up to MAX_RETRIES times for transient
        failures. If all retries fail, tries the next provider in the
        priority list.
        """
        if not self._cost_tracker.within_budget(
            self._config.llm.budget.daily_limit_usd,
            self._config.llm.budget.per_task_limit_usd,
        ):
            raise RuntimeError(
                f"Budget exceeded. Daily: ${self._cost_tracker.daily_total:.2f}, "
                f"Task: ${self._cost_tracker.task_total:.2f}"
            )

        # Collect all providers to try (primary + fallbacks)
        tried: set[str] = set()
        last_error: Exception | None = None

        while True:
            try:
                provider, model = self._select_provider_and_model(
                    task_type, model_override, exclude=tried
                )
            except RuntimeError:
                # No more providers to try
                if last_error:
                    raise RuntimeError(
                        f"All LLM providers failed. Last error: {last_error}"
                    ) from last_error
                raise

            tried.add(provider)
            logger.info(f"Routing to {provider}/{model} for task_type={task_type}")

            try:
                return await self._call_with_retries(
                    provider, model, messages, tools, temperature, max_tokens
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Provider {provider}/{model} exhausted retries, trying next: {e}"
                )
                # If model_override was given, don't try other providers
                if model_override:
                    raise

    def _select_provider_and_model(
        self,
        task_type: str,
        model_override: str | None,
        exclude: set[str] | None = None,
    ) -> tuple[str, str]:
        """Select the best provider and model for the given task type."""
        exclude = exclude or set()

        # 1. Explicit override
        if model_override:
            provider = self._infer_provider(model_override)
            return provider, model_override

        # 2. Preferred provider from per-task routing
        routing = self._config.llm.routing.get(task_type)
        if routing and routing.preferred_provider:
            provider_name = routing.preferred_provider
            provider_cfg = self._config.llm.providers.get(provider_name)
            if (
                provider_cfg
                and provider_cfg.enabled
                and self._is_healthy(provider_name)
                and provider_name not in exclude
            ):
                model = self._resolve_model(provider_name, task_type)
                if model:
                    return provider_name, model

        # 3. Walk provider priority — look up per-provider model
        for provider_name in self._config.llm.provider_priority:
            if provider_name in exclude:
                continue
            provider_cfg = self._config.llm.providers.get(provider_name)
            if (
                provider_cfg
                and provider_cfg.enabled
                and self._is_healthy(provider_name)
            ):
                model = self._resolve_model(provider_name, task_type)
                if model:
                    return provider_name, model

        raise RuntimeError(
            "No LLM provider available. Run 'elophanto init' to configure providers."
        )

    def _infer_provider(self, model: str) -> str:
        """Infer provider from model name."""
        if "/" in model and not model.startswith("ollama/"):
            return "openrouter"
        if model.startswith("glm-"):
            return "zai"
        return "ollama"

    def _resolve_model(self, provider: str, task_type: str) -> str | None:
        """Resolve the model for a provider + task type.

        Checks (in order):
        1. ``routing.models[provider]`` — per-provider model map
        2. Legacy routing fields (preferred_model, fallback_model, local_fallback)
        3. Provider-level defaults (e.g. zai.default_model)
        """
        routing = self._config.llm.routing.get(task_type)

        # 1. Per-provider models map (new format)
        if routing and routing.models.get(provider):
            return routing.models[provider]

        # 2. Legacy flat fields
        if routing:
            if provider == routing.preferred_provider and routing.preferred_model:
                return routing.preferred_model
            if provider == routing.fallback_provider and routing.fallback_model:
                return routing.fallback_model
            if provider == "ollama" and routing.local_fallback:
                return routing.local_fallback

        # 3. Provider-level defaults
        if provider == "zai":
            zai_cfg = self._config.llm.providers.get("zai")
            return zai_cfg.default_model if zai_cfg else None

        return None

    async def _call_litellm(
        self,
        messages: list[dict[str, Any]],
        model: str,
        provider: str,
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int | None,
    ) -> LLMResponse:
        """Call via litellm (OpenRouter or Ollama)."""
        kwargs: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
        }

        if provider == "openrouter":
            kwargs["model"] = f"openrouter/{model}"
            or_cfg = self._config.llm.providers.get("openrouter")
            if or_cfg:
                kwargs["api_key"] = or_cfg.api_key
                kwargs["api_base"] = or_cfg.base_url
        elif provider == "ollama":
            kwargs["model"] = (
                f"ollama/{model}" if not model.startswith("ollama/") else model
            )
        else:
            kwargs["model"] = model

        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools

        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as e:
            logger.error(f"litellm call failed ({provider}/{model}): {e}")
            self._mark_unhealthy(provider)
            raise

        choice = response.choices[0]
        message = choice.message

        # Parse tool calls
        tool_calls = None
        if message.tool_calls:
            tool_calls = []
            for tc in message.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                )

        # Calculate cost
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        cost = float(
            getattr(response, "_hidden_params", {}).get("response_cost", 0) or 0
        )

        self._cost_tracker.record(provider, model, input_tokens, output_tokens, cost)

        return LLMResponse(
            content=message.content,
            model_used=model,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_estimate=cost,
            tool_calls=tool_calls,
        )

    async def _call_zai(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int | None,
    ) -> LLMResponse:
        """Call via Z.ai custom adapter."""
        from core.zai_adapter import ZaiAdapter

        adapter = ZaiAdapter(self._config)
        try:
            response = await adapter.complete(
                messages, model, tools, temperature, max_tokens
            )
            self._cost_tracker.record(
                "zai",
                model,
                response.input_tokens,
                response.output_tokens,
                response.cost_estimate,
            )
            return response
        except Exception as e:
            logger.error(f"Z.ai call failed ({model}): {e}")
            self._mark_unhealthy("zai")
            raise

    async def health_check(self) -> dict[str, bool]:
        """Check provider connectivity on startup.

        Runs all checks in parallel with asyncio.gather() for speed.
        Only local providers (Ollama) are gated by health check results.
        Cloud providers (Z.ai, OpenRouter) get a warning but remain eligible
        for routing — transient health check failures should not block them.
        """
        import httpx

        results: dict[str, bool] = {}

        async def _check_ollama() -> tuple[str, bool]:
            ollama_cfg = self._config.llm.providers.get("ollama")
            if not (ollama_cfg and ollama_cfg.enabled):
                return ("ollama", False)
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(f"{ollama_cfg.base_url}/api/tags")
                    return ("ollama", resp.status_code == 200)
            except Exception:
                logger.warning("Ollama not reachable")
                return ("ollama", False)

        async def _check_openrouter() -> tuple[str, bool]:
            or_cfg = self._config.llm.providers.get("openrouter")
            if not (or_cfg and or_cfg.enabled and or_cfg.api_key):
                return ("openrouter", False)
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(
                        f"{or_cfg.base_url}/models",
                        headers={"Authorization": f"Bearer {or_cfg.api_key}"},
                    )
                    return ("openrouter", resp.status_code == 200)
            except Exception:
                logger.warning("OpenRouter not reachable")
                return ("openrouter", False)

        async def _check_zai() -> tuple[str, bool]:
            zai_cfg = self._config.llm.providers.get("zai")
            if not (zai_cfg and zai_cfg.enabled and zai_cfg.api_key):
                return ("zai", False)
            try:
                from core.zai_adapter import ZaiAdapter

                adapter = ZaiAdapter(self._config)
                healthy = await adapter.health_check()
                if not healthy:
                    logger.warning("Z.ai health check returned non-200")
                return ("zai", healthy)
            except Exception as e:
                logger.warning(f"Z.ai not reachable: {e}")
                return ("zai", False)

        # Run all health checks in parallel
        tasks = []
        ollama_cfg = self._config.llm.providers.get("ollama")
        if ollama_cfg and ollama_cfg.enabled:
            tasks.append(_check_ollama())
        or_cfg = self._config.llm.providers.get("openrouter")
        if or_cfg and or_cfg.enabled and or_cfg.api_key:
            tasks.append(_check_openrouter())
        zai_cfg = self._config.llm.providers.get("zai")
        if zai_cfg and zai_cfg.enabled and zai_cfg.api_key:
            tasks.append(_check_zai())

        if tasks:
            check_results = await asyncio.gather(*tasks)
            for name, healthy in check_results:
                results[name] = healthy

        # Only gate local providers — cloud providers stay eligible
        # even if health check failed (could be transient)
        for name, healthy in results.items():
            if name == "ollama" and not healthy:
                self._mark_unhealthy(name)
            # Cloud providers: don't mark unhealthy from startup check

        logger.info(f"Provider health: {results}")
        return results
