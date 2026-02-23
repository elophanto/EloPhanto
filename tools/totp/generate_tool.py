"""totp_generate — generate a TOTP code for a stored service."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class TotpGenerateTool(BaseTool):
    """Generate a 6-digit TOTP code for a service with a stored secret."""

    def __init__(self) -> None:
        self._vault: Any = None

    @property
    def name(self) -> str:
        return "totp_generate"

    @property
    def description(self) -> str:
        return (
            "Generate a 6-digit TOTP authenticator code for a service. "
            "Use this when a service asks 'Enter your authenticator code'. "
            "The secret is retrieved from the vault — you never see it. "
            "Returns the code and seconds remaining before expiry."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": (
                        "Service name matching the enrolled name "
                        "(e.g. 'github', 'aws', 'google')"
                    ),
                },
            },
            "required": ["service"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._vault:
            return ToolResult(
                success=False,
                error="Vault not available — unlock the vault first.",
            )

        service = params["service"].lower().strip()
        secret = self._vault.get(f"totp_{service}")

        if not secret:
            return ToolResult(
                success=False,
                error=(
                    f"No TOTP secret found for '{service}'. "
                    "Use totp_list to see enrolled services, or totp_enroll to add one."
                ),
            )

        try:
            import pyotp
        except ImportError:
            return ToolResult(
                success=False,
                error="pyotp package not installed. Install it with: uv add pyotp",
            )

        try:
            totp = pyotp.TOTP(secret)
            # Check time remaining in current 30-second window
            now = time.time()
            seconds_remaining = int(totp.interval - (now % totp.interval))

            # If < 5 seconds remaining, wait for next window to avoid race
            if seconds_remaining < 5:
                await asyncio.sleep(seconds_remaining + 0.5)
                now = time.time()
                seconds_remaining = int(totp.interval - (now % totp.interval))

            code = totp.now()

            return ToolResult(
                success=True,
                data={
                    "code": code,
                    "seconds_remaining": seconds_remaining,
                    "service": service,
                },
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Failed to generate TOTP code: {e}",
            )
