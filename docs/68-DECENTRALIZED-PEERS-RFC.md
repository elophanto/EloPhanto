# RFC: Decentralized Peer Connections via libp2p

**Author:** Petr Royce + Claude (collab)
**Date:** 2026-05-03
**Status:** Draft

## Summary

Add libp2p as a cross-internet peer transport so two EloPhanto agents
on different networks can find and connect to each other using only
each other's Ed25519 public key — no Tailscale, no elophanto.com
registry, no port forwarding. Decentralized in the same operational
sense as Bitcoin or IPFS: requires bootstrap seeds (swappable, plural,
operator-runnable), but no single party is load-bearing.

Tailscale and direct-URL connections from [docs/67-AGENT-PEERS.md](67-AGENT-PEERS.md)
remain as alternative transports — this RFC adds an option, doesn't
replace anything.

## Motivation

Today, two agents on different networks can connect via:

1. **Tailscale** — easy, but requires both peers on the same tailnet,
   and Tailscale Inc is a (soft) third party.
2. **Public IP + port forward** — requires admin access to the router,
   doesn't work behind CGNAT, exposes the gateway publicly.
3. **Reverse tunnel (Cloudflare/ngrok)** — requires a hosted third
   party that sees all traffic.

None of these match the ethos of "your data stays on your machine."
The user has explicitly chosen *decentralized* — accepting the
operational cost in exchange for removing third-party dependencies on
the connection path.

The honest framing: pure P2P with literally zero seed nodes is
impossible (you cannot pull peers out of the void). Every production
P2P system — Bitcoin, IPFS, BitTorrent, Ethereum — has bootstrap seeds.
The architectural goal is **no single load-bearing party**: seeds and
relays are plural, swappable, and runnable by anyone, so the user can
choose who they trust (or trust no one and run their own).

## Design

### Architecture: layered transports

| Layer | Use case | Centralization cost |
|---|---|---|
| Loopback | local CLI/Web/VSCode adapters | none |
| mDNS | same LAN | none |
| Tailscale (existing) | both peers on same tailnet | Tailscale Inc |
| **libp2p Kademlia DHT** | identity-keyed peer lookup | needs ≥1 bootstrap seed in DHT |
| **libp2p DCUtR** | direct connection after NAT hole-punch | requires bootstrap to find peer first |
| **libp2p circuit-relay-v2** | symmetric NAT fallback (~20% of homes) | needs ≥1 reachable relay |
| Public IP | direct, no help | none |

The libp2p layers (the new work) compose into a single user-facing
operation: `agent_connect <pubkey>` resolves via DHT, attempts direct
connection (DCUtR), falls back to relay, and surfaces the wrapped
EloPhanto WebSocket protocol on top of the libp2p stream.

### Why libp2p

- **Identity-keyed addressing.** Peers are looked up by their Ed25519
  PeerID, not network address. Matches our existing Ed25519 + IDENTIFY
  + TOFU model from [docs/67-AGENT-PEERS.md](67-AGENT-PEERS.md).
- **NAT traversal that actually works.** DCUtR (Direct Connection
  Upgrade through Relay) achieves direct connections through ~80% of
  home NATs by hole-punching after an initial relayed handshake.
  Battle-tested by IPFS, Filecoin, Ethereum 2.0.
- **Noise transport.** Encryption end-to-end at the libp2p layer; even
  the relay sees only ciphertext.
- **Swappable everything.** Bootstrap seeds, relays, transports — all
  config, not protocol.

### Why a Go sidecar (not pure Python)

`py-libp2p` is significantly less mature than `go-libp2p` — missing
DCUtR, partial DHT, no production deployments at scale. Shipping it
would mean inheriting that maturity gap.

The pragmatic path mirrors the existing Node browser bridge
(`bridge/browser/`): spawn a Go binary as a sidecar daemon, talk to it
over a local Unix socket via JSON-RPC. The agent sees only the RPC
surface; the underlying P2P stack runs in a battle-tested binary.

