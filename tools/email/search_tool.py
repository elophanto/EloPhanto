"""email_search — search across the agent's inbox."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class EmailSearchTool(BaseTool):
    """Search the agent's inbox (AgentMail keyword search or IMAP search)."""

    def __init__(self) -> None:
        self._vault: Any = None
        self._config: Any = None

    @property
    def name(self) -> str:
        return "email_search"

    @property
    def description(self) -> str:
        return (
            "Search the agent's email inbox using natural language queries. "
            "Supports queries like 'verification emails from today' "
            "or 'invoices from Hetzner'."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default: 10)",
                },
            },
            "required": ["query"],
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

        query = params["query"]
        limit = params.get("limit", 10)

        try:
            from agentmail import AgentMail

            client = AgentMail(api_key=api_key)

            try:
                response = client.inboxes.messages.list(inbox_id=inbox_id)
                messages_raw = getattr(response, "messages", None) or response
                if not isinstance(messages_raw, list):
                    messages_raw = list(messages_raw) if messages_raw else []
            except Exception:
                messages_raw = []

            # Client-side relevance filtering
            query_lower = query.lower()
            results = []
            for msg in messages_raw:
                subject = getattr(msg, "subject", "") or ""
                snippet = getattr(msg, "snippet", "") or getattr(msg, "text", "") or ""
                sender = str(getattr(msg, "from_", None) or getattr(msg, "sender", ""))

                text = f"{subject} {snippet} {sender}".lower()
                score = sum(1 for word in query_lower.split() if word in text)

                if score > 0:
                    results.append(
                        {
                            "message_id": getattr(msg, "message_id", None)
                            or getattr(msg, "id", ""),
                            "from": sender,
                            "subject": subject,
                            "snippet": snippet[:200],
                            "relevance_score": score,
                            "received_at": str(
                                getattr(msg, "received_at", None)
                                or getattr(msg, "created_at", "")
                            ),
                        }
                    )

            results.sort(key=lambda x: x["relevance_score"], reverse=True)
            results = results[:limit]

            return ToolResult(
                success=True,
                data={"query": query, "results": results, "count": len(results)},
            )
        except ImportError:
            return ToolResult(
                success=False,
                error="agentmail package not installed. Install it with: uv add agentmail",
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to search emails: {e}")

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
            from tools.email.smtp_client import search_messages

            results = search_messages(
                host=imap_cfg.host,
                port=imap_cfg.port,
                username=imap_user,
                password=imap_pass,
                use_tls=imap_cfg.use_tls,
                mailbox=imap_cfg.mailbox,
                query=params["query"],
                limit=params.get("limit", 10),
            )

            return ToolResult(
                success=True,
                data={
                    "query": params["query"],
                    "results": results,
                    "count": len(results),
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to search emails: {e}")
