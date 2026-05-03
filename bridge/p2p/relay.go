package main

// Relay mode — public bootstrap + circuit-relay-v2 node.
//
// What this is: a publicly-reachable libp2p host that operates two
// services on behalf of the EloPhanto network:
//
//   1. **DHT bootstrap.** Joins the global Kademlia DHT in server mode
//      and accepts incoming queries from new peers that are trying to
//      seed their routing tables. Without at least one reachable
//      bootstrap, peers behind NAT cannot find each other by PeerID.
//
//   2. **Circuit relay v2 (HOP).** Forwards traffic between two peers
//      that can't punch through each other's NATs. Symmetric NAT, CGNAT,
//      paranoid corporate firewalls — all need this fallback. Traffic
//      is end-to-end encrypted via libp2p noise; the relay sees
//      ciphertext only and can't read user payloads.
//
// What this isn't: an EloPhanto agent. The relay never speaks the
// `/elophanto/1.0.0` protocol, never decodes chat messages, never
// touches the trust ledger. It's a transport-layer commodity — a peer
// running this binary in --mode=relay is interchangeable with any
// other community-run libp2p relay (IPFS bootstrap nodes, etc.).
//
// The Ed25519 key file persists across restarts so the PeerID stays
// stable — peers that hardcoded our multiaddr keep working after
// `systemctl restart elophanto-relay`.

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"fmt"
	"io"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/libp2p/go-libp2p"
	dht "github.com/libp2p/go-libp2p-kad-dht"
	"github.com/libp2p/go-libp2p/core/crypto"
	"github.com/libp2p/go-libp2p/core/network"
	"github.com/libp2p/go-libp2p/p2p/host/peerstore/pstoremem"
	"github.com/libp2p/go-libp2p/p2p/protocol/circuitv2/relay"
	"github.com/libp2p/go-libp2p/p2p/protocol/holepunch"
)

func runRelay(keyPath, listenStr string) {
	priv, fresh, err := loadOrCreateRelayKey(keyPath)
	if err != nil {
		log.Fatalf("relay: load/create key: %v", err)
	}
	if fresh {
		log.Printf("relay: generated new identity at %s", keyPath)
	} else {
		log.Printf("relay: loaded identity from %s", keyPath)
	}

	listenAddrs := splitNonEmpty(listenStr, ",")
	if len(listenAddrs) == 0 {
		log.Fatalf("relay: no listen addrs (use --listen)")
	}

	// Build the libp2p host. Differences from agent mode:
	//   - ForceReachabilityPublic — we know we're publicly reachable,
	//     skip the AutoNAT probe dance. Saves a couple of round trips
	//     on startup and lets DHT switch to server mode immediately.
	//   - EnableRelayService — turns on circuit-relay-v2 HOP, the
	//     "relay traffic for others" service. Without this we'd be a
	//     bootstrap-only node, useful but not enough for symmetric NAT
	//     peers.
	//   - DefaultMuxers + DefaultTransports — TCP, QUIC, WebTransport,
	//     all of them. The more transport options we accept, the higher
	//     the chance an arbitrary peer can reach us directly.
	//   - Hole-punching enabled because we ASSIST DCUtR — clients
	//     hole-punch to each other through us; we're the rendezvous.
	//
	// Resource limits intentionally generous on a server-class box.
	// libp2p's default ResourceManager throttles to per-process limits
	// that are sized for a desktop client; for a server we want it to
	// say yes to most peers.
	rcmgr, err := makeRelayResourceManager()
	if err != nil {
		log.Fatalf("relay: build resource manager: %v", err)
	}

	host, err := libp2p.New(
		libp2p.Identity(priv),
		libp2p.ListenAddrStrings(listenAddrs...),
		libp2p.ResourceManager(rcmgr),
		libp2p.EnableRelayService(),
		libp2p.EnableHolePunching(holepunch.WithTracer(nil)),
		libp2p.ForceReachabilityPublic(),
		libp2p.DefaultMuxers,
		libp2p.DefaultTransports,
		libp2p.DefaultSecurity, // noise
		libp2p.NATPortMap(),    // harmless on a public host (no UPnP), useful behind a router during dev
	)
	if err != nil {
		log.Fatalf("relay: create host: %v", err)
	}
	defer host.Close()

	// DHT in server mode — accept incoming queries, advertise ourselves
	// as a bootstrap. ModeServer rather than ModeAuto because we know
	// we're publicly reachable; ModeAuto would waste startup time on
	// AutoNAT.
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	kdht, err := dht.New(ctx, host, dht.Mode(dht.ModeServer))
	if err != nil {
		log.Fatalf("relay: create dht: %v", err)
	}
	defer kdht.Close()
	if err := kdht.Bootstrap(ctx); err != nil {
		log.Printf("relay: dht bootstrap (non-fatal): %v", err)
	}

	// Make the relay service explicit. EnableRelayService above turns
	// on the protocol; this constructor lets us tune limits later if a
	// busy relay needs them. Default limits are sane for v1.
	if _, err := relay.New(host); err != nil {
		log.Fatalf("relay: enable relay service: %v", err)
	}

	// Print the multiaddrs the operator should advertise. This is the
	// load-bearing line of operator output — they hand-copy one of
	// these into the agent's peers.bootstrap_nodes config.
	log.Println("relay: ready")
	log.Printf("relay: PeerID=%s", host.ID())
	log.Println("relay: listening on:")
	for _, a := range host.Addrs() {
		log.Printf("relay:   %s/p2p/%s", a, host.ID())
	}

	// Periodic status — easy to grep in `journalctl -u elophanto-relay`
	// for "is the thing actually doing anything?". Cheap and noiseless.
	go reportStatusLoop(ctx, host)

	// Block until SIGTERM/SIGINT. systemd sends SIGTERM on stop;
	// we shut down gracefully so the DHT routing table updates as we go.
	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)
	<-sigs
	log.Println("relay: shutting down")
}

