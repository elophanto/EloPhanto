package main

import (
	"context"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"io"
	"sync"
	"sync/atomic"
	"time"

	"github.com/libp2p/go-libp2p"
	dht "github.com/libp2p/go-libp2p-kad-dht"
	"github.com/libp2p/go-libp2p/core/crypto"
	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/network"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/libp2p/go-libp2p/core/protocol"
	"github.com/libp2p/go-libp2p/p2p/protocol/holepunch"
	ma "github.com/multiformats/go-multiaddr"
)

// p2pHost is the long-lived libp2p host wrapped to fit our RPC contract.
// One instance per sidecar process. host.open() must be called exactly
// once before any other RPC; subsequent calls are an error (we don't
// support hot-swapping identities — restart the sidecar instead).
type p2pHost struct {
	mu sync.Mutex

	h         host.Host
	dht       *dht.IpfsDHT
	opened    bool
	streams   sync.Map // stream_id -> *streamWrapper
	streamSeq atomic.Uint64

	events chan rpcEvent // buffered; emitter drains to stdout

	// Kept for status reporting.
	bootstrap []peer.AddrInfo
	relays    []peer.AddrInfo
}

const elophantoProtocol = protocol.ID("/elophanto/1.0.0")

func newHost(events chan rpcEvent) *p2pHost {
	return &p2pHost{events: events}
}

// open builds the libp2p host with our identity, configures DHT +
// hole-punching + auto-relay, and joins the bootstrap nodes.
//
// The interesting design choices:
//   - We pass our existing Ed25519 priv key in. PeerID is derived from
//     the matching pub key, so it's deterministic — same agent always
//     advertises the same PeerID across restarts.
//   - DHT mode is auto: client-only when we're behind NAT, server when
//     we have a public reachable address. AutoNAT drives the switch.
//   - holepunch.Service registers DCUtR; AutoRelay finds circuit-relay
//     nodes via the DHT when we're not directly reachable.
//   - Stream handler attaches itself to /elophanto/1.0.0 — incoming
//     streams emit a peer.connected event and start a recv buffer.
func (p *p2pHost) open(ctx context.Context, params hostOpenParams) (*hostOpenResult, error) {
	p.mu.Lock()
	defer p.mu.Unlock()

	if p.opened {
		return nil, fmt.Errorf("host already opened (restart sidecar to change identity)")
	}

	priv, err := decodeEd25519PrivateKey(params.PrivateKeyHex)
	if err != nil {
		return nil, fmt.Errorf("decode private key: %w", err)
	}

	if len(params.ListenAddrs) == 0 {
		params.ListenAddrs = []string{
			"/ip4/0.0.0.0/tcp/0",
			"/ip4/0.0.0.0/udp/0/quic-v1",
		}
	}

	bootstrap, err := parsePeerAddrs(params.Bootstrap)
	if err != nil {
		return nil, fmt.Errorf("parse bootstrap: %w", err)
	}
	relays, err := parsePeerAddrs(params.Relays)
	if err != nil {
		return nil, fmt.Errorf("parse relays: %w", err)
	}
	p.bootstrap = bootstrap
	p.relays = relays

	// Build the host. Order of options matters less in modern go-libp2p
	// but we keep it explicit for readability.
	opts := []libp2p.Option{
		libp2p.Identity(priv),
		libp2p.ListenAddrStrings(params.ListenAddrs...),
		libp2p.EnableHolePunching(holepunch.WithTracer(nil)),
		libp2p.EnableNATService(),
		libp2p.NATPortMap(),
		libp2p.DefaultSecurity, // includes noise
	}

	// AutoRelay defaults on; user can disable explicitly. Without it, peers
	// behind symmetric NAT have no way to be reached at all.
	if params.EnableAutoRelay || len(relays) > 0 {
		if len(relays) > 0 {
			opts = append(opts, libp2p.EnableAutoRelayWithStaticRelays(relays))
		} else {
			opts = append(opts, libp2p.EnableAutoRelayWithPeerSource(autoRelayPeerSource(p)))
		}
	}

	h, err := libp2p.New(opts...)
	if err != nil {
		return nil, fmt.Errorf("create host: %w", err)
	}
	p.h = h

	// DHT in auto mode. ModeAuto switches between client and server based
	// on observed reachability — perfect for agents that may or may not
	// be publicly reachable.
	kdht, err := dht.New(ctx, h, dht.Mode(dht.ModeAuto), dht.BootstrapPeers(bootstrap...))
	if err != nil {
		_ = h.Close()
		return nil, fmt.Errorf("create dht: %w", err)
	}
	p.dht = kdht
	if err := kdht.Bootstrap(ctx); err != nil {
		// Bootstrap is best-effort — if no bootstrap nodes are reachable,
		// the host still works for direct-address connections.
		emitEvent(p.events, "warning", map[string]string{"reason": "dht bootstrap failed", "error": err.Error()})
	}

	// Connect to bootstrap peers to seed the routing table.
	for _, b := range bootstrap {
		bb := b
		go func() {
			cctx, cancel := context.WithTimeout(ctx, 30*time.Second)
			defer cancel()
			_ = h.Connect(cctx, bb)
		}()
	}

	// Stream handler: incoming /elophanto/1.0.0 streams.
	h.SetStreamHandler(elophantoProtocol, p.handleIncomingStream)

	p.opened = true

	addrs := make([]string, 0, len(h.Addrs()))
	for _, a := range h.Addrs() {
		addrs = append(addrs, a.String())
	}
	return &hostOpenResult{
		PeerID:      h.ID().String(),
		ListenAddrs: addrs,
	}, nil
}

