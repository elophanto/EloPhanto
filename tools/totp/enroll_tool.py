"""totp_enroll — store a new TOTP secret from a 2FA setup page."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class TotpEnrollTool(BaseTool):
    """Store a TOTP secret extracted from a service's 2FA setup page."""

    def __init__(self) -> None:
        self._vault: Any = None
        self._identity_manager: Any = None

    @property
    def name(self) -> str:
        return "totp_enroll"

    @property
    def description(self) -> str:
        return (
            "Store a new TOTP authenticator secret for a service. Extract the "
            "Base32 secret from the 2FA setup page (use the 'Can't scan QR code?' "
            "link), then call this tool. The secret is encrypted in the vault — "
            "you never need to remember it. Optionally store backup/recovery codes."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Name for this entry (e.g. 'github', 'aws', 'google')",
                },
                "secret": {
                    "type": "string",
                    "description": "Base32-encoded TOTP secret from the 2FA setup page",
                },
                "account": {
                    "type": "string",
                    "description": "Account/email associated with this 2FA (optional)",
                },
                "backup_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Recovery/backup codes provided by the service (optional)",
                },
            },
            "required": ["service", "secret"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._vault:
            return ToolResult(
                success=False,
                error="Vault not available — unlock the vault first.",
            )

        service = params["service"].lower().strip()
        secret = params["secret"].strip().replace(" ", "")
        account = params.get("account", "")
        backup_codes = params.get("backup_codes")

        # Validate: secret must be valid Base32 and produce a TOTP code
        try:
            import pyotp
        except ImportError:
            return ToolResult(
                success=False,
                error="pyotp package not installed. Install it with: uv add pyotp",
            )

        try:
            totp = pyotp.TOTP(secret)
            totp.now()  # Validates the secret is usable
        except Exception:
            return ToolResult(
                success=False,
                error=(
                    "Invalid TOTP secret — must be a valid Base32-encoded string. "
                    "Check the secret from the 2FA setup page and try again."
                ),
            )

        # Store secret in vault (encrypted)
        try:
            self._vault.set(f"totp_{service}", secret)
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Failed to store TOTP secret in vault: {e}",
            )

        # Store metadata
        meta = {
            "account": account,
            "enrolled_at": datetime.now(UTC).isoformat(),
        }
        try:
            self._vault.set(f"totp_{service}_meta", meta)
        except Exception as e:
            logger.warning("Failed to store TOTP metadata: %s", e)

        # Store backup codes if provided
        if backup_codes:
            try:
                self._vault.set(f"totp_{service}_backup", backup_codes)
            except Exception as e:
                logger.warning("Failed to store backup codes: %s", e)

        # Update identity beliefs
        if self._identity_manager:
            try:
                await self._identity_manager.update_field(
                    "beliefs",
                    {f"totp_{service}": True},
                    reason=f"Enrolled TOTP 2FA for {service}",
                )
            except Exception as e:
                logger.warning("Failed to update identity beliefs: %s", e)

        return ToolResult(
            success=True,
            data={
                "service": service,
                "account": account,
                "enrolled": True,
            },
        )
