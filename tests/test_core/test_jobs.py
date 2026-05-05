"""Tests for the paid-job envelope verifier (core/jobs.py).

Pure-function tests — no DB, no I/O. Builds an Ed25519 signing
keypair in setUp, signs a known envelope, then asserts every
verification path: happy path, bad signature, expired, wrong
schema version, malformed wire format.

Mirrors the website's signing path verbatim: nacl.signing.SigningKey
signs the raw envelope JSON bytes, base64url-encodes both halves,
joins with '.', wraps in BEGIN/END markers.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest


class _Sig:
    """Mimics nacl's SignedMessage just enough — exposes `.signature`."""

    def __init__(self, signature: bytes) -> None:
        self.signature = signature


class _SigningKey:
    """Thin wrapper around cryptography's Ed25519PrivateKey so tests can
    keep `sk.sign(msg).signature` and `sk.verify_key.encode()` shapes."""

    def __init__(self, priv) -> None:
        self._priv = priv
        self._pub_raw = priv.public_key().public_bytes_raw()

    @classmethod
    def generate(cls) -> _SigningKey:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        return cls(Ed25519PrivateKey.generate())

    def sign(self, msg: bytes) -> _Sig:
        return _Sig(self._priv.sign(msg))

    @property
    def verify_key(self) -> _SigningKey:
        return self  # encode() lives on this same wrapper

    def encode(self) -> bytes:
        return self._pub_raw


@pytest.fixture
def signing_pair():
    """Returns (signing_key, pubkey_b64). Tests sign envelopes with the
    SigningKey, the verifier checks them against pubkey_b64."""
    sk = _SigningKey.generate()
    pubkey_b64 = base64.b64encode(sk.verify_key.encode()).decode("ascii")
    return sk, pubkey_b64


def _b64url(b: bytes) -> str:
    """Unpadded base64url encode — same shape the website emits."""
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _make_envelope(
    *,
    job_id: str = "01HXY8K9ZQRSTABCDEF1234567",
    task: str = "Research the top 5 Solana DEXes by 24h volume.",
    requester_email: str = "user@example.com",
    requester_wallet: str = "11111111111111111111111111111111",
    issued_at: str | None = None,
    expires_at: str | None = None,
    version: int = 1,
) -> dict:
    """Build an envelope dict matching JOB-SUBMISSION.md §"Job envelope format"."""
    now = datetime.now(UTC)
    return {
        "v": version,
        "jobId": job_id,
        "task": task,
        "requester": {"email": requester_email, "wallet": requester_wallet},
        "payment": {
            "mint": "BwUgJBQffm4HM49W7nsMphStJm4DbA5stuo4w7iwpump",
            "amount": "50000000000",
            "txSig": "fake-tx-sig-not-checked-here",
        },
        "issuedAt": issued_at or now.isoformat().replace("+00:00", "Z"),
        "expiresAt": expires_at
        or (now + timedelta(days=7)).isoformat().replace("+00:00", "Z"),
    }


def _wrap_envelope(env_dict: dict, sk) -> str:
    """Sign + wrap in BEGIN/END wire format. Mirrors the website."""
    env_bytes = json.dumps(env_dict, sort_keys=True).encode("utf-8")
    sig = sk.sign(env_bytes).signature
    body = f"{_b64url(env_bytes)}.{_b64url(sig)}"
    return f"-----BEGIN ELOPHANTO JOB-----\n{body}\n-----END ELOPHANTO JOB-----"


# ---------------------------------------------------------------------------
# parse_envelope — pure base64 + framing tests, no signature
# ---------------------------------------------------------------------------


