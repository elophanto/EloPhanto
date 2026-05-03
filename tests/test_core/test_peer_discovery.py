"""Peer discovery parser + tool tests.

Pure parsing tests against fixture JSON — no live tailscale needed.
The parser is the only piece with real logic; subprocess + HTTP probes
are I/O glue and tested at integration time.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.peer_discovery import (
    _AGENT_TAG,
    _parse_tailscale_peers,
    discover_peers,
    is_tailscale_available,
)


class TestTailscaleParser:
    def test_empty_status_returns_empty(self) -> None:
        assert _parse_tailscale_peers({}, 18789) == []

    def test_parses_modern_peer_dict_shape(self) -> None:
        """Tailscale ≥1.50 uses Peer: dict[str, dict] keyed by node ID."""
        fixture = {
            "Peer": {
                "node-aaa": {
                    "HostName": "home",
                    "DNSName": "home.tailnet.ts.net.",
                    "TailscaleIPs": ["100.64.0.5"],
                    "Tags": [_AGENT_TAG],
                }
            }
        }
        peers = _parse_tailscale_peers(fixture, 18789)
        assert len(peers) == 1
        p = peers[0]
        assert p.hostname == "home"
        assert p.address == "home.tailnet.ts.net"  # trailing dot stripped
        assert p.url == "ws://home.tailnet.ts.net:18789"
        assert p.tagged is True
        assert p.method == "tailscale"

    def test_falls_back_to_ip_when_no_dns_name(self) -> None:
        fixture = {
            "Peer": {
                "x": {
                    "HostName": "ipless",
                    "TailscaleIPs": ["100.64.0.10"],
                }
            }
        }
        peers = _parse_tailscale_peers(fixture, 18789)
        assert peers[0].address == "100.64.0.10"
        assert peers[0].url == "ws://100.64.0.10:18789"

    def test_skips_peers_with_no_addresses(self) -> None:
        fixture = {"Peer": {"x": {"HostName": "ghost"}}}  # no DNS, no IPs
        assert _parse_tailscale_peers(fixture, 18789) == []

    def test_handles_legacy_list_shape(self) -> None:
        """Older tailscale versions returned `Peers` as a list."""
        fixture = {
            "Peers": [
                {"HostName": "x", "TailscaleIPs": ["100.64.0.1"]},
                {"HostName": "y", "TailscaleIPs": ["100.64.0.2"]},
            ]
        }
        peers = _parse_tailscale_peers(fixture, 18789)
        assert len(peers) == 2
        assert {p.hostname for p in peers} == {"x", "y"}

    def test_tagged_field_only_true_for_agent_tag(self) -> None:
        """A peer tagged with something other than tag:elophanto-agent
        is still returned (we'll probe it) but `tagged` is False."""
        fixture = {
            "Peer": {
                "x": {
                    "HostName": "other",
                    "TailscaleIPs": ["100.64.0.1"],
                    "Tags": ["tag:database"],
                }
            }
        }
        peers = _parse_tailscale_peers(fixture, 18789)
        assert peers[0].tagged is False

    def test_custom_port_used_in_url(self) -> None:
        fixture = {
            "Peer": {
                "x": {
                    "HostName": "h",
                    "DNSName": "h.tailnet.ts.net.",
                    "TailscaleIPs": ["100.64.0.1"],
                }
            }
        }
        peers = _parse_tailscale_peers(fixture, 9999)
        assert peers[0].url.endswith(":9999")

    def test_corrupt_payload_silently_skipped(self) -> None:
        """A peer entry that's not a dict (corrupt JSON, mid-version
        shape change) must not crash the whole parser."""
        fixture = {
            "Peer": {
                "good": {"HostName": "ok", "TailscaleIPs": ["100.64.0.1"]},
                "bad": "not-a-dict",
            }
        }
        peers = _parse_tailscale_peers(fixture, 18789)
        assert len(peers) == 1
        assert peers[0].hostname == "ok"


class TestDiscoverPeersDispatch:
    @pytest.mark.asyncio
    async def test_unknown_method_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            await discover_peers(method="mdns")

    @pytest.mark.asyncio
    async def test_no_tailscale_returns_empty(self) -> None:
        """If `tailscale` CLI isn't on PATH, return [] gracefully —
        not an exception. Caller (the agent_discover tool) translates
        empty into a helpful error message."""
        with patch("core.peer_discovery.is_tailscale_available", return_value=False):
            result = await discover_peers()
            assert result == []


class TestTailscaleAvailability:
    def test_returns_bool(self) -> None:
        # Just check the type — actual presence is host-dependent.
        assert isinstance(is_tailscale_available(), bool)
