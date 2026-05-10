"""ProxyConfig tests — proxy URL building, defaults, parser.

Pins the v1 contract documented in docs/73-PROXY-ROUTING.md:
- Disabled by default; empty host/port means no routing
- `apply_to` defaults to ['browser'] in v1; other groups ignored
- `proxy_url()` builds Chrome-compatible scheme://host:port (no creds
  embedded — those go via Playwright's separate username/password
  fields)
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.config import ProxyConfig, load_config


class TestProxyConfigDefaults:
    def test_disabled_by_default(self) -> None:
        cfg = ProxyConfig()
        assert cfg.enabled is False
        assert cfg.host == ""
        assert cfg.port == 0

    def test_default_credentials_empty(self) -> None:
        cfg = ProxyConfig()
        assert cfg.username == ""
        assert cfg.password == ""

    def test_default_apply_to_is_browser_only(self) -> None:
        cfg = ProxyConfig()
        assert cfg.apply_to == ["browser"]

    def test_default_type_is_socks5(self) -> None:
        cfg = ProxyConfig()
        assert cfg.type == "socks5"


class TestProxyUrl:
    def test_empty_when_disabled(self) -> None:
        cfg = ProxyConfig(host="x", port=1)
        assert cfg.proxy_url() == ""

    def test_empty_when_no_host(self) -> None:
        cfg = ProxyConfig(enabled=True, port=1)
        assert cfg.proxy_url() == ""

    def test_empty_when_no_port(self) -> None:
        cfg = ProxyConfig(enabled=True, host="x")
        assert cfg.proxy_url() == ""

    def test_socks5_format(self) -> None:
        cfg = ProxyConfig(
            enabled=True, type="socks5", host="proxy.iproyal.com", port=12321
        )
        assert cfg.proxy_url() == "socks5://proxy.iproyal.com:12321"

    def test_http_format(self) -> None:
        cfg = ProxyConfig(
            enabled=True, type="http", host="proxy.smartproxy.com", port=7000
        )
        assert cfg.proxy_url() == "http://proxy.smartproxy.com:7000"

    def test_https_format(self) -> None:
        cfg = ProxyConfig(enabled=True, type="https", host="netnut.io", port=9090)
        assert cfg.proxy_url() == "https://netnut.io:9090"


class TestProxyConfigParsing:
    """Pin the YAML → ProxyConfig parser behaviour from load_config."""

    def _write_config(self, tmp_path: Path, proxy_section: dict) -> Path:
        """Write a minimal valid config.yaml with just the proxy section."""
        cfg = {
            "agent_name": "Test",
            "llm": {"providers": {}, "routing": {}, "budget": {}, "tool_profiles": {}},
            "proxy": proxy_section,
        }
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(cfg))
        return path

    def test_disabled_when_section_missing(self, tmp_path: Path) -> None:
        cfg = {
            "agent_name": "Test",
            "llm": {"providers": {}, "routing": {}, "budget": {}, "tool_profiles": {}},
        }
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(cfg))
        loaded = load_config(path)
        assert loaded.proxy.enabled is False
        assert loaded.proxy.apply_to == ["browser"]

    def test_full_config_parses(self, tmp_path: Path) -> None:
        path = self._write_config(
            tmp_path,
            {
                "enabled": True,
                "type": "socks5",
                "host": "86.109.84.59",
                "port": 12323,
                "username": "14acbb4d2e0d2",
                "password": "4376fd52bf",
                "bypass": ["*.internal", "example.com"],
                "apply_to": ["browser", "web_search"],
            },
        )
        loaded = load_config(path)
        assert loaded.proxy.enabled is True
        assert loaded.proxy.type == "socks5"
        assert loaded.proxy.host == "86.109.84.59"
        assert loaded.proxy.port == 12323
        assert loaded.proxy.username == "14acbb4d2e0d2"
        assert loaded.proxy.password == "4376fd52bf"
        assert loaded.proxy.bypass == ["*.internal", "example.com"]
        assert loaded.proxy.apply_to == ["browser", "web_search"]
        # And the URL builds correctly (no embedded creds — Playwright
        # passes username/password separately at launch)
        assert loaded.proxy.proxy_url() == "socks5://86.109.84.59:12323"

    def test_invalid_type_falls_back_to_socks5(self, tmp_path: Path) -> None:
        path = self._write_config(
            tmp_path,
            {"enabled": True, "type": "gopher", "host": "x", "port": 1},
        )
        loaded = load_config(path)
        assert loaded.proxy.type == "socks5"

    def test_type_case_insensitive(self, tmp_path: Path) -> None:
        path = self._write_config(
            tmp_path,
            {"enabled": True, "type": "HTTP", "host": "x", "port": 1},
        )
        loaded = load_config(path)
        assert loaded.proxy.type == "http"

    def test_non_string_bypass_entries_filtered(self, tmp_path: Path) -> None:
        # Operator typo: list with mixed types — only keep strings.
        path = self._write_config(
            tmp_path,
            {
                "enabled": True,
                "host": "x",
                "port": 1,
                "bypass": ["good.com", 42, None, "also-good.com"],
            },
        )
        loaded = load_config(path)
        assert loaded.proxy.bypass == ["good.com", "also-good.com"]

    def test_empty_apply_to_defaults_to_browser(self, tmp_path: Path) -> None:
        path = self._write_config(
            tmp_path,
            {"enabled": True, "host": "x", "port": 1, "apply_to": []},
        )
        loaded = load_config(path)
        # Empty list → falls back to default per parser
        assert loaded.proxy.apply_to == ["browser"]


class TestProxyDocAssumptions:
    """Pin assumptions the doc + threat model rely on."""

    def test_loopback_must_be_in_default_bypass_in_bridge(self) -> None:
        """The bridge auto-bypasses loopback and the Tailscale CGNAT
        range. This test pins the documented contract — the actual
        bypass list lives in TypeScript (bridge/browser/src/
        browser-agent.ts buildProxyOption). Doc and code must agree."""
        # The Python side never sees the auto-bypass list; we just
        # document that it exists. This test prevents silent doc drift
        # by asserting the doc claims what we believe.
        doc_path = Path(__file__).resolve().parents[2] / "docs" / "73-PROXY-ROUTING.md"
        if not doc_path.exists():
            pytest.skip("doc not present")
        text = doc_path.read_text(encoding="utf-8")
        assert "loopback" in text.lower()
        assert "100.64" in text or "tailnet" in text.lower()
