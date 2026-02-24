"""Gateway protocol — message types and serialization.

Defines the JSON message format used between the WebSocket gateway
and channel adapters. Inspired by the JSON-RPC pattern in node_bridge.py.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class MessageType(StrEnum):
    """All gateway protocol message types."""

    # Client → Gateway
    CHAT = "chat"
    APPROVAL_RESPONSE = "approval_response"
    COMMAND = "command"

    # Gateway → Client
    RESPONSE = "response"
    APPROVAL_REQUEST = "approval_request"
    EVENT = "event"

    # Bidirectional
    STATUS = "status"
    ERROR = "error"


class EventType(StrEnum):
    """Event subtypes for EVENT messages."""

    TASK_COMPLETE = "task_complete"
    TASK_ERROR = "task_error"
    STEP_PROGRESS = "step_progress"
    SESSION_CREATED = "session_created"
    NOTIFICATION = "notification"
    GOAL_STARTED = "goal_started"
    GOAL_CHECKPOINT_COMPLETE = "goal_checkpoint_complete"
    GOAL_COMPLETED = "goal_completed"
    GOAL_FAILED = "goal_failed"
    GOAL_PAUSED = "goal_paused"
    GOAL_RESUMED = "goal_resumed"
    USER_MESSAGE = "user_message"
    AGENT_SPAWNED = "agent_spawned"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    AGENT_REDIRECTED = "agent_redirected"
    AGENT_STOPPED = "agent_stopped"
    MIND_WAKEUP = "mind_wakeup"
    MIND_ACTION = "mind_action"
    MIND_SLEEP = "mind_sleep"
    MIND_PAUSED = "mind_paused"
    MIND_RESUMED = "mind_resumed"
    MIND_REVENUE = "mind_revenue"
    MIND_ERROR = "mind_error"


@dataclass
class GatewayMessage:
    """Base message for gateway protocol."""

    type: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    channel: str = ""
    user_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)

    @classmethod
    def from_json(cls, raw: str) -> GatewayMessage:
        d = json.loads(raw)
        return cls(**d)


def chat_message(
    content: str,
    channel: str,
    user_id: str,
    session_id: str = "",
    attachments: list[dict[str, Any]] | None = None,
) -> GatewayMessage:
    """Create a chat message from a channel adapter."""
    data: dict[str, Any] = {"content": content}
    if attachments:
        data["attachments"] = attachments
    return GatewayMessage(
        type=MessageType.CHAT,
        channel=channel,
        user_id=user_id,
        session_id=session_id,
        data=data,
    )


def response_message(
    session_id: str,
    content: str,
    done: bool = True,
    reply_to: str = "",
) -> GatewayMessage:
    """Create a response message from the gateway to a channel."""
    return GatewayMessage(
        type=MessageType.RESPONSE,
        session_id=session_id,
        data={"content": content, "done": done, "reply_to": reply_to},
    )


def approval_request_message(
    session_id: str,
    tool_name: str,
    description: str,
    params: dict[str, Any],
) -> GatewayMessage:
    """Create an approval request for a channel adapter to present to the user."""
    return GatewayMessage(
        type=MessageType.APPROVAL_REQUEST,
        session_id=session_id,
        data={
            "tool_name": tool_name,
            "description": description,
            "params": params,
        },
    )


def approval_response_message(
    request_id: str,
    approved: bool,
) -> GatewayMessage:
    """Create an approval response from a channel adapter."""
    return GatewayMessage(
        type=MessageType.APPROVAL_RESPONSE,
        id=request_id,
        data={"approved": approved},
    )


def event_message(
    session_id: str,
    event: str,
    data: dict[str, Any] | None = None,
) -> GatewayMessage:
    """Create an event broadcast message."""
    return GatewayMessage(
        type=MessageType.EVENT,
        session_id=session_id,
        data={"event": event, **(data or {})},
    )


def error_message(
    detail: str,
    session_id: str = "",
    reply_to: str = "",
) -> GatewayMessage:
    """Create an error message."""
    return GatewayMessage(
        type=MessageType.ERROR,
        session_id=session_id,
        data={"detail": detail, "reply_to": reply_to},
    )


def status_message(
    status: str = "ok",
    data: dict[str, Any] | None = None,
) -> GatewayMessage:
    """Create a status/heartbeat message."""
    return GatewayMessage(
        type=MessageType.STATUS,
        data={"status": status, **(data or {})},
    )


def command_message(
    command: str,
    args: dict[str, Any] | None = None,
    channel: str = "",
    user_id: str = "",
    session_id: str = "",
) -> GatewayMessage:
    """Create a slash command message."""
    return GatewayMessage(
        type=MessageType.COMMAND,
        channel=channel,
        user_id=user_id,
        session_id=session_id,
        data={"command": command, "args": args or {}},
    )
