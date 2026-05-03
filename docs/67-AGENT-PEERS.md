# EloPhanto — Agent-to-Agent Peer Connections

## Overview

EloPhanto agents can find and talk to each other across machines —
laptop ↔ home server, home ↔ cloud VM, etc. The protocol is the same
WebSocket gateway used for local channels, with three additions that
make `gateway.host: 0.0.0.0` actually safe:

1. **TLS** — encrypts the wire so the connection URL + token can't be
   sniffed.
2. **Verified-peers gate** — flips the trust model from "URL+token =
   trusted" to "must complete IDENTIFY handshake."
3. **Tailscale discovery** — finds peer agents on your tailnet without
   sharing URLs out-of-band.

None of the three works alone — TLS without IDENTIFY just hides
credentials in transit; IDENTIFY without TLS leaks the handshake;
discovery without either is dangerous. They ship together.

## Identity layer

Every agent has a long-lived **Ed25519 keypair**. On first connect to
a new peer, both sides exchange `IDENTIFY` messages with a
challenge-response signed by the private key. The receiver records the
peer's public key in a TOFU (trust-on-first-use) ledger with SSH
known-hosts semantics — the **next** time you see that peer ID, the
key must match or the connection is refused. This catches MITM and
key-rotation attempts.

## TLS

Add to `config.yaml`:

```yaml
gateway:
  tls_cert: "/path/to/cert.pem"   # PEM cert chain
  tls_key:  "/path/to/key.pem"    # PEM private key
```

When both are set, the gateway serves over `wss://` instead of `ws://`.
Bad paths fail loudly at startup — no silent fallback to plaintext.
Partial config (cert without key, or vice versa) does not enable TLS;
you must set both.

For self-signed dev certs, generate with:

```bash
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem \
  -days 365 -nodes -subj "/CN=localhost"
```

For production, use Let's Encrypt or your org's CA.

## Verified-peers gate

```yaml
gateway:
  require_verified_peers: true    # default false
  verify_grace_seconds: 15        # default 15
```

When on, only peers that have completed the IDENTIFY handshake can
send `chat` or `command` messages. **Loopback connections are always
exempt** — your local CLI / Web / VSCode adapters don't break when you
turn this on. There is a brief grace window (default 15s) after
connect where unverified peers can still chat — without it, the
peer's first message would race the handshake and get refused even
when about to verify successfully.

After the grace expires, unverified non-loopback peers are refused
with an explicit "verified-peers mode" error. Refusal is enforced in
both `_handle_chat` and `_handle_command`.

## Discovery (Tailscale)

```python
from core.peer_discovery import discover_peers
peers = await discover_peers(probe=True, tagged_only=False)
```

Or via the agent's `agent_discover` tool (DEFERRED tier — opt in
explicitly; not auto-loaded). Backend in v1 is **Tailscale**: shells
out to `tailscale status --json`, parses peers (modern dict shape +
legacy list shape both supported), then HTTP-probes each candidate's
`/capabilities` endpoint to confirm it's actually an EloPhanto.

Why Tailscale first:

- Free for personal use, magic-DNS, no port forwarding, encrypts at
  the WireGuard layer.
- Mature CLI / JSON output, easy to parse defensively.

Why not mDNS in v1: mDNS is LAN-only and noisier; Tailscale covers
LAN + cross-internet and is what most operators already use.

Discovery never auto-connects. It returns candidate URLs + capabilities
metadata; the operator (or the agent in chat) decides which to
`agent_connect` to.

### Tailscale ACL tag

Tag a machine with `tag:elophanto-agent` in your Tailscale ACLs and
the discovery layer treats it as a likely peer without probing. Useful
when the probe endpoint isn't reachable but you trust the tag.

## Doctor checks

`elophanto doctor` reports:

- **Gateway security** — five states: loopback OK / verified+TLS OK /
  verified-no-TLS warn / TLS-no-verified warn / both-off-with-public-host
  warn.
- **Tailscale** — warn if `gateway.host` is `0.0.0.0` and Tailscale
  isn't installed (you have a public-bound gateway with no easy
  discovery path for trusted peers).

## File layout

- `core/gateway.py` — TLS context, verified-peers gate
- `core/peer_discovery.py` — Tailscale backend + parser
- `tools/agent_identity/discover_tool.py` — `agent_discover` tool
- `tests/test_core/test_gateway_hardening.py` — TLS + gate tests
- `tests/test_core/test_peer_discovery.py` — parser fixtures

## Related

- [02-ARCHITECTURE.md](02-ARCHITECTURE.md) — gateway + session layer
- [07-SECURITY.md](07-SECURITY.md) — broader security posture
- [27-SECURITY-HARDENING.md](27-SECURITY-HARDENING.md) — other hardening
