"""``http_request`` — the guards must hold before a socket is ever opened.

These tests exercise the refusal paths, which is where the value is: the
happy path is just httpx, but a gap in the guards turns the agent into a
confused deputy with the operator's credentials.
"""

from __future__ import annotations

import pytest

from core.credentials import CredentialBroker, SecretString
from core.net_policy import NetPolicy
from core.scope_guard import ScopeGuard
from tools.base import PermissionLevel
from tools.http import HttpRequestTool


def _tool(
    *,
    owned: list[str] | None = None,
    broker: CredentialBroker | None = None,
    bindings: dict[str, str] | None = None,
) -> HttpRequestTool:
    tool = HttpRequestTool()
    tool._scope_guard = ScopeGuard(owned=owned or [])
    tool._net_policy = NetPolicy()
    tool._broker = broker
    tool._bindings = bindings or {}
    return tool


class TestDynamicPermission:
    def test_reads_are_safe(self) -> None:
        tool = _tool()
        assert (
            tool.dynamic_permission_level(
                {"url": "https://api.example.com/x", "method": "GET"}
            )
            == PermissionLevel.SAFE
        )

    def test_write_to_owned_host_is_moderate(self) -> None:
        tool = _tool(owned=["api.mygym.example"])
        assert (
            tool.dynamic_permission_level(
                {"url": "https://api.mygym.example/v1/bookings", "method": "POST"}
            )
            == PermissionLevel.MODERATE
        )

    def test_destructive_is_critical(self) -> None:
        tool = _tool(owned=["api.mygym.example"])
        assert (
            tool.dynamic_permission_level(
                {"url": "https://api.mygym.example/v1/bookings/1", "method": "DELETE"}
            )
            == PermissionLevel.CRITICAL
        )

    def test_foreign_write_is_critical_because_it_asks(self) -> None:
        tool = _tool()
        assert (
            tool.dynamic_permission_level(
                {"url": "https://api.other.example/v1/x", "method": "POST"}
            )
            == PermissionLevel.CRITICAL
        )

    def test_malformed_params_fall_back_to_moderate(self) -> None:
        tool = _tool()
        assert tool.dynamic_permission_level({"url": None, "method": "POST"}) in (
            PermissionLevel.MODERATE,
            PermissionLevel.CRITICAL,
        )


class TestRefusals:
    @pytest.mark.asyncio
    async def test_unknown_method_refused(self) -> None:
        result = await _tool().execute(
            {"url": "https://example.com", "method": "TRACE"}
        )
        assert not result.success
        assert "Unsupported method" in result.error

    @pytest.mark.asyncio
    async def test_destructive_on_foreign_account_refused_before_network(self) -> None:
        result = await _tool().execute(
            {"url": "https://api.gym.example/v1/users/8813", "method": "DELETE"}
        )
        assert not result.success
        assert "another person's record" in result.error

    @pytest.mark.asyncio
    async def test_metadata_endpoint_refused(self) -> None:
        result = await _tool().execute(
            {"url": "http://169.254.169.254/latest/meta-data/"}
        )
        assert not result.success
        assert "Refused" in result.error

    @pytest.mark.asyncio
    async def test_loopback_refused(self) -> None:
        result = await _tool().execute({"url": "http://localhost:9000/admin"})
        assert not result.success

    @pytest.mark.asyncio
    async def test_non_http_scheme_refused(self) -> None:
        result = await _tool().execute({"url": "file:///etc/passwd"})
        assert not result.success
        assert "scheme" in result.error


class TestCredentialHandling:
    @pytest.mark.asyncio
    async def test_credential_without_reason_refused(self) -> None:
        broker = CredentialBroker(default_mode="auto")
        tool = _tool(broker=broker, bindings={"gym": "env:GYM"})
        result = await tool.execute(
            {"url": "https://api.example.com/x", "credential": "gym"}
        )
        assert not result.success
        assert "reason" in result.error.lower()

    @pytest.mark.asyncio
    async def test_unknown_slug_explains_how_to_declare_it(self) -> None:
        broker = CredentialBroker(default_mode="auto")
        tool = _tool(broker=broker)
        result = await tool.execute(
            {
                "url": "https://api.example.com/x",
                "credential": "mystery",
                "reason": "test",
            }
        )
        assert not result.success
        assert "credentials.bindings" in result.error

    @pytest.mark.asyncio
    async def test_no_broker_means_no_authenticated_requests(self) -> None:
        tool = _tool()
        result = await tool.execute(
            {
                "url": "https://api.example.com/x",
                "credential": "gym",
                "reason": "test",
            }
        )
        assert not result.success
        assert "broker" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_auth_header_name_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GYM", "tok")
        broker = CredentialBroker(default_mode="auto")
        tool = _tool(broker=broker, bindings={"gym": "env:GYM"})
        result = await tool.execute(
            {
                "url": "https://api.example.com/x",
                "credential": "gym",
                "reason": "test",
                "auth_style": "header",
            }
        )
        assert not result.success
        assert "auth_header" in result.error

    def test_basic_auth_placeholder_is_encoded_after_materialization(self) -> None:
        """The value can only be base64'd once the sentinel is resolved."""
        from tools.http.request_tool import _fix_basic_auth

        fixed = _fix_basic_auth({"Authorization": "Basic-Plain user:pass"})
        assert fixed["Authorization"] == "Basic dXNlcjpwYXNz"

    def test_sentinel_keeps_the_secret_out_of_params(self) -> None:
        broker = CredentialBroker()
        sentinel = broker.issue_sentinel(SecretString("live-token", slug="gym"))
        headers = {"Authorization": f"Bearer {sentinel}"}
        assert "live-token" not in str(headers)
        assert broker.materialize(headers)["Authorization"] == "Bearer live-token"
