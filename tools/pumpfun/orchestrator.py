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
import sys
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

# ── Encoder reliability knobs ────────────────────────────────────────────
# These exist because pump.fun's WHIP/RTMP ingress on LiveKit Cloud is
# fragile: default ffmpeg settings produce too much bitrate (back-pressure
# → "No buffer space available") and the default 5s DTLS handshake timeout
# fires too aggressively on slow networks.
DEFAULT_VIDEO_BITRATE = "1500k"
DEFAULT_VIDEO_MAXRATE = "2000k"
DEFAULT_VIDEO_BUFSIZE = "4000k"
DEFAULT_TARGET_HEIGHT = 720  # downscale anything bigger; 720p has been
# the only resolution that streams reliably end-to-end here
DTLS_HANDSHAKE_TIMEOUT_MS = 20000  # WHIP only — default 5000 is too short

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


# System fonts for ffmpeg drawtext. macOS first, then Linux.
# Iterated lazily so a missing path on one OS doesn't break the build
# on another. drawtext fails the whole filter if the font is missing.
_FONT_CANDIDATES = (
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/SFNS.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial.ttf",
)


def _find_font() -> str:
    for f in _FONT_CANDIDATES:
        if Path(f).is_file():
            return f
    return ""  # drawtext will be skipped


_DRAWTEXT_AVAILABLE: bool | None = None


def _drawtext_available() -> bool:
    """Probe the ffmpeg binary to check if drawtext is compiled in.

    Homebrew's default ffmpeg 8.x build on macOS doesn't ship with
    libfreetype/libfontconfig, so the drawtext filter is missing.
    Without this check we'd build cmds that crash with "No such
    filter: 'drawtext'" on every retry. Cached after first probe.
    """
    global _DRAWTEXT_AVAILABLE
    if _DRAWTEXT_AVAILABLE is not None:
        return _DRAWTEXT_AVAILABLE
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        _DRAWTEXT_AVAILABLE = False
        return False
    try:
        out = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        _DRAWTEXT_AVAILABLE = "drawtext" in out.stdout
    except Exception:
        _DRAWTEXT_AVAILABLE = False
    if not _DRAWTEXT_AVAILABLE:
        logger.warning(
            "[livestream] ffmpeg has no 'drawtext' filter — caption "
            "overlay disabled. Install a full ffmpeg build "
            "(e.g. `brew tap homebrew-ffmpeg/ffmpeg && brew install "
            "homebrew-ffmpeg/ffmpeg/ffmpeg --with-fontconfig`) to "
            "enable on-stream text."
        )
    return _DRAWTEXT_AVAILABLE


def _build_video_filter(caption_file: str) -> str:
    """Compose the -vf chain for voice-mode ffmpeg.

    Always scales to 720p max. When ``caption_file`` is given AND a
    system font is available AND ffmpeg has drawtext compiled in,
    appends an overlay that reads the file every frame (``reload=1``).
    If any prerequisite is missing we silently skip the overlay so
    the stream keeps publishing.
    """
    chain = [f"scale=-2:'min(ih,{DEFAULT_TARGET_HEIGHT})'"]
    if caption_file and _drawtext_available():
        font = _find_font()
        if font:
            # Single quotes need escaping for ffmpeg filter syntax.
            font_esc = font.replace("'", r"\'")
            cap_esc = caption_file.replace("'", r"\'")
            chain.append(
                f"drawtext=fontfile='{font_esc}':textfile='{cap_esc}':"
                "reload=1:fontsize=36:fontcolor=white:"
                "box=1:boxcolor=black@0.55:boxborderw=18:"
                "x=(w-text_w)/2:y=h-text_h-50"
            )
    return ",".join(chain)


def _generate_idle_png(path: Path, mint: str) -> None:
    """Write a tiny 'agent idle' placeholder PNG at ``path``.

    Used as the video track when voice mode is on and the caller
    didn't supply an image. ffmpeg loops this still frame at low fps
    so almost no bandwidth goes to video and everything goes to the
    voice audio. We generate it via ffmpeg's lavfi color source so
    we don't need Pillow as a dep.
    """
    color_hex = "#16a34a"  # match the agent UI accent
    label = f"EloPhanto · {mint[:6]}…{mint[-4:]}"
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color_hex}:s=720x720:d=1",
        "-vf",
        f"drawtext=text='{label}':fontcolor=white:fontsize=28:x=(w-text_w)/2:y=(h-text_h)/2",
        "-frames:v",
        "1",
        str(path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except Exception:
        # Fallback: solid colour without text. Rare — only if the
        # libfreetype dep on the ffmpeg build is missing.
        cmd = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color_hex}:s=720x720:d=1",
            "-frames:v",
            "1",
            str(path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)


