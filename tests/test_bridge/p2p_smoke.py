"""Local two-sidecar smoke test — proves the full peer.connect + stream
pipeline works end-to-end on a single machine. Cross-NAT verification
is a separate test that needs two real machines.
"""

import json
import secrets
import socket
import subprocess
import time
from base64 import b64decode, b64encode
from pathlib import Path


def call(sock, method, params, req_id):
    sock.sendall(
        (json.dumps({"id": req_id, "method": method, "params": params}) + "\n").encode()
    )
    buf = b""
    deadline = time.time() + 30
    while time.time() < deadline:
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
        # Parse complete lines, return our response (skip events)
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("id") == req_id:
                return obj
            # event — print and keep waiting
            if "event" in obj:
                print(f"  [event {obj['event']}] {obj.get('data')}")
    raise TimeoutError(f"no response for {method}")


def connect(path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(path)
    s.settimeout(30)
    return s


def main():
    # Resolve the binary relative to the repo root regardless of where
    # the script is invoked from.
    repo_root = Path(__file__).resolve().parents[2]
    binary = repo_root / "bridge" / "p2p" / "elophanto-p2pd"
    if not binary.exists():
        raise SystemExit(
            f"binary not built at {binary}\n"
            "run: cd bridge/p2p && go build -o elophanto-p2pd ."
        )

    sock_a, sock_b = "/tmp/p2p-a.sock", "/tmp/p2p-b.sock"
    Path(sock_a).unlink(missing_ok=True)
    Path(sock_b).unlink(missing_ok=True)

    proc_a = subprocess.Popen([str(binary), "--socket", sock_a])
    proc_b = subprocess.Popen([str(binary), "--socket", sock_b])
    time.sleep(2)

    try:
        a = connect(sock_a)
        b = connect(sock_b)

        # Open both hosts on loopback
        seed_a = secrets.token_hex(32)
        seed_b = secrets.token_hex(32)

        ra = call(
            a,
            "host.open",
            {
                "private_key_hex": seed_a,
                "listen_addrs": ["/ip4/127.0.0.1/tcp/0"],
                "bootstrap": [],
                "relays": [],
                "enable_auto_relay": False,
            },
            1,
        )
        print("A opened:", ra["result"])

        rb = call(
            b,
            "host.open",
            {
                "private_key_hex": seed_b,
                "listen_addrs": ["/ip4/127.0.0.1/tcp/0"],
                "bootstrap": [],
                "relays": [],
                "enable_auto_relay": False,
            },
            1,
        )
        print("B opened:", rb["result"])

        b_peer = rb["result"]["peer_id"]
        b_addrs = rb["result"]["listen_addrs"]

        # A connects directly to B (skip DHT — pass explicit addrs)
        rc = call(
            a,
            "peer.connect",
            {
                "peer_id": b_peer,
                "addrs": b_addrs,
                "protocol_id": "/elophanto/1.0.0",
                "timeout_ms": 10000,
            },
            2,
        )
        print("A->B connect:", rc)
        if "error" in rc:
            raise SystemExit(f"connect failed: {rc['error']}")
        stream_id_a = rc["result"]["stream_id"]
        print(f"  via_relay={rc['result']['via_relay']}")

        # A sends "hello" on its stream
        payload = b"hello from A"
        rs = call(
            a,
            "stream.send",
            {
                "stream_id": stream_id_a,
                "data_b64": b64encode(payload).decode(),
            },
            3,
        )
        print("A send:", rs)

        # Drain events on B to find the incoming stream id
        time.sleep(0.5)
        b.sendall(
            (
                json.dumps({"id": 99, "method": "host.status", "params": {}}) + "\n"
            ).encode()
        )
        buf = b""
        b_stream_id = None
        deadline = time.time() + 5
        while time.time() < deadline and b_stream_id is None:
            chunk = b.recv(65536)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line:
                    continue
                obj = json.loads(line)
                if obj.get("event") == "peer.connected":
                    b_stream_id = obj["data"]["stream_id"]
                    print(
                        f"B saw incoming stream: {b_stream_id} from {obj['data']['peer_id']}"
                    )
        if not b_stream_id:
            raise SystemExit("B never saw the incoming stream")

        # B reads
        rr = call(
            b,
            "stream.recv",
            {
                "stream_id": b_stream_id,
                "max_bytes": 1024,
                "timeout_ms": 5000,
            },
            4,
        )
        print("B recv:", rr)
        decoded = b64decode(rr["result"]["data_b64"])
        assert decoded == payload, f"mismatch: got {decoded!r}, want {payload!r}"
        print(f"\nROUND-TRIP OK: A sent {payload!r}, B received {decoded!r}")
        print("Spike step 1 PASS — local stream pipeline works.")

    finally:
        proc_a.terminate()
        proc_b.terminate()
        proc_a.wait(timeout=5)
        proc_b.wait(timeout=5)
        Path(sock_a).unlink(missing_ok=True)
        Path(sock_b).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
