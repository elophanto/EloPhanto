"""``pump_caption`` native tool — set on-stream text overlay.

Two render paths, picked at runtime:

  1. **drawtext path** (preferred): if the user's ffmpeg has the
     ``drawtext`` filter (libfreetype-enabled build), the orchestrator's
     voice-mode cmd already includes a drawtext overlay reading from
     ``<state>/<mint[:16]>.caption.txt`` with ``reload=1``. Updates show
     within one frame.

  2. **Pillow bake path** (fallback, used by default Homebrew ffmpeg):
     the standard ffmpeg build doesn't ship libfreetype, so drawtext is
     missing. We render the caption text directly into the static
     ``idle.png`` via Pillow, then bounce the running ffmpeg child
     (SIGTERM); the supervisor restarts it within a couple of seconds
     and the new ffmpeg loads the freshly-baked image. Trade-off is a
     ~2–3 s audio gap per caption change — fine for messages that
     rotate every minute or so, not so good for high-frequency updates.

Use case:
    Agent runs on a schedule / heartbeat that updates the caption
    every minute or so — current price, recent trade, "supply
    locked" badge, response to a chat question, etc. Pairs with
    ``pump_say`` for the audio side: the caption is what someone
    watching with sound off can read.

Actions:

    {"action": "set", "text": "$ELO live · supply locked · CA: BwUg…pump"}
        Replace the on-stream text. Multiline allowed (``\\n``).

    {"action": "clear"}
        Remove the overlay.

    {"action": "current"}
        Return what's currently on screen.
"""

from __future__ import annotations

import json
import logging
import os
import signal
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult
from tools.pumpfun.orchestrator import (
    COIN_MINT_VAULT_KEY,
    LivestreamError,
    _drawtext_available,
    _generate_idle_png,
)

logger = logging.getLogger(__name__)

_MAX_CAPTION_LEN = 500


def _state_dir() -> Path:
    p = Path.home() / ".elophanto" / "livestream-state"
    p.mkdir(parents=True, exist_ok=True)
    return p


def caption_path(mint: str) -> Path:
    return _state_dir() / f"{mint[:16]}.caption.txt"


def _bake_caption_into_image(image_path: Path, text: str, mint: str) -> None:
    """Render ``text`` onto ``image_path`` (in place) via Pillow.

    If ``image_path`` doesn't exist, regenerate the placeholder first
    via the orchestrator's helper. We always start from a fresh base
    so successive captions don't stack up.
    """
    from PIL import Image, ImageDraw, ImageFont

    # Always rebuild the base image so previous captions are wiped.
    _generate_idle_png(image_path, mint)

    if not text.strip():
        return  # base image is the "cleared" state

    img = Image.open(image_path).convert("RGBA")
    draw = ImageDraw.Draw(img)

    # Try a real TrueType font first (sized text); fall back to PIL's
    # default bitmap font if no TTF found.
    font: Any = None
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNS.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ):
        if Path(path).is_file():
            try:
                font = ImageFont.truetype(path, 36)
                break
            except OSError:
                continue
    if font is None:
        font = ImageFont.load_default()

    # Word-wrap manually so long captions don't overflow the canvas.
    max_w = img.width - 80
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        line = words[0]
        for word in words[1:]:
            candidate = f"{line} {word}"
            bbox = draw.textbbox((0, 0), candidate, font=font)
            if (bbox[2] - bbox[0]) > max_w:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)

    # Lay out at the bottom with a translucent black box behind for
    # readability against any background.
    line_height_bbox = draw.textbbox((0, 0), "Ay", font=font)
    line_h = (line_height_bbox[3] - line_height_bbox[1]) + 8
    block_h = line_h * len(lines) + 30
    block_y = img.height - block_h - 50
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.rectangle(
        (40, block_y, img.width - 40, block_y + block_h),
        fill=(0, 0, 0, 165),
    )
    img = Image.alpha_composite(img, overlay)

    draw = ImageDraw.Draw(img)
    y = block_y + 15
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        x = (img.width - line_w) // 2
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_h

    img.convert("RGB").save(image_path, "PNG")


def _bounce_ffmpeg_for_mint(mint: str) -> bool:
    """SIGTERM the running ffmpeg child for this mint so the supervisor
    restarts it with the freshly-baked image. Returns True if a process
    was signalled.
    """
    state_path = _state_dir() / (
        # state filename stamped with full mint, see orchestrator._state_path
        ("".join(c for c in mint if c.isalnum())[:64])
        + ".json"
    )
    if not state_path.is_file():
        return False
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    # Find the actual ffmpeg child of the supervisor — easier than
    # looking at the pid in state (which is the supervisor itself).
    # We just signal the supervisor's *child* via a process-tree walk.
    sup_pid = int(state.get("pid") or 0)
    if not sup_pid:
        return False
    return _kill_ffmpeg_children(sup_pid)


