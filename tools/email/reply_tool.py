"""email_reply — reply to an email thread."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class EmailReplyTool(BaseTool):
    """Reply to an email in the agent's inbox (AgentMail or SMTP)."""

    def __init__(self) -> None:
        self._vault: Any = None
        self._config: Any = None
        self._db: Any = None

    @property
    def name(self) -> str:
        return "email_reply"

    @property
    def description(self) -> str:
        return (
            "Reply to an email by message ID. Maintains threading. "
            "Supports reply-all for multi-recipient threads."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "The message ID to reply to",
                },
                "body": {
                    "type": "string",
                    "description": "Reply body text",
                },
                "reply_all": {
                    "type": "boolean",
                    "description": "Reply to all recipients (default: false)",
                },
            },
            "required": ["message_id", "body"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

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
        body = params["body"]
        reply_all = params.get("reply_all", False)

        try:
            from agentmail import AgentMail

            client = AgentMail(api_key=api_key)

            if reply_all:
                response = client.inboxes.messages.reply_all(
                    inbox_id=inbox_id, message_id=message_id, text=body
                )
            else:
                response = client.inboxes.messages.reply(
                    inbox_id=inbox_id, message_id=message_id, text=body
                )

            reply_id = getattr(response, "message_id", None) or str(response)
            thread_id = getattr(response, "thread_id", None) or ""

            await self._log_reply(inbox_id, str(reply_id), str(thread_id), message_id)

            return ToolResult(
                success=True,
                data={
                    "message_id": str(reply_id),
                    "thread_id": str(thread_id),
                    "in_reply_to": message_id,
                    "reply_all": reply_all,
                    "status": "sent",
                },
            )
        except ImportError:
            return ToolResult(
                success=False,
                error="agentmail package not installed. Install it with: uv add agentmail",
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to reply: {e}")

    async def _execute_smtp(self, params: dict[str, Any]) -> ToolResult:
        smtp_cfg = self._config.smtp
        imap_cfg = self._config.imap

        # Need both SMTP (to send) and IMAP (to read original)
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

        try:
            from tools.email.smtp_client import read_message, send_email

            # Fetch original message to get threading headers
            original = read_message(
                host=imap_cfg.host,
                port=imap_cfg.port,
                username=imap_user,
                password=imap_pass,
                use_tls=imap_cfg.use_tls,
                mailbox=imap_cfg.mailbox,
                message_id=params["message_id"],
            )

            if "error" in original and not original.get("message_id"):
                return ToolResult(success=False, error=original["error"])

            original_msg_id = original.get("message_id", params["message_id"])
            original_subject = original.get("subject", "")
            reply_to_addr = original.get("from", "")
            original_references = original.get("references", "") or ""

            # Build threading headers
            references = f"{original_references} {original_msg_id}".strip()
            subject = (
                original_subject
                if original_subject.lower().startswith("re:")
                else f"Re: {original_subject}"
            )

            # Determine recipients
            from_address = (
                self._vault.get("smtp_from_address")
                or smtp_cfg.from_address
                or smtp_user
            )
            reply_all = params.get("reply_all", False)

            if reply_all:
                # Combine original From + To + CC, remove our own address
                all_addrs = set()
                if reply_to_addr:
                    all_addrs.add(reply_to_addr)
                for field in (original.get("to", ""), original.get("cc", "")):
                    if field:
                        all_addrs.update(
                            a.strip() for a in field.split(",") if a.strip()
                        )
                all_addrs.discard(from_address)
                to = ", ".join(all_addrs) if all_addrs else reply_to_addr
            else:
                to = reply_to_addr

            result = send_email(
                host=smtp_cfg.host,
                port=smtp_cfg.port,
                username=smtp_user,
                password=smtp_pass,
                use_tls=smtp_cfg.use_tls,
                from_address=from_address,
                from_name=smtp_cfg.from_name,
                to=to,
                subject=subject,
                body=params["body"],
                in_reply_to=original_msg_id,
                references=references,
            )

            await self._log_reply(
                from_address,
                result["message_id"],
                original_msg_id,
                params["message_id"],
            )

            return ToolResult(
                success=True,
                data={
                    "message_id": result["message_id"],
                    "thread_id": original_msg_id,
                    "in_reply_to": original_msg_id,
                    "reply_all": reply_all,
                    "status": "sent",
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to reply: {e}")

    async def _log_reply(
        self, inbox_id: str, reply_id: str, thread_id: str, in_reply_to: str
    ) -> None:
        if not self._db:
            return
        try:
            await self._db.execute_insert(
                "INSERT INTO email_log (timestamp, tool_name, inbox_id, direction, "
                "subject, message_id, thread_id, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(UTC).isoformat(),
                    "email_reply",
                    inbox_id,
                    "outbound",
                    f"Re: (reply to {in_reply_to})",
                    str(reply_id),
                    str(thread_id),
                    "sent",
                ),
            )
        except Exception:
            pass
