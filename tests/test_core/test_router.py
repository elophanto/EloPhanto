"""Router model selection tests."""

from __future__ import annotations

import pytest

from core.config import BudgetConfig, Config, LLMConfig, ProviderConfig, RoutingConfig
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
                        models={
                            "openrouter": "anthropic/claude-sonnet-4.6",
                            "zai": "glm-5",
                            "ollama": "qwen2.5:32b",
                        },
                    ),
                    "coding": RoutingConfig(
                        preferred_provider="zai",
                        models={
                            "zai": "glm-4.7",
                            "openrouter": "qwen/qwen3.5-plus-02-15",
                            "ollama": "qwen2.5-coder:32b",
                        },
                    ),
                    "simple": RoutingConfig(
                        preferred_provider="zai",
                        models={
                            "zai": "glm-4.7",
                            "openrouter": "minimax/minimax-m2.5",
                            "ollama": "llama3.2:3b",
                        },
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
        assert model == "anthropic/claude-sonnet-4.6"

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
        assert model == "glm-4.7"

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

        # Coding prefers zai, should fallback via provider_priority
        provider, model = router._select_provider_and_model("coding", None)
        # ollama is first in priority, has a model in the map
        assert provider == "ollama"
        assert model == "qwen2.5-coder:32b"

    def test_fallback_to_openrouter_via_priority(self) -> None:
        config = self._make_config()
        config.llm.providers["zai"].enabled = False
        config.llm.providers["ollama"].enabled = False
        router = LLMRouter(config)

        # Coding: zai disabled, ollama disabled → openrouter via priority
        provider, model = router._select_provider_and_model("coding", None)
        assert provider == "openrouter"
        assert model == "qwen/qwen3.5-plus-02-15"

    def test_provider_priority_fallthrough(self) -> None:
        config = self._make_config()
        # Disable all preferred providers
        config.llm.providers["openrouter"].enabled = False
        config.llm.providers["zai"].enabled = False
        router = LLMRouter(config)

        # Planning prefers openrouter, should fall through to ollama via priority
        provider, model = router._select_provider_and_model("planning", None)
        assert provider == "ollama"
        assert model == "qwen2.5:32b"

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
        router._mark_unhealthy("openrouter")

        # Planning prefers openrouter, but it's unhealthy
        provider, model = router._select_provider_and_model("planning", None)
        assert provider != "openrouter"

    def test_infer_provider(self) -> None:
        config = self._make_config()
        router = LLMRouter(config)
        assert router._infer_provider("anthropic/claude-sonnet-4.6") == "openrouter"
        assert router._infer_provider("openai/gpt-4o") == "openrouter"
        assert router._infer_provider("glm-4.7") == "zai"
        assert router._infer_provider("glm-4.7-flash") == "zai"
        assert router._infer_provider("qwen2.5:32b") == "ollama"
        assert router._infer_provider("llama3.1:8b") == "ollama"

    def test_models_map_lookup_per_provider(self) -> None:
        """Each provider resolves its own model from the models map."""
        config = self._make_config()
        router = LLMRouter(config)

        # Planning: each provider gets its own model
        assert (
            router._resolve_model("openrouter", "planning")
            == "anthropic/claude-sonnet-4.6"
        )
        assert router._resolve_model("zai", "planning") == "glm-5"
        assert router._resolve_model("ollama", "planning") == "qwen2.5:32b"

        # Coding
        assert router._resolve_model("zai", "coding") == "glm-4.7"
        assert (
            router._resolve_model("openrouter", "coding") == "qwen/qwen3.5-plus-02-15"
        )
        assert router._resolve_model("ollama", "coding") == "qwen2.5-coder:32b"

    def test_resolve_model_unknown_provider_returns_none(self) -> None:
        config = self._make_config()
        router = LLMRouter(config)
        assert router._resolve_model("unknown", "planning") is None

    def test_resolve_model_unknown_task_returns_none(self) -> None:
        config = self._make_config()
        router = LLMRouter(config)
        assert router._resolve_model("openrouter", "unknown_task") is None


class TestLegacyRoutingCompat:
    """Legacy configs with flat fields (preferred_model etc.) still work."""

    def _make_legacy_config(self) -> Config:
        return Config(
            llm=LLMConfig(
                providers={
                    "ollama": ProviderConfig(
                        enabled=True, base_url="http://localhost:11434"
                    ),
                    "zai": ProviderConfig(
                        enabled=True,
                        api_key="test-key",
                        default_model="glm-4.7",
                    ),
                    "openrouter": ProviderConfig(
                        enabled=True,
                        api_key="test-key",
                        base_url="https://openrouter.ai/api/v1",
                    ),
                },
                provider_priority=["zai", "openrouter", "ollama"],
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
                },
                budget=BudgetConfig(daily_limit_usd=10.0, per_task_limit_usd=2.0),
            ),
        )

    def test_legacy_preferred_model_works(self) -> None:
        config = self._make_legacy_config()
        router = LLMRouter(config)
        provider, model = router._select_provider_and_model("planning", None)
        assert provider == "openrouter"
        assert model == "anthropic/claude-sonnet-4-20250514"

    def test_legacy_fallback_fields_work(self) -> None:
        config = self._make_legacy_config()
        config.llm.providers["zai"].enabled = False
        router = LLMRouter(config)

        # Coding: zai disabled → openrouter via fallback_provider/fallback_model
        provider, model = router._select_provider_and_model("coding", None)
        assert provider == "openrouter"
        assert model == "anthropic/claude-sonnet-4-20250514"

    def test_legacy_local_fallback_works(self) -> None:
        config = self._make_legacy_config()
        config.llm.providers["openrouter"].enabled = False
        config.llm.providers["zai"].enabled = False
        router = LLMRouter(config)

        provider, model = router._select_provider_and_model("planning", None)
        assert provider == "ollama"
        assert model == "qwen2.5:32b"

    def test_legacy_zai_default_model_fallback(self) -> None:
        """Z.ai provider-level default_model used when no models map entry."""
        config = self._make_legacy_config()
        router = LLMRouter(config)

        # "simple" task has no routing config at all — falls through to provider_priority
        # zai is first, should use its default_model
        provider, model = router._select_provider_and_model("simple", None)
        assert provider == "zai"
        assert model == "glm-4.7"
