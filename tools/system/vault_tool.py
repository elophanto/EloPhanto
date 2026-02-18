"""Vault lookup tool — lets the agent retrieve stored credentials."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class VaultLookupTool(BaseTool):
    """Look up stored credentials from the encrypted vault."""

    def __init__(self) -> None:
        self._vault: Any = None  # Injected by agent

    @property
    def name(self) -> str:
        return "vault_lookup"

    @property
    def description(self) -> str:
        return (
            "Look up stored credentials for a domain (e.g. google.com). "
            "Returns email/username and password if available. "
            "Use this when you encounter a login page and need credentials."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Domain to look up (e.g. google.com, github.com)",
                },
            },
            "required": ["domain"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._vault:
            return ToolResult(
                success=False,
                error=(
                    "No vault available and no stored credentials. "
                    "Ask the user directly for their login credentials "
                    "(email/username and password) so you can type them "
                    "into the browser login form."
                ),
            )

        domain = params["domain"]
        creds = self._vault.get(domain)

        if not creds:
            # Try partial match (e.g. "accounts.google.com" matches "google.com")
            for key in self._vault.list_keys():
                if key in domain or domain in key:
                    creds = self._vault.get(key)
                    domain = key
                    break

        if not creds:
            return ToolResult(
                success=False,
                error=(
                    f"No credentials found for {params['domain']}. "
                    "Ask the user directly for their login credentials "
                    "(email/username and password) so you can type them "
                    "into the browser login form."
                ),
            )

        return ToolResult(success=True, data={"domain": domain, "credentials": creds})


class VaultSetTool(BaseTool):
    """Store a credential in the encrypted vault."""

    def __init__(self) -> None:
        self._vault: Any = None

    @property
    def name(self) -> str:
        return "vault_set"

    @property
    def description(self) -> str:
        return (
            "Store a credential (API key, token, password) in the encrypted vault. "
            "Use this when the user provides a token or credential that should be "
            "saved securely for later use."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Key name (e.g., 'telegram_bot_token', 'github.com')",
                },
                "value": {
                    "type": "string",
                    "description": "The credential value to store",
                },
            },
            "required": ["key", "value"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.CRITICAL

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._vault:
            return ToolResult(
                success=False,
                error=(
                    "Vault not available. The vault must be unlocked first. "
                    "Ask the user to restart with vault unlocking enabled."
                ),
            )

        key = params["key"]
        value = params["value"]

        try:
            self._vault.set(key, value)
            return ToolResult(
                success=True,
                data={"key": key, "stored": True},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to store credential: {e}")
