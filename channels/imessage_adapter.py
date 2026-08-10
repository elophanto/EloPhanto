"""iMessage channel adapter — macOS only, reads chat.db and sends via AppleScript.

Apple ships no API for Messages, so this works the way every iMessage
integration works: poll the local SQLite database Messages keeps, and send
through AppleScript. Two consequences the operator should know up front:

* **Full Disk Access is required.** ``~/Library/Messages/chat.db`` is
  protected; without it the adapter cannot start. Grant it to the terminal
  (or whatever process runs the gateway) in System Settings → Privacy.
* **Messages are sent from the operator's own account.** Like the Signal
  adapter, there is no bot identity — replies come from *you*. The
  allowlist is the only thing standing between "my assistant" and "anyone
  who has my number can run commands", so it defaults to closed.

The database is opened read-only and in immutable mode so a poll can never
corrupt Messages' own state.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

from channels.base import ChannelAdapter
from core.protocol import GatewayMessage

logger = logging.getLogger(__name__)

_CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"

# Apple stores message dates as nanoseconds since 2001-01-01 UTC.
_APPLE_EPOCH_OFFSET = 978_307_200

_RECENT_SQL = """
SELECT
    message.ROWID,
    message.text,
    message.attributedBody,
    message.is_from_me,
    handle.id            AS sender,
    chat.chat_identifier AS chat_id,
    chat.room_name       AS room_name
