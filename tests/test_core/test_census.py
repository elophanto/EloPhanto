"""Tests for Agent Census — fingerprint, payload, and heartbeat behavior."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.census import (
    _SALT,
    CENSUS_URL,
    _build_payload,
    get_agent_fingerprint,
    send_heartbeat,
)

# ---------------------------------------------------------------------------
# Fingerprint tests
# ---------------------------------------------------------------------------


class TestFingerprint:
    """Agent fingerprint derivation."""

    def test_deterministic(self, tmp_path: Path) -> None:
        """Same machine UUID → same fingerprint across calls."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        fp1 = get_agent_fingerprint(data_dir)
        fp2 = get_agent_fingerprint(data_dir)
        assert fp1 == fp2

    def test_is_sha256_hex(self, tmp_path: Path) -> None:
        """Output is a valid 64-char hex string (SHA-256)."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        fp = get_agent_fingerprint(data_dir)
        assert len(fp) == 64
        assert re.fullmatch(r"[0-9a-f]{64}", fp)

    def test_fallback_creates_persistent_file(self, tmp_path: Path) -> None:
        """When machine UUID unavailable, generates and persists a random ID."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        with patch("core.census._get_machine_uuid", return_value=None):
            fp1 = get_agent_fingerprint(data_dir)
            # File should exist now
            assert (data_dir / ".census_id").exists()
            # Second call should return same fingerprint
            fp2 = get_agent_fingerprint(data_dir)
            assert fp1 == fp2

    def test_fallback_survives_reinstall(self, tmp_path: Path) -> None:
        """If data/.census_id exists from previous install, fingerprint matches."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # Simulate leftover file from previous install
        (data_dir / ".census_id").write_text("previous-install-uuid")

        with patch("core.census._get_machine_uuid", return_value=None):
            fp = get_agent_fingerprint(data_dir)
            expected = hashlib.sha256(
                f"previous-install-uuid{_SALT}".encode()
            ).hexdigest()
            assert fp == expected

    def test_different_machines_different_fingerprints(self) -> None:
        """Different machine UUIDs produce different fingerprints."""
        with patch("core.census._get_machine_uuid", return_value="machine-a"):
            fp_a = get_agent_fingerprint(Path("/tmp/nonexistent"))
        with patch("core.census._get_machine_uuid", return_value="machine-b"):
            fp_b = get_agent_fingerprint(Path("/tmp/nonexistent"))
        assert fp_a != fp_b


# ---------------------------------------------------------------------------
# Payload tests
# ---------------------------------------------------------------------------


class TestPayload:
    """Heartbeat payload construction."""

    _ALLOWED_FIELDS = {"agent_id", "v", "platform", "python", "first_seen"}

    def test_contains_only_allowed_fields(self, tmp_path: Path) -> None:
        """Payload contains ONLY the 5 specified fields."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        payload = _build_payload(data_dir)
        assert set(payload.keys()) == self._ALLOWED_FIELDS

    def test_no_pii(self, tmp_path: Path) -> None:
        """Payload does NOT contain hostname, username, IP, or paths."""
        import getpass
        import socket

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        payload = _build_payload(data_dir)
        payload_str = str(payload).lower()

        hostname = socket.gethostname().lower()
        username = getpass.getuser().lower()

        # These should not appear anywhere in the payload
        if len(hostname) > 3:  # Skip very short hostnames that might match
            assert hostname not in payload_str
        if len(username) > 3:
            assert username not in payload_str
        assert "/users/" not in payload_str
        assert "/home/" not in payload_str
        assert "c:\\users" not in payload_str

    def test_agent_id_prefixed(self, tmp_path: Path) -> None:
        """agent_id is prefixed with 'sha256:'."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        payload = _build_payload(data_dir)
        assert payload["agent_id"].startswith("sha256:")

    def test_first_seen_true_initially(self, tmp_path: Path) -> None:
        """first_seen is True when .census_sent marker doesn't exist."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        payload = _build_payload(data_dir)
        assert payload["first_seen"] is True

    def test_first_seen_false_after_send(self, tmp_path: Path) -> None:
        """first_seen is False when .census_sent marker exists."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / ".census_sent").write_text("1")
        payload = _build_payload(data_dir)
        assert payload["first_seen"] is False

    def test_version_is_string(self, tmp_path: Path) -> None:
        """Version field is a non-empty string."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        payload = _build_payload(data_dir)
        assert isinstance(payload["v"], str)
        assert len(payload["v"]) > 0

    def test_platform_format(self, tmp_path: Path) -> None:
        """Platform field follows 'os-arch' format."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        payload = _build_payload(data_dir)
        assert "-" in payload["platform"]


# ---------------------------------------------------------------------------
# Heartbeat behavior tests
# ---------------------------------------------------------------------------


class TestHeartbeat:
    """send_heartbeat() behavior — timeout, failure handling."""

    @pytest.mark.asyncio
    async def test_timeout_respected(self, tmp_path: Path) -> None:
        """Heartbeat respects the 3s timeout and doesn't hang."""
        import asyncio

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Should complete quickly even if the server is unreachable
        # (httpx will fail fast on connection refused)
        with patch("core.census.CENSUS_URL", "http://127.0.0.1:1"):
            try:
                await asyncio.wait_for(send_heartbeat(data_dir), timeout=5)
            except TimeoutError:
                pytest.fail("send_heartbeat hung past 5s — timeout not working")

    @pytest.mark.asyncio
    async def test_failure_silent(self, tmp_path: Path) -> None:
        """Network error doesn't raise — completely silent."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        with patch("core.census.CENSUS_URL", "http://127.0.0.1:1"):
            # Should NOT raise any exception
            await send_heartbeat(data_dir)

    @pytest.mark.asyncio
    async def test_success_creates_marker(self, tmp_path: Path) -> None:
        """Successful heartbeat creates .census_sent marker."""
        import httpx

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.census.httpx.AsyncClient", return_value=mock_client):
            await send_heartbeat(data_dir)

        assert (data_dir / ".census_sent").exists()

    @pytest.mark.asyncio
    async def test_posts_to_census_url(self, tmp_path: Path) -> None:
        """Heartbeat POSTs to the correct URL with correct payload shape."""
        import httpx

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.census.httpx.AsyncClient", return_value=mock_client):
            await send_heartbeat(data_dir)

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == CENSUS_URL
        payload = call_args[1]["json"]
        assert "agent_id" in payload
        assert "v" in payload
