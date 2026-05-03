# elophanto-p2pd — libp2p sidecar daemon

Why a Go sidecar (not pure Python): py-libp2p is missing DCUtR + parts
of the DHT and has no production deployments. go-libp2p is the
canonical impl (IPFS, Filecoin, Ethereum). Same trade we already made
for the Node browser bridge — battle-tested transport without forcing
the agent to become a Go process.

## Build

```bash
cd bridge/p2p
go build -o elophanto-p2pd .
```

Binary is ~40 MB (QUIC + WebRTC pull in pion's stack). Per-platform;
`setup.sh` builds it on first run when `peers.p2p.enabled: true`.

## Wire protocol

Newline-delimited JSON over a Unix socket. One request per line, one
response per line. Server-pushed events have no `id`.

```jsonc
// request
{"id": 1, "method": "host.open", "params": {...}}

// response
{"id": 1, "result": {...}}      // success
{"id": 1, "error": "..."}       // failure

// server-pushed event
{"event": "peer.connected", "data": {...}}
```

## RPC verbs

| Verb | Purpose |
|------|---------|
| `host.open`     | Initialize the libp2p host with our Ed25519 priv key. Idempotent only across restarts — calling twice is an error. |
| `host.status`   | Report our PeerID, listen addrs, peer count, NAT reachability. |
| `peer.find`     | DHT FIND_NODE for a PeerID. Returns reachable multiaddrs. |
| `peer.connect`  | Open a libp2p stream to a peer (auto-retries direct via DCUtR; falls back to relay). |
| `stream.send`   | Write base64-encoded bytes to a stream. |
| `stream.recv`   | Read bytes from a stream (with timeout + EOF flag). |

See [rpc.go](rpc.go) for the full param/result schemas.

## Local smoke test

```bash
go build -o elophanto-p2pd .
python3 ../../tests/test_bridge/p2p_smoke.py
```

Two sidecars open, A connects to B over loopback, sends "hello", B
receives. Proves the full pipeline minus NAT traversal.

## Cross-network test (the real spike gate)

See [docs/68-DECENTRALIZED-PEERS-RFC.md](../../docs/68-DECENTRALIZED-PEERS-RFC.md)
for the two-machine procedure. If DCUtR doesn't punch through your
home NATs, the rest of the libp2p plan needs replanning.

## Why the binary isn't committed

Per-platform builds (darwin/arm64, darwin/amd64, linux/amd64,
linux/arm64). `setup.sh` builds the right one on install. Avoids
shipping ~40 MB per platform in git, and builds reproducibly from
pinned dependencies in [go.mod](go.mod).
