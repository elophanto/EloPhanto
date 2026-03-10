"""wallet_export — export wallet private key for owner access."""

from __future__ import annotations

import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class WalletExportTool(BaseTool):
    """Export wallet private key so the owner can import it into their own wallet."""

    @property
    def group(self) -> str:
        return "payments"

    def __init__(self) -> None:
        self._payments_manager: Any = None  # Injected by agent

    @property
    def name(self) -> str:
        return "wallet_export"

    @property
    def description(self) -> str:
        return (
            "Export the agent's wallet private key for the OWNER to import into "
            "their own wallet (Phantom, MetaMask, etc.). CRITICAL: Only share the "
            "key with the owner via a secure channel. Never log or display in "
            "public channels."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to confirm key export. This is a sensitive operation.",
                },
            },
            "required": ["confirm"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.CRITICAL

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._payments_manager:
            return ToolResult(success=False, error="Payments system not initialized.")

        if not params.get("confirm"):
            return ToolResult(
                success=False,
                error="You must set confirm: true to export wallet keys.",
            )

        try:
            export_data = await self._payments_manager.export_wallet_keys()
            if not export_data.get("private_key"):
                return ToolResult(
                    success=False,
                    error="No wallet private key found. Create a wallet first.",
                )

            return ToolResult(
                success=True,
                data={
                    "address": export_data["address"],
                    "chain": export_data["chain"],
                    "private_key": export_data["private_key"],
                    "format": export_data.get("format", ""),
                    "import_instructions": export_data.get("import_instructions", ""),
                    "warning": (
                        "SENSITIVE: This is your wallet's private key. "
                        "Anyone with this key has full control of the wallet. "
                        "Store it securely and never share it publicly."
                    ),
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to export keys: {e}")