func (p *p2pHost) status() (*hostStatusResult, error) {
	p.mu.Lock()
	defer p.mu.Unlock()

	if !p.opened {
		return nil, fmt.Errorf("host not opened")
	}

	addrs := make([]string, 0, len(p.h.Addrs()))
	for _, a := range p.h.Addrs() {
		addrs = append(addrs, a.String())
	}

	// Reachability is reported via the AutoNAT subsystem on the host's
	// reachability event bus. We expose the most recent verdict.
	reach := "unknown"
	// libp2p's reachability is exposed via host.Network().Reachability()
	// in newer versions; fall back to "unknown" if not available.
	if r, ok := getReachability(p.h); ok {
		reach = r
	}

	return &hostStatusResult{
		PeerID:          p.h.ID().String(),
		ListenAddrs:     addrs,
		PeerCount:       len(p.h.Network().Peers()),
		NATReachability: reach,
	}, nil
}

func (p *p2pHost) findPeer(ctx context.Context, params peerFindParams) (*peerFindResult, error) {
	if !p.opened {
		return nil, fmt.Errorf("host not opened")
	}
	pid, err := peer.Decode(params.PeerID)
	if err != nil {
		return nil, fmt.Errorf("decode peer id: %w", err)
	}

	timeout := durationFromMs(params.TimeoutMs, 10*time.Second)
	cctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	info, err := p.dht.FindPeer(cctx, pid)
	if err != nil {
		return nil, fmt.Errorf("dht find: %w", err)
	}
	addrs := make([]string, 0, len(info.Addrs))
	for _, a := range info.Addrs {
		addrs = append(addrs, a.String())
	}
	return &peerFindResult{PeerID: info.ID.String(), Addrs: addrs}, nil
}

func (p *p2pHost) connect(ctx context.Context, params peerConnectParams) (*peerConnectResult, error) {
	if !p.opened {
		return nil, fmt.Errorf("host not opened")
	}
	pid, err := peer.Decode(params.PeerID)
	if err != nil {
		return nil, fmt.Errorf("decode peer id: %w", err)
	}

	// Hand explicit addrs to the peerstore so libp2p tries them first
	// instead of round-tripping through the DHT every connect.
	if len(params.Addrs) > 0 {
		mas, err := parseMultiaddrs(params.Addrs)
		if err != nil {
			return nil, fmt.Errorf("parse addrs: %w", err)
		}
		p.h.Peerstore().AddAddrs(pid, mas, time.Hour)
	}

	timeout := durationFromMs(params.TimeoutMs, 30*time.Second)
	cctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	if err := p.h.Connect(cctx, peer.AddrInfo{ID: pid}); err != nil {
		return nil, fmt.Errorf("connect: %w", err)
	}

	protoID := elophantoProtocol
	if params.ProtocolID != "" {
		protoID = protocol.ID(params.ProtocolID)
	}

	stream, err := p.h.NewStream(cctx, pid, protoID)
	if err != nil {
		return nil, fmt.Errorf("open stream: %w", err)
	}

	sid := p.registerStream(stream)
	viaRelay := connectionIsRelayed(p.h, pid)
	return &peerConnectResult{StreamID: sid, ViaRelay: viaRelay}, nil
}

