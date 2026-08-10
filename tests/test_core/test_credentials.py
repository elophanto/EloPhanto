"""Credential broker — the model must never receive the secret.

Three properties are pinned here, in descending order of how badly a
regression would hurt: the value never appears in anything the model or
the transcript sees, policy actually gates resolution, and a missing
approval path fails closed rather than open.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.credentials import (
    CredentialBroker,
    CredentialError,
    CredentialPolicy,
    SecretString,
    parse_ref,
)


class _FakeVault:
    def __init__(self, data: dict) -> None:
        self._data = data

    def get(self, key: str):
        return self._data.get(key)


class TestSecretString:
    def test_str_and_repr_are_redacted(self) -> None:
        secret = SecretString("hunter2-the-real-token", slug="gym")
        assert "hunter2" not in str(secret)
        assert "hunter2" not in repr(secret)
        assert "hunter2" not in f"{secret}"
        assert secret.reveal() == "hunter2-the-real-token"

    def test_formatting_into_a_message_does_not_leak(self) -> None:
        secret = SecretString("super-secret", slug="x")
        assert "super-secret" not in f"token is {secret}"

    def test_truthiness_and_length_still_work(self) -> None:
        assert SecretString("abc")
        assert not SecretString("")
        assert len(SecretString("abcd")) == 4


class TestRefParsing:
    @pytest.mark.parametrize(
        "raw,source,ident,field",
        [
            ("env:GITHUB_TOKEN", "env", "GITHUB_TOKEN", ""),
            ("${GITHUB_TOKEN}", "env", "GITHUB_TOKEN", ""),
            ("vault:github.com", "vault", "github.com", ""),
            ("vault:github.com#token", "vault", "github.com", "token"),
            ("oauth:google", "oauth", "google", ""),
            ("file:/run/secrets/api#key.sub", "file", "/run/secrets/api", "key.sub"),
        ],
    )
    def test_forms(self, raw: str, source: str, ident: str, field: str) -> None:
        ref = parse_ref(raw)
        assert (ref.source, ref.id, ref.field) == (source, ident, field)

    def test_unknown_source_is_rejected_loudly(self) -> None:
        with pytest.raises(CredentialError, match="Unknown credential source"):
            parse_ref("s3cret:thing")

    def test_missing_separator_is_rejected(self) -> None:
        with pytest.raises(CredentialError, match="Malformed"):
            parse_ref("just-a-string")


class TestSentinels:
    def test_sentinel_hides_value_until_materialized(self) -> None:
        broker = CredentialBroker()
        sentinel = broker.issue_sentinel(SecretString("tok-abc123", slug="gym"))

        headers = {"Authorization": f"Bearer {sentinel}"}
        assert "tok-abc123" not in str(headers)

        materialized = broker.materialize(headers)
        assert materialized["Authorization"] == "Bearer tok-abc123"
        # The original is untouched, so logging it stays safe.
        assert "tok-abc123" not in str(headers)

    def test_materialize_walks_nested_structures(self) -> None:
        broker = CredentialBroker()
        sentinel = broker.issue_sentinel(SecretString("v-9", slug="s"))
        payload = {"a": [{"b": sentinel}], "c": (sentinel,)}
        out = broker.materialize(payload)
        assert out["a"][0]["b"] == "v-9"
        assert out["c"][0] == "v-9"

    def test_redact_scrubs_an_echoed_secret(self) -> None:
        broker = CredentialBroker()
        broker.issue_sentinel(SecretString("tok-abc123", slug="gym"))
        scrubbed = broker.redact("the server echoed tok-abc123 back at us")
        assert "tok-abc123" not in scrubbed
        assert "«redacted:gym»" in scrubbed

    def test_short_values_are_not_scrubbed(self) -> None:
        # Redacting a 3-char secret would blank out ordinary prose.
        broker = CredentialBroker()
        broker.issue_sentinel(SecretString("abc", slug="s"))
        assert broker.redact("abc appears in many words") == (
            "abc appears in many words"
        )

    def test_forget_clears_the_map(self) -> None:
        broker = CredentialBroker()
        sentinel = broker.issue_sentinel(SecretString("tok-abc123", slug="gym"))
        broker.forget_sentinels()
        # Unknown sentinel passes through rather than resolving.
        assert broker.materialize(sentinel) == sentinel


class TestResolution:
    @pytest.mark.asyncio
    async def test_env_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_TOKEN_X", "from-env")
        broker = CredentialBroker(default_mode="auto")
        secret = await broker.resolve("x", "env:TEST_TOKEN_X", reason="test")
        assert secret.reveal() == "from-env"

    @pytest.mark.asyncio
    async def test_vault_source_with_field(self) -> None:
        broker = CredentialBroker(
            vault=_FakeVault({"trello": {"token": "t-1", "key": "k-1"}}),
            default_mode="auto",
        )
        secret = await broker.resolve("trello", "vault:trello#token", reason="test")
        assert secret.reveal() == "t-1"

    @pytest.mark.asyncio
    async def test_vault_record_without_field_needs_disambiguation(self) -> None:
        broker = CredentialBroker(
            vault=_FakeVault({"acct": {"username": "u", "other": "o"}}),
            default_mode="auto",
        )
        with pytest.raises(CredentialError, match="name one"):
            await broker.resolve("acct", "vault:acct", reason="test")

    @pytest.mark.asyncio
    async def test_file_source_with_json_pointer(self, tmp_path: Path) -> None:
        path = tmp_path / "creds.json"
        path.write_text('{"outer": {"inner": "deep-value"}}', encoding="utf-8")
        broker = CredentialBroker(default_mode="auto")
        secret = await broker.resolve("f", f"file:{path}#outer.inner", reason="test")
        assert secret.reveal() == "deep-value"

    @pytest.mark.asyncio
    async def test_reason_is_mandatory(self) -> None:
        broker = CredentialBroker(default_mode="auto")
        with pytest.raises(CredentialError, match="reason is required"):
            await broker.resolve("x", "env:ANY", reason="  ")

    @pytest.mark.asyncio
    async def test_missing_value_reports_where_it_looked(self) -> None:
        broker = CredentialBroker(default_mode="auto")
        os.environ.pop("DEFINITELY_NOT_SET_XYZ", None)
        with pytest.raises(CredentialError, match="not found"):
            await broker.resolve("x", "env:DEFINITELY_NOT_SET_XYZ", reason="test")


class TestPolicy:
    @pytest.mark.asyncio
    async def test_deny_policy_blocks_resolution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("T", "v")
        broker = CredentialBroker(policies={"x": CredentialPolicy(mode="deny")})
        with pytest.raises(CredentialError, match="denied by policy"):
            await broker.resolve("x", "env:T", reason="test")

    @pytest.mark.asyncio
    async def test_approve_policy_without_callback_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No approval path must mean no credential, not a silent grant."""
        monkeypatch.setenv("T", "v")
        broker = CredentialBroker(default_mode="approve")
        with pytest.raises(CredentialError, match="denied"):
            await broker.resolve("x", "env:T", reason="test")

    @pytest.mark.asyncio
    async def test_operator_denial_is_honoured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("T", "v")
        broker = CredentialBroker(default_mode="approve")
        broker.set_approval_callback(lambda *a, **k: False)
        with pytest.raises(CredentialError, match="denied"):
            await broker.resolve("x", "env:T", reason="test")

    @pytest.mark.asyncio
    async def test_operator_approval_resolves(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("T", "approved-value")
        asked: list[str] = []

        def _cb(tool: str, description: str, params: dict) -> bool:
            asked.append(description)
            return True

        broker = CredentialBroker(default_mode="approve")
        broker.set_approval_callback(_cb)
        secret = await broker.resolve("x", "env:T", reason="book the gym")
        assert secret.reveal() == "approved-value"
        # The operator sees the stated reason on the prompt.
        assert any("book the gym" in a for a in asked)

    @pytest.mark.asyncio
    async def test_ttl_grant_prompts_once_for_a_burst(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("T", "v")
        calls: list[int] = []
        broker = CredentialBroker(
            policies={"x": CredentialPolicy(mode="approve", grant_ttl_seconds=300)}
        )
        broker.set_approval_callback(lambda *a, **k: calls.append(1) or True)

        for _ in range(4):
            await broker.resolve("x", "env:T", reason="multi-step booking")
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_wildcard_policy_applies_to_prefixed_slugs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("T", "v")
        broker = CredentialBroker(policies={"google.*": CredentialPolicy(mode="deny")})
        with pytest.raises(CredentialError, match="denied by policy"):
            await broker.resolve("google.calendar", "env:T", reason="test")
