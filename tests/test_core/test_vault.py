"""Tests for the encrypted credential vault."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.vault import Vault, VaultError


class TestVault:
    def test_create_and_unlock(self, tmp_path: Path) -> None:
        vault = Vault.create(tmp_path, "password123")
        vault.set("google.com", {"email": "a@b.com", "password": "secret"})

        vault2 = Vault.unlock(tmp_path, "password123")
        creds = vault2.get("google.com")
        assert creds == {"email": "a@b.com", "password": "secret"}

    def test_wrong_password(self, tmp_path: Path) -> None:
        Vault.create(tmp_path, "correct")
        with pytest.raises(VaultError, match="Wrong password"):
            Vault.unlock(tmp_path, "wrong")

    def test_no_vault_exists(self, tmp_path: Path) -> None:
        with pytest.raises(VaultError, match="No vault found"):
            Vault.unlock(tmp_path, "anything")

    def test_exists_check(self, tmp_path: Path) -> None:
        assert not Vault.exists(tmp_path)
        Vault.create(tmp_path, "pw")
        assert Vault.exists(tmp_path)

    def test_set_get_delete(self, tmp_path: Path) -> None:
        vault = Vault.create(tmp_path, "pw")
        vault.set("site.com", {"user": "me", "password": "p"})

        assert vault.get("site.com") is not None
        assert vault.get("other.com") is None

        assert vault.delete("site.com") is True
        assert vault.get("site.com") is None
        assert vault.delete("site.com") is False

    def test_list_keys(self, tmp_path: Path) -> None:
        vault = Vault.create(tmp_path, "pw")
        assert vault.list_keys() == []

        vault.set("a.com", {"p": "1"})
        vault.set("b.com", {"p": "2"})
        assert sorted(vault.list_keys()) == ["a.com", "b.com"]

    def test_persistence_across_unlocks(self, tmp_path: Path) -> None:
        vault = Vault.create(tmp_path, "pw")
        vault.set("x.com", {"data": "value"})

        vault2 = Vault.unlock(tmp_path, "pw")
        assert vault2.get("x.com") == {"data": "value"}

        vault2.set("y.com", {"data": "other"})

        vault3 = Vault.unlock(tmp_path, "pw")
        assert vault3.get("x.com") == {"data": "value"}
        assert vault3.get("y.com") == {"data": "other"}

    def test_overwrite_existing_vault(self, tmp_path: Path) -> None:
        vault = Vault.create(tmp_path, "old-pw")
        vault.set("site.com", {"old": True})

        vault2 = Vault.create(tmp_path, "new-pw")
        assert vault2.list_keys() == []

        with pytest.raises(VaultError, match="Wrong password"):
            Vault.unlock(tmp_path, "old-pw")

        vault3 = Vault.unlock(tmp_path, "new-pw")
        assert vault3.list_keys() == []
