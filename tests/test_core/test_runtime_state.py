"""Tests for core/runtime_state.py — runtime state XML builder."""

from __future__ import annotations

from unittest.mock import MagicMock

from core.runtime_state import build_runtime_state
from tools.base import PermissionLevel


def _mock_tool(name: str, permission: PermissionLevel) -> MagicMock:
    t = MagicMock()
    t.name = name
    t.permission_level = permission
    return t


class TestBuildRuntimeState:
    def test_default_output(self) -> None:
        """Default parameters should produce valid XML."""
        result = build_runtime_state()
        assert "<runtime_state>" in result
        assert "</runtime_state>" in result
        assert 'status="unavailable"' in result

    def test_fingerprint_included(self) -> None:
        """Fingerprint should appear in output when provided."""
        result = build_runtime_state(
            fingerprint="abcdef123456",
            fingerprint_status="verified",
        )
        assert 'status="verified"' in result
        assert "abcdef123456" in result

    def test_tool_counting(self) -> None:
        """Tool counts should be correct by permission level."""
        tools = [
            _mock_tool("t1", PermissionLevel.SAFE),
            _mock_tool("t2", PermissionLevel.SAFE),
            _mock_tool("t3", PermissionLevel.MODERATE),
            _mock_tool("t4", PermissionLevel.DESTRUCTIVE),
            _mock_tool("t5", PermissionLevel.CRITICAL),
        ]
        result = build_runtime_state(tools=tools)
        assert 'total="5"' in result
        assert 'safe="2"' in result
        assert 'moderate="1"' in result
        assert 'destructive="1"' in result
        assert 'critical="1"' in result

    def test_authority_in_output(self) -> None:
        """Authority level and channel should appear."""
        result = build_runtime_state(authority="trusted", channel="discord")
        assert 'current_user="trusted"' in result
        assert 'channel="discord"' in result

    def test_context_mode(self) -> None:
        """Context mode should appear."""
        result = build_runtime_state(context_mode="mind")
        assert 'mode="mind"' in result

    def test_empty_tools(self) -> None:
        """Empty tool list should show all zeros."""
        result = build_runtime_state(tools=[])
        assert 'total="0"' in result
        assert 'safe="0"' in result

    def test_no_fingerprint_self_closing(self) -> None:
        """No fingerprint should produce self-closing tag."""
        result = build_runtime_state(fingerprint="", fingerprint_status="unavailable")
        assert 'status="unavailable"/>' in result

    def test_storage_line_present(self) -> None:
        """Storage element should appear when status is provided."""
        result = build_runtime_state(
            storage_status="warning",
            storage_used_mb=1600.0,
            storage_quota_mb=2000.0,
        )
        assert "<storage" in result
        assert 'status="warning"' in result
        assert 'used_mb="1600.0"' in result
        assert 'quota_mb="2000.0"' in result

    def test_storage_line_absent_when_empty(self) -> None:
        """Storage element should NOT appear when status is empty."""
        result = build_runtime_state(storage_status="")
        assert "<storage" not in result

    def test_processes_line_present(self) -> None:
        """Processes element should always appear."""
        result = build_runtime_state(active_processes=3, max_processes=10)
        assert "<processes" in result
        assert 'active="3"' in result
        assert 'max="10"' in result

    def test_processes_default_values(self) -> None:
        """Default process values should be 0 active, 10 max."""
        result = build_runtime_state()
        assert 'active="0"' in result
        assert 'max="10"' in result

    def test_providers_line_present(self) -> None:
        """<providers> XML element should appear when provider_stats given."""
        stats = {
            "openrouter": {
                "total_calls": 42,
                "failures": 1,
                "truncations": 0,
                "avg_latency_ms": 1200,
            },
            "zai": {
                "total_calls": 30,
                "failures": 3,
                "truncations": 2,
                "avg_latency_ms": 800,
            },
        }
        result = build_runtime_state(provider_stats=stats)
        assert "<providers>" in result
        assert "</providers>" in result
        assert 'name="openrouter"' in result
        assert 'calls="42"' in result
        assert 'failures="1"' in result
        assert 'name="zai"' in result
        assert 'truncations="2"' in result

    def test_providers_line_absent(self) -> None:
        """<providers> should NOT appear when provider_stats is None."""
        result = build_runtime_state(provider_stats=None)
        assert "<providers>" not in result

    def test_providers_line_absent_empty(self) -> None:
        """<providers> should NOT appear when provider_stats is empty dict."""
        result = build_runtime_state(provider_stats={})
        assert "<providers>" not in result
