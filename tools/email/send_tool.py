"""email_send — send an email from the agent's inbox."""

from __future__ import annotations

import base64
import logging
import mimetypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class EmailSendTool(BaseTool):
    """Send an email from the agent's inbox (AgentMail or SMTP)."""

    def __init__(self) -> None:
        self._vault: Any = None
        self._config: Any = None
        self._db: Any = None

    @property
    def name(self) -> str:
        return "email_send"

    @property
    def description(self) -> str:
        return (
            "Send an email from the agent's inbox. Requires an inbox to be created first. "
            "Supports plain text and HTML body. Supports file attachments."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "body": {
                    "type": "string",
                    "description": "Email body (plain text or HTML)",
                },
                "html": {
                    "type": "boolean",
                    "description": "Whether body is HTML (default: false)",
                },
                "attachments": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of absolute file paths to attach "
                        '(e.g. ["/tmp/report.pdf", "/tmp/data.csv"]). '
                        "Max 25 MB total."
                    ),
                },
            },
            "required": ["to", "subject", "body"],
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

        to_addr = params["to"]
        subject = params["subject"]
        body = params["body"]
        is_html = params.get("html", False)
        file_paths: list[str] = params.get("attachments") or []

        try:
            from agentmail import AgentMail

            client = AgentMail(api_key=api_key)

            send_kwargs: dict[str, Any] = {
                "inbox_id": inbox_id,
                "to": to_addr,
                "subject": subject,
            }
            if is_html:
                send_kwargs["html"] = body
            else:
                send_kwargs["text"] = body

            if file_paths:
                send_kwargs["attachments"] = self._encode_attachments(file_paths)

            message = client.inboxes.messages.send(**send_kwargs)
            message_id = getattr(message, "message_id", None) or str(message)

            await self._log_send(inbox_id, to_addr, subject, str(message_id), "sent")

            return ToolResult(
                success=True,
                data={
                    "message_id": str(message_id),
                    "from": inbox_id,
                    "to": to_addr,
                    "subject": subject,
                    "status": "sent",
                },
            )
        except ImportError:
            return ToolResult(
                success=False,
                error="agentmail package not installed. Install it with: uv add agentmail",
            )
        except Exception as e:
            await self._log_send(inbox_id, to_addr, subject, "", "failed", str(e))
            return ToolResult(success=False, error=f"Failed to send email: {e}")

    async def _execute_smtp(self, params: dict[str, Any]) -> ToolResult:
        smtp_cfg = self._config.smtp
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

        from_address = (
            self._vault.get("smtp_from_address") or smtp_cfg.from_address or smtp_user
        )
        to_addr = params["to"]
        subject = params["subject"]
        body = params["body"]
        is_html = params.get("html", False)
        file_paths: list[str] = params.get("attachments") or []

        try:
            from tools.email.smtp_client import send_email

            result = send_email(
                host=smtp_cfg.host,
                port=smtp_cfg.port,
                username=smtp_user,
                password=smtp_pass,
                use_tls=smtp_cfg.use_tls,
                from_address=from_address,
                from_name=smtp_cfg.from_name,
                to=to_addr,
                subject=subject,
                body=body,
                html=is_html,
                attachments=file_paths or None,
            )

            await self._log_send(
                from_address, to_addr, subject, result["message_id"], "sent"
            )

            return ToolResult(
                success=True,
                data={
                    "message_id": result["message_id"],
                    "from": from_address,
                    "to": to_addr,
                    "subject": subject,
                    "status": "sent",
                },
            )
        except Exception as e:
            await self._log_send(from_address, to_addr, subject, "", "failed", str(e))
            return ToolResult(success=False, error=f"Failed to send email: {e}")

    @staticmethod
    def _encode_attachments(file_paths: list[str]) -> list[dict[str, str]]:
        """Encode files as base64 attachment dicts for AgentMail."""
        max_total = 25 * 1024 * 1024
        total_size = 0
        attachments: list[dict[str, str]] = []
        for fp in file_paths:
            path = Path(fp)
            if not path.is_file():
                raise FileNotFoundError(f"Attachment not found: {fp}")
            size = path.stat().st_size
            total_size += size
            if total_size > max_total:
                raise ValueError(
                    f"Total attachment size exceeds 25 MB limit "
                    f"(at file: {path.name})"
                )
            content_type, _ = mimetypes.guess_type(fp)
            encoded = base64.b64encode(path.read_bytes()).decode()
            att: dict[str, str] = {
                "content": encoded,
                "filename": path.name,
            }
            if content_type:
                att["content_type"] = content_type
            attachments.append(att)
        return attachments

    async def _log_send(
        self,
        inbox_id: str,
        to_addr: str,
        subject: str,
        message_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        if not self._db:
            return
        try:
            if error:
                await self._db.execute_insert(
                    "INSERT INTO email_log (timestamp, tool_name, inbox_id, direction, "
                    "recipient, subject, message_id, status, error) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        datetime.now(UTC).isoformat(),
                        "email_send",
                        inbox_id,
                        "outbound",
                        to_addr,
                        subject,
                        message_id,
                        status,
                        error,
                    ),
                )
            else:
                await self._db.execute_insert(
                    "INSERT INTO email_log (timestamp, tool_name, inbox_id, direction, "
                    "recipient, subject, message_id, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        datetime.now(UTC).isoformat(),
                        "email_send",
                        inbox_id,
                        "outbound",
                        to_addr,
                        subject,
                        message_id,
                        status,
                    ),
                )
        except Exception:
            pass
