# EloPhanto relay node

Public bootstrap + circuit-relay-v2 node for the EloPhanto libp2p
network. The same `bridge/p2p/elophanto-p2pd` binary that runs as the
agent's sidecar runs here in `--mode=relay` and:

1. Joins the Kademlia DHT in **server mode** so new peers can seed
   their routing tables from us
2. Runs **circuit-relay-v2 (HOP)** so peers behind symmetric NAT can
   route traffic through us as a fallback when DCUtR can't punch
   through (~20% of home NATs)

The relay is transport-only. It never speaks `/elophanto/1.0.0`,
never decodes chat messages, never touches a trust ledger. Traffic
through the HOP relay is end-to-end encrypted via libp2p noise; the
relay sees ciphertext only and can't read user payloads.

## Operational profile

- **Resource use:** idle ~50 MB RSS, scales linearly with active
  relayed connections. Limit set to 512 MB in the systemd unit.
- **Bandwidth:** dominated by relayed peer traffic. No relay caps in
  v1; if abuse becomes a problem, libp2p has per-peer relay limits
  we can wire up.
- **Identity:** stable Ed25519 PeerID across restarts. Key persisted
  at `/var/lib/elophanto-relay/identity.key` (mode 0600, owned by the
  `elophanto` system user). Don't lose it — peers that pinned the
  PeerID in their `bootstrap_nodes` will silently stop reaching you.

## Deploy

This directory contains everything needed to deploy to a fresh Ubuntu
or Debian box. Tested on Ubuntu 24.04 LTS / Hetzner CPX11.

### Server prerequisites

- Public IPv4 (and ideally IPv6)
- Open inbound: TCP 22 (SSH from your IP), TCP 4001, UDP 4001
- 1 GB RAM minimum, 2 GB recommended for headroom
- Go is **not** required on the server — we ship a prebuilt binary

### From a developer machine

1. **Cross-compile the binary:**

   ```bash
   cd bridge/p2p
   GOOS=linux GOARCH=amd64 go build -o elophanto-p2pd-linux-amd64 .
   ```

2. **Upload binary + unit + installer to the server:**

   ```bash
   scp bridge/p2p/elophanto-p2pd-linux-amd64 \
       infra/relay/elophanto-relay.service \
       infra/relay/install.sh \
       root@<server-ip>:/tmp/
   ```

3. **Run the installer:**

   ```bash
   ssh root@<server-ip> "mv /tmp/elophanto-p2pd-linux-amd64 /tmp/elophanto-p2pd && bash /tmp/install.sh"
   ```

   The installer:
   - Creates the `elophanto` system user (no shell, no home)
   - Creates `/var/lib/elophanto-relay` (0700, key file lives here)
   - Installs the binary at `/usr/local/bin/elophanto-p2pd`
   - Drops the systemd unit at `/etc/systemd/system/elophanto-relay.service`
   - Reloads systemd, enables, starts the service
   - Tails the journal and prints the **multiaddr** the relay is
     reachable on — copy this into the agent's
     `peers.bootstrap_nodes` config

### What success looks like

The installer's final output will include something like:

```
relay: PeerID=12D3KooW...
relay: listening on:
relay:   /ip4/<your-public-ip>/tcp/4001/p2p/12D3KooW...
relay:   /ip4/<your-public-ip>/udp/4001/quic-v1/p2p/12D3KooW...
```

Either of those `/ip4/.../p2p/...` lines is what you paste into a
peer's `peers.bootstrap_nodes`.

## Operations

```bash
# Tail logs (relay status reports every 5min)
journalctl -u elophanto-relay -f

# Restart (PeerID stays stable across restarts)
systemctl restart elophanto-relay

# Stop
systemctl stop elophanto-relay

# How many peers connected right now
journalctl -u elophanto-relay --since "5 min ago" | grep status
```

## Updating the binary

```bash
# On dev machine
cd bridge/p2p && GOOS=linux GOARCH=amd64 go build -o elophanto-p2pd-linux-amd64 .
scp bridge/p2p/elophanto-p2pd-linux-amd64 root@<server-ip>:/tmp/elophanto-p2pd
# On server
sudo install -m 0755 /tmp/elophanto-p2pd /usr/local/bin/elophanto-p2pd
sudo systemctl restart elophanto-relay
```

The Ed25519 key file is untouched; PeerID stays stable.

## Security notes

- The systemd unit runs as the unprivileged `elophanto` user with
  `NoNewPrivileges=true`, `ProtectSystem=strict`, and an empty
  `CapabilityBoundingSet`. The relay can read its key file and bind
  ports >1024; nothing else.
- Memory ceiling 512 MB — a leaking binary OOM-kills instead of
  taking down the host.
- The relay's identity key MUST stay 0600 owned by `elophanto`. Loss
  of confidentiality means anyone can impersonate this PeerID.
- The relay does NOT need to be in the trust ledger of its users —
  it's a transport, not an authenticated peer. Users that connect
  through us still authenticate each other's identities via libp2p
  noise + EloPhanto's TOFU layer.
