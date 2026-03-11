"""Webhook endpoint tests.

Tests gateway webhook routing, auth, and payload validation
without starting a real WebSocket server.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from core.config import Config, WebhookConfig


class TestWebhookConfig:
    def test_defaults(self) -> None:
        cfg = WebhookConfig()
        assert cfg.enabled is False
        assert cfg.auth_token_ref == ""
        assert cfg.max_payload_bytes == 65536

    def test_config_accessible(self) -> None:
        config = Config()
        assert hasattr(config, "webhooks")
        assert isinstance(config.webhooks, WebhookConfig)


class TestWebhookRouting:
    """Test gateway._handle_webhook routing logic."""

    def _make_gateway(
        self, webhooks_enabled: bool = True, auth_token: str | None = None
    ) -> MagicMock:
        """Create a minimal Gateway mock with webhook methods."""
        from core.gateway import Gateway

        # We can't easily instantiate Gateway without full setup,
        # so test the individual methods by calling them directly
        # on a real instance via mock dependencies.
        agent = MagicMock()
        agent._config = Config(webhooks=WebhookConfig(enabled=webhooks_enabled))
        agent._autonomous_mind = None
        agent._conversation_history = []

        gw = MagicMock(spec=Gateway)
        gw._agent = agent
        gw._webhook_config = WebhookConfig(enabled=webhooks_enabled)
        gw._webhook_auth_token = auth_token
        gw._heartbeat_engine = None
        gw._handle_webhook = Gateway._handle_webhook.__get__(gw, Gateway)
        gw._webhook_wake = Gateway._webhook_wake.__get__(gw, Gateway)
        gw._webhook_task = Gateway._webhook_task.__get__(gw, Gateway)
        return gw

    def _make_request(
        self, path: str, body: bytes = b"", headers: dict | None = None
    ) -> MagicMock:
        req = MagicMock()
        req.path = path
        req.body = body
        req.headers = headers or {}
        return req

    def test_webhooks_disabled_returns_404(self) -> None:
        gw = self._make_gateway(webhooks_enabled=False)
        req = self._make_request("/hooks/wake")
        resp = gw._handle_webhook(req)
        assert resp.status_code == 404

    def test_auth_required_and_missing(self) -> None:
        gw = self._make_gateway(auth_token="secret123")
        req = self._make_request("/hooks/wake", headers={})
        resp = gw._handle_webhook(req)
        assert resp.status_code == 401

    def test_auth_required_and_wrong(self) -> None:
        gw = self._make_gateway(auth_token="secret123")
        req = self._make_request(
            "/hooks/wake", headers={"Authorization": "Bearer wrong"}
        )
        resp = gw._handle_webhook(req)
        assert resp.status_code == 401

    def test_auth_required_and_correct(self) -> None:
        gw = self._make_gateway(auth_token="secret123")
        gw._heartbeat_engine = None  # Will get 503, but auth passes
        req = self._make_request(
            "/hooks/wake", headers={"Authorization": "Bearer secret123"}
        )
        resp = gw._handle_webhook(req)
        # Should pass auth (503 because no heartbeat engine, not 401)
        assert resp.status_code == 503

    def test_unknown_hook_returns_404(self) -> None:
        gw = self._make_gateway()
        req = self._make_request("/hooks/unknown")
        resp = gw._handle_webhook(req)
        assert resp.status_code == 404
        body = json.loads(resp.body)
        assert "unknown hook" in body["error"]

    def test_payload_too_large(self) -> None:
        gw = self._make_gateway()
        gw._webhook_config.max_payload_bytes = 10
        req = self._make_request("/hooks/task", body=b"x" * 100)
        resp = gw._handle_webhook(req)
        assert resp.status_code == 413

    def test_invalid_json_returns_400(self) -> None:
        gw = self._make_gateway()
        req = self._make_request("/hooks/task", body=b"not json{")
        resp = gw._handle_webhook(req)
        assert resp.status_code == 400

    def test_wake_without_heartbeat_returns_503(self) -> None:
        gw = self._make_gateway()
        gw._heartbeat_engine = None
        req = self._make_request("/hooks/wake", body=b"{}")
        resp = gw._handle_webhook(req)
        assert resp.status_code == 503

    def test_task_missing_goal_returns_400(self) -> None:
        gw = self._make_gateway()
        req = self._make_request("/hooks/task", body=json.dumps({}).encode())
        resp = gw._handle_webhook(req)
        assert resp.status_code == 400
        body = json.loads(resp.body)
        assert "goal" in body["error"]

    def test_task_with_goal_returns_202(self) -> None:
        gw = self._make_gateway()
        req = self._make_request(
            "/hooks/task",
            body=json.dumps({"goal": "Check server status"}).encode(),
        )
        resp = gw._handle_webhook(req)
        assert resp.status_code == 202
        body = json.loads(resp.body)
        assert body["status"] == "accepted"
        assert "Check server status" in body["goal"]

    def test_empty_body_treated_as_empty_dict(self) -> None:
        gw = self._make_gateway()
        # /hooks/task with no body → missing goal → 400
        req = self._make_request("/hooks/task", body=b"")
        resp = gw._handle_webhook(req)
        assert resp.status_code == 400
