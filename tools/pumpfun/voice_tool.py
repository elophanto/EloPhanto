"""``pump_say`` native tool — make the agent talk on its pump.fun stream.

Pairs with ``pump_livestream`` running in voice mode (static image
+ TTS audio). The agent calls this whenever it wants to say
something out loud — answer a viewer's chat question, drop a
"proof" line, narrate what it's working on. The tool just appends
to a queue file; the voice engine picks it up, renders TTS, streams
to ffmpeg.

Why a queue + separate engine instead of TTS-and-stream-inline?

  - Tool calls return immediately (no waiting on the OpenAI API).
  - The voice engine owns the PCM FIFO that ffmpeg is reading;
    keeping it in one place avoids two writers fighting for the
    same file descriptor.
  - If the agent says ten things in two seconds, they queue up and
    play in order rather than getting cut off.

Action:

    {"action": "say", "text": "the elephant is online"}
        Queue a line. Returns immediately.

    {"action": "queue_size"}
        Return how many lines are pending.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult
from tools.pumpfun.orchestrator import (
    COIN_MINT_VAULT_KEY,
    LivestreamError,
)

logger = logging.getLogger(__name__)

_MAX_TEXT_LEN = 1000  # OpenAI TTS hard cap is 4096 chars; keep it tight


def _state_dir() -> Path:
    p = Path.home() / ".elophanto" / "livestream-state"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _queue_file(mint: str) -> Path:
    return _state_dir() / f"{mint[:16]}.voice_queue.jsonl"


class PumpSayTool(BaseTool):
    """Queue text for the agent to speak on its pump.fun stream."""

    def __init__(self) -> None:
        self._vault: Any = None

    @property
    def group(self) -> str:
        return "monetization"

    @property
    def name(self) -> str:
        return "pump_say"

    @property
    def description(self) -> str:
        return (
            "Queue text for the agent's pump.fun livestream voice. "
            "Requires pump_livestream to be running in voice mode "
            "(start with voice=true). The line is rendered to TTS "
            "audio and mixed into the live audio track. Returns "
            "immediately — the voice engine does the actual TTS in "
            "the background. Actions: say, queue_size."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["say", "queue_size"],
                    "description": (
                        "'say' queues a line to be spoken; "
                        "'queue_size' returns how many are pending."
                    ),
                },
                "text": {
                    "type": "string",
                    "description": (
                        "What to say (required for 'say'). Capped at "
                        f"{_MAX_TEXT_LEN} chars; the voice engine "
                        "speaks one line per queue entry with a "
                        "short pause between."
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
        # Public broadcast under the agent's coin name — same risk
        # bracket as pump_chat.
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

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._vault is None:
            return ToolResult(
                success=False,
                error="Vault not injected — pump_say needs the running vault.",
            )

        action = params.get("action", "")
        try:
            mint = self._resolve_mint(params)
            qf = _queue_file(mint)

            if action == "queue_size":
                if not qf.exists():
                    return ToolResult(
                        success=True, data={"mint": mint, "queue_size": 0}
                    )
                with qf.open("r", encoding="utf-8") as f:
                    count = sum(1 for line in f if line.strip())
                return ToolResult(
                    success=True, data={"mint": mint, "queue_size": count}
                )

            if action == "say":
                text = (params.get("text") or "").strip()
                if not text:
                    return ToolResult(
                        success=False, error="'text' is required for action='say'."
                    )
                if len(text) > _MAX_TEXT_LEN:
                    return ToolResult(
                        success=False,
                        error=(
                            f"Text exceeds {_MAX_TEXT_LEN} chars "
                            f"({len(text)}); break it into multiple "
                            "say calls."
                        ),
                    )
                entry = {"text": text, "ts": int(time.time() * 1000)}
                with qf.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                return ToolResult(
                    success=True,
                    data={
                        "queued": True,
                        "mint": mint,
                        "text": text,
                        "queue_file": str(qf),
                    },
                )

            return ToolResult(success=False, error=f"Unknown action: {action!r}")

        except LivestreamError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            logger.exception("pump_say failed unexpectedly")
            return ToolResult(success=False, error=f"Unexpected: {e}")
