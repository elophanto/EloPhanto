"""Router model selection tests."""

from __future__ import annotations

import pytest

from core.config import Config, LLMConfig, ProviderConfig, RoutingConfig, BudgetConfig
from core.router import LLMRouter


class TestRouterSelection:
    def _make_config(self, **overrides) -> Config:
        """Build a config with multiple providers for routing tests."""
        config = Config(
            llm=LLMConfig(
                providers={
                    "ollama": ProviderConfig(
                        enabled=True, base_url="http://localhost:11434"
                    ),
                    "zai": ProviderConfig(
                        enabled=True,
                        api_key="test-key",
                        default_model="glm-4.7",
                        fast_model="glm-4.7-flash",
                    ),
                    "openrouter": ProviderConfig(
                        enabled=True,
                        api_key="test-key",
                        base_url="https://openrouter.ai/api/v1",
                    ),
                },
                provider_priority=["ollama", "zai", "openrouter"],
                routing={
                    "planning": RoutingConfig(
                        preferred_provider="openrouter",
                        preferred_model="anthropic/claude-sonnet-4-20250514",
                        local_fallback="qwen2.5:32b",
                    ),
                    "coding": RoutingConfig(
                        preferred_provider="zai",
                        preferred_model="glm-4.7",
                        fallback_provider="openrouter",
                        fallback_model="anthropic/claude-sonnet-4-20250514",
                        local_fallback="qwen2.5-coder:32b",
                    ),
                    "simple": RoutingConfig(
                        preferred_provider="zai",
                        preferred_model="glm-4.7-flash",
                        local_fallback="llama3.2:3b",
                    ),
                },
                budget=BudgetConfig(daily_limit_usd=10.0, per_task_limit_usd=2.0),
            ),
        )
        for k, v in overrides.items():
            setattr(config, k, v)
        return config

    def test_task_type_routing_planning(self) -> None:
        config = self._make_config()
        router = LLMRouter(config)
        provider, model = router._select_provider_and_model("planning", None)
        assert provider == "openrouter"
        assert model == "anthropic/claude-sonnet-4-20250514"

    def test_task_type_routing_coding(self) -> None:
        config = self._make_config()
        router = LLMRouter(config)
        provider, model = router._select_provider_and_model("coding", None)
        assert provider == "zai"
        assert model == "glm-4.7"

    def test_task_type_routing_simple(self) -> None:
        config = self._make_config()
        router = LLMRouter(config)
        provider, model = router._select_provider_and_model("simple", None)
        assert provider == "zai"
        assert model == "glm-4.7-flash"

    def test_explicit_model_override(self) -> None:
        config = self._make_config()
        router = LLMRouter(config)
        provider, model = router._select_provider_and_model("planning", "glm-4.7")
        assert provider == "zai"
        assert model == "glm-4.7"

    def test_explicit_override_openrouter_model(self) -> None:
        config = self._make_config()
        router = LLMRouter(config)
        provider, model = router._select_provider_and_model("simple", "openai/gpt-4o")
        assert provider == "openrouter"
        assert model == "openai/gpt-4o"

    def test_fallback_when_preferred_disabled(self) -> None:
        config = self._make_config()
        config.llm.providers["zai"].enabled = False
        router = LLMRouter(config)

        # Coding prefers zai, should fallback to openrouter
        provider, model = router._select_provider_and_model("coding", None)
        assert provider == "openrouter"

    def test_provider_priority_fallthrough(self) -> None:
        config = self._make_config()
        # Disable all preferred providers
        config.llm.providers["openrouter"].enabled = False
        config.llm.providers["zai"].enabled = False
        router = LLMRouter(config)

        # Planning prefers openrouter, should fall through to ollama via priority
        provider, model = router._select_provider_and_model("planning", None)
        assert provider == "ollama"

    def test_no_provider_raises(self) -> None:
        config = self._make_config()
        config.llm.providers["ollama"].enabled = False
        config.llm.providers["zai"].enabled = False
        config.llm.providers["openrouter"].enabled = False
        router = LLMRouter(config)

        with pytest.raises(RuntimeError, match="No LLM provider"):
            router._select_provider_and_model("planning", None)

    def test_unhealthy_provider_skipped(self) -> None:
        config = self._make_config()
        router = LLMRouter(config)
        router._provider_health["openrouter"] = False

        # Planning prefers openrouter, but it's unhealthy
        provider, model = router._select_provider_and_model("planning", None)
        # Should fall through to coding fallback or priority list
        assert provider != "openrouter"

    def test_infer_provider(self) -> None:
        config = self._make_config()
        router = LLMRouter(config)
        assert (
            router._infer_provider("anthropic/claude-sonnet-4-20250514") == "openrouter"
        )
        assert router._infer_provider("openai/gpt-4o") == "openrouter"
        assert router._infer_provider("glm-4.7") == "zai"
        assert router._infer_provider("glm-4.7-flash") == "zai"
        assert router._infer_provider("qwen2.5:32b") == "ollama"
        assert router._infer_provider("llama3.1:8b") == "ollama"