class TestParseEnvelope:
    def test_parses_begin_end_form(self, signing_pair):
        from core.jobs import parse_envelope

        sk, _ = signing_pair
        wire = _wrap_envelope(_make_envelope(), sk)
        env_bytes, sig_bytes = parse_envelope(wire)
        # Round-trip: decoded envelope is valid JSON.
        decoded = json.loads(env_bytes)
        assert decoded["jobId"] == "01HXY8K9ZQRSTABCDEF1234567"
        assert len(sig_bytes) == 64  # Ed25519 sig is always 64 bytes

    def test_parses_bare_form_without_begin_end(self, signing_pair):
        """Pull endpoint sends the bare ``<env>.<sig>`` form too."""
        from core.jobs import parse_envelope

        sk, _ = signing_pair
        wire = _wrap_envelope(_make_envelope(), sk)
        # Strip the wrapping
        bare = (
            wire.replace("-----BEGIN ELOPHANTO JOB-----", "")
            .replace("-----END ELOPHANTO JOB-----", "")
            .strip()
        )
        env_bytes, sig_bytes = parse_envelope(bare)
        assert json.loads(env_bytes)["v"] == 1
        assert len(sig_bytes) == 64

    def test_tolerates_email_linewrapping(self, signing_pair):
        """Email clients linewrap long base64. The parser must drop
        any internal whitespace before splitting on the dot."""
        from core.jobs import parse_envelope

        sk, _ = signing_pair
        wire = _wrap_envelope(_make_envelope(task="x" * 200), sk)
        # Insert newlines mid-base64.
        chunks = []
        for line in wire.splitlines():
            for i in range(0, len(line), 70):
                chunks.append(line[i : i + 70])
        wrapped = "\n".join(chunks)
        env_bytes, _ = parse_envelope(wrapped)
        assert json.loads(env_bytes)["task"] == "x" * 200

    def test_empty_input_raises(self):
        from core.jobs import JobError, parse_envelope

        with pytest.raises(JobError, match="empty"):
            parse_envelope("")

    def test_missing_dot_raises(self):
        from core.jobs import JobError, parse_envelope

        with pytest.raises(JobError, match="missing '\\.' separator"):
            parse_envelope("just-some-base64-no-dot")

    def test_three_parts_raises(self):
        from core.jobs import JobError, parse_envelope

        with pytest.raises(JobError, match="expected 2 base64url parts"):
            parse_envelope("a.b.c")

    def test_malformed_base64_raises(self):
        from core.jobs import JobError, parse_envelope

        with pytest.raises(JobError, match="base64url"):
            parse_envelope("not-base64-!!!.also-not-!!!")

    def test_begin_without_end_raises(self):
        from core.jobs import JobError, parse_envelope

        with pytest.raises(JobError):
            # End marker absent — split[1] yields a string with no
            # `-----END`, then split([END]) returns the original
            # string; the dot-split + base64 decode should both fail.
            parse_envelope("-----BEGIN ELOPHANTO JOB-----\nrandom-not-formatted")


# ---------------------------------------------------------------------------
# verify_signature — Ed25519 path, isolated from JSON/schema concerns
# ---------------------------------------------------------------------------


class TestVerifySignature:
    def test_valid_signature_returns_true(self, signing_pair):
        from core.jobs import verify_signature

        sk, pubkey = signing_pair
        msg = b"hello"
        sig = sk.sign(msg).signature
        assert verify_signature(msg, sig, pubkey) is True

    def test_wrong_message_returns_false(self, signing_pair):
        from core.jobs import verify_signature

        sk, pubkey = signing_pair
        sig = sk.sign(b"hello").signature
        assert verify_signature(b"goodbye", sig, pubkey) is False

    def test_wrong_pubkey_returns_false(self, signing_pair):
        """A signature from sk1 won't verify against sk2's pubkey."""
        from core.jobs import verify_signature

        sk1, _ = signing_pair
        other = _SigningKey.generate()
        other_pubkey = base64.b64encode(other.verify_key.encode()).decode("ascii")
        sig = sk1.sign(b"hello").signature
        assert verify_signature(b"hello", sig, other_pubkey) is False

    def test_malformed_pubkey_returns_false_no_crash(self):
        """A bogus pubkey input must NOT raise — return False so the
        skill ritual treats the envelope as spam silently."""
        from core.jobs import verify_signature

        assert verify_signature(b"hi", b"\x00" * 64, "this-isn't-base64") is False

    def test_wrong_length_pubkey_returns_false(self):
        """Short or long key bytes must be rejected before nacl gets
        them — Ed25519 keys are exactly 32 bytes."""
        from core.jobs import verify_signature

        # 16-byte key, base64-encoded
        short = base64.b64encode(b"\x00" * 16).decode("ascii")
        assert verify_signature(b"hi", b"\x00" * 64, short) is False

    def test_accepts_base64url_pubkey_too(self, signing_pair):
        """Some operators may copy the pubkey in URL-safe form. The
        verifier tries standard base64 first, falls back to base64url."""
        from core.jobs import verify_signature

        sk, _ = signing_pair
        raw = sk.verify_key.encode()
        # base64url encoding (no padding, hyphens/underscores instead
        # of plus/slash). Same 32 bytes either way.
        url_safe = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        sig = sk.sign(b"hi").signature
        assert verify_signature(b"hi", sig, url_safe) is True


# ---------------------------------------------------------------------------
# verify_envelope — end-to-end happy path + every rejection branch
# ---------------------------------------------------------------------------


