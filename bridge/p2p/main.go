// elophanto-p2pd: a libp2p sidecar daemon for the EloPhanto agent.
//
// Speaks newline-delimited JSON-RPC over a Unix socket. Mirrors the
// design of the Node browser bridge — Python parent spawns this binary,
// connects to the socket, sends requests, receives responses + events.
//
// Why a sidecar at all: py-libp2p is missing DCUtR + parts of the DHT
// and has no production deployments. go-libp2p is the canonical impl
// (IPFS, Filecoin, Ethereum). Shipping the Go binary as a sidecar gets
// us battle-tested transport without forcing the agent to become a Go
// process. Same trade we already made for the browser bridge.
//
// Usage (Python parent will do this; manual run is for debugging):
//
//	$ elophanto-p2pd --socket /tmp/elophanto-p2p.sock
//
// Then send requests, one JSON object per line:
//
//	{"id":1,"method":"host.open","params":{"private_key_hex":"...","listen_addrs":[],"bootstrap":[],"relays":[]}}
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"sync"
	"syscall"
)

func main() {
	var (
		socketPath string
		mode       string
		keyPath    string
		listenStr  string
	)
	flag.StringVar(&socketPath, "socket", defaultSocketPath(), "Unix socket path to listen on (mode=agent only)")
	flag.StringVar(&mode, "mode", "agent", "operating mode: 'agent' (JSON-RPC sidecar) or 'relay' (public bootstrap+relay)")
	flag.StringVar(&keyPath, "key", "/var/lib/elophanto-relay/identity.key", "path to Ed25519 private key (mode=relay only — created if missing)")
	flag.StringVar(&listenStr, "listen", "/ip4/0.0.0.0/tcp/4001,/ip4/0.0.0.0/udp/4001/quic-v1,/ip6/::/tcp/4001,/ip6/::/udp/4001/quic-v1", "comma-separated multiaddrs to listen on (mode=relay only)")
	flag.Parse()

	if mode == "relay" {
		// Public bootstrap+relay — no JSON-RPC, just runs forever.
		// See relay.go for the implementation.
		runRelay(keyPath, listenStr)
		return
	}

	// Pre-clean the socket file — listen() fails if it already exists.
	// Operators occasionally hard-kill the daemon and leave a stale
	// inode; this saves a confused restart.
	_ = os.Remove(socketPath)

	if err := os.MkdirAll(filepath.Dir(socketPath), 0o700); err != nil {
		log.Fatalf("create socket dir: %v", err)
	}

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		log.Fatalf("listen %s: %v", socketPath, err)
	}
	defer listener.Close()

	// Restrict to owner — the socket carries our private key on
	// host.open, so 0600 is non-negotiable.
	if err := os.Chmod(socketPath, 0o600); err != nil {
		log.Fatalf("chmod %s: %v", socketPath, err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	events := make(chan rpcEvent, 256)
	host := newHost(events)
	disp := &dispatcher{host: host}

	// Single connection at a time. The Python side multiplexes requests
	// onto one socket — we don't need accept-loop concurrency, and a
	// single writer simplifies the response/event interleaving.
	go acceptLoop(ctx, listener, disp, events)

	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)
	<-sigs
	log.Println("shutting down")
}

func defaultSocketPath() string {
	dir := os.Getenv("XDG_RUNTIME_DIR")
	if dir == "" {
		dir = "/tmp"
	}
	return filepath.Join(dir, fmt.Sprintf("elophanto-p2p-%d.sock", os.Getpid()))
}

func acceptLoop(ctx context.Context, l net.Listener, disp *dispatcher, events chan rpcEvent) {
	for {
		conn, err := l.Accept()
		if err != nil {
			select {
			case <-ctx.Done():
				return
			default:
				log.Printf("accept: %v", err)
				continue
			}
		}
		go handleConn(ctx, conn, disp, events)
	}
}

// handleConn is the per-connection request loop. Reads newline-delimited
// JSON requests, dispatches them, and concurrently drains the events
// channel onto the same socket. A single mutex serializes writes so
// responses and events don't interleave mid-line.
func handleConn(ctx context.Context, conn net.Conn, disp *dispatcher, events chan rpcEvent) {
	defer conn.Close()

	var writeMu sync.Mutex
	encoder := json.NewEncoder(conn)

	writeLine := func(v interface{}) {
		writeMu.Lock()
		defer writeMu.Unlock()
		if err := encoder.Encode(v); err != nil {
			log.Printf("write: %v", err)
		}
	}

	// Event drainer — runs until the connection closes.
	pumpCtx, pumpCancel := context.WithCancel(ctx)
	defer pumpCancel()
	go func() {
		for {
			select {
			case <-pumpCtx.Done():
				return
			case ev := <-events:
				writeLine(ev)
			}
		}
	}()

	scanner := bufio.NewScanner(conn)
	// Big buffer — host.open params can include long bootstrap lists,
	// and stream.send carries base64 payloads that grow.
	scanner.Buffer(make([]byte, 0, 64*1024), 8*1024*1024)
	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}
		var req rpcRequest
		if err := json.Unmarshal(line, &req); err != nil {
			writeLine(rpcResponse{ID: 0, Error: fmt.Sprintf("parse request: %v", err)})
			continue
		}
		// Dispatch on a goroutine so a slow handler doesn't block the
		// next request. The Python side can send concurrent requests
		// (e.g. stream.recv polls happening alongside a peer.find).
		go func(req rpcRequest) {
			resp := disp.dispatch(ctx, req)
			writeLine(resp)
		}(req)
	}
	if err := scanner.Err(); err != nil {
		log.Printf("scanner: %v", err)
	}
}
