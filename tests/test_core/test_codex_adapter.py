"""Tests for CodexAdapter — auth loading, JWT parsing, message formatting."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import pytest

from core.codex_adapter import (
    CodexAdapter,
    CodexAuthError,
    _account_id_from_jwt,
    _b64url_decode,
    _clamp_effort,
    _jwt_exp,
    _jwt_payload,
)
from core.config import Config, LLMConfig, ProviderConfig


def _make_jwt(payload: dict) -> str:
    """Create an unsigned JWT for testing (no signature verification)."""
    header = {"alg": "none", "typ": "JWT"}
    h = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
    p = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{h}.{p}.sig"


def _make_auth_file(
    path: Path, mode: str = "chatgpt", account_id: str = "acc-123"
) -> None:
    exp = int(time.time()) + 3600
    access = _make_jwt(
        {
            "exp": exp,
            "https://api.openai.com/auth": {"chatgpt_account_id": account_id},
        }
    )
    path.write_text(
        json.dumps(
            {
                "auth_mode": mode,
                "tokens": {
                    "access_token": access,
                    "refresh_token": "refresh-xyz",
                    "account_id": account_id,
                },
            },
            indent=2,
        ),
        "utf-8",
    )


def _make_config(codex_enabled: bool = True) -> Config:
    providers = {}
    if codex_enabled:
        providers["codex"] = ProviderConfig(
            enabled=True,
            base_url="https://chatgpt.com/backend-api/codex",
            default_model="gpt-5.4",
        )
    return Config(llm=LLMConfig(providers=providers))


class TestJWTHelpers:
    def test_b64url_decode_with_padding(self) -> None:
        # "hello" base64url is "aGVsbG8" (no padding needed at 8 chars)
        assert _b64url_decode("aGVsbG8") == b"hello"

    def test_b64url_decode_needs_padding(self) -> None:
        # Without padding — should auto-pad
        assert _b64url_decode("aGVsbG8_") == b"hello?"

    def test_jwt_payload_valid(self) -> None:
        token = _make_jwt({"sub": "user1", "exp": 1234567890})
        payload = _jwt_payload(token)
        assert payload["sub"] == "user1"
        assert payload["exp"] == 1234567890

    def test_jwt_payload_malformed(self) -> None:
        with pytest.raises(CodexAuthError, match="Malformed"):
            _jwt_payload("justonesegment")

    def test_jwt_exp(self) -> None:
        token = _make_jwt({"exp": 9999999999})
        assert _jwt_exp(token) == 9999999999.0

    def test_jwt_exp_missing(self) -> None:
        token = _make_jwt({"sub": "x"})
        assert _jwt_exp(token) == 0.0

    def test_account_id_from_jwt(self) -> None:
        token = _make_jwt(
            {"https://api.openai.com/auth": {"chatgpt_account_id": "acc-42"}}
        )
        assert _account_id_from_jwt(token) == "acc-42"

    def test_account_id_missing(self) -> None:
        token = _make_jwt({"sub": "x"})
        with pytest.raises(CodexAuthError, match="chatgpt_account_id"):
            _account_id_from_jwt(token)


class TestEffortClamp:
    def test_gpt54_minimal_clamps_to_low(self) -> None:
        assert _clamp_effort("gpt-5.4", "minimal") == "low"

    def test_gpt54_high_passthrough(self) -> None:
        assert _clamp_effort("gpt-5.4", "high") == "high"

    def test_gpt51_codex_mini_clamps_high(self) -> None:
        assert _clamp_effort("gpt-5.1-codex-mini", "high") == "medium"

    def test_gpt51_codex_mini_clamps_xhigh(self) -> None:
        assert _clamp_effort("gpt-5.1-codex-mini", "xhigh") == "medium"

    def test_gpt51_codex_clamps_xhigh_to_high(self) -> None:
        assert _clamp_effort("gpt-5.1-codex", "xhigh") == "high"

    def test_unknown_model_passthrough(self) -> None:
        assert _clamp_effort("unknown-model", "medium") == "medium"

    def test_empty_effort_passthrough(self) -> None:
        assert _clamp_effort("gpt-5.4", "") == ""


class TestCodexAdapterInit:
    def test_missing_auth_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        config = _make_config()
        with pytest.raises(CodexAuthError, match="not found"):
            CodexAdapter(config)

    def test_wrong_auth_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        auth_path = tmp_path / "auth.json"
        _make_auth_file(auth_path, mode="apikey")
        config = _make_config()
        with pytest.raises(CodexAuthError, match="apikey"):
            CodexAdapter(config)

    def test_valid_auth(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        auth_path = tmp_path / "auth.json"
        _make_auth_file(auth_path, account_id="acc-xyz")
        config = _make_config()
        adapter = CodexAdapter(config)
        assert adapter._auth["account_id"] == "acc-xyz"
        assert adapter._auth["refresh"] == "refresh-xyz"
        assert adapter._auth["exp"] > time.time()

    def test_missing_tokens(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        auth_path = tmp_path / "auth.json"
        auth_path.write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {}}))
        config = _make_config()
        with pytest.raises(CodexAuthError, match="access_token"):
            CodexAdapter(config)

    def test_no_codex_provider_configured(self, tmp_path: Path) -> None:
        config = _make_config(codex_enabled=False)
        with pytest.raises(ValueError, match="not configured"):
            CodexAdapter(config)


class TestBuildInput:
    @pytest.fixture
    def adapter(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CodexAdapter:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        _make_auth_file(tmp_path / "auth.json")
        return CodexAdapter(_make_config())

    def test_system_becomes_instructions(self, adapter: CodexAdapter) -> None:
        messages = [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Hello"},
        ]
        instructions, blocks = adapter._build_input(messages)
        assert instructions == "Be concise."
        assert len(blocks) == 1
        assert blocks[0]["role"] == "user"
        assert blocks[0]["content"][0]["type"] == "input_text"
        assert blocks[0]["content"][0]["text"] == "Hello"

    def test_multiple_system_merge(self, adapter: CodexAdapter) -> None:
        messages = [
            {"role": "system", "content": "Rule 1"},
            {"role": "system", "content": "Rule 2"},
            {"role": "user", "content": "Go"},
        ]
        instructions, _ = adapter._build_input(messages)
        assert instructions == "Rule 1\n\nRule 2"

    def test_assistant_uses_output_text(self, adapter: CodexAdapter) -> None:
        messages = [
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": "A"},
            {"role": "user", "content": "Q2"},
        ]
        _, blocks = adapter._build_input(messages)
        assert len(blocks) == 3
        assert blocks[0]["content"][0]["type"] == "input_text"
        assert blocks[1]["content"][0]["type"] == "output_text"
        assert blocks[2]["content"][0]["type"] == "input_text"

    def test_image_content_passthrough(self, adapter: CodexAdapter) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this:"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,AAA"},
                    },
                ],
            }
        ]
        _, blocks = adapter._build_input(messages)
        assert len(blocks) == 1
        parts = blocks[0]["content"]
        assert parts[0]["type"] == "input_text"
        assert parts[1]["type"] == "input_image"
        assert parts[1]["image_url"] == "data:image/png;base64,AAA"

    def test_image_url_string_form(self, adapter: CodexAdapter) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "X"},
                    {"type": "image_url", "image_url": "https://example.com/pic.png"},
                ],
            }
        ]
        _, blocks = adapter._build_input(messages)
        parts = blocks[0]["content"]
        assert parts[1]["image_url"] == "https://example.com/pic.png"

    def test_tool_role_skipped(self, adapter: CodexAdapter) -> None:
        messages = [
            {"role": "user", "content": "Q"},
            {"role": "tool", "content": "result", "tool_call_id": "x"},
            {"role": "assistant", "content": "A"},
        ]
        _, blocks = adapter._build_input(messages)
        roles = [b["role"] for b in blocks]
        assert "tool" not in roles
        assert roles == ["user", "assistant"]

    def test_empty_content_dropped(self, adapter: CodexAdapter) -> None:
        messages = [
            {"role": "user", "content": ""},
            {"role": "user", "content": "real"},
        ]
        _, blocks = adapter._build_input(messages)
        assert len(blocks) == 1
        assert blocks[0]["content"][0]["text"] == "real"

    def test_no_instructions_when_no_system(self, adapter: CodexAdapter) -> None:
        messages = [{"role": "user", "content": "hi"}]
        instructions, _ = adapter._build_input(messages)
        assert instructions is None
