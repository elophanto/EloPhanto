"""Signal channel adapter — bridges signal-cli to the gateway.

Signal has no bot API. The supported route for a program is `signal-cli`,
which registers as a *linked device* on the operator's own account — the
same trust model as Signal Desktop. That has a consequence worth stating
plainly: messages the agent sends appear as the operator, not as a bot. The
allowlist below is therefore not a nicety; without it, anyone who can
message the operator can drive the agent.

Transport is signal-cli's JSON-RPC mode over stdio (newline-delimited
JSON), which avoids standing up an HTTP daemon and keeps the process
lifetime tied to ours.

Setup:
    brew install signal-cli          # or see github.com/AsamK/signal-cli
    signal-cli link -n "EloPhanto"   # scan the QR from your phone

Requires: signal-cli on PATH.
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


class SignalAdapter(ChannelAdapter):
    """Signal interface as a gateway channel adapter."""

    name = "signal"

    def __init__(
        self,
        account: str,
        config: Any,
        gateway_url: str = "ws://127.0.0.1:18789",
    ) -> None:
        super().__init__(gateway_url)
        self._account = account
        self._cfg = config
        self._proc: asyncio.subprocess.Process | None = None
        self._rpc_id = 0
        # session_id → the Signal address to reply to.
        self._session_targets: dict[str, dict[str, str]] = {}
        # request_id → pending approval target, so a reply routes home.
        self._pending_approvals: dict[str, dict[str, str]] = {}

    # ── lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        binary = getattr(self._cfg, "signal_cli_path", "") or "signal-cli"
        await self.connect_gateway()

        try:
            self._proc = await asyncio.create_subprocess_exec(
                binary,
                "-a",
                self._account,
                "jsonRpc",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as err:
            raise RuntimeError(
                f"{binary} not found on PATH. Install signal-cli and link it "
                "with: signal-cli link -n 'EloPhanto'"
            ) from err

        logger.info("Signal adapter started for %s", self._account)
        await asyncio.gather(
            self.gateway_listener(),
            self._read_signal(),
            self._log_stderr(),
        )

    async def stop(self) -> None:
        self._running = False
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._proc.wait(), timeout=5)
        await self.disconnect_gateway()

    # ── signal-cli plumbing ─────────────────────────────────────────

    async def _rpc(self, method: str, params: dict[str, Any]) -> None:
        """Fire a JSON-RPC call at signal-cli. Fire-and-forget by design:
        send failures surface in stderr, and blocking the gateway loop on a
        Signal round-trip would stall every other channel."""
        if not self._proc or not self._proc.stdin:
            return
        self._rpc_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._rpc_id,
            "method": method,
            "params": params,
        }
        self._proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()

    async def _log_stderr(self) -> None:
        if not self._proc or not self._proc.stderr:
            return
        async for line in self._proc.stderr:
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                logger.debug("signal-cli: %s", text)

    async def _read_signal(self) -> None:
        """Consume signal-cli's newline-delimited JSON stream."""
        if not self._proc or not self._proc.stdout:
            return
        async for raw in self._proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("signal-cli non-JSON line: %s", line[:200])
                continue
            try:
                await self._handle_signal_event(msg)
            except Exception as exc:
                logger.error("Signal event handling failed: %s", exc)

    async def _handle_signal_event(self, event: dict[str, Any]) -> None:
        if event.get("method") != "receive":
            return
        envelope = (event.get("params") or {}).get("envelope") or {}
        data_message = envelope.get("dataMessage") or {}
        text = (data_message.get("message") or "").strip()
        if not text:
            return  # receipts, typing indicators, reactions

        source = str(envelope.get("sourceNumber") or envelope.get("source") or "")
        source_name = str(envelope.get("sourceName") or "")
        group_info = data_message.get("groupInfo") or {}
        group_id = str(group_info.get("groupId") or "")

        if not self._is_authorized(source):
            logger.warning("Ignoring Signal message from unauthorized %s", source)
            return

        target = {"group_id": group_id} if group_id else {"recipient": source}
        session_id = f"signal:{group_id or source}"
        self._session_targets[session_id] = target

        # Approvals come back as plain messages: "approve <id>" / "deny <id>".
        lowered = text.lower()
        if lowered.startswith(("approve ", "deny ")):
            verb, _, request_id = text.partition(" ")
            request_id = request_id.strip()
            if request_id in self._pending_approvals:
                await self.send_approval(request_id, verb.lower() == "approve")
                self._pending_approvals.pop(request_id, None)
                await self._send_text(
                    target, f"{'Approved' if verb.lower() == 'approve' else 'Denied'}."
                )
                return

        logger.info("Signal message from %s (%s)", source_name or source, session_id)
        response = await self.send_chat(
            content=text, user_id=source, session_id=session_id
        )
        content = response.data.get("content", "")
        if content:
            await self._send_text(target, content)

    def _is_authorized(self, number: str) -> bool:
        """Only allowlisted numbers may drive the agent.

        Empty allowlist means nobody — a linked-device account sends as the
        operator, so defaulting open would hand that to any stranger.
        """
        allowed = list(getattr(self._cfg, "allowed_numbers", None) or [])
        if not allowed:
            logger.warning(
                "signal.allowed_numbers is empty — refusing all inbound Signal "
                "messages. Add your own number to enable the channel."
            )
            return False
        return number in allowed or _normalize(number) in {
            _normalize(a) for a in allowed
        }

    async def _send_text(self, target: dict[str, str], text: str) -> None:
        params: dict[str, Any] = {"message": text[:4000]}
        if target.get("group_id"):
            params["groupId"] = target["group_id"]
        else:
            params["recipient"] = [target["recipient"]]
        await self._rpc("send", params)

    # ── gateway callbacks ───────────────────────────────────────────

    async def on_response(self, msg: GatewayMessage) -> None:
        target = self._session_targets.get(msg.session_id)
        content = msg.data.get("content", "")
        if target and content:
            await self._send_text(target, content)

    async def on_approval_request(self, msg: GatewayMessage) -> None:
        target = self._session_targets.get(msg.session_id)
        if not target:
            return
        request_id = msg.data.get("request_id", "")
        self._pending_approvals[request_id] = target
        description = msg.data.get("description", "(no description)")
        await self._send_text(
            target,
            f"Approval needed:\n{description}\n\n"
            f"Reply: approve {request_id}  /  deny {request_id}",
        )

    async def on_event(self, msg: GatewayMessage) -> None:
        content = msg.data.get("content") or msg.data.get("message") or ""
        if not content:
            return
        target = self._session_targets.get(msg.session_id)
        if target:
            await self._send_text(target, str(content))


def _normalize(number: str) -> str:
    """Compare phone numbers ignoring spaces and punctuation."""
    return "".join(ch for ch in number if ch.isdigit() or ch == "+")
