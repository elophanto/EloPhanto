"""Outbound network policy — the agent must not be talked into calling home.

A fetched page or an injected instruction can propose any URL. These tests
pin the addresses that must never be reachable, including the encodings
that exist specifically to smuggle them past a naive check.
"""

from __future__ import annotations

import ipaddress

import pytest

from core.net_policy import (
    NetPolicy,
    NetPolicyError,
    check_url,
    is_blocked_ip,
)


class TestBlockedRanges:
    @pytest.mark.parametrize(
        "address,why",
        [
            ("127.0.0.1", "loopback"),
            ("::1", "loopback"),
            ("10.0.0.5", "private"),
            ("192.168.1.1", "private"),
            ("172.16.0.1", "private"),
            ("169.254.169.254", "link-local"),  # cloud metadata
            ("100.64.0.1", "CGNAT"),
            ("224.0.0.1", "multicast"),
            ("0.0.0.0", "unspecified"),
            ("fd00::1", "private"),
        ],
    )
    def test_internal_addresses_are_blocked(self, address: str, why: str) -> None:
        blocked, reason = is_blocked_ip(ipaddress.ip_address(address))
        assert blocked, f"{address} should be blocked"
        assert reason

    def test_metadata_address_names_link_local_specifically(self) -> None:
        _, reason = is_blocked_ip(ipaddress.ip_address("169.254.169.254"))
        assert "link-local" in reason

    @pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "2606:4700::1111"])
    def test_public_addresses_pass(self, address: str) -> None:
        blocked, _ = is_blocked_ip(ipaddress.ip_address(address))
        assert not blocked


class TestEncodingBypasses:
    """Re-encoding a private address must not get it past the check."""

    def test_ipv4_mapped_ipv6_loopback_is_blocked(self) -> None:
        blocked, reason = is_blocked_ip(ipaddress.ip_address("::ffff:127.0.0.1"))
        assert blocked
        assert "embedded" in reason.lower() or "loopback" in reason.lower()

    def test_nat64_embedded_private_address_is_blocked(self) -> None:
        blocked, _ = is_blocked_ip(ipaddress.ip_address("64:ff9b::a00:1"))
        assert blocked

    def test_6to4_embedded_private_address_is_blocked(self) -> None:
        blocked, _ = is_blocked_ip(ipaddress.ip_address("2002:0a00:0001::"))
        assert blocked


class TestCheckUrl:
    def test_public_https_allowed(self) -> None:
        assert check_url("https://example.com/api") == "https://example.com/api"

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "gopher://example.com",
            "ftp://example.com",
            "data:text/plain,hello",
        ],
    )
    def test_non_http_schemes_refused(self, url: str) -> None:
        with pytest.raises(NetPolicyError, match="scheme"):
            check_url(url)

    def test_localhost_refused(self) -> None:
        with pytest.raises(NetPolicyError, match="blocked hostname"):
            check_url("http://localhost:8080/admin")

    def test_metadata_endpoint_refused(self) -> None:
        with pytest.raises(NetPolicyError):
            check_url("http://169.254.169.254/latest/meta-data/")

    def test_google_metadata_hostname_refused(self) -> None:
        with pytest.raises(NetPolicyError, match="blocked hostname"):
            check_url("http://metadata.google.internal/computeMetadata/v1/")

    def test_deny_list_wins(self) -> None:
        policy = NetPolicy(deny_hosts=["evil.example"])
        with pytest.raises(NetPolicyError, match="deny list"):
            check_url("https://evil.example/x", policy)

    def test_allowlist_only_blocks_everything_else(self) -> None:
        policy = NetPolicy(allow_hosts=["good.example"], allowlist_only=True)
        assert check_url("https://good.example/x", policy)
        with pytest.raises(NetPolicyError, match="allowlist-only"):
            check_url("https://other.example/x", policy)

    def test_explicit_allow_is_the_break_glass_for_internal_hosts(self) -> None:
        policy = NetPolicy(allow_hosts=["nas.local"])
        # Would otherwise be refused; the operator opted in explicitly.
        assert check_url("http://nas.local/api", policy)

    def test_suspicious_port_refused_unless_host_allowed(self) -> None:
        with pytest.raises(NetPolicyError, match="internal service"):
            check_url("https://example.com:6379/", NetPolicy())
        assert check_url(
            "https://example.com:6379/", NetPolicy(allow_hosts=["example.com"])
        )

    def test_missing_hostname_refused(self) -> None:
        with pytest.raises(NetPolicyError):
            check_url("https:///nohost")
