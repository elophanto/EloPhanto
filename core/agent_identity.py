"""Agent cryptographic identity — Ed25519 keypair for agent-to-agent auth.

Distinct from the evolving `Identity` (values/beliefs/capabilities). This
is the *cryptographic* identity used to prove "this connection is
actually agent X" when one EloPhanto talks to another over the gateway.

Design choices:

- **Ed25519** — small (32-byte keys, 64-byte sigs), fast, no parameter
  choices, no obscure failure modes. Standard for agent-to-agent identity
  in modern systems (Tailscale, signal, libp2p).
- **Auto-generate on first boot.** Existing agents upgrade silently; no
  config required. Doctor warns if missing or unreadable.
- **Persisted as a 0600 PEM file** at ``~/.elophanto/agent_identity.pem``.
  Not in the encrypted vault — the vault needs a password to unlock and
  agents must auth before that. Keeping the key on a 0600 file mirrors
  how SSH host keys work.
- **Trust ledger is TOFU by default** — first time we see a peer's
  agent_id+public_key, we record it as ``trust_level='tofu'``. If the
  same agent_id ever shows up with a different public_key, we refuse
  the connection and surface the conflict (SSH known_hosts model).
- **Backward compatible** — peers that don't speak the IDENTIFY protocol
  still connect with the legacy auth-token path, and their session is
  flagged as ``verified=False`` so sensitive code paths can refuse them.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

logger = logging.getLogger(__name__)


# Default location — overridable via ELOPHANTO_AGENT_KEY env or constructor.
_DEFAULT_KEY_PATH = Path.home() / ".elophanto" / "agent_identity.pem"


# ---------------------------------------------------------------------------
# Trust levels — order matters for upgrade semantics
# ---------------------------------------------------------------------------

TRUST_BLOCKED = "blocked"  # never accept connections from this agent
TRUST_UNKNOWN = "unknown"  # never seen before — pre-handshake state
TRUST_TOFU = "tofu"  # trust-on-first-use: accepted, may downgrade
TRUST_VERIFIED = "verified"  # explicitly approved by owner — manual gate


@dataclass
class AgentIdentityKey:
    """Loaded keypair + agent_id for cryptographic identity operations."""

    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey
    agent_id: str

    # ── Sign / verify ────────────────────────────────────────────────

    def sign(self, payload: bytes) -> bytes:
        """Sign arbitrary bytes with this agent's private key."""
        return self.private_key.sign(payload)

    def public_key_b64(self) -> str:
        """Public key in raw 32-byte Ed25519 format, base64-encoded.

        This is what gets exchanged in the IDENTIFY handshake and stored
        in the trust ledger. Compact and URL-safe-ish."""
        raw = self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.b64encode(raw).decode("ascii")

    def private_key_seed_hex(self) -> str:
        """Raw 32-byte Ed25519 seed as hex.

        Used by the libp2p sidecar — go-libp2p's PeerID is derived
        deterministically from the matching public key, so handing over
        this same seed means our IDENTIFY identity AND our libp2p PeerID
        come from one keypair. Same agent, same identity across
        transports.

        SECURITY: this exposes the raw private key material. Only pass
        it to processes we own (the sidecar over a 0600 Unix socket) —
        never log it, never commit it, never transmit over the network.
        """
        raw = self.private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return raw.hex()


# ---------------------------------------------------------------------------
# Static helpers — verify someone else's signature
# ---------------------------------------------------------------------------


def verify_signature(public_key_b64: str, signature: bytes, payload: bytes) -> bool:
    """Verify a peer's signature given their base64 public key.

    Returns False on any failure (invalid sig, bad key encoding, wrong
    length) rather than raising — caller decides how to react.
    """
    try:
        raw = base64.b64decode(public_key_b64)
        if len(raw) != 32:
            return False
        peer_key = Ed25519PublicKey.from_public_bytes(raw)
        peer_key.verify(signature, payload)
        return True
    except (InvalidSignature, ValueError, Exception):
        return False


def make_nonce() -> bytes:
    """Generate a 32-byte random nonce for the IDENTIFY handshake.

    Both sides should challenge each other with a fresh nonce so neither
    side can replay a stale signature."""
    return secrets.token_bytes(32)


def derive_agent_id_from_public_key(public_key_b64: str) -> str:
    """Derive a stable, short agent_id from a public key.

    Pattern: ``elo-{first 12 chars of base64 public key}``. Stable across
    reboots because the public key doesn't change. Easy to eyeball when
    comparing two agents in logs."""
    return f"elo-{public_key_b64[:12]}"


# ---------------------------------------------------------------------------
# Load / generate
# ---------------------------------------------------------------------------


def load_or_create(
    key_path: Path | None = None,
    *,
    auto_create: bool = True,
) -> AgentIdentityKey:
    """Load the local agent's cryptographic identity, generating one if
    missing. The keypair persists across reboots; if you want a new
    identity, delete the file and call again.

    Existing agents that upgrade past the IDENTIFY protocol get a key
    auto-generated on first boot here — no config change required.
    """
    path = (
        Path(key_path)
        if key_path is not None
        else Path(os.environ.get("ELOPHANTO_AGENT_KEY", str(_DEFAULT_KEY_PATH)))
    )

    if path.exists():
        try:
            data = path.read_bytes()
            private_key = serialization.load_pem_private_key(data, password=None)
            if not isinstance(private_key, Ed25519PrivateKey):
                raise ValueError(
                    f"agent identity key at {path} is not Ed25519 — "
                    "delete it and let the agent regenerate"
                )
            public_key = private_key.public_key()
            pk_b64 = base64.b64encode(
                public_key.public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
            ).decode("ascii")
            return AgentIdentityKey(
                private_key=private_key,
                public_key=public_key,
                agent_id=derive_agent_id_from_public_key(pk_b64),
            )
        except Exception as e:
            logger.error("Failed to load agent identity key at %s: %s", path, e)
            if not auto_create:
                raise
            # Fall through to regenerate.

    if not auto_create:
        raise RuntimeError(f"No agent identity key at {path}")

    return _generate_and_persist(path)


def _generate_and_persist(path: Path) -> AgentIdentityKey:
    """Generate a fresh Ed25519 keypair and write it to disk (0600).

    Internal — call ``load_or_create`` instead unless you want to force
    a new identity. The parent directory is created if missing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(pem)
    # 0600: readable only by the owning user. SSH host-key convention.
    try:
        path.chmod(0o600)
    except OSError as e:
        # Windows / non-POSIX — best-effort, don't fail bootstrap.
        logger.debug("Could not chmod 0600 on %s: %s", path, e)
    public_key = private_key.public_key()
    pk_b64 = base64.b64encode(
        public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    agent_id = derive_agent_id_from_public_key(pk_b64)
    logger.info("Generated agent identity %s at %s", agent_id, path)
    return AgentIdentityKey(
        private_key=private_key, public_key=public_key, agent_id=agent_id
    )


__all__ = [
    "TRUST_BLOCKED",
    "TRUST_TOFU",
    "TRUST_UNKNOWN",
    "TRUST_VERIFIED",
    "AgentIdentityKey",
    "derive_agent_id_from_public_key",
    "load_or_create",
    "make_nonce",
    "verify_signature",
]
