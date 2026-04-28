"""Pump.fun livestream orchestrator (library API).

Importable functions for the native ``pump_livestream`` tool to call
in-process. The same logic powers the standalone scripts in
``skills/pumpfun-livestream/scripts/`` for shell-based debugging.

Design:
- ``LivestreamOrchestrator`` is the unit of work. It takes an
  already-unlocked ``Vault`` instance — no password handling here.
- All HTTP calls go through ``httpx`` (synchronous; the underlying
  pump.fun + LiveKit calls finish in <2s, not worth async overhead).
- Streaming is started as a *detached subprocess* of ``lk room join``
  so the agent can return immediately and check ``status`` later.
- Process state for active streams lives in
  ``~/.elophanto/livestream-state/<mint>.json`` so a subsequent
  ``stop`` or ``status`` call (or a fresh agent restart) can find it.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

# Project root — needed when spawning the loop runner via ``python -m``,
# which resolves imports relative to cwd.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

logger = logging.getLogger(__name__)

PUMP_API_BASE = "https://frontend-api-v3.pump.fun"
# Pump.fun's livestream service is on a separate host. Its endpoints
# (POST /livestream/create, /livestream/join, /livestream/close, etc.)
# return LiveKit JWTs scoped to a specific room — that's what the agent
# uses to publish via the LiveKit CLI.
PUMP_LIVESTREAM_API_BASE = "https://livestream-api.pump.fun"

# Vault keys
JWT_VAULT_KEY = "pumpfun_jwt"
JWT_EXPIRES_AT_VAULT_KEY = "pumpfun_jwt_expires_at"
WALLET_VAULT_KEY = "solana_wallet_private_key"
COIN_MINT_VAULT_KEY = "pumpfun_coin_mint"

# Cache config
ASSUMED_JWT_TTL_SECONDS = 24 * 3600
REFRESH_LEEWAY_SECONDS = 3600

# Default LiveKit cluster pump.fun streams attach to.
# Override via LIVEKIT_URL env or explicit param to `start_stream`.
DEFAULT_LIVEKIT_URL = "wss://pump-prod-tg2x9b6r.livekit.cloud"

# State directory for tracking detached publisher processes
_STATE_DIR = Path.home() / ".elophanto" / "livestream-state"


class LivestreamError(RuntimeError):
    """Raised on any pump.fun / LiveKit / ffmpeg failure surfaced to caller."""


def _state_dir() -> Path:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    return _STATE_DIR


def _state_path(mint: str) -> Path:
    safe = "".join(c for c in mint if c.isalnum())[:64]
    return _state_dir() / f"{safe}.json"


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _require_binary(name: str, install_hint: str) -> str:
    path = shutil.which(name)
    if not path:
        raise LivestreamError(f"'{name}' not found on PATH. {install_hint}")
    return path


class LivestreamOrchestrator:
    """Drive the full pump.fun livestream pipeline using an unlocked vault.

    The orchestrator is stateless aside from JWT caching (in the vault)
    and per-mint subprocess state (in ``~/.elophanto/livestream-state/``).
    Safe to instantiate per call.
    """

    def __init__(self, vault: Any, workspace_dir: str | Path | None = None) -> None:
        if vault is None:
            raise LivestreamError(
                "LivestreamOrchestrator needs an unlocked Vault instance."
            )
        self._vault = vault
        # Workspace is used to resolve bare filenames passed as ``video`` —
        # e.g. "demo.mp4" gets looked up in <workspace>/livestream_videos/.
        # Absolute paths bypass this entirely. Tool injects this from
        # ``agent.workspace`` in config.yaml; CLI scripts can omit it
        # and just pass absolute paths.
        self._workspace_dir = (
            Path(workspace_dir).expanduser() if workspace_dir else None
        )

    def _resolve_video_path(self, video: str) -> Path:
        """Turn the user's ``video`` arg into a real, resolvable file path.

        Resolution order:
          1. Absolute path → use as-is
          2. Path containing a slash → resolve relative to CWD
          3. Bare filename (no slash) and workspace_dir set → look in
             ``<workspace>/livestream_videos/<name>``
          4. Bare filename and no workspace → resolve relative to CWD
        """
        p = Path(video).expanduser()
        if p.is_absolute():
            return p
        # Has a slash component — relative path the caller really meant
        if "/" in video:
            return p.resolve()
        # Bare filename: prefer workspace's livestream_videos/ if available
        if self._workspace_dir is not None:
            candidate = self._workspace_dir / "livestream_videos" / p.name
            if candidate.exists():
                return candidate
        return p.resolve()

    # ── Wallet ────────────────────────────────────────────────────────

    def _load_keypair(self) -> Any:
        import base58
        from solders.keypair import Keypair  # type: ignore[import-untyped]

        stored = self._vault.get(WALLET_VAULT_KEY)
        if not stored:
            raise LivestreamError(
                f"No Solana wallet in vault under '{WALLET_VAULT_KEY}'. "
                "Run the agent at least once so the wallet auto-creates, "
                "or import via vault_set."
            )
        secret_bytes = base58.b58decode(stored)
        return Keypair.from_bytes(secret_bytes)

    def wallet_address(self) -> str:
        return str(self._load_keypair().pubkey())

    # ── Auth ──────────────────────────────────────────────────────────

    def _build_login_message(self, address: str) -> tuple[str, int]:
        """Build the current Pump.fun login message.

        Pump.fun's web frontend currently signs exactly:
            "Sign in to pump.fun: <timestamp>"
        and POSTs {address, signature, timestamp} to /auth/login.
        The address argument is kept for API symmetry/debug logging.
        """
        _ = address
        ts = int(time.time() * 1000)
        return f"Sign in to pump.fun: {ts}", ts

    def _sign_message(self, message: str, keypair: Any) -> str:
        import base58

        sig = keypair.sign_message(message.encode("utf-8"))
        return base58.b58encode(bytes(sig)).decode("ascii")

    def login(self) -> str:
        """Sign a fresh login message and exchange it for a Pump.fun JWT.

        Caches the JWT in the vault and returns it.
        """
        import httpx

        keypair = self._load_keypair()
        address = str(keypair.pubkey())
        message, timestamp = self._build_login_message(address)
        signature = self._sign_message(message, keypair)

        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                f"{PUMP_API_BASE}/auth/login",
                json={
                    "wallet": address,
                    "signature": signature,
                    "message": message,
                    # Some deployments accept legacy field names — include them
                    # so older API versions still validate the body.
                    "address": address,
                    "timestamp": timestamp,
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
                    "Origin": "https://pump.fun",
                    "Referer": "https://pump.fun/",
                },
            )

        if r.status_code >= 400:
            raise LivestreamError(
                f"Pump.fun /auth/login failed ({r.status_code}): "
                f"{r.text[:400]}. If the message format is rejected, "
                "inspect pump.fun's frontend during a real login and "
                "adjust _build_login_message()."
            )

        try:
            payload = r.json()
        except Exception as e:
            raise LivestreamError(
                f"Pump.fun /auth/login returned non-JSON: {r.text[:200]}"
            ) from e

        token = (
            payload.get("token")
            or payload.get("access_token")
            or payload.get("jwt")
            or ""
        )
        cookie_name = ""
        # Pump.fun's /auth/login returns the decoded JWT claims in the body
        # and the actual signed token in a Set-Cookie header. Capture the
        # cookie name too so we replay it exactly on subsequent calls.
        if not token:
            cookie_map = dict(r.cookies)
            for name in (
                "auth_token",
                "pump_session",
                "session",
                "jwt",
                "token",
                "access_token",
                "authToken",
            ):
                v = cookie_map.get(name)
                if isinstance(v, str) and v.count(".") >= 2:
                    token, cookie_name = v, name
                    break
            if not token:
                for name, v in cookie_map.items():
                    if isinstance(v, str) and v.count(".") >= 2:
                        token, cookie_name = v, name
                        break
        if not token:
            raise LivestreamError(
                "Login succeeded but no token in body or JWT-like cookies. "
                f"Body keys: {list(payload.keys())}, "
                f"Cookies: {list(r.cookies.keys())}"
            )

        logger.info(
            "[livestream] login ok; token from %s, cookie_name=%r",
            "body" if not cookie_name else "cookie",
            cookie_name or "(none)",
        )
        self._vault.set(JWT_VAULT_KEY, token)
        if cookie_name:
            self._vault.set("pumpfun_cookie_name", cookie_name)
        expires_at = payload.get("exp")
        if isinstance(expires_at, (int, float)) and expires_at > time.time():
            expires_at_str = str(int(expires_at))
        else:
            expires_at_str = str(int(time.time()) + ASSUMED_JWT_TTL_SECONDS)
        self._vault.set(JWT_EXPIRES_AT_VAULT_KEY, expires_at_str)
        return token

    def get_token(self, force_refresh: bool = False) -> str:
        if force_refresh:
            return self.login()

        cached = self._vault.get(JWT_VAULT_KEY)
        expires_at_str = self._vault.get(JWT_EXPIRES_AT_VAULT_KEY)
        if cached and expires_at_str:
            try:
                expires_at = int(expires_at_str)
                if expires_at - REFRESH_LEEWAY_SECONDS > time.time():
                    return cached
            except (TypeError, ValueError):
                pass
        return self.login()

    # ── Pump.fun API ──────────────────────────────────────────────────

    def _api_call(
        self,
        method: str,
        path: str,
        *,
        base: str = PUMP_API_BASE,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import httpx

        token = self.get_token()
        with httpx.Client(timeout=30.0) as client:
            r = client.request(
                method,
                f"{base}{path}",
                json=body if body is not None else None,
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Cookie": (
                        f"{self._vault.get('pumpfun_cookie_name') or 'auth_token'}={token}"
                    ),
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
                    "Origin": "https://pump.fun",
                    "Referer": "https://pump.fun/",
                },
            )
            try:
                payload = r.json() if r.content else {}
            except Exception:
                payload = {"raw": r.text}
            if r.status_code >= 400:
                raise LivestreamError(
                    f"{method} {path} failed ({r.status_code}): "
                    f"{json.dumps(payload)[:500]}"
                )
            return payload

    def create_livestream(
        self, mint: str, *, title: str = "", mode: str = "interactive"
    ) -> dict[str, Any]:
        """Create or refresh a pump.fun livestream record and get the host token.

        Returns the full response body, which contains:
            - ``token``: a LiveKit JWT scoped to the host role with publish
              rights for the room encoded in the token's ``video.room`` claim.
            - ``role``: ``"host"``.

        ``mode`` can be ``"interactive"`` (Pump Studio webcam — what we use
        for publishing a video file via LiveKit's WebRTC) or ``"view-only"``
        (RTMP — host pushes via OBS-style RTMP credentials).
        """
        creator = self.wallet_address()
        return self._api_call(
            "POST",
            "/livestream/create",
            base=PUMP_LIVESTREAM_API_BASE,
            body={
                "mintId": mint,
                "mode": mode,
                "title": title or "Live now",
                "creatorUsername": creator[:16],
            },
        )

    def get_host_token(self, mint: str) -> dict[str, Any]:
        """Back-compat shim — pump.fun no longer exposes a separate host
        token endpoint. The token comes back from /livestream/create."""
        return self.create_livestream(mint)

    # Pump.fun's create-credentials accepts a numeric protocol enum:
    #   0 = RTMP (rtmps://...rtmp.livekit.cloud/x + streamKey)
    #   1 = WHIP (https://...whip.livekit.cloud/w  + streamKey)
    # Returns {"url": "...", "streamKey": "..."}.
    INGRESS_RTMP = 0
    INGRESS_WHIP = 1

    def get_ingress_credentials(
        self, mint: str, protocol: int = INGRESS_RTMP
    ) -> dict[str, Any]:
        """Get LiveKit Cloud RTMP/WHIP ingress URL + stream key for the mint.

        ffmpeg can publish directly to these endpoints — no LiveKit CLI
        or pre-issued JWT needed. The stream key is bound to the active
        livestream record, so call ``create_livestream(mint)`` first.
        """
        return self._api_call(
            "POST",
            "/livestream/livekit/create-credentials",
            base=PUMP_LIVESTREAM_API_BASE,
            body={"mintId": mint, "input": int(protocol)},
        )

    @staticmethod
    def _decode_room_from_livekit_token(token: str) -> str:
        """Pull the LiveKit room name out of the token's ``video.room`` claim.

        LiveKit JWTs are unsigned-readable: just base64url-decode the middle
        segment. We don't verify the signature — the LiveKit server will do
        that when we connect.
        """
        import base64

        try:
            parts = token.split(".")
            if len(parts) < 2:
                return ""
            payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload_b64))
            video = claims.get("video") or {}
            return str(video.get("room") or "")
        except Exception:
            return ""

    # ── Video transcoding ─────────────────────────────────────────────

    def transcode_to_h264(self, input_path: str, output_path: str) -> None:
        """Convert any local video file into raw H.264 Annex-B format.

        ``lk room join --publish`` accepts ``.h264``, ``.ivf``, or
        ``.ogg`` — NOT mp4/mov/webm. Audio is dropped (separate track,
        out of scope for v1).
        """
        ffmpeg = _require_binary(
            "ffmpeg",
            "Install via 'brew install ffmpeg' or 'apt-get install ffmpeg'.",
        )
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            input_path,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-pix_fmt",
            "yuv420p",
            "-bsf:v",
            "h264_mp4toannexb",
            "-an",  # drop audio
            "-f",
            "h264",
            output_path,
        ]
        logger.info("[livestream] transcoding: %s", " ".join(cmd))
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise LivestreamError(
                f"ffmpeg failed (code {proc.returncode}):\n" f"{proc.stderr[-2000:]}"
            )

    # ── Stream lifecycle ──────────────────────────────────────────────

    def start_stream(
        self,
        mint: str,
        video: str,
        *,
        fps: float = 30.0,
        livekit_url: str = "",
        skip_create: bool = False,
        keep_h264: bool = False,
        loop: bool = False,
        max_iterations: int = 0,
    ) -> dict[str, Any]:
        """End-to-end: create → token → transcode → publish.

        Returns immediately after spawning the publisher subprocess.
        Caller should poll ``status_stream(mint)`` to track progress.

        Uses LiveKit Cloud's RTMP ingress (the same URL pump.fun gives
        OBS users): ffmpeg pushes ``rtmps://...rtmp.livekit.cloud/x/<key>``
        directly. With ``loop=True`` we use ffmpeg's native
        ``-stream_loop -1`` for seamless restarts; no Python supervisor
        needed. ``max_iterations`` becomes ``-stream_loop N-1`` (0 maps to
        infinite).
        """
        ffmpeg = _require_binary(
            "ffmpeg",
            "Install via 'brew install ffmpeg' or 'apt-get install ffmpeg'.",
        )

        existing = self._read_state(mint)
        if existing and _is_alive(existing.get("pid", -1)):
            return {
                "status": "already_running",
                "mint": mint,
                "pid": existing["pid"],
                "started_at": existing.get("started_at"),
            }

        video_path = self._resolve_video_path(video)
        if not video_path.is_file():
            raise LivestreamError(
                f"Video file not found: {video_path}. "
                f"Drop your video in {self._workspace_dir}/livestream_videos/ "
                "and pass just the filename, or use an absolute path."
                if self._workspace_dir
                else f"Video file not found: {video_path}"
            )

        # 1. Make sure the livestream record exists. Use view-only mode —
        #    that's the one paired with RTMP/WHIP ingest credentials.
        if not skip_create:
            self.create_livestream(mint, mode="view-only")

        # 2. Get ingest credentials. Pump.fun gates RTMP behind manual
        #    approval ("contact support"), but WHIP works for everyone —
        #    so try RTMP first and fall back to WHIP if pump.fun returns
        #    the support placeholder.
        creds = self.get_ingress_credentials(mint, self.INGRESS_RTMP)
        ingest_url = str(creds.get("url") or "")
        stream_key = str(creds.get("streamKey") or "")
        protocol = "rtmp"
        if not ingest_url or "error" in ingest_url.lower() or not stream_key:
            logger.info(
                "[livestream] RTMP unavailable (%r); falling back to WHIP",
                ingest_url,
            )
            creds = self.get_ingress_credentials(mint, self.INGRESS_WHIP)
            ingest_url = str(creds.get("url") or "")
            stream_key = str(creds.get("streamKey") or "")
            protocol = "whip"
        if not ingest_url or "error" in ingest_url.lower() or not stream_key:
            raise LivestreamError(
                f"create-credentials returned no usable creds: {creds}"
            )

        # 3. Build the ffmpeg command. The stream is loop-aware in ffmpeg
        #    itself (-stream_loop). One subprocess; no supervisor.
        log_file = _state_dir() / f"{mint[:16]}.log"
        stop_marker = _state_dir() / f"{mint[:16]}.stop"
        if stop_marker.exists():
            try:
                stop_marker.unlink()
            except OSError:
                pass

        cmd: list[str] = [ffmpeg, "-y", "-re"]
        if loop:
            # -stream_loop -1 = infinite; otherwise N means "play (N+1) times"
            n = -1 if max_iterations <= 0 else max(0, max_iterations - 1)
            cmd += ["-stream_loop", str(n)]
        video_opts = [
            "-i",
            str(video_path),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            "-g",
            str(int(fps * 2)),  # 2-second keyframe interval
        ]
        if protocol == "whip":
            # WHIP requires Opus audio; auth via Bearer header.
            cmd += [
                *video_opts,
                "-c:a",
                "libopus",
                "-b:a",
                "128k",
                "-ar",
                "48000",
                "-authorization",
                stream_key,
                "-f",
                "whip",
                ingest_url.rstrip("/"),
            ]
        else:
            cmd += [
                *video_opts,
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-ar",
                "44100",
                "-f",
                "flv",
                f"{ingest_url.rstrip('/')}/{stream_key}",
            ]

        redacted = " ".join("<key>" if c == stream_key else c for c in cmd)
        logger.info("[livestream] starting ffmpeg (%s): %s", protocol, redacted)
        log_fh = open(log_file, "ab")
        proc = subprocess.Popen(  # noqa: S603 — controlled command
            cmd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )

        state = {
            "mint": mint,
            "pid": proc.pid,
            "video": str(video_path),
            "ingest_url": ingest_url,
            "started_at": int(time.time()),
            "log_file": str(log_file),
            "loop": loop,
            "stop_marker": str(stop_marker) if loop else "",
            # Legacy fields kept so older state-file readers don't crash:
            "h264": "",
            "keep_h264": keep_h264,
            "livekit_url": livekit_url or DEFAULT_LIVEKIT_URL,
        }
        self._write_state(mint, state)
        return {"status": "started", **state}

    def stop_stream(self, mint: str) -> dict[str, Any]:
        state = self._read_state(mint)
        if not state:
            return {"status": "not_running", "mint": mint}

        # If looping, drop the stop marker first so the supervisor exits
        # at the next iteration boundary instead of getting SIGKILL'd
        # mid-publish (which leaves an orphaned `lk` child behind).
        stop_marker_path = state.get("stop_marker") or ""
        if state.get("loop") and stop_marker_path:
            try:
                Path(stop_marker_path).touch()
            except OSError:
                pass

        pid = state.get("pid")
        killed = False
        if isinstance(pid, int) and _is_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
                for _ in range(50):
                    if not _is_alive(pid):
                        break
                    time.sleep(0.1)
                if _is_alive(pid):
                    os.kill(pid, signal.SIGKILL)
                killed = True
            except OSError as e:
                return {
                    "status": "kill_failed",
                    "mint": mint,
                    "error": str(e),
                }

        # Clean up any leftover stop marker
        if stop_marker_path:
            try:
                Path(stop_marker_path).unlink(missing_ok=True)
            except OSError:
                pass

        if not state.get("keep_h264"):
            h264 = state.get("h264")
            if h264 and Path(h264).exists():
                try:
                    Path(h264).unlink()
                except OSError:
                    pass

        self._clear_state(mint)
        return {"status": "stopped", "mint": mint, "killed": killed, "pid": pid}

    def status_stream(self, mint: str) -> dict[str, Any]:
        state = self._read_state(mint)
        if not state:
            return {"status": "not_running", "mint": mint}
        pid = state.get("pid", -1)
        alive = _is_alive(pid) if isinstance(pid, int) else False
        if not alive:
            return {"status": "exited", "mint": mint, **state}
        return {"status": "running", "mint": mint, **state}

    # ── Internal: per-mint state files ─────────────────────────────────

    def _read_state(self, mint: str) -> dict[str, Any] | None:
        p = _state_path(mint)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except Exception:
            return None

    def _write_state(self, mint: str, state: dict[str, Any]) -> None:
        _state_path(mint).write_text(json.dumps(state, indent=2))

    def _clear_state(self, mint: str) -> None:
        p = _state_path(mint)
        if p.exists():
            p.unlink()