```
┌──────────────────────────────────────────┐
│ EloPhanto agent (Python)                 │
│   core/peer_p2p.py — RPC client          │
└──────────────┬───────────────────────────┘
               │ JSON-RPC over Unix socket
               ▼
┌──────────────────────────────────────────┐
│ bridge/p2p/elophanto-p2pd (Go binary)    │
│   - go-libp2p host                       │
│   - Kademlia DHT                         │
│   - DCUtR + AutoNAT + circuit-relay-v2   │
│   - noise transport                      │
└──────────────────────────────────────────┘
```

Binary size: ~15 MB, shipped per-platform like the Node bridge does.

### RPC surface (the contract)

The Go sidecar exposes 4 verbs over Unix socket:

```jsonc
// Open the host with our Ed25519 key. Returns our PeerID.
{ "method": "host.open", "params": {
    "private_key_hex": "...",          // our Ed25519 priv key
    "listen_addrs": ["/ip4/0.0.0.0/tcp/0", "/ip4/0.0.0.0/udp/0/quic"],
    "bootstrap": ["/ip4/.../p2p/12D3...", ...],
    "relays":    ["/ip4/.../p2p/12D3...", ...]
}}

// Find a peer's reachable multiaddrs by their PeerID. Uses DHT.
{ "method": "peer.find", "params": {
    "peer_id": "12D3KooW...",
    "timeout_ms": 10000
}}

// Open a stream to a peer (auto-attempts direct, falls back to relay).
{ "method": "peer.connect", "params": {
    "peer_id": "12D3KooW...",
    "protocol_id": "/elophanto/1.0.0"
}} // returns stream_id

// Send / receive on a stream.
{ "method": "stream.send", "params": { "stream_id": "...", "data_b64": "..." }}
{ "method": "stream.recv", "params": { "stream_id": "...", "max_bytes": 65536 }}
```

Events (server-pushed): `peer.connected`, `peer.disconnected`,
`stream.opened`, `stream.closed`, `nat.status` (for AutoNAT
public-reachability detection).

### Identity bridge

EloPhanto already has Ed25519 keypairs per agent (used for IDENTIFY +
TOFU ledger from the prior peer hardening work). libp2p's PeerID is
deterministically derived from an Ed25519 public key — same key, same
PeerID. The integration:

- On agent start, `core/peer_p2p.py` reads our existing identity key,
  hands the private key to the Go sidecar via `host.open`.
- Our PeerID is published to the DHT automatically (libp2p host
  behaviour).
- Incoming streams pass through the same TOFU ledger we already use:
  the libp2p noise handshake's peer-key pin maps to our
  `verified-peers` known-hosts file. Same trust semantics, new
  transport.
- The verified-peers gate from [docs/67-AGENT-PEERS.md](67-AGENT-PEERS.md)
  applies unchanged — the gate doesn't care which transport delivered
  the connection.

### Discovery integration

`agent_discover` grows a new method:

```python
peers = await discover_peers(method="p2p", peer_id="12D3KooW...")
```

For known PeerIDs (e.g. a friend gave you their pubkey out of band),
this DHT-resolves to their current multiaddrs. For "find any
EloPhanto peers nearby," we use a libp2p **rendezvous protocol** topic
(`/elophanto/peers/v1`) so peers can announce + discover each other
without a central registry.

Tailscale discovery stays. Users with both methods enabled get a
union of results.

### Connect path

`agent_connect <peer_id_or_url>` becomes:

1. If input is a URL (`wss://...`), use existing Tailscale/direct
   transport.
2. If input is a PeerID, call `peer.find` to resolve multiaddrs, then
   `peer.connect` with our protocol ID.
3. The libp2p stream gets wrapped in our existing WebSocket-shaped
   protocol — the channels layer doesn't change. From the
   `_handle_chat` / `_handle_command` perspective, a libp2p stream is
   indistinguishable from a wss:// connection.

### Bootstrap + relay nodes

We ship a hardcoded default seed list (5-10 entries, community-runnable):

```yaml
peers:
  bootstrap_nodes:
    - "/dnsaddr/bootstrap.elophanto.community/p2p/12D3KooW..."
    - "/dnsaddr/seed-1.community/p2p/12D3KooW..."
    # ... 3-8 more
  relay_nodes:
    - "/dnsaddr/relay-1.community/p2p/12D3KooW..."
    - "/dnsaddr/relay-2.community/p2p/12D3KooW..."
  # Operators who trust nobody point both lists at their own infra:
  # bootstrap_nodes: ["/ip4/192.168.1.10/tcp/4001/p2p/12D3..."]
```

