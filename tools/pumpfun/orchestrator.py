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

import contextlib
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


def _find_orphans_for_mint(mint: str) -> set[int]:
    """Scan `ps` for any ffmpeg/supervisor processes whose cmdline
    references this mint's per-mint state files.

    Why this exists: state.json holds at most ONE supervisor PID. When
    `start` runs twice without an intervening `stop` (agent crash,
    user error, double-click), the older supervisor's PID is
    overwritten and becomes an orphan happily pushing video to the
    same pump.fun WHIP endpoint forever. We hit this in production —
    found 3 zombies from prior days streaming the same mint at once.

    The match key is the mint prefix that appears in our state-dir
    filenames (`<state_dir>/<mint[:16]>.*`). Unique enough — no other
    tool writes there — and matches both the supervisor's --config
    arg and the ffmpeg child's voice-FIFO arg.

    Best-effort: if `ps` isn't available (sandboxed env), returns
    empty set rather than crashing the stop path.
    """
    if not mint:
        return set()
    needle = mint[:16]
    out: set[int] = set()
    try:
        proc = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return out
    if proc.returncode != 0:
        return out
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or needle not in line:
            continue
        # Defence in depth: only kill processes that look like ours.
        # Avoid matching a random user-script that happened to grep
        # for the mint.
        if (
            "_ffmpeg_supervisor" not in line
            and "ffmpeg" not in line.split(None, 1)[1].split()[0]
        ):
            continue
        try:
            pid = int(line.split(None, 1)[0])
        except (ValueError, IndexError):
            continue
        if _is_alive(pid):
            out.add(pid)
    return out


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


def _find_idle_logo_source() -> Path | None:
    """Locate the operator's logo for the voice-mode idle frame.

    Search order, first hit wins:
    1. ``ELOPHANTO_LIVESTREAM_LOGO`` env var (operator override)
    2. ``misc/logo/livestream_idle.png`` in the repo (bundled asset)
    3. ``misc/logo/elophanto.jpeg`` (the README banner — fallback)

    Returns None when nothing's there → orchestrator generates the
    plain text card instead.
    """
    env = os.environ.get("ELOPHANTO_LIVESTREAM_LOGO")
    if env:
        p = Path(env)
        if p.is_file():
            return p
    repo_root = Path(__file__).resolve().parents[2]
    for candidate in (
        repo_root / "misc" / "logo" / "livestream_idle.png",
        repo_root / "misc" / "logo" / "elophanto.jpeg",
    ):
        if candidate.is_file():
            return candidate
    return None


_IDLE_FRAME_W = 1280
_IDLE_FRAME_H = 720
_IDLE_BG_HEX = "white"
_IDLE_TEXT_HEX = "#1f2937"  # slate-800 — readable on white


# Extensions to auto-discover for an operator-supplied idle frame.
# PNG first because that's what we generate; the rest because
# everyone who exports a logo gets one of these and shouldn't have
# to rename. Order matters — first match wins.
_IDLE_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp")


def _resolve_idle_frame(*, workspace_dir: Path | None, mint: str) -> Path:
    """Pick the static frame for voice-mode video.

    Search order:
    1. ``<workspace>/livestream_videos/idle.{png,jpg,jpeg,webp}`` —
       any operator-provided file with a sane extension wins
    2. ``<workspace>/livestream_videos/idle.png`` — the canonical
       location for the auto-generated placeholder when nothing
       operator-provided exists
    3. ``<state_dir>/<mint[:16]>.idle.png`` — fallback when no
       workspace is configured

    Returns the path that ffmpeg should be pointed at. Caller
    generates a placeholder there if the file doesn't exist yet.
    """
    if workspace_dir is None:
        return _state_dir() / f"{mint[:16]}.idle.png"

    target_dir = workspace_dir / "livestream_videos"
    target_dir.mkdir(parents=True, exist_ok=True)

    # First-match-wins across extensions. ffmpeg doesn't care what the
    # extension says; it sniffs the actual bytes. So `idle.jpg`,
    # `idle.png`, `idle.webp` all work as the static frame regardless
    # of which one the operator dropped.
    for ext in _IDLE_EXTENSIONS:
        candidate = target_dir / f"idle{ext}"
        if candidate.is_file():
            return candidate

    # No operator file — return the canonical .png path so the caller
    # generates a placeholder there (and finds it next time without
    # regenerating).
    return target_dir / "idle.png"


