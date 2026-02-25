"""Tests for core/fingerprint.py — agent fingerprint generation and verification."""

from __future__ import annotations

from unittest.mock import MagicMock

from core.fingerprint import (
    compute_config_hash,
    generate_fingerprint,
    get_or_create_fingerprint,
)


class TestGenerateFingerprint:
    def test_deterministic(self) -> None:
        """Same inputs should produce the same fingerprint."""
        fp1 = generate_fingerprint("hash1", "salt1")
        fp2 = generate_fingerprint("hash1", "salt1")
        assert fp1 == fp2

    def test_different_config(self) -> None:
        """Different config hash should produce different fingerprint."""
        fp1 = generate_fingerprint("hash1", "salt1")
        fp2 = generate_fingerprint("hash2", "salt1")
        assert fp1 != fp2

    def test_different_salt(self) -> None:
        """Different vault salt should produce different fingerprint."""
        fp1 = generate_fingerprint("hash1", "salt1")
        fp2 = generate_fingerprint("hash1", "salt2")
        assert fp1 != fp2

    def test_hex_format(self) -> None:
        """Fingerprint should be a 64-char hex string (SHA-256)."""
        fp = generate_fingerprint("test", "test")
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)


class TestComputeConfigHash:
    def test_deterministic(self) -> None:
        """Same config should produce the same hash."""
        config = MagicMock()
        config.agent_name = "EloPhanto"
        config.project_root = "/some/path"
        config.permission_mode = "ask_always"

        h1 = compute_config_hash(config)
        h2 = compute_config_hash(config)
        assert h1 == h2

    def test_different_name(self) -> None:
        """Different agent name should produce different hash."""
        c1 = MagicMock()
        c1.agent_name = "EloPhanto"
        c1.project_root = "/some/path"
        c1.permission_mode = "ask_always"

        c2 = MagicMock()
        c2.agent_name = "OtherAgent"
        c2.project_root = "/some/path"
        c2.permission_mode = "ask_always"

        assert compute_config_hash(c1) != compute_config_hash(c2)


class TestGetOrCreateFingerprint:
    def test_first_boot_creates(self) -> None:
        """First boot (no stored fingerprint) should create and store."""
        vault = MagicMock()
        vault.get.return_value = None

        fp, status = get_or_create_fingerprint(vault, "config_hash", "salt_hash")

        assert status == "created"
        assert len(fp) == 64
        vault.set.assert_called_once()

    def test_verified_on_match(self) -> None:
        """Matching fingerprint should return 'verified'."""
        expected = generate_fingerprint("config_hash", "salt_hash")
        vault = MagicMock()
        vault.get.return_value = {"fingerprint": expected, "config_hash": "config_hash"}

        fp, status = get_or_create_fingerprint(vault, "config_hash", "salt_hash")

        assert status == "verified"
        assert fp == expected
        vault.set.assert_not_called()

    def test_changed_on_drift(self) -> None:
        """Changed config should detect drift and re-stamp."""
        old_fp = generate_fingerprint("old_hash", "salt_hash")
        vault = MagicMock()
        vault.get.return_value = {"fingerprint": old_fp, "config_hash": "old_hash"}

        fp, status = get_or_create_fingerprint(vault, "new_hash", "salt_hash")

        assert status == "changed"
        assert fp != old_fp
        vault.set.assert_called_once()
        stored = vault.set.call_args[0][1]
        assert stored["previous_fingerprint"] == old_fp