def _kill_ffmpeg_children(parent_pid: int) -> bool:
    """Send SIGTERM to ffmpeg processes whose parent is ``parent_pid``."""
    import subprocess as sp

    try:
        out = sp.check_output(["pgrep", "-P", str(parent_pid)], text=True)
    except sp.CalledProcessError:
        return False
    for line in out.splitlines():
        try:
            child_pid = int(line.strip())
        except ValueError:
            continue
        # Only signal ffmpeg, not the supervisor's own python (just in
        # case pgrep -P returns weird matches).
        try:
            with open(f"/proc/{child_pid}/comm", encoding="utf-8") as f:
                comm = f.read().strip()
        except OSError:
            # macOS doesn't expose /proc; trust pgrep + signal anyway.
            comm = ""
        if comm and "ffmpeg" not in comm:
            continue
        try:
            os.kill(child_pid, signal.SIGTERM)
        except OSError:
            continue
    return True


class PumpCaptionTool(BaseTool):
    """Set/clear on-stream text overlay on the agent's pump.fun stream."""

    def __init__(self) -> None:
        self._vault: Any = None
        self._workspace: str = ""

    @property
    def group(self) -> str:
        return "monetization"

    @property
    def name(self) -> str:
        return "pump_caption"

    @property
    def description(self) -> str:
        return (
            "Write / set / display visible text on the agent's "
            "pump.fun livestream (the on-screen caption overlay). "
            "Use this when the user says 'write X on the stream', "
            "'show X on pump.fun', 'display X', 'put X on the video', "
            "or 'caption: X' — distinct from pump_chat (chat panel) "
            "and pump_say (TTS audio). On ffmpeg builds with "
            "libfreetype the change appears within ~33 ms; on the "
            "default Homebrew build (no drawtext) the agent rebakes "
            "the image and bounces ffmpeg, ~2–3 s blip per change. "
            "Voice-mode streams only. Actions: set, clear, current."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["set", "clear", "current"],
                    "description": (
                        "'set' replaces the overlay text; 'clear' "
                        "removes it; 'current' returns what's "
                        "currently on screen."
                    ),
                },
                "text": {
                    "type": "string",
                    "description": (
                        "Caption text (required for 'set'). Multiline "
                        f"allowed via \\n. Capped at {_MAX_CAPTION_LEN} "
                        "chars; longer text gets truncated."
                    ),
                },
                "mint": {
                    "type": "string",
                    "description": (
                        "Pump.fun coin mint (optional — falls back "
                        "to vault key 'pumpfun_coin_mint')."
                    ),
                },
            },
            "required": ["action"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        # Public broadcast under the agent's coin name.
        return PermissionLevel.DESTRUCTIVE

    def _resolve_mint(self, params: dict[str, Any]) -> str:
        explicit = (params.get("mint") or "").strip()
        if explicit:
            return explicit
        if self._vault is None:
            raise LivestreamError("Vault not injected; cannot resolve mint.")
        stored = (self._vault.get(COIN_MINT_VAULT_KEY) or "").strip()
        if not stored:
            raise LivestreamError(
                f"No 'mint' param and no '{COIN_MINT_VAULT_KEY}' in vault."
            )
        return stored

    def _idle_png_path(self, mint: str) -> Path:
        """Wherever the orchestrator's start_stream put the auto idle.

        Mirrors the orchestrator's logic: prefer the workspace's
        livestream_videos/idle.png (so users find and edit it easily),
        fall back to the state dir.
        """
        if self._workspace:
            return Path(self._workspace).expanduser() / "livestream_videos" / "idle.png"
        return _state_dir() / f"{mint[:16]}.idle.png"

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._vault is None:
            return ToolResult(
                success=False,
                error="Vault not injected — pump_caption needs the running vault.",
            )

        action = params.get("action", "")
        try:
            mint = self._resolve_mint(params)
            path = caption_path(mint)
            use_drawtext = _drawtext_available()

            if action == "current":
                current = path.read_text(encoding="utf-8") if path.exists() else ""
                return ToolResult(
                    success=True,
                    data={
                        "mint": mint,
                        "text": current,
                        "render_path": "drawtext" if use_drawtext else "pillow_bake",
                    },
                )

            if action == "clear":
                path.write_text("", encoding="utf-8")
                bounced = False
                if not use_drawtext:
                    # Rebake with empty text → fresh placeholder image.
                    img = self._idle_png_path(mint)
                    _bake_caption_into_image(img, "", mint)
                    bounced = _bounce_ffmpeg_for_mint(mint)
                return ToolResult(
                    success=True,
                    data={"mint": mint, "cleared": True, "bounced_ffmpeg": bounced},
                )

            if action == "set":
                text = (params.get("text") or "").strip()
                if not text:
                    return ToolResult(
                        success=False, error="'text' is required for action='set'."
                    )
                if len(text) > _MAX_CAPTION_LEN:
                    text = text[:_MAX_CAPTION_LEN]
                path.write_text(text, encoding="utf-8")

                bounced = False
                render_path = "drawtext"
                if not use_drawtext:
                    render_path = "pillow_bake"
                    img = self._idle_png_path(mint)
                    _bake_caption_into_image(img, text, mint)
                    bounced = _bounce_ffmpeg_for_mint(mint)

                return ToolResult(
                    success=True,
                    data={
                        "mint": mint,
                        "text": text,
                        "render_path": render_path,
                        "bounced_ffmpeg": bounced,
                        "caption_file": str(path),
                    },
                )

            return ToolResult(success=False, error=f"Unknown action: {action!r}")

        except LivestreamError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            logger.exception("pump_caption failed unexpectedly")
            return ToolResult(success=False, error=f"Unexpected: {e}")