FROM message
JOIN chat_message_join ON message.ROWID = chat_message_join.message_id
JOIN chat              ON chat.ROWID    = chat_message_join.chat_id
LEFT JOIN handle       ON message.handle_id = handle.ROWID
WHERE message.ROWID > ?
ORDER BY message.ROWID ASC
LIMIT 50
"""


class IMessageAdapter(ChannelAdapter):
    """iMessage interface as a gateway channel adapter (macOS only)."""

    name = "imessage"

    def __init__(
        self,
        config: Any,
        gateway_url: str = "ws://127.0.0.1:18789",
    ) -> None:
        super().__init__(gateway_url)
        self._cfg = config
        self._last_rowid = 0
        self._poll_seconds = float(getattr(config, "poll_seconds", 3.0) or 3.0)
        self._session_targets: dict[str, str] = {}
        self._pending_approvals: dict[str, str] = {}

    # ── lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("The iMessage adapter only runs on macOS.")
        if not _CHAT_DB.exists():
            raise RuntimeError(
                f"{_CHAT_DB} not found — is Messages set up on this Mac?"
            )
        try:
            self._last_rowid = await asyncio.to_thread(self._max_rowid)
        except sqlite3.OperationalError as err:
            raise RuntimeError(
                "Cannot read the Messages database. Grant Full Disk Access to "
                "the process running the gateway (System Settings → Privacy & "
                "Security → Full Disk Access), then restart it."
            ) from err

        await self.connect_gateway()
        logger.info(
            "iMessage adapter started (polling every %.1fs from rowid %d)",
            self._poll_seconds,
            self._last_rowid,
        )
        await asyncio.gather(self.gateway_listener(), self._poll_loop())

    async def stop(self) -> None:
        self._running = False
        await self.disconnect_gateway()

    # ── chat.db ─────────────────────────────────────────────────────

    @staticmethod
    def _connect() -> sqlite3.Connection:
        # immutable=1 promises we will not write and lets sqlite skip
        # locking entirely — Messages keeps the db busy otherwise.
        conn = sqlite3.connect(f"file:{_CHAT_DB}?mode=ro&immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _max_rowid(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(ROWID) AS m FROM message").fetchone()
            return int(row["m"] or 0)

    def _fetch_since(self, rowid: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(_RECENT_SQL, (rowid,)).fetchall()
        return [dict(r) for r in rows]

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                rows = await asyncio.to_thread(self._fetch_since, self._last_rowid)
                for row in rows:
                    self._last_rowid = max(self._last_rowid, int(row["ROWID"]))
                    await self._handle_row(row)
            except sqlite3.OperationalError as exc:
                # Messages vacuums/locks the db periodically; a failed poll
                # is normal and self-heals on the next tick.
                logger.debug("chat.db poll skipped: %s", exc)
            except Exception as exc:
                logger.error("iMessage poll failed: %s", exc)
            await asyncio.sleep(self._poll_seconds)

    async def _handle_row(self, row: dict[str, Any]) -> None:
        if row.get("is_from_me"):
            return  # our own outbound message echoing back

        text = (row.get("text") or "").strip()
        if not text and row.get("attributedBody"):
            text = _decode_attributed_body(row["attributedBody"])
        if not text:
            return

        sender = str(row.get("sender") or "")
        chat_id = str(row.get("chat_id") or sender)
        if not self._is_authorized(sender):
            logger.warning("Ignoring iMessage from unauthorized %s", sender)
            return

        session_id = f"imessage:{chat_id}"
        self._session_targets[session_id] = chat_id

        lowered = text.lower()
        if lowered.startswith(("approve ", "deny ")):
            verb, _, request_id = text.partition(" ")
            request_id = request_id.strip()
            if request_id in self._pending_approvals:
                await self.send_approval(request_id, verb.lower() == "approve")
                self._pending_approvals.pop(request_id, None)
                await self._send_text(
                    chat_id,
                    f"{'Approved' if verb.lower() == 'approve' else 'Denied'}.",
                )
                return

        logger.info("iMessage from %s (%s)", sender, session_id)
        response = await self.send_chat(
            content=text, user_id=sender, session_id=session_id
        )
        content = response.data.get("content", "")
        if content:
            await self._send_text(chat_id, content)

    def _is_authorized(self, handle: str) -> bool:
        allowed = list(getattr(self._cfg, "allowed_handles", None) or [])
        if not allowed:
            logger.warning(
                "imessage.allowed_handles is empty — refusing all inbound "
                "iMessages. Add your own number or Apple ID to enable it."
            )
            return False
        normalized = _normalize(handle)
        return handle in allowed or normalized in {_normalize(a) for a in allowed}

    # ── sending ─────────────────────────────────────────────────────

    async def _send_text(self, chat_id: str, text: str) -> None:
        await asyncio.to_thread(self._osascript_send, chat_id, text[:4000])

    @staticmethod
    def _osascript_send(chat_id: str, text: str) -> None:
        import subprocess

        # Pass both strings as argv, never interpolated into the script —
        # a message containing a quote would otherwise break out of the
        # AppleScript literal.
        script = """
        on run argv
            set targetId to item 1 of argv
            set msgText to item 2 of argv
            tell application "Messages"
                try
                    set targetChat to a reference to chat id targetId
                    send msgText to targetChat
                on error
                    set targetService to 1st account whose service type = iMessage
                    set targetBuddy to participant targetId of targetService
                    send msgText to targetBuddy
                end try
            end tell
        end run
        """
        try:
            result = subprocess.run(
                ["osascript", "-", chat_id, text],
                input=script,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.error("osascript send failed: %s", result.stderr.strip()[:300])
        except Exception as exc:
            logger.error("iMessage send failed: %s", exc)

    # ── gateway callbacks ───────────────────────────────────────────

    async def on_response(self, msg: GatewayMessage) -> None:
        chat_id = self._session_targets.get(msg.session_id)
        content = msg.data.get("content", "")
        if chat_id and content:
            await self._send_text(chat_id, content)

    async def on_approval_request(self, msg: GatewayMessage) -> None:
        chat_id = self._session_targets.get(msg.session_id)
        if not chat_id:
            return
        request_id = msg.data.get("request_id", "")
        self._pending_approvals[request_id] = chat_id
        await self._send_text(
            chat_id,
            f"Approval needed:\n{msg.data.get('description', '(no description)')}\n\n"
            f"Reply: approve {request_id}  /  deny {request_id}",
        )

    async def on_event(self, msg: GatewayMessage) -> None:
        content = msg.data.get("content") or msg.data.get("message") or ""
        chat_id = self._session_targets.get(msg.session_id)
        if chat_id and content:
            await self._send_text(chat_id, str(content))


def _decode_attributed_body(blob: Any) -> str:
    """Recover text from the NSAttributedString archive newer macOS uses.

    Messages moved rich text out of ``message.text`` into a binary plist in
    ``attributedBody``; without this, recent messages read as empty. Best
    effort by design — a failure here just means we skip one message.
    """
    if not isinstance(blob, bytes | bytearray):
        return ""
    try:
        import re

        raw = bytes(blob).decode("utf-8", errors="ignore")
        marker = "NSString"
        idx = raw.find(marker)
        if idx == -1:
            return ""
        chunk = raw[idx + len(marker) :]
        # The payload begins after a short type/length header; strip control
        # bytes and take the first printable run.
        match = re.search(r"[ -~ -￿]{2,}", chunk)
        return match.group(0).strip() if match else ""
    except Exception:
        return ""


def _normalize(handle: str) -> str:
    if "@" in handle:
        return handle.strip().lower()
    return "".join(ch for ch in handle if ch.isdigit() or ch == "+")
