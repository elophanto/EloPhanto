"""Bridge between libp2p PeerIDs and our Ed25519 trust ledger.

A libp2p PeerID for an Ed25519 key is just the protobuf-wrapped public
key, hashed with the identity multihash (i.e. not really hashed —
the bytes are recoverable). That's deliberate so peers can verify
each other from the PeerID alone, without an extra round trip.

We exploit that to make libp2p connections pin into the same trust
ledger our existing IDENTIFY/WS handshake uses. A peer that connects
to us via wss:// today and via libp2p tomorrow shares one trust
record — the ledger doesn't care which transport delivered the key.

Wire format reference (libp2p spec):
- PeerID: base58btc-encoded multihash
- Multihash for Ed25519: 0x00 (identity hash code) + varint length + payload
- Payload: protobuf PublicKey { KeyType key_type = 1; bytes data = 2; }
- KeyType for Ed25519 = 1 (in the Go enum) — see crypto.proto.
- Data: the raw 32-byte Ed25519 public key.

We hand-decode rather than pull a libp2p Python library (none are
production-ready) — the format is stable and tiny.
"""

from __future__ import annotations

import base64
import logging

logger = logging.getLogger(__name__)

# Identity multihash code per the multihash spec.
# https://github.com/multiformats/multihash
_IDENTITY_HASH_CODE = 0x00

# libp2p crypto KeyType enum (from go-libp2p/core/crypto/pb/crypto.proto).
# We only care about Ed25519 — RSA peers are vanishingly rare in modern
# libp2p networks and we don't generate them.
_KEY_TYPE_ED25519 = 1


class PeerIDDecodeError(ValueError):
    """Raised when a PeerID can't be decoded into an Ed25519 public key.

    Common causes: not a real PeerID, an RSA peer (we don't support
    those), or a corrupted base58 string. Callers treat this as
    "skip TOFU; keep the connection but don't pin it" — better to
    talk to a peer we can't trust-pin than to refuse outright."""


def peer_id_to_ed25519_pubkey_b64(peer_id: str) -> str:
    """Decode a libp2p Ed25519 PeerID into the matching b64 public key.

    The b64 format matches what AgentIdentityKey.public_key_b64()
    produces, so the result drops directly into the trust ledger's
    `public_key` column without further conversion.

    Raises PeerIDDecodeError if the PeerID isn't an Ed25519 identity
    encoding (RSA / ECDSA peers, malformed input, etc.).
    """
    if not peer_id:
        raise PeerIDDecodeError("empty peer id")

    try:
        raw = _b58btc_decode(peer_id)
    except Exception as e:
        raise PeerIDDecodeError(f"not valid base58btc: {e}") from e

    if len(raw) < 2:
        raise PeerIDDecodeError(f"peer id payload too short: {len(raw)} bytes")

    # Multihash: <code: varint><length: varint><digest: bytes>
    code, code_len = _read_varint(raw, 0)
    length, length_len = _read_varint(raw, code_len)
    digest = raw[code_len + length_len :]

    if code != _IDENTITY_HASH_CODE:
        # Non-identity hash means the PeerID is sha256(protobuf pubkey)
        # rather than the protobuf itself — the pubkey is not
        # recoverable. Happens for RSA peers (because their pubkey is
        # large) and for older libp2p versions that hashed everything.
        raise PeerIDDecodeError(
            f"peer id uses non-identity multihash 0x{code:02x}; "
            "public key not recoverable (RSA peer or legacy encoding)"
        )

    if len(digest) != length:
        raise PeerIDDecodeError(
            f"multihash length mismatch: declared {length}, got {len(digest)}"
        )

    # digest is the protobuf-encoded crypto.PublicKey. Decode just enough
    # to extract the Ed25519 raw bytes — full protobuf is overkill.
    pubkey_bytes = _extract_ed25519_from_pubkey_proto(digest)
    return base64.b64encode(pubkey_bytes).decode("ascii")


# ---------------------------------------------------------------------------
# Helpers — base58btc + varint + minimal protobuf
# ---------------------------------------------------------------------------

# Bitcoin base58 alphabet. Note no 0/O/I/l (visually ambiguous) — that's
# why "base58btc" is the spec name, distinguishing it from base58check.
_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {ch: i for i, ch in enumerate(_B58_ALPHABET)}


def _b58btc_decode(s: str) -> bytes:
    """Decode a base58btc string. Raises on invalid characters."""
    n = 0
    for ch in s:
        try:
            n = n * 58 + _B58_INDEX[ch]
        except KeyError:
            raise ValueError(f"invalid base58btc character: {ch!r}") from None
    # Convert big-int to bytes.
    out = bytearray()
    while n > 0:
        out.insert(0, n & 0xFF)
        n >>= 8
    # Restore leading zero bytes (base58 strips them — each leading '1'
    # in the input represents one leading 0x00 in the output).
    for ch in s:
        if ch == "1":
            out.insert(0, 0)
        else:
            break
    return bytes(out)


def _read_varint(buf: bytes, offset: int) -> tuple[int, int]:
    """Read a single unsigned varint. Returns (value, bytes_consumed).

    Multihash uses the multiformats unsigned-varint flavor — same as
    protobuf's, max 9 bytes. We bound to 4 because no realistic
    multihash code or length exceeds that here, and an adversarial
    input shouldn't be able to make us loop on a malformed varint.
    """
    value = 0
    shift = 0
    consumed = 0
    while consumed < 9 and offset + consumed < len(buf):
        byte = buf[offset + consumed]
        consumed += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, consumed
        shift += 7
    raise PeerIDDecodeError("varint did not terminate within 9 bytes")


def _extract_ed25519_from_pubkey_proto(buf: bytes) -> bytes:
    """Parse a libp2p crypto.PublicKey protobuf and return the raw key.

    Only the two fields we care about:
        field 1, varint -> KeyType
        field 2, length-delimited -> Data (the raw key bytes)

    Anything else we encounter is skipped per protobuf's standard
    forward-compat behaviour. We refuse non-Ed25519 keys because the
    rest of the trust ledger assumes 32-byte Ed25519 pubkeys.
    """
    pos = 0
    key_type: int | None = None
    data: bytes | None = None
    while pos < len(buf):
        # Each field starts with a "tag" varint = (field_num << 3) | wire_type.
        tag, used = _read_varint(buf, pos)
        pos += used
        field_num = tag >> 3
        wire_type = tag & 0x07

        if wire_type == 0:  # varint
            val, used = _read_varint(buf, pos)
            pos += used
            if field_num == 1:
                key_type = val
        elif wire_type == 2:  # length-delimited
            length, used = _read_varint(buf, pos)
            pos += used
            chunk = buf[pos : pos + length]
            pos += length
            if field_num == 2:
                data = chunk
        else:
            # We don't expect 64-bit / 32-bit wire types in this proto,
            # but skip them defensively if a future libp2p version adds
            # them. Skipping = bail; we can't trust the parse.
            raise PeerIDDecodeError(
                f"unsupported protobuf wire type {wire_type} in pubkey proto"
            )

    if key_type != _KEY_TYPE_ED25519:
        raise PeerIDDecodeError(
            f"pubkey is not Ed25519 (KeyType={key_type}); "
            "trust ledger only supports Ed25519 peers"
        )
    if data is None or len(data) != 32:
        raise PeerIDDecodeError(
            f"Ed25519 pubkey field missing or wrong length "
            f"(got {len(data) if data is not None else 'None'} bytes)"
        )
    return data
