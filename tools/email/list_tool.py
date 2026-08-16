"""email_list — list emails in the agent's inbox."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class EmailListTool(BaseTool):
    """List emails in the agent's inbox (AgentMail or IMAP)."""

    @property
    def group(self) -> str:
        return "comms"

    def __init__(self) -> None:
        self._vault: Any = None
        self._config: Any = None

    @property
    def name(self) -> str:
        return "email_list"

    @property
    def description(self) -> str:
        return (
            "List emails across EVERY inbox on the AgentMail account (or one via "
            "`inbox`). Returns message summaries (inbox, id, from, "
            "subject, snippet, timestamp). Use email_read for full content."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max messages to return (default: 20)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Skip first N messages (default: 0)",
                },
                "unread_only": {
                    "type": "boolean",
                    "description": "Only show unread messages (default: false)",
                },
                "from_address": {
                    "type": "string",
                    "description": "Filter by sender email address",
                },
                "inbox": {
                    "type": "string",
                    "description": (
                        "Inbox address or id to read (e.g. lonelydegree799@agentmail.to). "
                        "Default: EVERY inbox on the AgentMail account, not only the "
                        "agent's own address — the account has several."
                    ),
                },
            },
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

        default_inbox = self._vault.get("agentmail_inbox_id")
        limit = params.get("limit", 20)
        offset = params.get("offset", 0)

        try:
            from agentmail import AgentMail

            from tools.email._inboxes import list_messages, resolve_inbox

            client = AgentMail(api_key=api_key)
            inboxes = resolve_inbox(params.get("inbox"), client, default_inbox)
            if not inboxes:
                return ToolResult(
                    success=False,
                    error="No inbox on the account yet. Use email_create_inbox first.",
                )
            # Every inbox on the account, newest first across all of them.
            tagged: list[tuple[str, Any]] = []
            for ib in inboxes:
                tagged.extend((ib, m) for m in list_messages(client, ib))
            tagged.sort(
                key=lambda t: str(
                    getattr(t[1], "received_at", None) or getattr(t[1], "created_at", "")
                ),
                reverse=True,
            )
            tagged = tagged[offset : offset + limit]
            from_filter = params.get("from_address", "")

            summaries = []
            for inbox_id, msg in tagged:
                sender = getattr(msg, "from_", None) or getattr(msg, "sender", "")
                if isinstance(sender, dict):
                    sender = sender.get("email", str(sender))

                if from_filter and from_filter.lower() not in str(sender).lower():
                    continue

                summary = {
                    "message_id": getattr(msg, "message_id", None)
                    or getattr(msg, "id", ""),
                    "inbox": inbox_id,
                    "from": str(sender),
                    "subject": getattr(msg, "subject", ""),
                    "snippet": (
                        getattr(msg, "snippet", "") or getattr(msg, "text", "") or ""
                    )[:200],
                    "received_at": str(
                        getattr(msg, "received_at", None)
                        or getattr(msg, "created_at", "")
                    ),
                }
                summaries.append(summary)

            if params.get("unread_only"):
                summaries = [s for s in summaries if not getattr(s, "is_read", False)]

            return ToolResult(
                success=True,
                data={
                    "inboxes": inboxes,
                    "messages": summaries,
                    "count": len(summaries),
                },
            )
        except ImportError:
            return ToolResult(
                success=False,
                error="agentmail package not installed. Install it with: uv add agentmail",
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to list emails: {e}")

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
                error=(
                    "IMAP host not configured. Update config.yaml: "
                    "email.imap.host (e.g. imap.gmail.com)"
                ),
            )

        try:
            from tools.email.smtp_client import list_messages

            messages = list_messages(
                host=imap_cfg.host,
                port=imap_cfg.port,
                username=imap_user,
                password=imap_pass,
                use_tls=imap_cfg.use_tls,
                mailbox=imap_cfg.mailbox,
                limit=params.get("limit", 20),
                offset=params.get("offset", 0),
                from_filter=params.get("from_address", ""),
                unread_only=params.get("unread_only", False),
            )

            inbox_id = self._vault.get("smtp_from_address") or imap_user
            return ToolResult(
                success=True,
                data={
                    "inbox_id": inbox_id,
                    "messages": messages,
                    "count": len(messages),
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to list emails: {e}")
