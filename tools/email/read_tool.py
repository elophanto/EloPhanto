"""email_read — read a specific email from the agent's inbox."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class EmailReadTool(BaseTool):
    """Read the full content of a specific email (AgentMail or IMAP)."""

    def __init__(self) -> None:
        self._vault: Any = None
        self._config: Any = None

    @property
    def name(self) -> str:
        return "email_read"

    @property
    def description(self) -> str:
        return (
            "Read the full content of a specific email by message ID. "
            "Returns full body, headers, and attachment list."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "The message ID to read (from email_list results)",
                },
            },
            "required": ["message_id"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._vault:
            return ToolResult(success=False, error="Vault not available.")
        if not self._config:
            return ToolResult(success=False, error="Email not configured.")

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

        inbox_id = self._vault.get("agentmail_inbox_id")
        if not inbox_id:
            return ToolResult(
                success=False,
                error="No inbox created yet. Use email_create_inbox first.",
            )

        message_id = params["message_id"]

        try:
            from agentmail import AgentMail

            client = AgentMail(api_key=api_key)
            msg = client.inboxes.messages.get(inbox_id=inbox_id, message_id=message_id)

            sender = getattr(msg, "from_", None) or getattr(msg, "sender", "")
            if isinstance(sender, dict):
                sender = sender.get("email", str(sender))

            to_addr = getattr(msg, "to", "")
            if isinstance(to_addr, list):
                to_addr = ", ".join(str(a) for a in to_addr)

            attachments_raw = getattr(msg, "attachments", []) or []
            attachments = []
            for att in attachments_raw:
                attachments.append(
                    {
                        "filename": getattr(att, "filename", None)
                        or getattr(att, "name", "unknown"),
                        "content_type": getattr(att, "content_type", None)
                        or getattr(att, "mime_type", ""),
                        "size_bytes": getattr(att, "size", None)
                        or getattr(att, "size_bytes", 0),
                    }
                )

            return ToolResult(
                success=True,
                data={
                    "message_id": str(getattr(msg, "message_id", message_id)),
                    "from": str(sender),
                    "to": str(to_addr),
                    "subject": getattr(msg, "subject", ""),
                    "body": getattr(msg, "text", "") or "",
                    "html_body": getattr(msg, "html", "") or "",
                    "received_at": str(
                        getattr(msg, "received_at", None)
                        or getattr(msg, "created_at", "")
                    ),
                    "attachments": attachments,
                },
            )
        except ImportError:
            return ToolResult(
                success=False,
                error="agentmail package not installed. Install it with: uv add agentmail",
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to read email: {e}")

    async def _execute_smtp(self, params: dict[str, Any]) -> ToolResult:
        imap_cfg = self._config.imap
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

        if not imap_cfg.host:
            return ToolResult(
                success=False,
                error="IMAP host not configured. Update config.yaml: email.imap.host",
            )

        try:
            from tools.email.smtp_client import read_message

            result = read_message(
                host=imap_cfg.host,
                port=imap_cfg.port,
                username=imap_user,
                password=imap_pass,
                use_tls=imap_cfg.use_tls,
                mailbox=imap_cfg.mailbox,
                message_id=params["message_id"],
            )

            if "error" in result and not result.get("message_id"):
                return ToolResult(success=False, error=result["error"])

            return ToolResult(success=True, data=result)
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to read email: {e}")
