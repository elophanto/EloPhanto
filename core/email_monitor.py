"""Background monitor for the agent's own email inbox.

Polls for new unread emails in the agent's inbox every N minutes.
When new messages arrive, broadcasts a NOTIFICATION event to all
connected channels via the gateway.
No LLM calls — direct tool execution only.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.protocol import EventType, event_message

if TYPE_CHECKING:
    from core.gateway import Gateway

logger = logging.getLogger(__name__)


class EmailMonitor:
    """Polls the agent's email inbox and pushes new-mail notifications."""

    def __init__(
        self,
        email_list_tool: Any,
        config: Any,
        data_dir: Path,
    ) -> None:
        self._tool = email_list_tool
        self._config = config
        self._data_dir = data_dir
        self._gateway: Gateway | None = None
        self._seen_ids: set[str] = set()
        self._task: asyncio.Task[None] | None = None
        self._poll_interval_minutes: int = config.monitor.poll_interval_minutes
        self._first_poll: bool = True
        self._seen_ids_path = data_dir / "email_seen_ids.json"

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, poll_interval_minutes: int | None = None) -> None:
        """Launch the background polling loop."""
        if self.is_running:
            return
        if poll_interval_minutes is not None:
            self._poll_interval_minutes = poll_interval_minutes
        self._first_poll = True
        self._load_seen_ids()
        self._task = asyncio.create_task(self._poll_loop(), name="email-monitor")
        logger.info(
            "Email monitor started (interval=%dm)",
            self._poll_interval_minutes,
        )

    async def stop(self) -> None:
        """Cancel the background loop gracefully."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._save_seen_ids()
        logger.info("Email monitor stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop — sleep then check."""
        interval = self._poll_interval_minutes * 60
        while True:
            try:
                await asyncio.sleep(interval)
                await self._check_inbox()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("Email monitor tick error", exc_info=True)

    async def _check_inbox(self) -> None:
        """Run email_list and broadcast notifications for new messages."""
        try:
            result = await self._tool.execute({"unread_only": True, "limit": 50})
        except Exception as e:
            logger.debug("Email monitor poll failed: %s", e)
            return

        if not result.success:
            logger.debug("Email monitor poll error: %s", result.error)
            return

        messages = result.data.get("messages", [])
        new_messages = [
            m
            for m in messages
            if m.get("message_id") and m["message_id"] not in self._seen_ids
        ]

        # Track all current message IDs
        for msg in new_messages:
            self._seen_ids.add(msg["message_id"])

        # First poll is silent — seeds seen IDs without notification flood
        if self._first_poll:
            self._first_poll = False
            if new_messages:
                logger.info(
                    "Email monitor: seeded %d existing messages (silent)",
                    len(new_messages),
                )
                self._save_seen_ids()
            return

        # Notify for genuinely new messages
        for msg in new_messages:
            await self._broadcast_notification(msg)

        if new_messages:
            self._save_seen_ids()

    async def _broadcast_notification(self, msg: dict[str, Any]) -> None:
        """Push a new-email notification to all channels."""
        sender = msg.get("from", "unknown")
        subject = msg.get("subject", "(no subject)")
        snippet = msg.get("snippet", "")[:200]
        received_at = msg.get("received_at", "")

        data = {
            "notification_type": "new_email",
            "message_id": msg.get("message_id", ""),
            "from": sender,
            "subject": subject,
            "snippet": snippet,
            "received_at": received_at,
        }

        if self._gateway:
            await self._gateway.broadcast(
                event_message("", EventType.NOTIFICATION, data),
                session_id=None,
            )
        else:
            logger.info("New email from %s: %s", sender, subject)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_seen_ids(self) -> None:
        """Load previously seen message IDs from disk."""
        if not self._config.monitor.persist_seen_ids:
            return
        try:
            if self._seen_ids_path.exists():
                raw = self._seen_ids_path.read_text()
                self._seen_ids = set(json.loads(raw))
                logger.debug("Loaded %d seen email IDs", len(self._seen_ids))
        except Exception as e:
            logger.debug("Failed to load seen IDs: %s", e)
            self._seen_ids = set()

    def _save_seen_ids(self) -> None:
        """Persist seen message IDs to disk."""
        if not self._config.monitor.persist_seen_ids:
            return
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            self._seen_ids_path.write_text(json.dumps(list(self._seen_ids)))
        except Exception as e:
            logger.debug("Failed to save seen IDs: %s", e)
