"""Tests for core/kid_bootstrap.py — vault consumption, env clearing,
config build, agent construction. These run on the host (not inside a
container) since the bootstrap module is pure Python that just builds
in-memory state. Container-actually-running tests are integration only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.kid_bootstrap import (
    _VAULT_ENV,
    _consume_vault_env,
    build_kid_config,
)


class TestVaultConsumption:
    def test_consume_strips_env_var_after_read(self) -> None:
        os.environ[_VAULT_ENV] = json.dumps({"openrouter": "secret"})
        try:
            subset = _consume_vault_env()
            assert subset == {"openrouter": "secret"}
            # Critical invariant: env var is GONE after consumption.
            # /proc/<pid>/environ exposure window is bounded.
            assert _VAULT_ENV not in os.environ
        finally:
            os.environ.pop(_VAULT_ENV, None)

    def test_missing_env_returns_empty_dict(self) -> None:
        os.environ.pop(_VAULT_ENV, None)
        assert _consume_vault_env() == {}

    def test_malformed_json_returns_empty_dict(self) -> None:
        os.environ[_VAULT_ENV] = "{not valid json"
        try:
            assert _consume_vault_env() == {}
            # Even on parse failure, the env var must be cleared so a
            # malformed payload doesn't linger.
            assert _VAULT_ENV not in os.environ
        finally:
            os.environ.pop(_VAULT_ENV, None)

    def test_non_dict_payload_returns_empty(self) -> None:
        os.environ[_VAULT_ENV] = json.dumps(["not", "a", "dict"])
        try:
            assert _consume_vault_env() == {}
        finally:
            os.environ.pop(_VAULT_ENV, None)

    def test_values_coerced_to_strings(self) -> None:
        os.environ[_VAULT_ENV] = json.dumps({"port": 8080, "key": "abc"})
        try:
            subset = _consume_vault_env()
            assert subset == {"port": "8080", "key": "abc"}
        finally:
            os.environ.pop(_VAULT_ENV, None)


class TestKidConfigBuild:
    def test_empty_subset_yields_no_providers(self, tmp_path: Path) -> None:
        cfg = build_kid_config({}, project_root=tmp_path)
        assert cfg.llm.providers == {}
        assert cfg.llm.provider_priority == []

    def test_known_keys_become_provider_api_keys(self, tmp_path: Path) -> None:
        subset = {"openrouter": "or-key", "openai": "oai-key"}
        cfg = build_kid_config(subset, project_root=tmp_path)
        assert cfg.llm.providers["openrouter"].api_key == "or-key"
        assert cfg.llm.providers["openrouter"].enabled is True
        assert cfg.llm.providers["openai"].api_key == "oai-key"
        assert cfg.llm.providers["openai"].enabled is True

    def test_unknown_keys_silently_ignored(self, tmp_path: Path) -> None:
        """Garbage keys don't crash, don't become providers."""
        subset = {"openrouter": "or-key", "twitter_token": "tw-token"}
        cfg = build_kid_config(subset, project_root=tmp_path)
        # Only openrouter became a provider
        assert "openrouter" in cfg.llm.providers
        # twitter_token is not a provider — just sits as data the kid
        # might use for tool config but doesn't auto-wire.
        assert "twitter_token" not in cfg.llm.providers

    def test_disables_dangerous_features(self, tmp_path: Path) -> None:
        """Hard invariant: kid config disables organization, kids,
        swarm, payments. These are blocked at the config level even
        before the registry filter runs."""
        cfg = build_kid_config({}, project_root=tmp_path)
        assert cfg.organization.enabled is False
        assert cfg.kids.enabled is False  # depth=1
        assert cfg.swarm.enabled is False
        assert cfg.payments.enabled is False
        assert cfg.identity.enabled is False  # kids don't evolve identity

    def test_provider_priority_matches_granted_providers(self, tmp_path: Path) -> None:
        subset = {"openrouter": "k1", "huggingface": "k2"}
        cfg = build_kid_config(subset, project_root=tmp_path)
        # Priority covers exactly what was granted (no phantom providers)
        assert set(cfg.llm.provider_priority) == {"openrouter", "huggingface"}

    def test_config_uses_provided_project_root(self, tmp_path: Path) -> None:
        cfg = build_kid_config({}, project_root=tmp_path)
        assert cfg.project_root == tmp_path


class TestKidMainRefusesWithoutEnvFlag:
    @pytest.mark.asyncio
    async def test_refuses_when_elophanto_kid_not_set(self, monkeypatch) -> None:
        """Safety: kid_main only runs when ELOPHANTO_KID=true. Otherwise
        somebody invoked it on the host by mistake — exit non-zero."""
        from core.kid_bootstrap import kid_main

        monkeypatch.delenv("ELOPHANTO_KID", raising=False)
        rc = await kid_main()
        assert rc != 0
