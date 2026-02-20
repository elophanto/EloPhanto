"""email_create_inbox — create/verify an agent email inbox."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class EmailCreateInboxTool(BaseTool):
    """Create a new email inbox (AgentMail) or verify SMTP config."""

    def __init__(self) -> None:
        self._vault: Any = None  # Injected by agent
        self._config: Any = None  # EmailConfig, injected by agent
        self._identity_manager: Any = None  # Injected by agent
        self._db: Any = None  # Injected by agent

    @property
    def name(self) -> str:
        return "email_create_inbox"

    @property
    def description(self) -> str:
        return (
            "Create a new email inbox for the agent. For AgentMail: creates a new inbox. "
            "For SMTP: verifies server connection and stores the from_address. "
            "The address is stored in identity beliefs so the agent remembers it."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "display_name": {
                    "type": "string",
                    "description": "Friendly name for the inbox (e.g. 'EloPhanto Agent')",
                },
                "domain": {
                    "type": "string",
                    "description": "Email domain (default: agentmail.to). Custom domains require paid plan.",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._vault:
            return ToolResult(
                success=False, error="Vault not available. Unlock vault first."
            )
        if not self._config:
            return ToolResult(
                success=False,
                error="Email not configured. Set email.enabled: true in config.yaml",
            )

        if self._config.provider == "smtp":
            return await self._execute_smtp(params)
        return await self._execute_agentmail(params)

    async def _execute_agentmail(self, params: dict[str, Any]) -> ToolResult:
        api_key = self._vault.get(self._config.api_key_ref)
        if not api_key:
            return ToolResult(
                success=False,
                error=(
                    "No AgentMail API key found in vault. "
                    "Ask the user for their AgentMail API key "
                    "(from https://console.agentmail.to) and store it with vault_set "
                    f"using key name '{self._config.api_key_ref}'."
                ),
            )

        try:
            from agentmail import AgentMail
            from agentmail.inboxes.types import CreateInboxRequest

            client = AgentMail(api_key=api_key)
            display_name = params.get("display_name", self._config.inbox_display_name)
            domain = params.get("domain", self._config.domain)

            req_kwargs: dict[str, Any] = {"display_name": display_name}
            if domain and domain != "agentmail.to":
                req_kwargs["domain"] = domain

            inbox = client.inboxes.create(request=CreateInboxRequest(**req_kwargs))
            inbox_id = inbox.inbox_id

            # Persist inbox ID in vault for reconnection
            try:
                self._vault.set("agentmail_inbox_id", inbox_id)
            except Exception as e:
                logger.warning(f"Failed to persist inbox_id to vault: {e}")

            # Update identity beliefs with new email
            if self._identity_manager:
                try:
                    await self._identity_manager.update_field(
                        "beliefs",
                        {"email": inbox_id},
                        reason="Created agent email inbox via AgentMail",
                    )
                except Exception as e:
                    logger.warning(f"Failed to update identity with email: {e}")

            await self._log_event(
                inbox_id, f"Created inbox with display_name={display_name}"
            )

            return ToolResult(
                success=True,
                data={
                    "inbox_id": inbox_id,
                    "display_name": display_name,
                    "domain": domain,
                    "provider": "agentmail",
                },
            )
        except ImportError:
            return ToolResult(
                success=False,
                error="agentmail package not installed. Install it with: uv add agentmail",
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to create inbox: {e}")

    async def _execute_smtp(self, params: dict[str, Any]) -> ToolResult:
        smtp_cfg = self._config.smtp
        imap_cfg = self._config.imap

        # Check SMTP credentials
        smtp_user = self._vault.get(smtp_cfg.username_ref)
        smtp_pass = self._vault.get(smtp_cfg.password_ref)
        if not smtp_user or not smtp_pass:
            return ToolResult(
                success=False,
                error=(
                    "SMTP credentials not found in vault. "
                    "Ask the user for their SMTP username and password, "
                    "then store them with vault_set using key names "
                    f"'{smtp_cfg.username_ref}' and '{smtp_cfg.password_ref}'."
                ),
            )

        # Check IMAP credentials
        imap_user = self._vault.get(imap_cfg.username_ref)
        imap_pass = self._vault.get(imap_cfg.password_ref)
        if not imap_user or not imap_pass:
            return ToolResult(
                success=False,
                error=(
                    "IMAP credentials not found in vault. "
                    "Ask the user for their IMAP username and password, "
                    "then store them with vault_set using key names "
                    f"'{imap_cfg.username_ref}' and '{imap_cfg.password_ref}'."
                ),
            )

        if not smtp_cfg.host:
            return ToolResult(
                success=False,
                error=(
                    "SMTP host not configured. Update config.yaml: "
                    "email.smtp.host (e.g. smtp.gmail.com)"
                ),
            )

        try:
            from tools.email.smtp_client import (
                test_imap_connection,
                test_smtp_connection,
            )

            # Test SMTP
            smtp_result = test_smtp_connection(
                host=smtp_cfg.host,
                port=smtp_cfg.port,
                username=smtp_user,
                password=smtp_pass,
                use_tls=smtp_cfg.use_tls,
            )
            if not smtp_result.get("success"):
                return ToolResult(
                    success=False,
                    error=f"SMTP connection failed: {smtp_result.get('error')}",
                )

            # Test IMAP (if host configured)
            if imap_cfg.host:
                imap_result = test_imap_connection(
                    host=imap_cfg.host,
                    port=imap_cfg.port,
                    username=imap_user,
                    password=imap_pass,
                    use_tls=imap_cfg.use_tls,
                    mailbox=imap_cfg.mailbox,
                )
                if not imap_result.get("success"):
                    return ToolResult(
                        success=False,
                        error=f"IMAP connection failed: {imap_result.get('error')}",
                    )

            from_address = smtp_cfg.from_address or smtp_user
            display_name = params.get("display_name", smtp_cfg.from_name)

            # Persist for reconnection
            try:
                self._vault.set("smtp_from_address", from_address)
            except Exception as e:
                logger.warning(f"Failed to persist smtp_from_address to vault: {e}")

            # Update identity beliefs
            if self._identity_manager:
                try:
                    await self._identity_manager.update_field(
                        "beliefs",
                        {"email": from_address},
                        reason="Verified SMTP/IMAP email configuration",
                    )
                except Exception as e:
                    logger.warning(f"Failed to update identity with email: {e}")

            await self._log_event(
                from_address, f"Verified SMTP config for {from_address}"
            )

            return ToolResult(
                success=True,
                data={
                    "inbox_id": from_address,
                    "display_name": display_name,
                    "provider": "smtp",
                    "smtp_host": smtp_cfg.host,
                    "imap_host": imap_cfg.host or "(not configured)",
                },
            )
        except Exception as e:
            return ToolResult(
                success=False, error=f"Failed to verify email config: {e}"
            )

    async def _log_event(self, inbox_id: str, context: str) -> None:
        if self._db:
            try:
                await self._db.execute_insert(
                    "INSERT INTO email_log (timestamp, tool_name, inbox_id, direction, "
                    "status, task_context) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        datetime.now(UTC).isoformat(),
                        "email_create_inbox",
                        inbox_id,
                        "system",
                        "created",
                        context,
                    ),
                )
            except Exception:
                pass
