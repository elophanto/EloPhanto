"""Retired model ids resolve to their replacement wherever a config names them."""

from __future__ import annotations

import pytest

from core.config import Config, LLMConfig, ProviderConfig, RoutingConfig
from core.model_aliases import RETIRED_MODELS, current_model
from core.router import LLMRouter


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-5.5", "gpt-6.1-sol"),
        ("gpt-5.5-mini", "gpt-6-luna"),
        ("codex/gpt-5.5", "codex/gpt-6.1-sol"),
        ("openai/gpt-5.5", "openai/gpt-6.1-sol"),
    ],
)
def test_retired_ids_resolve(model: str, expected: str) -> None:
    assert current_model(model) == expected


@pytest.mark.parametrize(
    "model",
    [
        "gpt-6.1-sol",
        "codex/gpt-6-luna",
        "gpt-5.55",
        "gpt-5.5-codex",
        "anthropic/claude-sonnet-5.5",
        "",
    ],
)
def test_live_ids_pass_through(model: str) -> None:
    assert current_model(model) == model


def test_no_replacement_is_itself_retired() -> None:
    assert not set(RETIRED_MODELS.values()) & set(RETIRED_MODELS)


def _router(models: dict[str, str]) -> LLMRouter:
    return LLMRouter(
        Config(
            llm=LLMConfig(
                providers={
                    "codex": ProviderConfig(enabled=True, default_model="gpt-5.5")
                },
                provider_priority=["codex"],
                routing={
                    "planning": RoutingConfig(preferred_provider="codex", models=models)
                },
            )
        )
    )


def test_router_resolves_retired_routing_entry() -> None:
    router = _router({"codex": "gpt-5.5"})
    assert router._select_provider_and_model("planning", None) == (
        "codex",
        "gpt-6.1-sol",
    )


def test_router_resolves_retired_default_model() -> None:
    router = _router({})
    assert router._select_provider_and_model("planning", None) == (
        "codex",
        "gpt-6.1-sol",
    )
    assert router.get_model_for_provider("codex") == "gpt-6.1-sol"


def test_router_resolves_retired_override() -> None:
    router = _router({})
    assert router._select_provider_and_model("planning", "codex/gpt-5.5") == (
        "codex",
        "gpt-6.1-sol",
    )