class TestVerifyEnvelope:
    def test_happy_path_returns_verified_job(self, signing_pair):
        from core.jobs import verify_envelope

        sk, pubkey = signing_pair
        wire = _wrap_envelope(_make_envelope(), sk)
        job = verify_envelope(wire, pubkey)
        assert job.job_id == "01HXY8K9ZQRSTABCDEF1234567"
        assert job.task.startswith("Research the top 5")
        assert job.requester_email == "user@example.com"
        assert job.requester_wallet.startswith("1111")

    def test_bad_signature_raises(self, signing_pair):
        """Sign with sk1, verify against unrelated pubkey → reject."""
        from core.jobs import JobError, verify_envelope

        sk1, _ = signing_pair
        wire = _wrap_envelope(_make_envelope(), sk1)
        other = _SigningKey.generate()
        other_pubkey = base64.b64encode(other.verify_key.encode()).decode("ascii")
        with pytest.raises(JobError, match="signature does not verify"):
            verify_envelope(wire, other_pubkey)

    def test_expired_envelope_raises(self, signing_pair):
        from core.jobs import JobError, verify_envelope

        sk, pubkey = signing_pair
        past = (
            (datetime.now(UTC) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
        )
        wire = _wrap_envelope(_make_envelope(expires_at=past), sk)
        with pytest.raises(JobError, match="expired"):
            verify_envelope(wire, pubkey)

    def test_unsupported_version_raises(self, signing_pair):
        from core.jobs import JobError, verify_envelope

        sk, pubkey = signing_pair
        wire = _wrap_envelope(_make_envelope(version=2), sk)
        with pytest.raises(JobError, match="unsupported envelope version"):
            verify_envelope(wire, pubkey)

    def test_oversized_task_rejected(self, signing_pair):
        """4001-char task should be rejected — matches the website's
        own input cap so we never accept work longer than the website
        would have allowed at submit time."""
        from core.jobs import JobError, verify_envelope

        sk, pubkey = signing_pair
        wire = _wrap_envelope(_make_envelope(task="x" * 4001), sk)
        with pytest.raises(JobError, match="exceeds cap"):
            verify_envelope(wire, pubkey)

    def test_missing_requester_email_rejected(self, signing_pair):
        from core.jobs import JobError, verify_envelope

        sk, pubkey = signing_pair
        env = _make_envelope()
        env["requester"]["email"] = ""
        wire = _wrap_envelope(env, sk)
        with pytest.raises(JobError, match="email is required"):
            verify_envelope(wire, pubkey)

    def test_missing_job_id_rejected(self, signing_pair):
        from core.jobs import JobError, verify_envelope

        sk, pubkey = signing_pair
        env = _make_envelope()
        env["jobId"] = ""
        wire = _wrap_envelope(env, sk)
        with pytest.raises(JobError, match="jobId"):
            verify_envelope(wire, pubkey)

    def test_now_is_injectable(self, signing_pair):
        """An envelope expiring 'tomorrow' should still verify when
        we pretend `now` is yesterday — useful for replay tests."""
        from core.jobs import verify_envelope

        sk, pubkey = signing_pair
        tomorrow = (
            (datetime.now(UTC) + timedelta(days=1)).isoformat().replace("+00:00", "Z")
        )
        wire = _wrap_envelope(_make_envelope(expires_at=tomorrow), sk)
        # Pretend "now" is two days ago — envelope still valid.
        two_days_ago = datetime.now(UTC) - timedelta(days=2)
        job = verify_envelope(wire, pubkey, now=two_days_ago)
        assert job.job_id


# ---------------------------------------------------------------------------
# Real-world key from JOB-SUBMISSION.md — pin a known-good keypair
# ---------------------------------------------------------------------------


class TestProductionKey:
    """Smoke test: the verifier can be configured with the actual
    pubkey shipped in JOB-SUBMISSION.md without crashing on the
    config string itself. We can't sign with the website's private
    key (we don't have it), so this is a 'load + reject-bogus-sig'
    test, not a happy-path test."""

    PROD_PUBKEY = "es8ggSXCOHPl2y4qUOYYsLLitPSoyymgWBldFQ1dn0k="

    def test_prod_pubkey_loads_without_crash(self):
        from core.jobs import verify_signature

        # Random 64-byte signature won't verify, but the loader path
        # exercises the base64-decode + key-length check on the real
        # pubkey value. Returns False (correctly), no exception.
        result = verify_signature(b"any message", b"\x00" * 64, self.PROD_PUBKEY)
        assert result is False

    def test_prod_pubkey_is_32_bytes_after_decode(self):
        """Sanity-check that the shipped pubkey is the right length —
        if the website rotates and someone pastes a malformed value
        into config, the verifier silently rejects everything; this
        test catches that at config-review time."""
        decoded = base64.b64decode(self.PROD_PUBKEY)
        assert len(decoded) == 32