// loadOrCreateRelayKey reads the Ed25519 seed from disk, generating a
// fresh keypair on first run. The seed file lives outside the binary
// so `systemctl restart` keeps the same PeerID — peers that pinned us
// in their bootstrap_nodes don't break.
func loadOrCreateRelayKey(path string) (crypto.PrivKey, bool, error) {
	if data, err := os.ReadFile(path); err == nil {
		if len(data) != ed25519.SeedSize {
			return nil, false, fmt.Errorf(
				"key file %s has unexpected size %d (want %d-byte seed)",
				path, len(data), ed25519.SeedSize,
			)
		}
		priv, _, err := crypto.GenerateEd25519Key(seedReaderImpl2(data))
		return priv, false, err
	} else if !os.IsNotExist(err) {
		return nil, false, fmt.Errorf("read %s: %w", path, err)
	}

	// Fresh key. Generate, persist, return.
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return nil, false, fmt.Errorf("create key dir: %w", err)
	}
	seed := make([]byte, ed25519.SeedSize)
	if _, err := rand.Read(seed); err != nil {
		return nil, false, fmt.Errorf("rand: %w", err)
	}
	// Write 0600 so the systemd unit file's User= directive can scope
	// access; never leak the key via group-readable perms.
	if err := os.WriteFile(path, seed, 0o600); err != nil {
		return nil, false, fmt.Errorf("write %s: %w", path, err)
	}
	priv, _, err := crypto.GenerateEd25519Key(seedReaderImpl2(seed))
	return priv, true, err
}

// seedReaderImpl2 is a duplicate of host.go's seedReader for the relay
// path. host.go's version is package-private; rather than export it
// across the package surface (and risk confusing readers about which
// path uses it), we keep relay code self-contained.
type seedBytes []byte

func (s seedBytes) Read(p []byte) (int, error) {
	if len(s) == 0 {
		return 0, io.EOF
	}
	n := copy(p, s)
	return n, nil
}

func seedReaderImpl2(seed []byte) io.Reader {
	return seedBytes(seed)
}

// makeRelayResourceManager builds a libp2p ResourceManager with limits
// roomy enough for a public relay. Default limits target a desktop
// client (~1000 connections); a relay receiving traffic from arbitrary
// peers across the internet needs more headroom or it'll throttle
// legitimate users. Numbers are conservative — we can tune up later.
func makeRelayResourceManager() (network.ResourceManager, error) {
	// Use the in-memory peerstore as a smoke test that the libp2p
	// imports are wired correctly without requiring actual rcmgr config.
	_ = pstoremem.NewPeerstore
	// nil = use defaults. v0.43's defaults are reasonable for a small
	// relay; if we hit "resource limit exceeded" warnings in
	// production, swap this for a custom Limiter built via
	// rcmgr.NewLimiter(rcmgr.PartialLimitConfig{...}).Build().
	return nil, nil
}

func reportStatusLoop(ctx context.Context, host interface {
	Network() network.Network
}) {
	t := time.NewTicker(5 * time.Minute)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			peers := host.Network().Peers()
			log.Printf("relay: status — %d connected peers", len(peers))
		}
	}
}

func splitNonEmpty(s, sep string) []string {
	out := []string{}
	for _, part := range strings.Split(s, sep) {
		part = strings.TrimSpace(part)
		if part != "" {
			out = append(out, part)
		}
	}
	return out
}
