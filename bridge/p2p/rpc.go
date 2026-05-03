package main

import (
	"context"
	"encoding/json"
	"fmt"
)

// JSON-RPC over Unix socket. Newline-delimited JSON; one request per line,
// one response per line. Mirrors the shape used by bridge/browser so the
// Python side can use the same I/O pattern.
//
// Wire format (request):
//   {"id": 1, "method": "host.open", "params": {...}}
// Wire format (response):
//   {"id": 1, "result": {...}}              // on success
//   {"id": 1, "error": "human message"}     // on failure
//
// Server-pushed events are also newline-delimited JSON but with no "id":
//   {"event": "peer.connected", "data": {"peer_id": "..."}}
//
// We deliberately keep the surface small: 5 verbs total. More can come
// later without breaking the contract — clients tolerate unknown events.

type rpcRequest struct {
	ID     uint64          `json:"id"`
	Method string          `json:"method"`
	Params json.RawMessage `json:"params"`
}

type rpcResponse struct {
	ID     uint64      `json:"id"`
	Result interface{} `json:"result,omitempty"`
	Error  string      `json:"error,omitempty"`
}

type rpcEvent struct {
	Event string      `json:"event"`
	Data  interface{} `json:"data"`
}

// dispatcher routes a single request to the right handler. Each handler
// gets the parsed Params and returns either a result struct or an error.
// Errors are sent as plain strings — operators read them in logs and
// don't need structured codes for v1.
type dispatcher struct {
	host *p2pHost
}

func (d *dispatcher) dispatch(ctx context.Context, req rpcRequest) rpcResponse {
	resp := rpcResponse{ID: req.ID}
	defer func() {
		if r := recover(); r != nil {
			// Panics in handler code must not kill the sidecar — a single
			// bad request shouldn't take down the whole peer connection.
			resp.Result = nil
			resp.Error = fmt.Sprintf("handler panic: %v", r)
		}
	}()

	switch req.Method {
	case "host.open":
		var p hostOpenParams
		if err := json.Unmarshal(req.Params, &p); err != nil {
			return errResp(req.ID, fmt.Errorf("decode params: %w", err))
		}
		result, err := d.host.open(ctx, p)
		if err != nil {
			return errResp(req.ID, err)
		}
		resp.Result = result

	case "host.status":
		// No params; reports our PeerID, listen addrs, peer count, AutoNAT
		// reachability verdict. Cheap — used by doctor checks.
		result, err := d.host.status()
		if err != nil {
			return errResp(req.ID, err)
		}
		resp.Result = result

	case "peer.find":
		var p peerFindParams
		if err := json.Unmarshal(req.Params, &p); err != nil {
			return errResp(req.ID, fmt.Errorf("decode params: %w", err))
		}
		result, err := d.host.findPeer(ctx, p)
		if err != nil {
			return errResp(req.ID, err)
		}
		resp.Result = result

	case "peer.connect":
		var p peerConnectParams
		if err := json.Unmarshal(req.Params, &p); err != nil {
			return errResp(req.ID, fmt.Errorf("decode params: %w", err))
		}
		result, err := d.host.connect(ctx, p)
		if err != nil {
			return errResp(req.ID, err)
		}
		resp.Result = result

	case "stream.send":
		var p streamSendParams
		if err := json.Unmarshal(req.Params, &p); err != nil {
			return errResp(req.ID, fmt.Errorf("decode params: %w", err))
		}
		if err := d.host.streamSend(p); err != nil {
			return errResp(req.ID, err)
		}
		resp.Result = map[string]bool{"ok": true}

	case "stream.recv":
		var p streamRecvParams
		if err := json.Unmarshal(req.Params, &p); err != nil {
			return errResp(req.ID, fmt.Errorf("decode params: %w", err))
		}
		result, err := d.host.streamRecv(ctx, p)
		if err != nil {
			return errResp(req.ID, err)
		}
		resp.Result = result

	default:
		return errResp(req.ID, fmt.Errorf("unknown method: %s", req.Method))
	}

	return resp
}

func errResp(id uint64, err error) rpcResponse {
	return rpcResponse{ID: id, Error: err.Error()}
}

// ---------------------------------------------------------------------------
// Param + result schemas (mirrored on the Python side as dataclasses)
// ---------------------------------------------------------------------------

type hostOpenParams struct {
	// Hex-encoded Ed25519 private key (32 bytes seed). The same key
	// EloPhanto uses for its IDENTIFY handshake — libp2p's PeerID is
	// deterministically derived from the matching public key.
	PrivateKeyHex string `json:"private_key_hex"`
	// Multiaddr listen specs. Default if empty: TCP + QUIC on random ports.
	ListenAddrs []string `json:"listen_addrs"`
	// Bootstrap peer multiaddrs. The DHT joins via these on open.
	Bootstrap []string `json:"bootstrap"`
	// Static circuit-relay-v2 peers we'll register with on open.
	Relays []string `json:"relays"`
	// When true, opt into AutoRelay (auto-discover relays via DHT).
	// Default true unless explicitly disabled.
	EnableAutoRelay bool `json:"enable_auto_relay"`
}

type hostOpenResult struct {
	PeerID      string   `json:"peer_id"`
	ListenAddrs []string `json:"listen_addrs"`
}

type hostStatusResult struct {
	PeerID      string   `json:"peer_id"`
	ListenAddrs []string `json:"listen_addrs"`
	PeerCount   int      `json:"peer_count"`
	// AutoNAT verdict: "public", "private", or "unknown". Drives the doctor
	// check that warns the user "you'll need a relay" when private.
	NATReachability string `json:"nat_reachability"`
}

type peerFindParams struct {
	PeerID    string `json:"peer_id"`
	TimeoutMs int    `json:"timeout_ms"`
}

type peerFindResult struct {
	PeerID string   `json:"peer_id"`
	Addrs  []string `json:"addrs"`
}

type peerConnectParams struct {
	PeerID     string `json:"peer_id"`
	ProtocolID string `json:"protocol_id"`
	// Optional explicit addrs to dial — bypasses DHT lookup. Used when
	// caller already has them (e.g. from a recent peer.find).
	Addrs     []string `json:"addrs"`
	TimeoutMs int      `json:"timeout_ms"`
}

type peerConnectResult struct {
	StreamID string `json:"stream_id"`
	// Whether the connection was direct (DCUtR success) or through a
	// circuit-relay. Used by callers to flag relay-only connections in
	// the UI ("slower path") and by doctor checks.
	ViaRelay bool `json:"via_relay"`
}

type streamSendParams struct {
	StreamID string `json:"stream_id"`
	// Base64-encoded payload. Binary-safe over JSON; the Python side
	// already does the same trick for the browser bridge.
	DataB64 string `json:"data_b64"`
}

type streamRecvParams struct {
	StreamID  string `json:"stream_id"`
	MaxBytes  int    `json:"max_bytes"`
	TimeoutMs int    `json:"timeout_ms"`
}

type streamRecvResult struct {
	DataB64 string `json:"data_b64"`
	// True if the remote half-closed and no more data will arrive after
	// what's in DataB64. Caller uses this to stop polling.
	EOF bool `json:"eof"`
}
