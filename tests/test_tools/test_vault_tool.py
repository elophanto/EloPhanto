"""Tests for the vault lookup tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.vault import Vault
from tools.system.vault_tool import VaultLookupTool


class TestVaultLookupTool:
    def test_schema(self) -> None:
        tool = VaultLookupTool()
        assert tool.name == "vault_lookup"
        assert "domain" in tool.input_schema["properties"]

    @pytest.mark.asyncio
    async def test_no_vault(self) -> None:
        tool = VaultLookupTool()
        result = await tool.execute({"domain": "google.com"})
        assert not result.success
        assert "No vault available" in (result.error or "")

    @pytest.mark.asyncio
    async def test_lookup_found(self, tmp_path: Path) -> None:
        vault = Vault.create(tmp_path, "pw")
        vault.set("google.com", {"email": "me@gmail.com", "password": "secret"})

        tool = VaultLookupTool()
        tool._vault = vault
        result = await tool.execute({"domain": "google.com"})
        assert result.success
        assert result.data["credentials"]["email"] == "me@gmail.com"

    @pytest.mark.asyncio
    async def test_lookup_not_found(self, tmp_path: Path) -> None:
        vault = Vault.create(tmp_path, "pw")

        tool = VaultLookupTool()
        tool._vault = vault
        result = await tool.execute({"domain": "unknown.com"})
        assert not result.success
        assert "No credentials found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_partial_domain_match(self, tmp_path: Path) -> None:
        vault = Vault.create(tmp_path, "pw")
        vault.set("google.com", {"email": "me@gmail.com", "password": "s"})

        tool = VaultLookupTool()
        tool._vault = vault
        result = await tool.execute({"domain": "accounts.google.com"})
        assert result.success
        assert result.data["domain"] == "google.com"