**Honest operational reality:** at launch, "community-run" means us
running 1-2 of each on $5/mo VPSes until others contribute. We must
be honest in the doctor warnings if our nodes are the only ones
configured — the user is then trusting us by default, even though the
architecture allows them not to.

### Doctor checks

`elophanto doctor` extends:

- **P2P sidecar** — green if `elophanto-p2pd` is installed and running;
  red if missing; yellow if running but not yet bootstrapped.
- **Bootstrap reachability** — at least one configured bootstrap node
  must be reachable; warn if all dead.
- **NAT status** — surface AutoNAT's verdict: public / private /
  unknown. If private, note that incoming connections will route via
  relay (works but slower).
- **Trust posture** — warn if the user is using only the default seed
  list (i.e. trusting us by default), pointing at the config knob to
  swap.

### Wire compatibility with current peer protocol

The libp2p stream carries the **same** EloPhanto protocol messages
defined in `core/protocol.py` (chat, command, response, event,
IDENTIFY, etc.). Only the transport changes. This means:

- Existing `_handle_chat` / `_handle_command` paths work without modification.
- The verified-peers gate works without modification (it operates on
  the wrapped protocol layer, not the transport).
- Channel adapters (CLI, Web, VSCode) don't need to know whether the
  remote peer arrived via wss:// or libp2p.

### Tools added

- `agent_p2p_status` (SAFE) — reports sidecar health, our PeerID, AutoNAT verdict, peer count.
- `agent_discover` extended with `method="p2p"`.
- `agent_connect` accepts PeerIDs in addition to URLs.

No new tier; all existing in `agent_identity` group.

## Alternatives

### A. Tailscale-only (status quo)

Keep what we have. Honest, works for ~80% of cases. Trade: Tailscale
Inc is in the path; not aligned with the user's stated decentralization
goal. **Rejected** — user explicitly chose decentralized.

### B. WireGuard mesh via Headscale (self-hosted Tailscale)

Replaces Tailscale Inc with a user-operated coordinator. Removes one
trust anchor but introduces a new operational burden (running
Headscale) without adding anything Tailscale doesn't already do.
**Rejected** — same shape, different logo.

### C. Pure py-libp2p (no Go sidecar)

Avoids the binary dependency. Trade: py-libp2p is missing DCUtR,
partial DHT support, no production deployments at scale. We'd be
either shipping known-broken NAT traversal or contributing months of
upstream work to py-libp2p. **Rejected** — too immature.

### D. WebRTC data channels (DTLS-SRTP + STUN/ICE/TURN)

Same hole-punching machinery as libp2p, but designed for browsers and
audio/video. Could work, but inherits browser-shaped assumptions
(SDP, signaling servers) that don't fit headless agents. STUN/ICE/TURN
infrastructure burden is comparable to libp2p's bootstrap+relay.
**Rejected** — wrong shape for our use case; libp2p is purpose-built
for this.

### E. Custom hole-punching protocol

NIH. Months of work to reach where libp2p already is. **Rejected**.

### F. Yggdrasil / cjdns / other overlay meshes

Yggdrasil is closest to "true P2P" — uses cryptographic addressing,
no central coordinator, peers announce via link-local + manual peer
lists. Trade: smaller community than libp2p, less mature tooling, and
peers still need *some* initial address exchange (same bootstrap
problem, different shape). **Considered, deferred** — could be a
future additional transport, not v1.

### G. elophanto.com Supabase as central directory

Discussed and rejected by the user explicitly. Recreates the
third-party dependency we're trying to remove.

## Migration

Backward compatible — new transport, no breaking changes:

- Existing `gateway.host` / TLS / verified-peers config keeps working.
- Existing wss:// peer connections continue functioning.
- Tailscale discovery continues functioning.
- Users who want libp2p enable it explicitly:

```yaml
peers:
  p2p:
    enabled: true
    listen_addrs: ["/ip4/0.0.0.0/tcp/4001", "/ip4/0.0.0.0/udp/4001/quic"]
  bootstrap_nodes: [...]   # defaults from code if omitted
  relay_nodes: [...]
```

