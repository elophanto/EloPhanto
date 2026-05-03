"""Wiring tests for the P2P sidecar integration into Agent.

These cover the *wiring* — the lifecycle integration is verified
without spawning the actual Go binary. The sidecar's own behaviour is
covered by test_peer_p2p.py; the agent's identity bridge is covered
here, and the agent_p2p_status tool is exercised against a mock.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from core.agent_identity import AgentIdentityKey
from core.config import Config, PeersConfig, load_config
from tools.agent_identity.p2p_status_tool import AgentP2PStatusTool

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestPeersConfig:
    def test_defaults_disabled(self) -> None:
        """Decentralized peers must be opt-in. The sidecar is a real
        process — silent activation would surprise operators."""
        cfg = Config()
        assert cfg.peers.enabled is False
        assert cfg.peers.bootstrap_nodes == []
        assert cfg.peers.relay_nodes == []
        assert cfg.peers.enable_auto_relay is True
        # use_default_bootstraps defaults True so operators get a working
        # cold-start out of the box; explicit list overrides via
        # bootstrap_nodes are merged with defaults via
        # effective_bootstrap_nodes().
        assert cfg.peers.use_default_bootstraps is True

    def test_effective_bootstrap_nodes_merge(self) -> None:
        """effective_bootstrap_nodes merges operator entries (first)
        with DEFAULT_BOOTSTRAP_NODES (fallback), deduped."""
        from core.config import DEFAULT_BOOTSTRAP_NODES, PeersConfig

        # Default-only.
        cfg = PeersConfig()
        assert cfg.effective_bootstrap_nodes() == DEFAULT_BOOTSTRAP_NODES

        # Operator + defaults.
        custom = "/ip4/192.0.2.1/tcp/4001/p2p/12D3KooWMy"
        cfg = PeersConfig(bootstrap_nodes=[custom])
        merged = cfg.effective_bootstrap_nodes()
        assert merged[0] == custom
        for default in DEFAULT_BOOTSTRAP_NODES:
            assert default in merged

        # Default disabled — operator only.
        cfg = PeersConfig(bootstrap_nodes=[custom], use_default_bootstraps=False)
        assert cfg.effective_bootstrap_nodes() == [custom]

        # Empty list with defaults disabled — empty (not a default fallback).
        cfg = PeersConfig(use_default_bootstraps=False)
        assert cfg.effective_bootstrap_nodes() == []

        # Dedup — operator listing the same multiaddr as default doesn't double it.
        if DEFAULT_BOOTSTRAP_NODES:
            cfg = PeersConfig(bootstrap_nodes=[DEFAULT_BOOTSTRAP_NODES[0]])
            merged = cfg.effective_bootstrap_nodes()
            assert merged.count(DEFAULT_BOOTSTRAP_NODES[0]) == 1

    def test_yaml_parser_round_trip(self, tmp_path) -> None:
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "peers:\n"
            "  enabled: true\n"
            "  listen_addrs:\n"
            "    - /ip4/0.0.0.0/tcp/4001\n"
            "    - /ip4/0.0.0.0/udp/4001/quic-v1\n"
            "  bootstrap_nodes:\n"
            "    - /dnsaddr/seed-1.example/p2p/12D3KooWAaa\n"
            "  relay_nodes:\n"
            "    - /dnsaddr/relay-1.example/p2p/12D3KooWBbb\n"
            "  enable_auto_relay: false\n"
            "  sidecar_binary: /opt/elophanto/elophanto-p2pd\n",
            encoding="utf-8",
        )
        loaded = load_config(cfg_path)
        assert loaded.peers.enabled is True
        assert loaded.peers.listen_addrs == [
            "/ip4/0.0.0.0/tcp/4001",
            "/ip4/0.0.0.0/udp/4001/quic-v1",
        ]
        assert loaded.peers.bootstrap_nodes == [
            "/dnsaddr/seed-1.example/p2p/12D3KooWAaa"
        ]
        assert loaded.peers.relay_nodes == ["/dnsaddr/relay-1.example/p2p/12D3KooWBbb"]
        assert loaded.peers.enable_auto_relay is False
        assert loaded.peers.sidecar_binary == "/opt/elophanto/elophanto-p2pd"

    def test_yaml_parser_omits_section_falls_back_to_defaults(self, tmp_path) -> None:
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("agent_name: Test\n", encoding="utf-8")
        loaded = load_config(cfg_path)
        assert loaded.peers == PeersConfig()


# ---------------------------------------------------------------------------
# Identity bridge — Ed25519 seed extraction
# ---------------------------------------------------------------------------


class TestIdentityBridge:
    def test_seed_hex_round_trip_through_libp2p_keytype(self) -> None:
        """The 32-byte raw seed we hand to the Go sidecar must reproduce
        the same Ed25519 public key on both sides — that's the whole
        point of the bridge (one identity across IDENTIFY + libp2p)."""
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        priv = Ed25519PrivateKey.generate()
        key = AgentIdentityKey(
            private_key=priv,
            public_key=priv.public_key(),
            agent_id="test-agent",
        )

        seed_hex = key.private_key_seed_hex()
        assert len(seed_hex) == 64  # 32 raw bytes -> 64 hex chars

        # Reconstruct from seed and confirm pubkey matches — same
        # round trip the Go sidecar does internally.
        from cryptography.hazmat.primitives import serialization

        seed_bytes = bytes.fromhex(seed_hex)
        recovered = Ed25519PrivateKey.from_private_bytes(seed_bytes)
        original_pub = key.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        recovered_pub = recovered.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        assert original_pub == recovered_pub


# ---------------------------------------------------------------------------
# agent_p2p_status tool
# ---------------------------------------------------------------------------


class TestP2PStatusTool:
    @pytest.mark.asyncio
    async def test_disabled_when_sidecar_missing(self) -> None:
        """When peers.enabled=false (or sidecar failed to start), the
        tool reports disabled cleanly with a usable hint instead of
        raising."""
        tool = AgentP2PStatusTool()
        result = await tool.execute({})
        assert result.success is True
        assert result.data["enabled"] is False
        assert "peers.enabled" in result.data["reason"]

    @pytest.mark.asyncio
    async def test_reports_status_when_sidecar_present(self) -> None:
        from core.peer_p2p import HostStatus

        tool = AgentP2PStatusTool()
        # Inject a fake sidecar — we're testing the tool's reporting
        # logic, not the sidecar itself.
        tool._p2p_sidecar = type("FakeSidecar", (), {})()
        tool._p2p_sidecar.host_status = AsyncMock(  # type: ignore[attr-defined]
            return_value=HostStatus(
                peer_id="12D3KooWZ",
                listen_addrs=["/ip4/192.0.2.1/tcp/4001"],
                peer_count=3,
                nat_reachability="public",
            )
        )
        tool._p2p_peer_id = "12D3KooWZ"
        result = await tool.execute({})
        assert result.success is True
        assert result.data["enabled"] is True
        assert result.data["peer_id"] == "12D3KooWZ"
        assert result.data["peer_count"] == 3
        assert result.data["nat_reachability"] == "public"
        assert "directly without" in result.data["hint"]

    @pytest.mark.asyncio
    async def test_private_nat_hint_warns_about_relay(self) -> None:
        from core.peer_p2p import HostStatus

        tool = AgentP2PStatusTool()
        tool._p2p_sidecar = type("FakeSidecar", (), {})()
        tool._p2p_sidecar.host_status = AsyncMock(  # type: ignore[attr-defined]
            return_value=HostStatus(
                peer_id="12D3KooWP",
                listen_addrs=[],
                peer_count=0,
                nat_reachability="private",
            )
        )
        result = await tool.execute({})
        assert "relay" in result.data["hint"].lower()

    @pytest.mark.asyncio
    async def test_sidecar_failure_surfaces_error(self) -> None:
        tool = AgentP2PStatusTool()

        async def boom() -> Any:
            raise RuntimeError("sidecar exploded")

        tool._p2p_sidecar = type("FakeSidecar", (), {})()
        tool._p2p_sidecar.host_status = boom  # type: ignore[attr-defined]
        tool._p2p_peer_id = "12D3KooWE"

        result = await tool.execute({})
        assert result.success is False
        assert "sidecar exploded" in result.error
        # Even on failure we surface enabled=true + peer_id so the
        # operator can confirm the sidecar at least *started*.
        assert result.data["enabled"] is True
        assert result.data["peer_id"] == "12D3KooWE"


# ---------------------------------------------------------------------------
# Doctor check
# ---------------------------------------------------------------------------


class TestDoctorP2PCheck:
    def test_skips_when_peers_disabled(self, tmp_path) -> None:
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("peers:\n  enabled: false\n", encoding="utf-8")
        from cli.doctor_cmd import _check_p2p_sidecar

        result = _check_p2p_sidecar(tmp_path)
        assert result.status == "skip"
        assert "disabled" in result.detail

    def test_diversity_warns_when_only_defaults(self, tmp_path) -> None:
        cfg_path = tmp_path / "config.yaml"
        # peers.enabled with no bootstrap_nodes -> effective list is
        # exactly DEFAULT_BOOTSTRAP_NODES, which the diversity check
        # treats as a soft single point of failure.
        cfg_path.write_text("peers:\n  enabled: true\n", encoding="utf-8")
        from cli.doctor_cmd import _check_p2p_bootstrap_diversity

        result = _check_p2p_bootstrap_diversity(tmp_path)
        assert result.status == "warn"
        assert "single point of failure" in result.detail
        assert "peers.bootstrap_nodes" in (result.fix or "")

    def test_diversity_ok_with_operator_bootstrap(self, tmp_path) -> None:
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "peers:\n"
            "  enabled: true\n"
            "  bootstrap_nodes:\n"
            "    - /ip4/198.51.100.1/tcp/4001/p2p/12D3KooWMy\n",
            encoding="utf-8",
        )
        from cli.doctor_cmd import _check_p2p_bootstrap_diversity

        result = _check_p2p_bootstrap_diversity(tmp_path)
        assert result.status == "ok"
        assert "operator-controlled" in result.detail

    def test_diversity_warns_when_empty(self, tmp_path) -> None:
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "peers:\n" "  enabled: true\n" "  use_default_bootstraps: false\n",
            encoding="utf-8",
        )
        from cli.doctor_cmd import _check_p2p_bootstrap_diversity

        result = _check_p2p_bootstrap_diversity(tmp_path)
        assert result.status == "warn"
        assert "empty" in result.detail

    def test_diversity_skipped_when_peers_disabled(self, tmp_path) -> None:
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("peers:\n  enabled: false\n", encoding="utf-8")
        from cli.doctor_cmd import _check_p2p_bootstrap_diversity

        result = _check_p2p_bootstrap_diversity(tmp_path)
        assert result.status == "skip"

    def test_warns_when_enabled_but_binary_missing(self, tmp_path, monkeypatch) -> None:
        cfg_path = tmp_path / "config.yaml"
        # Point at a path that definitely doesn't exist; also clear
        # PATH so the autodiscover fallback doesn't accidentally pick
        # up a real binary on the dev box.
        cfg_path.write_text(
            "peers:\n"
            "  enabled: true\n"
            "  sidecar_binary: /nonexistent/elophanto-p2pd\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("ELOPHANTO_P2PD", raising=False)
        # Force find_sidecar_binary to come up empty.
        monkeypatch.setattr("core.peer_p2p.find_sidecar_binary", lambda: None)
        from cli.doctor_cmd import _check_p2p_sidecar

        result = _check_p2p_sidecar(tmp_path)
        assert result.status == "warn"
        assert "not found" in result.detail
        assert "go build" in (result.fix or "")