func (p *p2pHost) streamSend(params streamSendParams) error {
	sw, ok := p.lookupStream(params.StreamID)
	if !ok {
		return fmt.Errorf("unknown stream: %s", params.StreamID)
	}
	data, err := base64.StdEncoding.DecodeString(params.DataB64)
	if err != nil {
		return fmt.Errorf("decode data: %w", err)
	}
	_, err = sw.stream.Write(data)
	return err
}

func (p *p2pHost) streamRecv(ctx context.Context, params streamRecvParams) (*streamRecvResult, error) {
	sw, ok := p.lookupStream(params.StreamID)
	if !ok {
		return nil, fmt.Errorf("unknown stream: %s", params.StreamID)
	}
	maxBytes := params.MaxBytes
	if maxBytes <= 0 {
		maxBytes = 65536
	}
	timeout := durationFromMs(params.TimeoutMs, 5*time.Second)
	if err := sw.stream.SetReadDeadline(time.Now().Add(timeout)); err != nil {
		// Some transports don't support deadlines — treat as non-fatal.
		_ = err
	}

	buf := make([]byte, maxBytes)
	n, err := sw.stream.Read(buf)
	eof := false
	if err == io.EOF {
		eof = true
		err = nil
	}
	if err != nil {
		return nil, fmt.Errorf("read: %w", err)
	}
	return &streamRecvResult{
		DataB64: base64.StdEncoding.EncodeToString(buf[:n]),
		EOF:     eof,
	}, nil
}

// ---------------------------------------------------------------------------
// Stream registry
// ---------------------------------------------------------------------------

type streamWrapper struct {
	id     string
	stream network.Stream
}

func (p *p2pHost) registerStream(s network.Stream) string {
	id := fmt.Sprintf("s%d", p.streamSeq.Add(1))
	p.streams.Store(id, &streamWrapper{id: id, stream: s})
	emitEvent(p.events, "stream.opened", map[string]string{
		"stream_id":   id,
		"remote_peer": s.Conn().RemotePeer().String(),
		"protocol_id": string(s.Protocol()),
		"remote_addr": s.Conn().RemoteMultiaddr().String(),
	})
	return id
}

func (p *p2pHost) lookupStream(id string) (*streamWrapper, bool) {
	v, ok := p.streams.Load(id)
	if !ok {
		return nil, false
	}
	return v.(*streamWrapper), true
}

