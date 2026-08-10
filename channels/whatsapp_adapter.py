"""WhatsApp channel adapter — Meta Cloud API (official) or a local bridge.

Two modes, because the two ways to reach WhatsApp have genuinely different
trade-offs and neither is right for everyone:

``cloud`` (default)
    Meta's official WhatsApp Business Cloud API. Stable, supported, and
    survives Meta's periodic crackdowns — but needs a Business account, and
    Meta rate-limits *business-initiated* messages outside a 24-hour reply
    window. Inbound arrives by webhook, so the gateway must be reachable
    from the internet (a tunnel is fine).

``bridge``
    A local process speaking newline-delimited JSON on stdio, typically a
    Baileys script driving a linked personal account. Works with a normal
    WhatsApp number and no Business setup, at the cost of running on an
    unofficial library that can break, and of sending as the operator
    rather than as a business.

The bridge contract is deliberately tiny, so any implementation satisfies
it. Inbound (bridge → us), one JSON object per line::

    {"type": "message", "from": "4477…", "chat_id": "4477…@s.whatsapp.net",
     "text": "hello", "name": "Petr"}

Outbound (us → bridge)::

    {"type": "send", "chat_id": "4477…@s.whatsapp.net", "text": "hi"}
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from channels.base import ChannelAdapter
from core.protocol import GatewayMessage

logger = logging.getLogger(__name__)

_GRAPH = "https://graph.facebook.com/v21.0"


class WhatsAppAdapter(ChannelAdapter):
    """WhatsApp interface as a gateway channel adapter."""

    name = "whatsapp"

    def __init__(
        self,
        config: Any,
        access_token: str = "",
        gateway_url: str = "ws://127.0.0.1:18789",
    ) -> None:
        super().__init__(gateway_url)
        self._cfg = config
        self._mode = str(getattr(config, "mode", "cloud") or "cloud").lower()
        self._access_token = access_token
        self._phone_number_id = str(getattr(config, "phone_number_id", "") or "")
        self._proc: asyncio.subprocess.Process | None = None
        self._session_targets: dict[str, str] = {}
        self._pending_approvals: dict[str, str] = {}

    # ── lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        await self.connect_gateway()
        if self._mode == "bridge":
            await self._start_bridge()
            await asyncio.gather(self.gateway_listener(), self._read_bridge())
        else:
            if not self._access_token or not self._phone_number_id:
                raise RuntimeError(
                    "WhatsApp cloud mode needs an access token and "
                    "phone_number_id. Set whatsapp.access_token_ref (vault key) "
                    "and whatsapp.phone_number_id in config.yaml."
                )
            logger.info(
                "WhatsApp adapter started in cloud mode (phone_number_id=%s). "
                "Point the Meta webhook at the gateway's /hooks/whatsapp.",
                self._phone_number_id,
            )
            await self.gateway_listener()

    async def stop(self) -> None:
        self._running = False
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._proc.wait(), timeout=5)
        await self.disconnect_gateway()

    # ── bridge mode ─────────────────────────────────────────────────

    async def _start_bridge(self) -> None:
        command = list(getattr(self._cfg, "bridge_command", None) or [])
        if not command:
            raise RuntimeError(
                "whatsapp.mode is 'bridge' but whatsapp.bridge_command is "
                "empty. Point it at a script implementing the stdio JSON "
                "contract, e.g. ['node', 'elophanto_nodejs/whatsapp-bridge.js']."
            )
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as err:
            raise RuntimeError(f"WhatsApp bridge command not found: {command}") from err
        logger.info("WhatsApp bridge started: %s", " ".join(command))
        asyncio.create_task(self._log_bridge_stderr())

    async def _log_bridge_stderr(self) -> None:
        if not self._proc or not self._proc.stderr:
            return
        async for line in self._proc.stderr:
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                # QR codes for linking arrive here — worth surfacing.
                logger.info("whatsapp-bridge: %s", text)

    async def _read_bridge(self) -> None:
        if not self._proc or not self._proc.stdout:
            return
        async for raw in self._proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("bridge non-JSON line: %s", line[:200])
                continue
            if event.get("type") != "message":
                continue
            try:
                await self.handle_inbound(
                    sender=str(event.get("from", "")),
                    chat_id=str(event.get("chat_id") or event.get("from", "")),
                    text=str(event.get("text", "")),
                    name=str(event.get("name", "")),
                )
            except Exception as exc:
                logger.error("WhatsApp bridge event failed: %s", exc)

    # ── shared inbound path ─────────────────────────────────────────

    async def handle_inbound(
        self, *, sender: str, chat_id: str, text: str, name: str = ""
    ) -> None:
        """Process one inbound message from either transport.

        Public because cloud mode is fed by the gateway's webhook handler
        rather than by a stream this object owns.
        """
        text = (text or "").strip()
        if not text:
            return
        if not self._is_authorized(sender):
            logger.warning("Ignoring WhatsApp message from unauthorized %s", sender)
            return

        session_id = f"whatsapp:{chat_id}"
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

        logger.info("WhatsApp message from %s (%s)", name or sender, session_id)
        response = await self.send_chat(
            content=text, user_id=sender, session_id=session_id
        )
        content = response.data.get("content", "")
        if content:
            await self._send_text(chat_id, content)

    def _is_authorized(self, number: str) -> bool:
        allowed = list(getattr(self._cfg, "allowed_numbers", None) or [])
        if not allowed:
            logger.warning(
                "whatsapp.allowed_numbers is empty — refusing all inbound "
                "WhatsApp messages. Add your own number to enable the channel."
            )
            return False
        normalized = _normalize(number)
        return number in allowed or normalized in {_normalize(a) for a in allowed}

    # ── sending ─────────────────────────────────────────────────────

    async def _send_text(self, chat_id: str, text: str) -> None:
        body = text[:4000]
        if self._mode == "bridge":
            if not self._proc or not self._proc.stdin:
                return
            payload = {"type": "send", "chat_id": chat_id, "text": body}
            self._proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
            await self._proc.stdin.drain()
            return

        try:
            import httpx
        except ImportError:  # pragma: no cover
            logger.error("httpx required for WhatsApp cloud mode")
            return

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{_GRAPH}/{self._phone_number_id}/messages",
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    json={
                        "messaging_product": "whatsapp",
                        "to": _normalize(chat_id),
                        "type": "text",
                        "text": {"body": body},
                    },
                )
            if response.status_code >= 400:
                logger.error(
                    "WhatsApp send failed (%s): %s",
                    response.status_code,
                    response.text[:300],
                )
        except Exception as exc:
            logger.error("WhatsApp send failed: %s", exc)

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


def parse_cloud_webhook(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Flatten a Meta webhook body into ``{sender, chat_id, text, name}`` dicts.

    Meta nests messages four levels deep and mixes in status callbacks
    (delivered/read receipts) that must not be treated as user input.
    """
    out: list[dict[str, str]] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            contacts = {
                c.get("wa_id", ""): c.get("profile", {}).get("name", "")
                for c in value.get("contacts", []) or []
            }
            for message in value.get("messages", []) or []:
                if message.get("type") != "text":
                    continue
                sender = str(message.get("from", ""))
                out.append(
                    {
                        "sender": sender,
                        "chat_id": sender,
                        "text": str(message.get("text", {}).get("body", "")),
                        "name": contacts.get(sender, ""),
                    }
                )
    return out


def _normalize(number: str) -> str:
    """Strip WhatsApp JID decoration down to digits."""
    base = number.split("@")[0]
    return "".join(ch for ch in base if ch.isdigit())
