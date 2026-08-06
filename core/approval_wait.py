"""Shared approval wait — pause-not-deny for unattended autonomy.

When an operator does not answer an approval request in time, the
previous behaviour returned ``False`` (deny). That starved goals and
mind cycles: the tool was denied, the checkpoint burned a retry, and
the cycle looked "successful" with no work done.

Contract:
  1. Broadcast the approval request.
  2. Wait ``first_timeout_s``.
  3. On timeout, re-ping once (same message id / fresh broadcast).
  4. Wait ``second_timeout_s``.
  5. On second timeout, raise ``ApprovalTimeoutPause`` — callers MUST
     pause the goal/task as ``awaiting_approval`` and MUST NOT treat
     it as a permanent deny. Never soft-auto-approve on timeout.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default: 5m first wait, re-ping, then another 5m → pause (plan: ~10m
# total before awaiting_approval; goal runner used 300s flat before).
_DEFAULT_FIRST_S = 150.0
_DEFAULT_SECOND_S = 150.0


class ApprovalTimeoutPause(Exception):
    """Operator did not answer; caller must pause, not deny."""

    def __init__(self, tool_name: str, description: str = "") -> None:
        self.tool_name = tool_name
        self.description = description
        super().__init__(f"Approval timed out for {tool_name} — pausing (not denying)")


async def wait_for_operator_approval(
    gateway: Any,
    *,
    tool_name: str,
    description: str,
    params: dict[str, Any],
    first_timeout_s: float = _DEFAULT_FIRST_S,
    second_timeout_s: float = _DEFAULT_SECOND_S,
    label: str = "",
) -> bool:
    """Broadcast approval and wait with one re-ping; pause on total timeout.

    Returns True/False when the operator answers. Raises
    ``ApprovalTimeoutPause`` when both waits expire (never returns
    False on timeout).
    """
    if gateway is None:
        # No channel to ask — autonomous contexts historically
        # auto-approved. Keep that only when there is literally no
        # gateway; CRITICAL tools still go through the executor gate.
        return True

    from core.protocol import approval_request_message

    prefix = f"[{label}] " if label else ""
    msg = approval_request_message(
        session_id="",
        tool_name=tool_name,
        description=f"{prefix}{description}",
        params=params,
    )
    loop = asyncio.get_running_loop()
    future: asyncio.Future[bool] = loop.create_future()
    gateway._pending_approvals[msg.id] = future

    try:
        await gateway.broadcast(msg, session_id=None)
        try:
            # shield: wait_for must not cancel the shared future on
            # timeout — we re-use it for the re-ping wait.
            return await asyncio.wait_for(
                asyncio.shield(future), timeout=first_timeout_s
            )
        except TimeoutError:
            logger.warning(
                "Approval timeout (1st) for %s — re-pinging operator", tool_name
            )
            # Re-ping: same pending future, fresh broadcast so channels
            # surface the request again.
            await gateway.broadcast(msg, session_id=None)
            try:
                return await asyncio.wait_for(
                    asyncio.shield(future), timeout=second_timeout_s
                )
            except TimeoutError:
                logger.warning(
                    "Approval timeout (2nd) for %s — pausing (not denying)",
                    tool_name,
                )
                raise ApprovalTimeoutPause(tool_name, description) from None
    finally:
        gateway._pending_approvals.pop(msg.id, None)
