"""``gmail`` — read, search, send, and triage the operator's real inbox."""

from __future__ import annotations

import base64
import logging
from email.message import EmailMessage
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult
from tools.google.base import GoogleAuthMissing, google_request

logger = logging.getLogger(__name__)

_API = "https://gmail.googleapis.com/gmail/v1/users/me"
_MAX_BODY_CHARS = 20_000


class GmailTool(BaseTool):
    """Gmail over the operator's OAuth grant."""

    def __init__(self) -> None:
        self._token_store: Any = None  # injected
        # Present so _inject_http_deps can wire uniformly with http_request.
        self._broker: Any = None
        self._scope_guard: Any = None
        self._net_policy: Any = None
        self._bindings: dict[str, str] = {}

    @property
    def name(self) -> str:
        return "gmail"

    @property
    def group(self) -> str:
        return "email"

    @property
    def description(self) -> str:
        return (
            "Read, search, send, and triage the operator's Gmail. Actions: "
            "'search' (Gmail query syntax), 'read' (full message by id), "
            "'send', 'reply', 'archive', 'mark_read', 'labels'. Requires the "
            "Google account to be connected via `elophanto oauth login google`."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        "search | read | send | reply | archive | mark_read | labels"
                    ),
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Gmail search query for 'search', e.g. "
                        "'is:unread from:boss@example.com newer_than:7d'"
                    ),
                },
                "message_id": {
                    "type": "string",
                    "description": "Message id for read / reply / archive / mark_read.",
                },
                "to": {"type": "string", "description": "Recipient for send."},
                "subject": {"type": "string", "description": "Subject for send."},
                "body": {
                    "type": "string",
                    "description": "Plain-text body for send/reply.",
                },
                "cc": {"type": "string", "description": "Optional CC for send."},
                "max_results": {
                    "type": "integer",
                    "description": "Result cap for search (default 15, max 100).",
                },
            },
            "required": ["action"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    def dynamic_permission_level(
        self, params: dict[str, Any]
    ) -> PermissionLevel | None:
        """Reading the inbox is routine; sending mail as the operator is not.

        Outbound mail is irreversible and speaks in the operator's name, so
        it always asks — that is the one Gmail action a mistaken read of the
        conversation cannot walk back.
        """
        action = str(params.get("action", "") or "").lower()
        if action in ("search", "read", "labels"):
            return PermissionLevel.SAFE
        if action in ("send", "reply"):
            return PermissionLevel.CRITICAL
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        action = str(params.get("action", "") or "").lower()
        try:
            if action == "search":
                return await self._search(params)
            if action == "read":
                return await self._read(params)
            if action in ("send", "reply"):
                return await self._send(params, is_reply=action == "reply")
            if action == "archive":
                return await self._modify(params, remove=["INBOX"])
            if action == "mark_read":
                return await self._modify(params, remove=["UNREAD"])
            if action == "labels":
                data = await google_request(self._token_store, "GET", f"{_API}/labels")
                return ToolResult(
                    success=True,
                    data={
                        "labels": [
                            {"id": lbl.get("id"), "name": lbl.get("name")}
                            for lbl in data.get("labels", [])
                        ]
                    },
                )
            return ToolResult(
                success=False,
                error=(
                    f"Unknown action {action!r}. Use search, read, send, reply, "
                    "archive, mark_read, or labels."
                ),
            )
        except GoogleAuthMissing as exc:
            return ToolResult(success=False, error=str(exc))
        except Exception as exc:
            logger.error("gmail %s failed: %s", action, exc)
            return ToolResult(success=False, error=f"Gmail {action} failed: {exc}")

    # ── actions ─────────────────────────────────────────────────────

    async def _search(self, params: dict[str, Any]) -> ToolResult:
        limit = max(1, min(int(params.get("max_results") or 15), 100))
        listing = await google_request(
            self._token_store,
            "GET",
            f"{_API}/messages",
            params={"q": params.get("query", ""), "maxResults": limit},
        )
        ids = [m["id"] for m in listing.get("messages", [])]
        if not ids:
            return ToolResult(success=True, data={"messages": [], "count": 0})

        messages = []
        for msg_id in ids:
            detail = await google_request(
                self._token_store,
                "GET",
                f"{_API}/messages/{msg_id}",
                params={
                    "format": "metadata",
                    "metadataHeaders": ["From", "To", "Subject", "Date"],
                },
            )
            messages.append(
                {
                    "id": msg_id,
                    "thread_id": detail.get("threadId"),
                    "snippet": detail.get("snippet", ""),
                    "unread": "UNREAD" in (detail.get("labelIds") or []),
                    **_headers_of(detail),
                }
            )
        return ToolResult(
            success=True, data={"messages": messages, "count": len(messages)}
        )

    async def _read(self, params: dict[str, Any]) -> ToolResult:
        msg_id = str(params.get("message_id", "") or "")
        if not msg_id:
            return ToolResult(success=False, error="read requires `message_id`.")
        detail = await google_request(
            self._token_store,
            "GET",
            f"{_API}/messages/{msg_id}",
            params={"format": "full"},
        )
        body = _extract_body(detail.get("payload", {}))
        return ToolResult(
            success=True,
            data={
                "id": msg_id,
                "thread_id": detail.get("threadId"),
                **_headers_of(detail),
                "body": body[:_MAX_BODY_CHARS],
                "truncated": len(body) > _MAX_BODY_CHARS,
                "labels": detail.get("labelIds", []),
            },
        )

    async def _send(self, params: dict[str, Any], *, is_reply: bool) -> ToolResult:
        body = str(params.get("body", "") or "")
        if not body:
            return ToolResult(success=False, error="A `body` is required.")

        thread_id = None
        to = str(params.get("to", "") or "")
        subject = str(params.get("subject", "") or "")
        headers: dict[str, str] = {}

        if is_reply:
            msg_id = str(params.get("message_id", "") or "")
            if not msg_id:
                return ToolResult(success=False, error="reply requires `message_id`.")
            original = await google_request(
                self._token_store,
                "GET",
                f"{_API}/messages/{msg_id}",
                params={
                    "format": "metadata",
                    "metadataHeaders": ["From", "Subject", "Message-ID", "References"],
                },
            )
            meta = _headers_of(original)
            thread_id = original.get("threadId")
            to = to or meta.get("from", "")
            subject = subject or _reply_subject(meta.get("subject", ""))
            raw_headers = _raw_headers(original)
            if raw_headers.get("message-id"):
                headers["In-Reply-To"] = raw_headers["message-id"]
                headers["References"] = (
                    f"{raw_headers.get('references', '')} "
                    f"{raw_headers['message-id']}"
                ).strip()

        if not to:
            return ToolResult(success=False, error="A `to` recipient is required.")

        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject or "(no subject)"
        if params.get("cc"):
            message["Cc"] = str(params["cc"])
        for key, value in headers.items():
            message[key] = value
        message.set_content(body)

        payload: dict[str, Any] = {
            "raw": base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        }
        if thread_id:
            payload["threadId"] = thread_id

        sent = await google_request(
            self._token_store, "POST", f"{_API}/messages/send", json_body=payload
        )
        return ToolResult(
            success=True,
            data={
                "id": sent.get("id"),
                "thread_id": sent.get("threadId"),
                "to": to,
                "subject": subject,
            },
        )

    async def _modify(self, params: dict[str, Any], *, remove: list[str]) -> ToolResult:
        msg_id = str(params.get("message_id", "") or "")
        if not msg_id:
            return ToolResult(success=False, error="This action requires `message_id`.")
        await google_request(
            self._token_store,
            "POST",
            f"{_API}/messages/{msg_id}/modify",
            json_body={"removeLabelIds": remove},
        )
        return ToolResult(success=True, data={"id": msg_id, "removed_labels": remove})


# ── payload helpers ─────────────────────────────────────────────────


def _raw_headers(detail: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for header in detail.get("payload", {}).get("headers", []) or []:
        name = str(header.get("name", "")).lower()
        out[name] = str(header.get("value", ""))
    return out


def _headers_of(detail: dict[str, Any]) -> dict[str, str]:
    raw = _raw_headers(detail)
    return {
        "from": raw.get("from", ""),
        "to": raw.get("to", ""),
        "subject": raw.get("subject", ""),
        "date": raw.get("date", ""),
    }


def _reply_subject(subject: str) -> str:
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


def _extract_body(payload: dict[str, Any]) -> str:
    """Walk a MIME tree for the best text representation.

    Prefers text/plain; falls back to stripped HTML, because plenty of
    senders ship HTML-only and an empty body helps nobody.
    """
    plain = _find_part(payload, "text/plain")
    if plain:
        return plain
    html = _find_part(payload, "text/html")
    if html:
        import re

        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        import html as html_mod

        return re.sub(r"[ \t]{2,}", " ", html_mod.unescape(text)).strip()
    return ""


def _find_part(part: dict[str, Any], mime: str) -> str:
    if part.get("mimeType") == mime:
        data = part.get("body", {}).get("data")
        if data:
            return _decode(data)
    for child in part.get("parts", []) or []:
        found = _find_part(child, mime)
        if found:
            return found
    return ""


def _decode(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    except Exception:
        return ""