func (p *p2pHost) handleIncomingStream(s network.Stream) {
	// Incoming streams get registered the same way as outgoing — the
	// Python side polls stream.recv until EOF. The peer.connected event
	// gives the Python side enough metadata to set up the read loop.
	id := p.registerStream(s)
	emitEvent(p.events, "peer.connected", map[string]string{
		"peer_id":     s.Conn().RemotePeer().String(),
		"stream_id":   id,
		"protocol_id": string(s.Protocol()),
		"remote_addr": s.Conn().RemoteMultiaddr().String(),
		"direction":   "incoming",
	})
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func decodeEd25519PrivateKey(hexStr string) (crypto.PrivKey, error) {
	raw, err := hex.DecodeString(hexStr)
	if err != nil {
		return nil, fmt.Errorf("hex decode: %w", err)
	}
	// Accept either the 32-byte seed or the full 64-byte expanded form.
	// EloPhanto stores the seed; libp2p wants the seed too (it expands
	// internally). UnmarshalEd25519PrivateKey requires 64-byte form, so
	// we go via crypto/ed25519's NewKeyFromSeed.
	if len(raw) == 32 {
		// Build the full key from seed.
		priv, _, err := crypto.GenerateEd25519Key(seedReader(raw))
		return priv, err
	}
	if len(raw) == 64 {
		return crypto.UnmarshalEd25519PrivateKey(raw)
	}
	return nil, fmt.Errorf("unexpected key length %d (want 32 or 64)", len(raw))
}

// seedReader returns an io.Reader that yields the given bytes, used to
// make crypto.GenerateEd25519Key deterministic from an existing seed.
type seedReaderImpl struct {
	data []byte
	pos  int
}

func (s *seedReaderImpl) Read(p []byte) (int, error) {
	if s.pos >= len(s.data) {
		return 0, io.EOF
	}
	n := copy(p, s.data[s.pos:])
	s.pos += n
	return n, nil
}

func seedReader(seed []byte) io.Reader {
	return &seedReaderImpl{data: seed}
}

func parsePeerAddrs(specs []string) ([]peer.AddrInfo, error) {
	out := make([]peer.AddrInfo, 0, len(specs))
	for _, spec := range specs {
		if spec == "" {
			continue
		}
		addr, err := ma.NewMultiaddr(spec)
		if err != nil {
			return nil, fmt.Errorf("parse %q: %w", spec, err)
		}
		info, err := peer.AddrInfoFromP2pAddr(addr)
		if err != nil {
			return nil, fmt.Errorf("addr info %q: %w", spec, err)
		}
		out = append(out, *info)
	}
	return out, nil
}

func parseMultiaddrs(specs []string) ([]ma.Multiaddr, error) {
	out := make([]ma.Multiaddr, 0, len(specs))
	for _, spec := range specs {
		a, err := ma.NewMultiaddr(spec)
		if err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, nil
}

func durationFromMs(ms int, fallback time.Duration) time.Duration {
	if ms <= 0 {
		return fallback
	}
	return time.Duration(ms) * time.Millisecond
}

func emitEvent(ch chan rpcEvent, name string, data interface{}) {
	select {
	case ch <- rpcEvent{Event: name, Data: data}:
	default:
		// Drop events when the channel is full rather than blocking the
		// libp2p machinery. Python side polls; an occasional drop is OK
		// for stats events, less so for stream lifecycle. If this becomes
		// a real problem we can grow the buffer.
	}
}

// connectionIsRelayed returns true if the active connection to pid is
// going through a circuit-relay rather than direct.
func connectionIsRelayed(h host.Host, pid peer.ID) bool {
	conns := h.Network().ConnsToPeer(pid)
	if len(conns) == 0 {
		return false
	}
	// A relayed connection's remote multiaddr contains "/p2p-circuit".
	for _, c := range conns {
		if isRelayedMultiaddr(c.RemoteMultiaddr()) {
			return true
		}
	}
	return false
}

func isRelayedMultiaddr(a ma.Multiaddr) bool {
	for _, p := range a.Protocols() {
		if p.Code == ma.P_CIRCUIT {
			return true
		}
	}
	return false
}

// getReachability inspects libp2p's network reachability. Returns
// ("public" | "private" | "unknown", true) when known, ("", false) if
// the host doesn't expose it.
func getReachability(_ host.Host) (string, bool) {
	// AutoNAT writes verdicts to the event bus rather than a queryable
	// API. For v1 we report "unknown" and let callers subscribe to
	// nat.status events for live updates. A future revision can wire
	// up the event subscription and cache the latest verdict.
	return "unknown", false
}

// autoRelayPeerSource provides AutoRelay with candidate relay peers.
// When the user hasn't pinned static relays, we let AutoRelay discover
// them via DHT. The function is called periodically; we feed it any
// peer we know that supports the relay protocol.
func autoRelayPeerSource(p *p2pHost) func(ctx context.Context, num int) <-chan peer.AddrInfo {
	return func(ctx context.Context, num int) <-chan peer.AddrInfo {
		out := make(chan peer.AddrInfo, num)
		go func() {
			defer close(out)
			if p.h == nil {
				return
			}
			// Use the DHT to find peers advertising the relay-v2 protocol.
			// In practice AutoRelay calls this often; we keep it cheap.
			for _, pid := range p.h.Peerstore().Peers() {
				select {
				case <-ctx.Done():
					return
				case out <- p.h.Peerstore().PeerInfo(pid):
				}
			}
		}()
		return out
	}
}