def _generate_idle_png(path: Path, mint: str) -> None:
    """Write a 1280×720 'agent idle' placeholder PNG at ``path``.

    Used as the video track when voice mode is on and the caller
    didn't supply an image. ffmpeg loops this still frame at low fps
    so almost no bandwidth goes to video and everything goes to the
    voice audio. 16:9 because that's what every streaming platform
    expects for full-screen display.

    NEVER OVERWRITES AN EXISTING FILE. If `path` already exists,
    returns immediately as a no-op. The operator's image is sacred —
    even if the resolver upstream gets the path wrong, this final
    check guarantees we never silently destroy their file. Real bug
    that motivated this guard: an upstream resolver miss caused this
    function to be called with the operator's idle.png path, blowing
    away their image with the auto-generated placeholder.

    Composition (when generating fresh):
      - White 1280×720 canvas
      - If a logo source is found (see _find_idle_logo_source), it's
        scaled to fit ~60% of the height and centered above the label
      - Mint label rendered in slate text below the logo

    All done via ffmpeg's filter graph so we don't need Pillow.
    """
    if path.exists():
        # Hard refusal. Caller is responsible for deciding whether
        # they actually want regen — if so, they delete the file
        # first, explicitly. Defence in depth complement to the
        # resolver-side `is_file()` check.
        logger.info(
            "[livestream] _generate_idle_png: refusing to overwrite "
            "existing file at %s (operator image preserved)",
            path,
        )
        return
    label = f"EloPhanto · {mint[:6]}…{mint[-4:]}"
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    logo = _find_idle_logo_source()
    # Atomic write target. ffmpeg writes to <stem>.tmp.<pid>.png,
    # we rename on success. The supervisor's ffmpeg can race with us
    # (it starts reading idle.png almost immediately after we return
    # from this function), and reading a half-written PNG produces
    # "Invalid PNG signature 0x..." in the supervisor log → ffmpeg
    # dies → nothing streams. os.replace below makes the publish
    # atomic so readers see either the OLD file or the FULL new
    # file, never a partial one.
    #
    # The .png suffix is preserved on the tmp file so ffmpeg's
    # format-from-extension inference works — without it, ffmpeg
    # bails with "Unable to choose an output format".
    tmp_path = path.with_name(f"{path.stem}.tmp.{os.getpid()}{path.suffix}")

    if logo is not None:
        # Composite: scale the logo down (preserving aspect) to fit
        # ~60% of the canvas height, place it centered with the label
        # below it. drawtext fontsize 36 + canvas y offset gives the
        # label breathing room without overlapping the logo.
        cmd = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            # Background: white 1280x720 still
            "-f",
            "lavfi",
            "-i",
            f"color=c={_IDLE_BG_HEX}:s={_IDLE_FRAME_W}x{_IDLE_FRAME_H}:d=1",
            # Logo input
            "-i",
            str(logo),
            "-filter_complex",
            (
                # Scale logo: fit within 60% width × 60% height, preserve aspect.
                f"[1:v]scale=w={int(_IDLE_FRAME_W * 0.6)}:"
                f"h={int(_IDLE_FRAME_H * 0.6)}:force_original_aspect_ratio=decrease[logo];"
                # Overlay logo centered, biased slightly upward to leave room for label.
                f"[0:v][logo]overlay=x=(W-w)/2:y=(H-h)/2-40[bg];"
                # Draw label centered, near the bottom.
                f"[bg]drawtext=text='{label}':"
                f"fontcolor={_IDLE_TEXT_HEX}:"
                f"fontsize=36:"
                f"x=(w-text_w)/2:"
                f"y=h-h/6"
            ),
            "-frames:v",
            "1",
            str(tmp_path),
        ]
    else:
        # No logo available — plain white card with centered label.
        cmd = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={_IDLE_BG_HEX}:s={_IDLE_FRAME_W}x{_IDLE_FRAME_H}:d=1",
            "-vf",
            (
                f"drawtext=text='{label}':"
                f"fontcolor={_IDLE_TEXT_HEX}:"
                f"fontsize=48:"
                f"x=(w-text_w)/2:y=(h-text_h)/2"
            ),
            "-frames:v",
            "1",
            str(tmp_path),
        ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except Exception:
        # Fallback: solid white frame, no text or logo. Hits when the
        # ffmpeg build lacks libfreetype (drawtext) or the logo path
        # exists but is malformed (corrupt PNG, etc.). Better a blank
        # frame than no stream.
        cmd = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={_IDLE_BG_HEX}:s={_IDLE_FRAME_W}x{_IDLE_FRAME_H}:d=1",
            "-frames:v",
            "1",
            str(tmp_path),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except Exception:
            # Even the fallback failed — clean up tmp + bail. Nothing
            # left to do; caller will see a missing target file and
            # ffmpeg upstream will surface the real error.
            with contextlib.suppress(OSError):
                tmp_path.unlink()
            raise

    # Atomic publish: rename tmp -> target. os.replace is atomic on
    # POSIX same-filesystem moves, so a reader (the supervisor's
    # ffmpeg) either sees the OLD file or the FULL new file — never
    # a half-written one. This is the fix for the "Invalid PNG
    # signature 0x802008C00000" race that bricked the stream.
    os.replace(tmp_path, path)


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
        # Orphan sweep BEFORE we spawn anything new. state.json holds
        # at most ONE supervisor PID, so an unclean restart (agent
        # crash, double-start, lost state) leaves the prior supervisor
        # alive and pushing to the same WHIP endpoint. If we spawn on
        # top of that, the second ffmpeg fights the first for the
        # token and pump.fun shows whichever wins the race. Always
        # reap before starting — defence in depth complement to the
        # same sweep on stop.
        prior_orphans = _find_orphans_for_mint(mint)
        for pid in prior_orphans:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                continue
        if prior_orphans:
            for _ in range(50):
                if not any(_is_alive(p) for p in prior_orphans):
                    break
                time.sleep(0.1)
            for pid in prior_orphans:
                if _is_alive(pid):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass
            logger.info(
                "[livestream] reaped %d orphan supervisor(s) for mint %s before start",
                len(prior_orphans),
                mint[:16],
            )

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
                # Auto-pick the user's idle frame from a known location.
                # Look for ANY of {idle.png, idle.jpg, idle.jpeg, idle.webp}
                # so the operator can drop whatever format they have
                # without having to rename. ffmpeg sniffs the format
                # from bytes regardless of extension. Real bug avoided
                # here: previously we hardcoded `idle.png`, so a user
                # who saved `idle.jpg` got the auto-generated green
                # placeholder instead of their image, with no warning.
                #
                # Falls back to the state dir + auto-generated PNG only
                # when no workspace is configured AND no idle file is
                # found in the workspace.
                image_resolved = _resolve_idle_frame(
                    workspace_dir=self._workspace_dir, mint=mint
                )
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
        state = self._read_state(mint) or {}

        # If looping, drop the stop marker first so the supervisor exits
        # at the next iteration boundary instead of getting SIGKILL'd
        # mid-publish (which leaves an orphaned `lk` child behind).
        stop_marker_path = state.get("stop_marker") or ""
        if state.get("loop") and stop_marker_path:
            try:
                Path(stop_marker_path).touch()
            except OSError:
                pass

        # ── Defensive sweep ──────────────────────────────────────────────
        # state.json only knows about the most recent (mint, pid) pair.
        # If the agent crashed mid-stream OR `start` was called twice
        # without a `stop` between, the older supervisor's PID was
        # overwritten and is now an orphan happily pushing video to
        # the same pump.fun WHIP endpoint. Many users hit this — we
        # found 3 zombies from prior days all pushing to the same
        # mint at once.
        #
        # The fix: in addition to the PIDs from state.json, scan
        # `ps` for ANY ffmpeg/supervisor process whose cmdline mentions
        # our per-mint state dir. The mint-prefix in
        # `<state_dir>/<mint[:16]>.*` is unique enough to be a safe
        # match key — no other tool writes there.
        pids_to_kill: set[int] = set()
        for key in ("pid", "voice_pid"):
            v = state.get(key)
            if isinstance(v, int) and v > 0 and _is_alive(v):
                pids_to_kill.add(v)
        pids_to_kill.update(_find_orphans_for_mint(mint))

        killed_pids: list[int] = []
        for pid in pids_to_kill:
            try:
                os.kill(pid, signal.SIGTERM)
                killed_pids.append(pid)
            except OSError:
                continue
        # Wait up to 5s for them all to exit, then SIGKILL the holdouts.
        for _ in range(50):
            if not any(_is_alive(p) for p in killed_pids):
                break
            time.sleep(0.1)
        for pid in killed_pids:
            if _is_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

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
        if not killed_pids and not state:
            return {"status": "not_running", "mint": mint}
        return {
            "status": "stopped",
            "mint": mint,
            "killed": bool(killed_pids),
            "killed_pids": killed_pids,
        }

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