- First boot with `peers.p2p.enabled: true` triggers the sidecar
  install (same UX as the Node browser bridge first-run).
- Existing TOFU ledger entries from wss:// connections carry over —
  the trust pin is on the Ed25519 pubkey, not the transport.

## Drawbacks

1. **New binary dependency.** `elophanto-p2pd` joins the Node browser
   bridge as a per-platform shipped binary. ~15 MB additional install
   size. Mitigation: only installed when `peers.p2p.enabled: true`.

2. **Operational burden.** We must run at least one bootstrap and one
   relay until community contributes more. ~$10/mo VPS cost. If we
   stop running them and no community exists yet, default users get
   broken decentralization. Mitigation: be honest in doctor warnings;
   recruit community operators early.

3. **Symmetric NAT residual ~20%.** Some home routers and most carrier
   NATs cannot be hole-punched. These users will route through relays
   permanently — works, but slower (~50-200ms added latency, depending
   on relay location). Not unique to us; same constraint applies to
   IPFS, WebRTC, and every other P2P system.

4. **Metadata leak to bootstrap nodes.** Bootstrap operators see that
   `<our PeerID> connected from <our IP>`. Not message content
   (encrypted), but enough to build a presence graph. Lower than
   centralized directories (operator only sees their slice), but
   non-zero. Mitigation: document clearly; users who need stronger
   privacy can route the sidecar over Tor (libp2p supports onion
   transports).

5. **Implementation cost.** ~7 days to ship v1 (sidecar + integration
   + doctor + tests). Comparable to the original peer-hardening work.
   Plus ongoing operational tail.

6. **DHT poisoning surface.** Sybil attacks on Kademlia are a known
   issue (an attacker spinning up many fake PeerIDs can degrade
   lookups). libp2p has mitigations (S/Kademlia, peer routing
   filters); we inherit them. If our network grows large enough to
   attract attacks, we may need additional hardening.

## Implementation plan

Ordered, with checkpoints:

1. **Spike (~2 days):** `bridge/p2p/` Go sidecar with go-libp2p,
   exposing the 4 RPC verbs. **Acceptance:** two laptops on different
   home networks (one behind home NAT, one on hotel WiFi) can connect
   via DCUtR. If DCUtR fails for our setup, this RFC is moot — replan.

2. **Identity bridge (~1 day):** Convert our Ed25519 keypair to
   libp2p PeerID. Verify TOFU ledger entries created via wss://
   transport accept connections from the same PeerID via libp2p.

3. **Discovery integration (~2 days):** `agent_discover --method=p2p`
   (DHT FIND_NODE + rendezvous topic). Tailscale path unchanged.

4. **Connect path (~1 day):** `agent_connect <pubkey>` resolves via
   DHT, opens libp2p stream, wraps in existing protocol.

5. **Default seeds + relays + doctor checks (~1 day):** Config knobs,
   hardcoded defaults, doctor extensions.

6. **Operate one bootstrap + one relay (~ongoing):** $10/mo VPS each.
   Document the multiaddrs in the default seed list.

7. **Tests:** sidecar mocking + protocol-level integration tests +
   one true cross-internet test in CI (skippable when CI lacks
   network access).

**Total:** ~7 days work + operational tail.

**First go/no-go gate:** step 1 spike. If go-libp2p's DCUtR doesn't
reliably hole-punch through the home NATs we test on, the rest of the
plan needs replanning (likely: lean harder on relay-first, not
direct-first).

## Open questions

1. **Where do the bootstrap nodes live?** $5/mo VPS we operate vs.
   recruiting community ops day one. Probably us at v1; community
   over time.

2. **Should the sidecar be optional or always-installed?** Lean
   optional — many users won't need cross-network peers and don't
   want the binary. `peers.p2p.enabled: true` triggers install.

3. **Tor transport — v1 or later?** libp2p supports it. Adds privacy
   for paranoid users but adds complexity. Defer to v2.

4. **Does the agent-commune layer use this or stay separate?** Likely
   stays separate (commune is async social, not interactive peer
   chat). But worth asking.

5. **PeerID rotation / multi-device.** If one user runs EloPhanto on
   laptop + server, are they two PeerIDs or one shared? Probably two,
   but worth a UX think.
