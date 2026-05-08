"""LLM Router: selects provider and model, makes calls, tracks cost.

Routes LLM calls to the correct provider (Ollama, Z.ai, Kimi, OpenRouter, OpenAI)
based on task type, user configuration, and provider availability.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

import httpx
import litellm

from core.config import Config
from core.provider_tracker import ProviderEvent, ProviderTracker, detect_truncation

logger = logging.getLogger(__name__)

# Suppress litellm's verbose logging — all three are needed:
# suppress_debug_info: hides the startup "Give Feedback" banner
# set_verbose: prevents litellm from adding its own DEBUG StreamHandler
# Logger levels: prevent DEBUG messages from flowing up to root handlers
litellm.suppress_debug_info = True
litellm.set_verbose = False
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("LiteLLM Router").setLevel(logging.WARNING)
logging.getLogger("LiteLLM Proxy").setLevel(logging.WARNING)


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
    finish_reason: str = "stop"
    latency_ms: int = 0
    fallback_from: str = ""
    suspected_truncated: bool = False


@dataclass
class CostTracker:
    """Tracks LLM spending for budget enforcement."""

    daily_total: float = 0.0
    task_total: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    # Bounded ring of recent calls. The per-call list grew unboundedly
    # before 2026-05-08 — multi-hour sessions accumulated tens of MB and
    # CPU walked the full list on every status refresh.
    calls: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=1000))
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
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
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
        # Lazy singletons — avoid re-creating HTTP clients per call
        self._zai_adapter: Any = None
        self._kimi_adapter: Any = None
        self._codex_adapter: Any = None
        # Provider transparency tracker (Gap 5)
        self._provider_tracker = ProviderTracker()
        # Affect handle (Phase 2). When wired, temperature on every call
        # is biased by current affect state via AffectManager.
        # temperature_modifier(). Capped to ±0.2 in core/affect.py. Set
        # by Agent.initialize() once affect is up.
        self._affect_manager: Any = None

    @property
    def cost_tracker(self) -> CostTracker:
        return self._cost_tracker

    @property
    def provider_tracker(self) -> ProviderTracker:
        return self._provider_tracker

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
        reasoning_effort: str = "",
    ) -> LLMResponse:
        """Call a provider with retries on transient failures."""
        for attempt in range(self.MAX_RETRIES):
            _attempt_start = time.monotonic()
            try:
                if provider == "zai":
                    result = await self._call_zai(
                        messages, model, tools, temperature, max_tokens
                    )
                elif provider == "kimi":
                    result = await self._call_kimi(
                        messages, model, tools, temperature, max_tokens
                    )
                elif provider == "codex":
                    result = await self._call_codex(
                        messages, model, tools, reasoning_effort
                    )
                else:
                    result = await self._call_litellm(
                        messages,
                        model,
                        provider,
                        tools,
                        temperature,
                        max_tokens,
                        reasoning_effort=reasoning_effort,
                    )
                result.latency_ms = int((time.monotonic() - _attempt_start) * 1000)
                logger.info(
                    "[TIMING] %s/%s attempt %d: %.2fs",
                    provider,
                    model,
                    attempt + 1,
                    time.monotonic() - _attempt_start,
                )
                return result
            except Exception as e:
                elapsed = time.monotonic() - _attempt_start
                # Timeouts mean the request is too heavy — retrying the same
                # provider won't help.  Fall through to the next provider.
                is_timeout = (
                    isinstance(e, (httpx.TimeoutException, asyncio.TimeoutError))
                    or "timed out" in str(e).lower()
                )
                is_rate_limited = "429" in str(e)

                if is_timeout:
                    logger.warning(
                        f"[TIMING] {provider}/{model} timed out after {elapsed:.0f}s "
                        f"— skipping to next provider"
                    )
                    self._mark_unhealthy(provider)
                    raise

                if is_rate_limited:
                    logger.warning(
                        f"[TIMING] {provider}/{model} rate-limited (429) "
                        f"— skipping to next provider (will retry after {self.HEALTH_RECOVERY_SECONDS}s)"
                    )
                    self._mark_unhealthy(provider)
                    raise

                # Deterministic errors — retrying the same payload with the
                # same provider will always fail.  Skip to next provider
                # immediately (no sleep, no retries).
                _err_lower = str(e).lower()
                is_context_overflow = any(
                    p in _err_lower
                    for p in (
                        "context length",
                        "context_length_exceeded",
                        "maximum context",
                        "exceeds the model",
                        "too many tokens",
                        "input too long",
                    )
                )
                if is_context_overflow:
                    logger.warning(
                        f"[TIMING] {provider}/{model} context overflow after {elapsed:.2f}s "
                        f"— skipping to next provider immediately"
                    )
                    raise

                # Capability mismatch (e.g. model doesn't support image input) —
                # also deterministic, no point retrying.
                is_capability_mismatch = any(
                    p in _err_lower
                    for p in (
                        "no endpoints found",
                        "unsupported media type",
                        "does not support vision",
                        "does not support image",
                    )
                )
                if is_capability_mismatch:
                    logger.warning(
                        f"[TIMING] {provider}/{model} capability mismatch after {elapsed:.2f}s "
                        f"— skipping to next provider immediately: {e}"
                    )
                    raise

                delay = self.RETRY_DELAYS[min(attempt, len(self.RETRY_DELAYS) - 1)]
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(
                        f"[TIMING] {provider}/{model} attempt {attempt + 1}/{self.MAX_RETRIES} "
                        f"failed after {elapsed:.2f}s: {e}. "
                        f"Retrying in {delay}s..."
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

    @staticmethod
    def _contains_images(messages: list[dict[str, Any]]) -> bool:
        """Return True if any message has image_url content blocks."""
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        return True
        return False

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

        # Affect-based temperature bias (Phase 2 from docs/69-AFFECT.md).
        # Frustrated/anxious states pull temperature down (more
        # conservative outputs); joyful/restless states push it up
        # (more exploration). Capped ±0.2 by AffectManager. Best-effort:
        # affect failure must not break routing.
        if self._affect_manager is not None:
            try:
                delta = await self._affect_manager.temperature_modifier()
                if delta != 0.0:
                    biased = max(0.0, min(1.5, temperature + delta))
                    if abs(biased - temperature) >= 0.01:
                        logger.info(
                            "[router] affect bias applied: temp %.2f → %.2f "
                            "(Δ=%+.2f)",
                            temperature,
                            biased,
                            delta,
                        )
                    temperature = biased
            except Exception as e:  # pragma: no cover — defensive
                logger.debug("Affect temperature bias failed: %s", e)

        # Auto-route to vision model when messages contain image_url blocks
        # and no explicit override was given.
        if (
            not model_override
            and self._config.llm.vision_model
            and self._contains_images(messages)
        ):
            logger.info(
                "[router] messages contain images — routing to vision model: %s",
                self._config.llm.vision_model,
            )
            model_override = self._config.llm.vision_model

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
            _route_start = time.monotonic()
            logger.info(
                f"[TIMING] routing to {provider}/{model} for task_type={task_type}"
            )

            # Pick up reasoning_effort from per-task routing config
            _routing = self._config.llm.routing.get(task_type)
            _reasoning_effort = _routing.reasoning_effort if _routing else ""

            try:
                result = await self._call_with_retries(
                    provider,
                    model,
                    messages,
                    tools,
                    temperature,
                    max_tokens,
                    reasoning_effort=_reasoning_effort,
                )
                logger.info(
                    "[TIMING] %s/%s responded in %.2fs",
                    provider,
                    model,
                    time.monotonic() - _route_start,
                )
                # Track fallback origin
                failed_providers = tried - {provider}
                if failed_providers:
                    result.fallback_from = ",".join(sorted(failed_providers))
                # Record provider event for transparency
                self._provider_tracker.record(
                    ProviderEvent(
                        provider=provider,
                        model=model,
                        task_type=task_type,
                        finish_reason=result.finish_reason,
                        latency_ms=result.latency_ms,
                        fallback_from=result.fallback_from,
                        suspected_truncated=result.suspected_truncated,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                    )
                )
                return result
            except Exception as e:
                logger.warning(
                    "[TIMING] %s/%s failed after %.2fs, trying next: %s",
                    provider,
                    model,
                    time.monotonic() - _route_start,
                    e,
                )
                # Record failure event
                self._provider_tracker.record(
                    ProviderEvent(
                        provider=provider,
                        model=model,
                        task_type=task_type,
                        finish_reason="error",
                        latency_ms=int((time.monotonic() - _route_start) * 1000),
                        error_message=str(e)[:200],
                    )
                )
                last_error = e
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

        # 4. Last resort — if all providers are "unhealthy" (e.g. a timeout
        #    marked them dead), try anyway rather than refusing to work.
        #    A previous timeout doesn't mean the next request will fail.
        for provider_name in self._config.llm.provider_priority:
            if provider_name in exclude:
                continue
            provider_cfg = self._config.llm.providers.get(provider_name)
            if provider_cfg and provider_cfg.enabled:
                model = self._resolve_model(provider_name, task_type)
                if model:
                    logger.warning(
                        "All providers unhealthy — forcing %s/%s as last resort",
                        provider_name,
                        model,
                    )
                    self._provider_health[provider_name] = True
                    return provider_name, model

        raise RuntimeError(
            "No LLM provider available. Run 'elophanto init' to configure providers."
        )

    def filter_tools_for_task(
        self,
        tools: list[Any],
        task_type: str,
        provider: str | None = None,
    ) -> list[Any]:
        """Filter tool instances by profile and provider limits.

        Args:
            tools: BaseTool instances (must have .group attribute).
            task_type: The task type (planning, coding, analysis, simple).
            provider: Target provider name (for max_tools / deny).

        Returns:
            Filtered list of BaseTool instances.
        """
        from core.tool_profiles import (
            filter_tools_by_profile,
            resolve_profiles,
            select_profile,
        )

        # Resolve profiles (user config overrides + defaults)
        profiles = resolve_profiles(self._config.llm.tool_profiles or None)

        # Determine profile from routing config or task type
        routing = self._config.llm.routing.get(task_type)
        routing_profile = routing.tool_profile if routing else ""
        profile_name = select_profile(task_type, routing_profile or None)

        # Get provider-level deny list
        deny_groups: list[str] | None = None
        if provider:
            pcfg = self._config.llm.providers.get(provider)
            if pcfg and pcfg.tool_deny:
                deny_groups = pcfg.tool_deny

        filtered = filter_tools_by_profile(tools, profile_name, profiles, deny_groups)

        logger.debug(
            "Tool profile '%s' for task_type=%s: %d → %d tools",
            profile_name,
            task_type,
            len(tools),
            len(filtered),
        )
        return filtered

    def _infer_provider(self, model: str) -> str:
        """Infer provider from model name."""
        # HuggingFace models use org/model format (e.g. Qwen/Qwen3.5-397B-A17B)
        # Check if huggingface is configured and the model looks like an HF repo
        if "/" in model and not model.startswith("ollama/"):
            hf_cfg = self._config.llm.providers.get("huggingface")
            if hf_cfg and hf_cfg.enabled:
                # Check if model is in HF routing config
                for rt in self._config.llm.routing.values():
                    if rt.models.get("huggingface") == model:
                        return "huggingface"
            return "openrouter"
        if model.startswith("glm-"):
            return "zai"
        if model.startswith("kimi-"):
            return "kimi"
        if model.startswith("gpt-") or model.startswith("o1") or model.startswith("o3"):
            return "openai"
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
        if provider == "kimi":
            kimi_cfg = self._config.llm.providers.get("kimi")
            return kimi_cfg.default_model if kimi_cfg else None
        if provider == "openai":
            oai_cfg = self._config.llm.providers.get("openai")
            return oai_cfg.default_model if oai_cfg and oai_cfg.default_model else None

        # 4. Provider default_model — set via Settings UI or config.yaml default_model field
        provider_cfg = self._config.llm.providers.get(provider)
        if provider_cfg and provider_cfg.default_model:
            return provider_cfg.default_model

        return None

    def get_model_for_provider(self, provider: str, task_type: str = "planning") -> str:
        """Public helper: resolve model for a provider + task type.

        Used by godmode racing to get the right model per provider.
        Falls back to the provider's default model.
        """
        return self._resolve_model(provider, task_type) or ""

    async def _call_litellm(
        self,
        messages: list[dict[str, Any]],
        model: str,
        provider: str,
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int | None,
        reasoning_effort: str = "",
    ) -> LLMResponse:
        """Call via litellm (OpenAI, OpenRouter, or Ollama)."""
        kwargs: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
        }

        if provider == "openrouter":
            # Strip provider prefix if already present (e.g., vision_model
            # may be configured as "openrouter/x-ai/grok-4.1-fast")
            _or_model = model.removeprefix("openrouter/")
            kwargs["model"] = f"openrouter/{_or_model}"
            or_cfg = self._config.llm.providers.get("openrouter")
            if or_cfg:
                kwargs["api_key"] = or_cfg.api_key
                kwargs["api_base"] = or_cfg.base_url
            kwargs["extra_headers"] = {
                "HTTP-Referer": "https://elophanto.com",
                "X-Title": "EloPhanto",
            }
            if reasoning_effort:
                kwargs["extra_body"] = {"reasoning": {"effort": reasoning_effort}}
        elif provider == "openai":
            kwargs["model"] = model
            oai_cfg = self._config.llm.providers.get("openai")
            if oai_cfg:
                kwargs["api_key"] = oai_cfg.api_key
                if oai_cfg.base_url:
                    kwargs["api_base"] = oai_cfg.base_url
            # GPT-5 models only support temperature=1
            if model.startswith("gpt-5"):
                kwargs.pop("temperature", None)
            # OpenAI reasoning models use reasoning_effort param directly
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort
        elif provider == "huggingface":
            kwargs["model"] = f"huggingface/{model}"
            hf_cfg = self._config.llm.providers.get("huggingface")
            if hf_cfg:
                kwargs["api_key"] = hf_cfg.api_key
                kwargs["api_base"] = (
                    hf_cfg.base_url or "https://router.huggingface.co/v1"
                )
        elif provider == "ollama":
            kwargs["model"] = (
                f"ollama/{model}" if not model.startswith("ollama/") else model
            )
        else:
            kwargs["model"] = model

        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if tools:
            # Apply provider max_tools limit as last resort
            pcfg = self._config.llm.providers.get(provider)
            max_tools = pcfg.max_tools if pcfg else 0
            # OpenAI hard limit is 128 regardless of config
            if provider == "openai":
                max_tools = max_tools or 128
            if max_tools and len(tools) > max_tools:
                from core.tool_profiles import trim_tools_for_limit

                # Pin recently-used tools so they survive trimming
                recently_used: set[str] = set()
                for msg in messages:
                    if msg.get("role") == "assistant":
                        for tc in msg.get("tool_calls") or []:
                            fn = tc.get("function", {}).get("name", "")
                            if fn:
                                recently_used.add(fn)

                logger.info(
                    "Trimming tools from %d to %d for %s (pinning %d recently used)",
                    len(tools),
                    max_tools,
                    provider,
                    len(recently_used),
                )
                tools = trim_tools_for_limit(tools, max_tools, recently_used)
            kwargs["tools"] = tools

        try:
            response = await asyncio.wait_for(
                litellm.acompletion(**kwargs), timeout=180
            )
        except TimeoutError:
            logger.error(f"litellm call timed out after 180s ({provider}/{model})")
            self._mark_unhealthy(provider)
            raise
        except Exception as e:
            logger.error(f"litellm call failed ({provider}/{model}): {e}")
            self._mark_unhealthy(provider)
            raise

        choice = response.choices[0]
        message = choice.message
        finish_reason = getattr(choice, "finish_reason", "stop") or "stop"

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

        truncated = detect_truncation(finish_reason, output_tokens, message.content)

        return LLMResponse(
            content=message.content,
            model_used=model,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_estimate=cost,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            suspected_truncated=truncated,
        )

    def _get_zai_adapter(self) -> Any:
        """Get or create the shared ZaiAdapter instance."""
        if self._zai_adapter is None:
            from core.zai_adapter import ZaiAdapter

            self._zai_adapter = ZaiAdapter(self._config)
        return self._zai_adapter

    async def _call_zai(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int | None,
    ) -> LLMResponse:
        """Call via Z.ai custom adapter."""
        adapter = self._get_zai_adapter()
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

    def _get_codex_adapter(self) -> Any:
        """Get or create the shared CodexAdapter instance."""
        if self._codex_adapter is None:
            from core.codex_adapter import CodexAdapter

            self._codex_adapter = CodexAdapter(self._config)
        return self._codex_adapter

    async def _call_codex(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None,
        reasoning_effort: str,
    ) -> LLMResponse:
        """Call via ChatGPT Codex subscription adapter."""
        adapter = self._get_codex_adapter()
        try:
            response = await adapter.complete(
                messages,
                model,
                tools,
                0.0,  # temperature ignored by Codex
                None,  # max_tokens ignored by Codex
                reasoning_effort or "medium",
            )
            self._cost_tracker.record(
                "codex",
                model,
                response.input_tokens,
                response.output_tokens,
                response.cost_estimate,
            )
            return response
        except Exception as e:
            logger.error(f"Codex call failed ({model}): {e}")
            self._mark_unhealthy("codex")
            raise

    def _get_kimi_adapter(self) -> Any:
        """Get or create the shared KimiAdapter instance."""
        if self._kimi_adapter is None:
            from core.kimi_adapter import KimiAdapter

            self._kimi_adapter = KimiAdapter(self._config)
        return self._kimi_adapter

    async def _call_kimi(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int | None,
    ) -> LLMResponse:
        """Call via Kimi custom adapter."""
        adapter = self._get_kimi_adapter()
        try:
            response = await adapter.complete(
                messages, model, tools, temperature, max_tokens
            )
            self._cost_tracker.record(
                "kimi",
                model,
                response.input_tokens,
                response.output_tokens,
                response.cost_estimate,
            )
            return response
        except Exception as e:
            logger.error(f"Kimi call failed ({model}): {e}")
            self._mark_unhealthy("kimi")
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

        async def _check_openai() -> tuple[str, bool]:
            oai_cfg = self._config.llm.providers.get("openai")
            if not (oai_cfg and oai_cfg.enabled and oai_cfg.api_key):
                return ("openai", False)
            try:
                base = oai_cfg.base_url or "https://api.openai.com/v1"
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(
                        f"{base}/models",
                        headers={"Authorization": f"Bearer {oai_cfg.api_key}"},
                    )
                    return ("openai", resp.status_code == 200)
            except Exception:
                logger.warning("OpenAI not reachable")
                return ("openai", False)

        async def _check_zai() -> tuple[str, bool]:
            zai_cfg = self._config.llm.providers.get("zai")
            if not (zai_cfg and zai_cfg.enabled and zai_cfg.api_key):
                return ("zai", False)
            try:
                adapter = self._get_zai_adapter()
                healthy = await adapter.health_check()
                if not healthy:
                    logger.warning("Z.ai health check returned non-200")
                return ("zai", healthy)
            except Exception as e:
                logger.warning(f"Z.ai not reachable: {e}")
                return ("zai", False)

        async def _check_kimi() -> tuple[str, bool]:
            kimi_cfg = self._config.llm.providers.get("kimi")
            if not (kimi_cfg and kimi_cfg.enabled and kimi_cfg.api_key):
                return ("kimi", False)
            try:
                adapter = self._get_kimi_adapter()
                healthy = await adapter.health_check()
                if not healthy:
                    logger.warning("Kimi health check returned non-200")
                return ("kimi", healthy)
            except Exception as e:
                logger.warning(f"Kimi not reachable: {e}")
                return ("kimi", False)

        async def _check_codex() -> tuple[str, bool]:
            codex_cfg = self._config.llm.providers.get("codex")
            if not (codex_cfg and codex_cfg.enabled):
                return ("codex", False)
            try:
                adapter = self._get_codex_adapter()
                healthy = await adapter.health_check()
                if not healthy:
                    logger.warning("Codex health check returned False")
                return ("codex", healthy)
            except Exception as e:
                logger.warning(f"Codex not reachable: {e}")
                return ("codex", False)

        async def _check_huggingface() -> tuple[str, bool]:
            hf_cfg = self._config.llm.providers.get("huggingface")
            if not (hf_cfg and hf_cfg.enabled and hf_cfg.api_key):
                return ("huggingface", False)
            try:
                base = hf_cfg.base_url or "https://router.huggingface.co/v1"
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(
                        f"{base}/models",
                        headers={"Authorization": f"Bearer {hf_cfg.api_key}"},
                    )
                    return ("huggingface", resp.status_code == 200)
            except Exception:
                logger.warning("HuggingFace not reachable")
                return ("huggingface", False)

        # Run all health checks in parallel
        tasks = []
        ollama_cfg = self._config.llm.providers.get("ollama")
        if ollama_cfg and ollama_cfg.enabled:
            tasks.append(_check_ollama())
        oai_cfg = self._config.llm.providers.get("openai")
        if oai_cfg and oai_cfg.enabled and oai_cfg.api_key:
            tasks.append(_check_openai())
        or_cfg = self._config.llm.providers.get("openrouter")
        if or_cfg and or_cfg.enabled and or_cfg.api_key:
            tasks.append(_check_openrouter())
        zai_cfg = self._config.llm.providers.get("zai")
        if zai_cfg and zai_cfg.enabled and zai_cfg.api_key:
            tasks.append(_check_zai())
        kimi_cfg = self._config.llm.providers.get("kimi")
        if kimi_cfg and kimi_cfg.enabled and kimi_cfg.api_key:
            tasks.append(_check_kimi())
        hf_cfg = self._config.llm.providers.get("huggingface")
        if hf_cfg and hf_cfg.enabled and hf_cfg.api_key:
            tasks.append(_check_huggingface())
        codex_cfg = self._config.llm.providers.get("codex")
        if codex_cfg and codex_cfg.enabled:
            # Codex doesn't use api_key — auth comes from ~/.codex/auth.json
            tasks.append(_check_codex())

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