def build_ffmpeg_cmd(
    ffmpeg_path: str,
    video_path: str,
    *,
    fps: float,
    loop: bool,
    max_iterations: int,
    protocol: str,  # "whip" | "rtmp"
    ingest_url: str,
    stream_key: str,
    voice_pcm_fifo: str = "",
    image_path: str = "",
    caption_file: str = "",
) -> list[str]:
    """Build the ffmpeg command for publishing to pump.fun's ingress.

    Two modes:

      - **video** (default): ``video_path`` is an mp4/mov; its audio
        track is what viewers hear.
      - **voice** (``voice_pcm_fifo`` set): ``image_path`` is a static
        PNG/JPG looped as the video; ``voice_pcm_fifo`` is a named
        FIFO from which the voice engine writes 48 kHz mono s16le PCM
        in real time. ffmpeg encodes that to Opus (WHIP) or AAC
        (RTMP) on the way out. ``video_path`` is ignored in this mode.

    Module-level so the supervisor can rebuild the command after each
    credential refresh without dragging the orchestrator into its
    process. All reliability knobs (bitrate cap, handshake timeout,
    720p downscale) live here in one place.
    """
    # Quiet logging — ffmpeg's per-frame progress meter (-stats) and
    # default INFO logs add up to MB of noise per hour. Anything tools
    # need to read (status checks, error tail) survives at "warning";
    # the supervisor still gets exit code on failure. Without this the
    # log file grew to 5+ MB / hour and a single tool capture could
    # bloat conversation context past every provider's limit.
    cmd: list[str] = [ffmpeg_path, "-loglevel", "warning", "-nostats", "-y"]

    voice_mode = bool(voice_pcm_fifo)

    if voice_mode:
        # Static image looped at low fps (still image — 5 fps is
        # plenty; libx264 + -tune stillimage compresses repeats to
        # near-zero bitrate). PCM audio fed from the named FIFO.
        # Big thread_queue_size on both inputs because the FIFO can
        # be momentarily empty (TTS render gap) and the image input
        # is real-time-ish — small queues hit "Not yet implemented"
        # paths inside the WHIP muxer's audio filter chain.
        # Match the proven video-mode encoder settings exactly. Earlier
        # attempts used `-tune stillimage -r 5 -g 10` to save bitrate,
        # but the WHIP muxer rejects those codec parameters with
        # "Could not write header (incorrect codec parameters ?)" —
        # whatever WHIP wants for 30 fps + zerolatency + main profile
        # works, anything cleverer doesn't. libx264 still compresses
        # static-image P-frames to near-zero, so 30 fps is fine.
        cmd += [
            # -re on each input: read at native rate. Without this,
            # `-loop 1` floods the encoder with image frames faster
            # than the audio can keep up; the WHIP muxer rejects the
            # resulting unsynced streams with "Could not write header
            # (incorrect codec parameters ?)".
            "-re",
            "-thread_queue_size",
            "4096",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            image_path or "",
            "-re",
            "-thread_queue_size",
            "4096",
            "-f",
            "s16le",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-i",
            voice_pcm_fifo,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            _build_video_filter(caption_file),
            # async=1 keeps the timeline monotonic when the FIFO has
            # gaps between TTS utterances. ``aformat`` forces stereo
            # output — pump.fun's WHIP muxer rejects mono with
            # "Unsupported audio channels 1 by RTC, choose stereo".
            "-af",
            "aresample=async=1:first_pts=0,aformat=channel_layouts=stereo",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-g",
            "60",
            "-b:v",
            "500k",
            "-maxrate",
            "800k",
            "-bufsize",
            "1600k",
            "-profile:v",
            "main",
        ]
    else:
        cmd += ["-re"]
        if loop:
            # -stream_loop -1 = infinite; otherwise N means "play (N+1) times"
            n = -1 if max_iterations <= 0 else max(0, max_iterations - 1)
            cmd += ["-stream_loop", str(n)]
        cmd += [
            "-i",
            video_path,
            # Downscale to 720p max so we never exceed what WHIP/RTMP
            # can absorb. 1080p sources cause "No buffer space
            # available" within seconds. -2 = preserve aspect.
            "-vf",
            f"scale=-2:'min(ih,{DEFAULT_TARGET_HEIGHT})'",
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
            # Hard bitrate cap — without these libx264 happily
            # produces 5–10 Mbps for 720p which back-pressures the
            # WHIP/RTMP socket.
            "-b:v",
            DEFAULT_VIDEO_BITRATE,
            "-maxrate",
            DEFAULT_VIDEO_MAXRATE,
            "-bufsize",
            DEFAULT_VIDEO_BUFSIZE,
            "-profile:v",
            "main",
        ]
    if protocol == "whip":
        cmd += [
            # WHIP requires Opus audio; auth via Bearer header.
            "-c:a",
            "libopus",
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-authorization",
            stream_key,
            # Bump DTLS handshake timeout — default 5s fires too aggressively
            # on slow paths and the muxer aborts before any frames flow.
            "-handshake_timeout",
            str(DTLS_HANDSHAKE_TIMEOUT_MS),
            "-f",
            "whip",
            ingest_url.rstrip("/"),
        ]
    elif protocol == "rtmp":
        cmd += [
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
    else:
        raise LivestreamError(f"Unknown protocol: {protocol!r}")
    return cmd


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
        voice: bool = False,
        image_path: str = "",
        voice_model: str = "tts-1",
        voice_id: str = "onyx",
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

        # Resolve video XOR image (voice mode) input.
        if voice:
            # Voice mode: needs a static image, not a video file. Falls
            # back to a generated 720x720 colour fill if no image given.
            if image_path:
                image_resolved = self._resolve_video_path(image_path)
                if not image_resolved.is_file():
                    raise LivestreamError(f"Image not found: {image_resolved}")
            else:
                # Place the auto-generated placeholder where the user's
                # videos live (next to whatever they'd swap it for) so
                # it's discoverable and easy to replace. Falls back to
                # the state dir only when no workspace is configured.
                if self._workspace_dir is not None:
                    target_dir = self._workspace_dir / "livestream_videos"
                    target_dir.mkdir(parents=True, exist_ok=True)
                    image_resolved = target_dir / "idle.png"
                else:
                    image_resolved = _state_dir() / f"{mint[:16]}.idle.png"
                if not image_resolved.exists():
                    _generate_idle_png(image_resolved, mint)
            video_path = image_resolved  # placeholder; not actually used as video
        else:
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

        # 2. Get ingest credentials. **WHIP is preferred** — empirically
        #    it streams reliably for hours. LiveKit Cloud's RTMP gateway
        #    on this pump.fun cluster keeps dropping connections with
        #    `Broken pipe` within seconds of connect (tested on multiple
        #    keys, multiple sessions). RTMP is only used as a fallback
        #    when WHIP returns the "contact support" placeholder.
        creds = self.get_ingress_credentials(mint, self.INGRESS_WHIP)
        ingest_url = str(creds.get("url") or "")
        stream_key = str(creds.get("streamKey") or "")
        protocol = "whip"
        if not ingest_url or "error" in ingest_url.lower() or not stream_key:
            logger.info(
                "[livestream] WHIP unavailable (%r); falling back to RTMP",
                ingest_url,
            )
            creds = self.get_ingress_credentials(mint, self.INGRESS_RTMP)
            ingest_url = str(creds.get("url") or "")
            stream_key = str(creds.get("streamKey") or "")
            protocol = "rtmp"
        if not ingest_url or "error" in ingest_url.lower() or not stream_key:
            raise LivestreamError(
                f"create-credentials returned no usable creds: {creds}"
            )

        # 3. Spawn the ffmpeg supervisor. It owns the whole publish
        #    lifecycle: re-fetches credentials on each retry (so a
        #    rotated stream key doesn't kill the stream), restarts
        #    ffmpeg with exponential backoff, exits cleanly on
        #    stop-marker. We discard the initial creds we just fetched
        #    in step 2 — they only confirmed the path works; the
        #    supervisor will mint fresh ones on its first iteration.
        _ = ingest_url, stream_key, protocol  # consumed by supervisor below

        log_file = _state_dir() / f"{mint[:16]}.log"
        stop_marker = _state_dir() / f"{mint[:16]}.stop"
        config_file = _state_dir() / f"{mint[:16]}.config.json"
        if stop_marker.exists():
            try:
                stop_marker.unlink()
            except OSError:
                pass

        # Voice mode: prepare the FIFO + queue file BEFORE spawning
        # ffmpeg, then spawn the voice engine which will block on the
        # FIFO write side until ffmpeg starts reading.
        voice_fifo = ""
        voice_queue = ""
        voice_cursor = ""
        caption_file_path = ""
        voice_pid = 0
        if voice:
            openai_key = (self._vault.get("openai_api_key") or "").strip()
            if not openai_key:
                # Try config-shaped vault key as a fallback.
                openai_key = (self._vault.get("openai_key") or "").strip()
            if not openai_key:
                raise LivestreamError(
                    "voice mode needs an OpenAI API key — vault_set "
                    "openai_api_key <sk-...>"
                )
            voice_fifo = str(_state_dir() / f"{mint[:16]}.voice.pcm")
            voice_queue = str(_state_dir() / f"{mint[:16]}.voice_queue.jsonl")
            voice_cursor = str(_state_dir() / f"{mint[:16]}.voice_cursor")
            caption_file_path = str(_state_dir() / f"{mint[:16]}.caption.txt")
            # Replace any stale FIFO / queue.
            for p in (voice_fifo, voice_cursor):
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError:
                    pass
            os.mkfifo(voice_fifo)
            # Make sure queue + caption files exist so the engine and
            # ffmpeg drawtext (reload=1) can stat / read them. Empty
            # caption renders nothing — drawtext silently skips empty
            # textfiles.
            Path(voice_queue).touch()
            Path(caption_file_path).touch()

        # Persist everything the supervisor needs. The pump.fun JWT
        # goes in too so the supervisor doesn't need vault access — it
        # just calls /create-credentials directly. JWT lives ~24h; on
        # 401 the supervisor exits and the agent can react.
        supervisor_config = {
            "mint": mint,
            "video_path": str(video_path),
            "fps": fps,
            "loop": loop,
            "max_iterations": max_iterations,
            "ffmpeg_path": ffmpeg,
            "jwt": self.get_token(),
            "prefer_protocol": protocol,  # "whip" if available, else "rtmp"
            "voice_pcm_fifo": voice_fifo,
            "image_path": str(video_path) if voice else "",
            "caption_file": caption_file_path,
        }
        config_file.write_text(json.dumps(supervisor_config), encoding="utf-8")

        # Spawn the supervisor as a detached subprocess. It lives in
        # its own session so SIGTERM-ing the agent doesn't reap it,
        # and survives agent restarts.
        log_fh = open(log_file, "ab")
        supervisor_cmd = [
            sys.executable,
            "-m",
            "tools.pumpfun._ffmpeg_supervisor",
            "--config",
            str(config_file),
            "--stop-marker",
            str(stop_marker),
        ]
        logger.info("[livestream] spawning supervisor: %s", " ".join(supervisor_cmd))
        proc = subprocess.Popen(  # noqa: S603 — controlled command
            supervisor_cmd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            cwd=str(_PROJECT_ROOT),  # supervisor imports tools.pumpfun
        )

        # Voice engine spawn — independent of the supervisor so a
        # ffmpeg restart doesn't reset the queue.
        if voice:
            voice_log = _state_dir() / f"{mint[:16]}.voice.log"
            voice_log_fh = open(voice_log, "ab")
            voice_cmd = [
                sys.executable,
                "-m",
                "tools.pumpfun._voice_engine",
                "--queue-file",
                voice_queue,
                "--cursor-file",
                voice_cursor,
                "--pcm-fifo",
                voice_fifo,
                "--stop-marker",
                str(stop_marker),
                "--openai-api-key",
                openai_key,
                "--model",
                voice_model,
                "--voice",
                voice_id,
            ]
            voice_proc = subprocess.Popen(  # noqa: S603 — controlled command
                voice_cmd,
                stdout=voice_log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
                cwd=str(_PROJECT_ROOT),
            )
            voice_pid = voice_proc.pid
            logger.info(
                "[livestream] voice engine spawned pid=%s queue=%s",
                voice_pid,
                voice_queue,
            )

        state = {
            "mint": mint,
            "pid": proc.pid,
            "voice_pid": voice_pid,
            "voice": voice,
            "video": str(video_path),
            "ingest_url": ingest_url,
            "started_at": int(time.time()),
            "log_file": str(log_file),
            "config_file": str(config_file),
            "loop": loop,
            "stop_marker": str(stop_marker),
            "supervisor": True,
            "voice_fifo": voice_fifo,
            "voice_queue": voice_queue,
            "caption_file": caption_file_path,
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

        pids_to_kill: list[int] = []
        for key in ("pid", "voice_pid"):
            v = state.get(key)
            if isinstance(v, int) and v > 0 and _is_alive(v):
                pids_to_kill.append(v)

        killed = False
        for pid in pids_to_kill:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                continue
        # Wait up to 5s for them all to exit, then SIGKILL the holdouts.
        for _ in range(50):
            if not any(_is_alive(p) for p in pids_to_kill):
                break
            time.sleep(0.1)
        for pid in pids_to_kill:
            if _is_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
        killed = bool(pids_to_kill)

        # Clean up any leftover stop marker + voice FIFO
        if stop_marker_path:
            try:
                Path(stop_marker_path).unlink(missing_ok=True)
            except OSError:
                pass
        voice_fifo = state.get("voice_fifo") or ""
        if voice_fifo:
            try:
                Path(voice_fifo).unlink(missing_ok=True)
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
