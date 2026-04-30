"""ffmpeg supervisor for pump.fun publishing — internal helper.

Spawned as a detached subprocess by ``LivestreamOrchestrator.start_stream``.
Owns the whole publish lifecycle so the agent's running process doesn't
have to:

  - Re-fetches a fresh stream key from pump.fun on every retry
    (so a rotated key — manual UI reset, server-side rotation,
    expired session — doesn't kill the stream).
  - Restarts ffmpeg with exponential backoff on any non-clean exit.
  - Honours the stop-marker file written by ``stop_stream``.
  - Exits with a distinct status code on JWT expiry so the agent
    can ask the user to re-auth.

This file deliberately has only ``httpx`` as an external dep — no
vault, no socketio, no orchestrator import — so it stays tiny and
its failure modes are easy to reason about. Invoked as
``python -m tools.pumpfun._ffmpeg_supervisor``.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from tools.pumpfun.orchestrator import (
    PUMP_LIVESTREAM_API_BASE,
    build_ffmpeg_cmd,
)

logger = logging.getLogger("pumpfun.supervisor")
logging.basicConfig(
    level=logging.INFO, format="[supervisor] %(asctime)s %(message)s", stream=sys.stdout
)

# Backoff schedule (seconds). Capped so we don't sleep forever on a
# permanent outage. After exhausting the schedule we keep retrying at
# the last interval until the stop marker appears.
_BACKOFF_SCHEDULE = [2, 4, 8, 16, 30, 60, 120]

# When ffmpeg ran for at least this many seconds before dying we treat
# the failure as "transient mid-stream" — reset the backoff counter so
# we don't slow ourselves down after a long successful run.
_HEALTHY_RUN_SECONDS = 60

# Distinct exit codes so the agent can tell why we gave up.
EXIT_CLEAN = 0
EXIT_FATAL = 1
EXIT_AUTH_EXPIRED = 2


def _http_post(
    url: str, *, jwt: str, body: dict[str, Any]
) -> tuple[int, dict[str, Any]]:
    headers = {
        "Authorization": f"Bearer {jwt}",
        "Cookie": f"auth_token={jwt}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://pump.fun",
        "Referer": "https://pump.fun/",
        "User-Agent": "Mozilla/5.0 (compatible; EloPhanto-livestream-supervisor)",
    }
    with httpx.Client(timeout=30.0) as client:
        r = client.post(url, json=body, headers=headers)
    try:
        payload = r.json() if r.content else {}
    except ValueError:
        payload = {"raw": r.text}
    return r.status_code, payload


def _get_credentials(jwt: str, mint: str, prefer: str) -> tuple[str, str, str]:
    """Return ``(protocol, ingest_url, stream_key)`` or raise.

    Tries the preferred protocol first; falls back to the other if
    pump.fun returns the "contact support" placeholder. Tries them in
    a deterministic order so logs are predictable.
    """
    # Make sure the livestream record exists. View-only mode is what
    # pumps RTMP/WHIP credentials. Idempotent.
    status, body = _http_post(
        f"{PUMP_LIVESTREAM_API_BASE}/livestream/create",
        jwt=jwt,
        body={
            "mintId": mint,
            "mode": "view-only",
            "title": "Live now",
            "creatorUsername": "agent",
        },
    )
    if status == 401:
        raise PermissionError("auth_expired")
    if status >= 400:
        logger.info("livestream/create status=%s body=%s", status, str(body)[:300])

    order = ["whip", "rtmp"] if prefer == "whip" else ["rtmp", "whip"]
    last_err: str = ""
    for proto in order:
        proto_enum = 1 if proto == "whip" else 0
        status, body = _http_post(
            f"{PUMP_LIVESTREAM_API_BASE}/livestream/livekit/create-credentials",
            jwt=jwt,
            body={"mintId": mint, "input": proto_enum},
        )
        if status == 401:
            raise PermissionError("auth_expired")
        url = str(body.get("url") or "")
        key = str(body.get("streamKey") or "")
        if url and "error" not in url.lower() and key:
            return proto, url, key
        last_err = f"{proto}: status={status} body={str(body)[:200]}"
        logger.info("[supervisor] %s unavailable: %s", proto, last_err)
    raise RuntimeError(f"No usable creds (last: {last_err})")


def _run_once(
    cfg: dict[str, Any],
    stop_marker: Path,
    *,
    prefer_protocol: str,
) -> tuple[bool, float, str, str]:
    """Spawn ffmpeg once, wait for it to die.

    Returns ``(success, elapsed_seconds, protocol_used, stderr_tail)``.
    The stderr tail (last ~6 KB) lets the caller decide whether the
    failure is a network reachability issue (v6 ICE candidate) and
    flip the next retry's protocol.
    """
    proto, url, key = _get_credentials(cfg["jwt"], cfg["mint"], prefer_protocol)
    cmd = build_ffmpeg_cmd(
        cfg["ffmpeg_path"],
        cfg["video_path"],
        fps=float(cfg["fps"]),
        loop=bool(cfg["loop"]),
        max_iterations=int(cfg["max_iterations"]),
        protocol=proto,
        ingest_url=url,
        stream_key=key,
        voice_pcm_fifo=str(cfg.get("voice_pcm_fifo") or ""),
        image_path=str(cfg.get("image_path") or ""),
        caption_file=str(cfg.get("caption_file") or ""),
    )
    redacted = " ".join("<key>" if c == key else c for c in cmd)
    logger.info("starting ffmpeg (%s): %s", proto, redacted)

    # Capture ffmpeg's combined stdout+stderr into a ring buffer so we
    # can post-mortem the failure mode (v6 ICE unreachable, auth
    # rejected, etc.) and let it through to the supervisor's own
    # stdout (which is the log file) so users still see it live.
    start = time.time()
    proc = subprocess.Popen(  # noqa: S603 — controlled command
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        close_fds=True,
        bufsize=1,
    )

    # Forward signals to ffmpeg so a SIGTERM to the supervisor doesn't
    # leave an orphaned ffmpeg behind.
    def _forward(_signum: int, _frame: object) -> None:
        try:
            stop_marker.touch()
        except OSError:
            pass
        try:
            proc.terminate()
        except OSError:
            pass

    signal.signal(signal.SIGTERM, _forward)
    signal.signal(signal.SIGINT, _forward)

    tail_buf: list[bytes] = []
    tail_max = 6_000  # bytes of trailing output we keep
    if proc.stdout is not None:
        for chunk in iter(lambda: proc.stdout.read(4096) if proc.stdout else b"", b""):
            sys.stdout.buffer.write(chunk)
            sys.stdout.flush()
            tail_buf.append(chunk)
            joined = b"".join(tail_buf)
            if len(joined) > tail_max:
                tail_buf = [joined[-tail_max:]]
    rc = proc.wait()
    stderr_tail = b"".join(tail_buf).decode("utf-8", errors="replace")
    elapsed = time.time() - start
    success = rc == 0
    logger.info("ffmpeg exited rc=%s after %.1fs", rc, elapsed)
    return success, elapsed, proto, stderr_tail


def _is_v6_unreachable(stderr_tail: str) -> bool:
    """Heuristic: WHIP picked an IPv6 ICE candidate we can't reach.

    macOS without IPv6 (or behind a v4-only NAT) sees this from
    LiveKit's TURN server roughly half the time. Symptoms in the log:
    "connect: No route to host" + "udp://[v6]:port".
    """
    if "No route to host" not in stderr_tail:
        return False
    # Look for udp://2... or udp://[ — both indicate v6 destinations
    # (unicast v6 starts with 2/3, link-local with fe80::).
    return (
        "udp://2" in stderr_tail
        or "udp://[" in stderr_tail
        or "udp://fe" in stderr_tail
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="pumpfun-ffmpeg-supervisor")
    parser.add_argument("--config", required=True, help="Path to JSON config file.")
    parser.add_argument(
        "--stop-marker",
        required=True,
        help="Path whose existence ends the supervisor at the next iteration.",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    stop_marker = Path(args.stop_marker)

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    backoff_idx = 0
    iteration = 0
    consecutive_failures = 0
    # Runtime protocol preference — starts at the cfg default, gets
    # flipped automatically on IPv6 ICE unreachable failures so we
    # don't loop forever on a path the network can't carry.
    prefer_protocol = str(cfg.get("prefer_protocol") or "whip")
    v6_failure_count = 0

    while True:
        iteration += 1
        if stop_marker.exists():
            logger.info(
                "stop marker present, exiting cleanly after %d iters", iteration - 1
            )
            try:
                stop_marker.unlink()
            except OSError:
                pass
            sys.exit(EXIT_CLEAN)

        proto_used = prefer_protocol
        stderr_tail = ""
        try:
            success, elapsed, proto_used, stderr_tail = _run_once(
                cfg, stop_marker, prefer_protocol=prefer_protocol
            )
        except PermissionError:
            logger.error(
                "pump.fun JWT expired; supervisor exiting (re-run start to re-auth)"
            )
            sys.exit(EXIT_AUTH_EXPIRED)
        except Exception as e:
            logger.exception("supervisor: cred fetch or spawn failed: %s", e)
            success, elapsed = False, 0.0

        # If WHIP died because LiveKit handed us a v6 ICE candidate
        # we can't reach, flip to RTMP for the next attempt. After
        # two consecutive v6 failures on WHIP we permanently switch
        # protocol preference for the rest of this supervisor run.
        if not success and proto_used == "whip" and _is_v6_unreachable(stderr_tail):
            v6_failure_count += 1
            logger.warning(
                "WHIP failed via IPv6 ICE candidate (count=%d); switching "
                "next attempt to RTMP",
                v6_failure_count,
            )
            prefer_protocol = "rtmp"
        elif success and proto_used == "rtmp":
            # RTMP worked — stay on it.
            pass

        # Stop-marker right after a run? Honour it before backing off.
        if stop_marker.exists():
            try:
                stop_marker.unlink()
            except OSError:
                pass
            logger.info("stop marker present after run %d, exiting cleanly", iteration)
            sys.exit(EXIT_CLEAN)

        if success:
            # Clean exit and no stop marker — ffmpeg finished its
            # max_iterations. Done.
            logger.info("ffmpeg exited cleanly without stop marker; finishing")
            sys.exit(EXIT_CLEAN)

        if elapsed >= _HEALTHY_RUN_SECONDS:
            # Long-lived run — reset backoff so we reconnect quickly.
            consecutive_failures = 0
            backoff_idx = 0
        else:
            consecutive_failures += 1
            backoff_idx = min(consecutive_failures - 1, len(_BACKOFF_SCHEDULE) - 1)

        wait = _BACKOFF_SCHEDULE[backoff_idx]
        logger.info(
            "backoff %ss before retry %d (consecutive_failures=%d, last_run=%.1fs)",
            wait,
            iteration + 1,
            consecutive_failures,
            elapsed,
        )
        # Sleep but check stop_marker periodically so stop is responsive.
        slept = 0.0
        while slept < wait:
            if stop_marker.exists():
                try:
                    stop_marker.unlink()
                except OSError:
                    pass
                logger.info("stop marker hit during backoff, exiting cleanly")
                sys.exit(EXIT_CLEAN)
            time.sleep(0.5)
            slept += 0.5


if __name__ == "__main__":
    main()
