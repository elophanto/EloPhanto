"""Job-envelope verification — paid jobs from elophanto.com.

The website verifies the user's on-chain $ELO payment, signs an
Ed25519 envelope with its signing key, and delivers it to the
agent's AgentMail inbox (or makes it pullable from /api/jobs/pending).
The agent's job is narrow: confirm the envelope's signature against
the website's public key. If the signature checks out, the website
already saw a confirmed payment — re-checking on-chain is the
website's threat model, not ours.

This module is pure: parse + verify + schema/expiry checks. No I/O,
no DB. Wrapped by `tools/jobs/verify_tool.py` for agent-facing use,
and by tests for offline verification.

Wire format (per JOB-SUBMISSION.md §"Job envelope format"):

    -----BEGIN ELOPHANTO JOB-----
    <base64url(envelope_json)>.<base64url(ed25519_signature)>
    -----END ELOPHANTO JOB-----

The signature is over the RAW envelope JSON bytes, not the base64.
Mirror the website's signing path exactly — see `nacl.signing`.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# Wire-format markers — the website wraps the envelope+signature in
# these so an envelope can be safely embedded in an email body
# alongside human-readable summary text.
_BEGIN = "-----BEGIN ELOPHANTO JOB-----"
_END = "-----END ELOPHANTO JOB-----"

# Expected envelope schema version. Bump only on incompatible changes
# to the envelope structure. Adding optional fields stays at v1.
_ENVELOPE_VERSION = 1

# Hard cap on the task field. Matches the website's input cap to
# guarantee we never accept an envelope the website wouldn't have
# accepted at submit time.
_TASK_MAX_LEN = 4000


class JobError(ValueError):
    """Raised when a job envelope fails any verification step.

    The error message is the surfaced reason; callers convert this
    into a user-facing rejection or skip the email entirely. Code
    grep-able to a single exception type so the agent's skill ritual
    can catch all verification failures uniformly.
    """


@dataclass
class VerifiedJob:
    """A parsed + signature-verified + schema-valid + non-expired job.

    Returned only when every check passed. The agent treats the
    contents as authoritative — the signature came from the website,
    which already confirmed payment before signing.
    """

    job_id: str
    task: str
    requester_email: str
    requester_wallet: str
    issued_at: str  # ISO-8601 UTC string from envelope
    expires_at: str  # ISO-8601 UTC string from envelope


def parse_envelope(wire_text: str) -> tuple[bytes, bytes]:
    """Extract envelope JSON bytes + Ed25519 signature bytes from a
    wire-format job string. Pure function — no signature check yet.

    Accepts either the bare ``<env_b64>.<sig_b64>`` form or the
    BEGIN/END-wrapped form. Strips whitespace, splits on the single
    ``.`` separator.

    Raises :class:`JobError` on any parse failure (no BEGIN/END,
    no dot, malformed base64). Callers should not need to handle
    other exception types.
    """
    if not wire_text:
        raise JobError("empty wire text")

    body = wire_text.strip()
    # Accept both BEGIN/END-wrapped and bare forms. Email bodies use
    # the wrapped form; the pull endpoint sends just `payload` which
    # is also wrapped per the spec but tolerate either.
    if _BEGIN in body:
        try:
            body = body.split(_BEGIN, 1)[1].split(_END, 1)[0].strip()
        except IndexError as e:
            raise JobError(f"BEGIN marker present but no END: {e}") from e

    # Strip any internal whitespace/newlines — base64url doesn't
    # contain any, so anything that's not [A-Za-z0-9_-.] is from
    # email-client linewrapping and safe to drop.
    body = "".join(body.split())

    if "." not in body:
        raise JobError("malformed envelope: missing '.' separator")

    parts = body.split(".")
    if len(parts) != 2:
        raise JobError(
            f"malformed envelope: expected 2 base64url parts, got {len(parts)}"
        )

    try:
        env_bytes = _b64url_decode(parts[0])
        sig_bytes = _b64url_decode(parts[1])
    except (ValueError, base64.binascii.Error) as e:
        raise JobError(f"base64url decode failed: {e}") from e

    return env_bytes, sig_bytes


def verify_signature(
    envelope_bytes: bytes,
    signature_bytes: bytes,
    pubkey_b64: str,
) -> bool:
    """Ed25519 verify ``signature_bytes`` over ``envelope_bytes`` using
    the website's public key.

    Returns True on a valid signature, False on any failure (bad sig,
    bad key encoding, wrong key length). Defensive: never raises —
    failures are silent so callers can simply branch on the bool.

    The website signs the RAW envelope JSON bytes, not the base64
    representation. Mirror that here.
    """
    try:
        # Pubkey may be base64 (standard) per the spec config example.
        # Defensive: also accept base64url in case someone copies a
        # URL-safe variant. Padding tolerated either way.
        try:
            raw_key = base64.b64decode(pubkey_b64)
        except (ValueError, base64.binascii.Error):
            raw_key = _b64url_decode(pubkey_b64)

        if len(raw_key) != 32:
            return False

        Ed25519PublicKey.from_public_bytes(raw_key).verify(
            signature_bytes, envelope_bytes
        )
        return True
    except InvalidSignature:
        return False
    except Exception:
        # Catch-all so a malformed key or surprise crypto error never
        # crashes the job-handling skill mid-loop.
        return False


def verify_envelope(
    wire_text: str,
    pubkey_b64: str,
    *,
    now: datetime | None = None,
) -> VerifiedJob:
    """End-to-end envelope verification — parse + signature + schema +
    expiry. Returns a :class:`VerifiedJob` on success, raises
    :class:`JobError` on any failure.

    `now` is injectable for tests; defaults to current UTC. All
    timestamps in the envelope are ISO-8601 UTC strings; parsed via
    :py:func:`datetime.fromisoformat` after the trailing ``Z`` is
    swapped for ``+00:00``.
    """
    env_bytes, sig_bytes = parse_envelope(wire_text)

    if not verify_signature(env_bytes, sig_bytes, pubkey_b64):
        raise JobError("signature does not verify against website pubkey")

    try:
        envelope = json.loads(env_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise JobError(f"envelope is not valid JSON: {e}") from e

    if not isinstance(envelope, dict):
        raise JobError(f"envelope must be a JSON object, got {type(envelope).__name__}")

    # Schema check — version + required fields.
    version = envelope.get("v")
    if version != _ENVELOPE_VERSION:
        raise JobError(
            f"unsupported envelope version: got {version!r}, "
            f"expected {_ENVELOPE_VERSION}"
        )

    job_id = envelope.get("jobId", "")
    if not isinstance(job_id, str) or not job_id:
        raise JobError("envelope missing or invalid jobId")

    task = envelope.get("task", "")
    if not isinstance(task, str) or not task:
        raise JobError("envelope missing or invalid task")
    if len(task) > _TASK_MAX_LEN:
        raise JobError(f"task length {len(task)} exceeds cap {_TASK_MAX_LEN}")

    requester = envelope.get("requester") or {}
    if not isinstance(requester, dict):
        raise JobError("envelope.requester must be an object")
    requester_email = str(requester.get("email", "")).strip()
    requester_wallet = str(requester.get("wallet", "")).strip()
    if not requester_email:
        raise JobError("envelope.requester.email is required")

    issued_at = str(envelope.get("issuedAt", ""))
    expires_at = str(envelope.get("expiresAt", ""))
    if not expires_at:
        raise JobError("envelope.expiresAt is required")

    # Expiry check. Spec defines expiry at 7 days; we re-check at
    # verification time so a stale email sitting in the inbox can't
    # be silently re-accepted weeks later.
    try:
        exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as e:
        raise JobError(f"envelope.expiresAt is not ISO-8601: {e}") from e
    current = now or datetime.now(UTC)
    if exp_dt < current:
        raise JobError(f"envelope expired at {expires_at} (now {current.isoformat()})")

    return VerifiedJob(
        job_id=job_id,
        task=task,
        requester_email=requester_email,
        requester_wallet=requester_wallet,
        issued_at=issued_at,
        expires_at=expires_at,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b64url_decode(s: str) -> bytes:
    """base64url decode with padding inferred. The website sends
    unpadded base64url; Python's stdlib needs the padding."""
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def envelope_to_dict(env_bytes: bytes) -> dict[str, Any]:
    """Decode envelope bytes to a dict without validation — useful in
    tests + tools that want to inspect the raw shape after a parse."""
    return json.loads(env_bytes.decode("utf-8"))
