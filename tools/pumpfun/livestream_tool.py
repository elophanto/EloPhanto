"""``pump_livestream`` native tool — start/stop/status/check pump.fun streams.

Single-action tool the agent can call directly from chat. Uses the
agent's already-unlocked vault (no VAULT_PASSWORD env var roundtrip)
and dispatches to ``LivestreamOrchestrator``.

Examples (LLM-facing JSON):

    {"action": "start", "video": "/abs/path/to/video.mp4"}
        → uses vault's pumpfun_coin_mint, returns {status: "started", pid, ...}

    {"action": "start", "mint": "BwUg...pump", "video": "...mp4", "fps": 24}

    {"action": "status"}                  # uses vault mint
    {"action": "stop"}                    # uses vault mint
    {"action": "address"}                 # which wallet would sign
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult
from tools.pumpfun.orchestrator import (
    COIN_MINT_VAULT_KEY,
    LivestreamError,
    LivestreamOrchestrator,
)

logger = logging.getLogger(__name__)


class PumpLivestreamTool(BaseTool):
    """Stream local video to pump.fun's livestream player for an existing coin."""

    def __init__(self) -> None:
        self._vault: Any = None
        # Injected by Agent (`agent._inject_monetization_deps`) — used to
        # resolve bare filenames against ``<workspace>/livestream_videos/``.
        self._workspace: str = ""

    @property
    def group(self) -> str:
        return "monetization"

    @property
    def name(self) -> str:
        return "pump_livestream"

    @property
    def description(self) -> str:
        return (
            "Stream a local video file to pump.fun's livestream player. "
            "Auto-handles auth (signs with the agent's Solana wallet), "
            "creates the stream record, fetches a LiveKit token, transcodes "
            "the video, and publishes via the LiveKit CLI in a detached "
            "subprocess. Actions: start, stop, status, address. Uses the "
            "coin mint stored in vault as 'pumpfun_coin_mint' unless 'mint' "
            "is passed explicitly. Requires ffmpeg and lk (livekit-cli) on "
            "PATH."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "status", "address", "login"],
                    "description": (
                        "What to do. 'start' begins a new stream, 'stop' "
                        "kills the running publisher, 'status' reports "
                        "running/exited/not_running, 'address' returns the "
                        "wallet that would sign auth, 'login' forces a "
                        "fresh JWT exchange (debugging)."
                    ),
                },
                "video": {
                    "type": "string",
                    "description": (
                        "Local video file (mp4, mov, webm, etc.). Required "
                        "for 'start'. Either an absolute path, OR a bare "
                        "filename — bare filenames are looked up under "
                        "<agent.workspace>/livestream_videos/. So if the "
                        "agent's workspace is /Users/you/agent, "
                        "passing 'demo.mp4' resolves to "
                        "/Users/you/agent/livestream_videos/demo.mp4."
                    ),
                },
                "loop": {
                    "type": "boolean",
                    "description": (
                        "Restart the publisher every time the video ends, "
                        "creating an effectively-infinite loop. Useful for "
                        "marketing reels where the stream should stay live. "
                        "Default false (publish once and exit). Stop with "
                        "action='stop'."
                    ),
                },
                "max_iterations": {
                    "type": "integer",
                    "description": (
                        "Hard cap on loop iterations as a safety belt "
                        "(default 0 = infinite). Only relevant when loop=true."
                    ),
                },
                "mint": {
                    "type": "string",
                    "description": (
                        "Pump.fun coin mint address. Optional — falls back "
                        "to vault key 'pumpfun_coin_mint'."
                    ),
                },
                "fps": {
                    "type": "number",
                    "description": "Target frame rate when publishing (default 30).",
                },
                "livekit_url": {
                    "type": "string",
                    "description": (
                        "Override the LiveKit cluster URL (advanced). "
                        "Default cluster is used otherwise."
                    ),
                },
                "skip_create": {
                    "type": "boolean",
                    "description": (
                        "Skip POST /livestreams/create-livestream when the "
                        "stream record already exists. Default false."
                    ),
                },
                "keep_h264": {
                    "type": "boolean",
                    "description": (
                        "Keep the transcoded .h264 file after stop, useful "
                        "for re-streaming without re-encoding. Default false."
                    ),
                },
                "voice": {
                    "type": "boolean",
                    "description": (
                        "Voice mode: stream a static image as the video "
                        "track and the agent's spoken thoughts as the "
                        "audio track (TTS via OpenAI). Skips the 'video' "
                        "param entirely. Use the pump_say tool to queue "
                        "lines for the agent to speak. Requires "
                        "openai_api_key in the vault."
                    ),
                },
                "image_path": {
                    "type": "string",
                    "description": (
                        "Optional static image (PNG/JPG) to display "
                        "while voice mode runs. Bare filename resolves "
                        "under <workspace>/livestream_videos/. If omitted, "
                        "a placeholder is auto-generated."
                    ),
                },
                "voice_model": {
                    "type": "string",
                    "description": (
                        "OpenAI TTS model (default 'tts-1'). 'tts-1-hd' "
                        "is higher quality at higher cost."
                    ),
                },
                "voice_id": {
                    "type": "string",
                    "description": (
                        "OpenAI TTS voice id (default 'onyx'). Options: "
                        "alloy, echo, fable, onyx, nova, shimmer."
                    ),
                },
            },
            "required": ["action"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        # Streaming publishes content under the agent's coin — destructive
        # in the public-state sense, so the user gets to approve each call.
        return PermissionLevel.DESTRUCTIVE

    def _resolve_mint(self, params: dict[str, Any]) -> str:
        explicit = params.get("mint", "") or ""
        if explicit:
            return str(explicit).strip()
        if self._vault is None:
            raise LivestreamError("Vault not injected; cannot resolve mint.")
        stored = self._vault.get(COIN_MINT_VAULT_KEY) or ""
        if not stored:
            raise LivestreamError(
                f"No 'mint' param and no '{COIN_MINT_VAULT_KEY}' in vault. "
                "Either pass mint explicitly or run "
                f"`vault_set {COIN_MINT_VAULT_KEY} <mint>` first."
            )
        return str(stored).strip()

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._vault is None:
            return ToolResult(
                success=False,
                error="Vault not injected — pump_livestream needs the "
                "agent's running vault.",
            )

        action = params.get("action", "")
        try:
            orch = LivestreamOrchestrator(
                self._vault, workspace_dir=self._workspace or None
            )

            # Every orchestrator call below is synchronous — uses
            # httpx.Client (30s timeout per HTTP) and subprocess.
            # We wrap each in asyncio.to_thread so a slow pump.fun
            # endpoint can never starve the gateway's keepalive
            # ping or freeze the chat REPL. See docs/65-PUMPFUN-LIVESTREAM.md.
            if action == "address":
                addr = await asyncio.to_thread(orch.wallet_address)
                return ToolResult(success=True, data={"wallet": addr})

            if action == "login":
                token = await asyncio.to_thread(orch.login)
                return ToolResult(
                    success=True,
                    data={
                        "logged_in": True,
                        "token_preview": f"{token[:24]}..." if token else "",
                    },
                )

            mint = self._resolve_mint(params)

            if action == "status":
                data = await asyncio.to_thread(orch.status_stream, mint)
                return ToolResult(success=True, data=data)

            if action == "stop":
                data = await asyncio.to_thread(orch.stop_stream, mint)
                return ToolResult(success=True, data=data)

            if action == "start":
                voice = bool(params.get("voice", False))
                video = params.get("video", "") or ""
                if not voice and not video:
                    return ToolResult(
                        success=False,
                        error="action='start' needs either 'video' (path) "
                        "or 'voice'=true (TTS-driven static-image stream).",
                    )
                fps = float(params.get("fps", 30.0))
                livekit_url = str(params.get("livekit_url", "") or "")
                skip_create = bool(params.get("skip_create", False))
                keep_h264 = bool(params.get("keep_h264", False))
                loop = bool(params.get("loop", False))
                max_iterations = int(params.get("max_iterations", 0))
                image_path = str(params.get("image_path", "") or "")
                voice_model = str(params.get("voice_model", "") or "tts-1")
                voice_id = str(params.get("voice_id", "") or "onyx")
                result = await asyncio.to_thread(
                    orch.start_stream,
                    mint,
                    video,
                    fps=fps,
                    livekit_url=livekit_url,
                    skip_create=skip_create,
                    keep_h264=keep_h264,
                    loop=loop,
                    max_iterations=max_iterations,
                    voice=voice,
                    image_path=image_path,
                    voice_model=voice_model,
                    voice_id=voice_id,
                )
                return ToolResult(success=True, data=result)

            return ToolResult(success=False, error=f"Unknown action: {action!r}")

        except LivestreamError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            logger.exception("pump_livestream failed unexpectedly")
            return ToolResult(success=False, error=f"Unexpected: {e}")
