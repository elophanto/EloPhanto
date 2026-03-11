"""Kimi adapter tests.

Tests adapter instantiation, cost estimation, model mapping, and health
check setup without making actual API calls.
"""

from __future__ import annotations

import pytest

from core.config import Config, LLMConfig, ProviderConfig
from core.kimi_adapter import KIMI_COSTS, KIMI_MODEL_MAP, KimiAdapter


@pytest.fixture
def adapter() -> KimiAdapter:
    config = Config(
        llm=LLMConfig(
            providers={
                "kimi": ProviderConfig(
                    api_key="test-key",
                    enabled=True,
                    base_url="https://api.kilo.ai/api/gateway",
                    default_model="kimi-k2.5",
                ),
            }
        )
    )
    return KimiAdapter(config)


class TestKimiAdapter:
    def test_init_sets_base_url(self, adapter: KimiAdapter) -> None:
        assert adapter._base_url == "https://api.kilo.ai/api/gateway"

    def test_init_sets_default_model(self, adapter: KimiAdapter) -> None:
        assert adapter._default_model == "kimi-k2.5"

    def test_init_default_base_url(self) -> None:
        """Uses default base URL when none configured."""
        config = Config(
            llm=LLMConfig(
                providers={
                    "kimi": ProviderConfig(
                        api_key="test-key",
                        enabled=True,
                        default_model="kimi-k2.5",
                    ),
                }
            )
        )
        adapter = KimiAdapter(config)
        assert adapter._base_url == "https://api.kilo.ai/api/gateway"

    def test_init_raises_without_config(self) -> None:
        config = Config(llm=LLMConfig(providers={}))
        with pytest.raises(ValueError, match="Kimi provider not configured"):
            KimiAdapter(config)

    def test_cost_table_has_expected_models(self) -> None:
        assert "kimi-k2.5" in KIMI_COSTS
        assert "kimi-k2-thinking-turbo" in KIMI_COSTS

    def test_cost_structure(self) -> None:
        for model, costs in KIMI_COSTS.items():
            assert "input" in costs, f"{model} missing input cost"
            assert "output" in costs, f"{model} missing output cost"
            assert costs["input"] > 0
            assert costs["output"] > 0

    def test_model_map_resolves_to_gateway_ids(self) -> None:
        """Internal model names map to moonshotai/ gateway IDs."""
        assert KIMI_MODEL_MAP["kimi-k2.5"] == "moonshotai/kimi-k2.5"
        assert "moonshotai/" in KIMI_MODEL_MAP["kimi-k2-thinking-turbo"]


class TestKimiRouterIntegration:
    def test_infer_provider_kimi(self) -> None:
        from core.router import LLMRouter

        config = Config(llm=LLMConfig(providers={}))
        router = LLMRouter(config)
        assert router._infer_provider("kimi-k2.5") == "kimi"
        assert router._infer_provider("kimi-k2-thinking-turbo") == "kimi"

    def test_resolve_model_kimi_default(self) -> None:
        from core.router import LLMRouter

        config = Config(
            llm=LLMConfig(
                providers={
                    "kimi": ProviderConfig(
                        api_key="test-key",
                        enabled=True,
                        default_model="kimi-k2.5",
                    ),
                }
            )
        )
        router = LLMRouter(config)
        model = router._resolve_model("kimi", "planning")
        assert model == "kimi-k2.5"
