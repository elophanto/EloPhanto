"""``pump_chat`` native tool — post + read pump.fun livestream chat.

Pairs with ``pump_livestream``: same auth, same coin mint, but acts on
the chat panel instead of the video track. Lets the agent answer
viewer questions in real-time, drop "proof" messages periodically
("DB locked, tx <hash>"), or pull recent chat to react to.

Actions:

    {"action": "say", "text": "gm — agent live"}
        Post a message to the agent's coin chat. Uses
        ``pumpfun_coin_mint`` from vault unless ``mint`` is passed.

    {"action": "history", "limit": 50}
        Fetch up to N most recent messages.

The connection is opened, used, and closed within a single tool call
— no persistent socket. For high-frequency posting (every few
seconds) the user should batch via the agent's heartbeat / scheduled
task system rather than calling this in a tight loop.
"""

from __future__ import annotations

import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult
from tools.pumpfun.chat_client import LivechatClient, PumpChatError
from tools.pumpfun.orchestrator import (
    COIN_MINT_VAULT_KEY,
    LivestreamError,
    LivestreamOrchestrator,
)

logger = logging.getLogger(__name__)

_MAX_MESSAGE_LEN = 500


class PumpChatTool(BaseTool):
    """Send and read pump.fun livestream chat for the agent's coin."""

    def __init__(self) -> None:
        self._vault: Any = None

    @property
    def group(self) -> str:
        return "monetization"

    @property
    def name(self) -> str:
        return "pump_chat"

    @property
    def description(self) -> str:
        return (
            "Post or read messages on the agent's pump.fun coin live "
            "chat. Pairs with pump_livestream — same Solana wallet "
            "signs auth. Actions: say (post a message), history (fetch "
            "recent messages). Uses 'pumpfun_coin_mint' from vault "
            "unless 'mint' is passed explicitly."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["say", "history"],
                    "description": (
                        "'say' posts a chat message; 'history' returns "
                        "the most recent messages."
                    ),
                },
                "text": {
                    "type": "string",
                    "description": (
                        "Message to post (required for 'say'). Pump.fun "
                        f"caps messages around {_MAX_MESSAGE_LEN} chars."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "How many messages to fetch (history). Default 50.",
                },
                "mint": {
                    "type": "string",
                    "description": (
                        "Pump.fun coin mint (optional — falls back to "
                        "vault key 'pumpfun_coin_mint')."
                    ),
                },
                "reply_to_id": {
                    "type": "string",
                    "description": (
                        "Optional message id to reply to (turns the post "
                        "into a threaded reply)."
                    ),
                },
            },
            "required": ["action"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        # Posting publicly under the agent's coin name = visible to all
        # viewers. Reading is harmless but the action enum is shared,
        # so we mark the whole tool DESTRUCTIVE so 'say' always asks.
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
                f"No 'mint' param and no '{COIN_MINT_VAULT_KEY}' in vault. "
                f"Run `vault_set {COIN_MINT_VAULT_KEY} <mint>` first."
            )
        return stored

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._vault is None:
            return ToolResult(
                success=False,
                error="Vault not injected — pump_chat needs the agent's running vault.",
            )

        action = params.get("action", "")
        try:
            mint = self._resolve_mint(params)
            # Reuse the orchestrator just for auth (login / cached JWT).
            orch = LivestreamOrchestrator(self._vault)
            jwt = orch.get_token()
            username = orch.wallet_address()

            if action == "say":
                text = (params.get("text") or "").strip()
                if not text:
                    return ToolResult(
                        success=False, error="'text' is required for action='say'."
                    )
                if len(text) > _MAX_MESSAGE_LEN:
                    return ToolResult(
                        success=False,
                        error=(
                            f"Message exceeds {_MAX_MESSAGE_LEN} chars "
                            f"({len(text)}); pump.fun would reject it."
                        ),
                    )
                async with LivechatClient(jwt) as client:
                    ack = await client.send_message(
                        mint,
                        username,
                        text,
                        reply_to_id=params.get("reply_to_id") or None,
                    )
                return ToolResult(
                    success=True,
                    data={
                        "posted": True,
                        "id": ack.get("id"),
                        "mint": mint,
                        "wallet": username,
                        "text": text,
                    },
                )

            if action == "history":
                limit = max(1, min(int(params.get("limit", 50) or 50), 200))
                async with LivechatClient(jwt) as client:
                    messages = await client.get_message_history(
                        mint, username, limit=limit
                    )
                # Keep only the fields useful to the LLM — full payloads
                # carry profile_image URLs, reactions, and other noise.
                trimmed = [
                    {
                        "id": m.get("id"),
                        "username": m.get("username"),
                        "userAddress": m.get("userAddress"),
                        "message": m.get("message"),
                        "timestamp": m.get("timestamp"),
                        "isCreator": m.get("isCreator"),
                    }
                    for m in messages
                    if isinstance(m, dict)
                ]
                return ToolResult(
                    success=True,
                    data={"mint": mint, "count": len(trimmed), "messages": trimmed},
                )

            return ToolResult(success=False, error=f"Unknown action: {action!r}")

        except (PumpChatError, LivestreamError) as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            logger.exception("pump_chat failed unexpectedly")
            return ToolResult(success=False, error=f"Unexpected: {e}")
