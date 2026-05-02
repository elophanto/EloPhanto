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

    # Capability negotiation
    CAPABILITY_REQUEST = "capability_request"  # Client → Gateway
    CAPABILITY_RESPONSE = "capability_response"  # Gateway → Client

    # Agent-to-agent identity (Ed25519 handshake — both directions)
    # Optional — peers that don't speak this still connect under the
    # legacy auth-token model and end up as session.peer_verified=False.
    IDENTIFY = "identify"  # Either side: "here is my agent_id + signed nonce"
    IDENTIFY_RESPONSE = (
        "identify_response"  # Either side: "verified / refused / conflict"
    )

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
    AGENT_SECURITY_ALERT = "agent_security_alert"
    CHILD_REPORT = "child_report"
    CHILD_APPROVAL_REQUEST = "child_approval_request"
    CHILD_TASK_ASSIGNED = "child_task_assigned"
    CHILD_FEEDBACK = "child_feedback"
    MIND_WAKEUP = "mind_wakeup"
    MIND_ACTION = "mind_action"
    MIND_TOOL_USE = "mind_tool_use"
    MIND_SLEEP = "mind_sleep"
    MIND_PAUSED = "mind_paused"
    MIND_RESUMED = "mind_resumed"
    MIND_REVENUE = "mind_revenue"
    MIND_ERROR = "mind_error"
    HEARTBEAT_CHECK = "heartbeat_check"
    HEARTBEAT_ACTION = "heartbeat_action"
    HEARTBEAT_IDLE = "heartbeat_idle"
    WEBHOOK_RECEIVED = "webhook_received"
    WEBHOOK_TASK_STARTED = "webhook_task_started"
    SHUTDOWN = "shutdown"


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
    provider: str = "",
    model: str = "",
) -> GatewayMessage:
    """Create a response message from the gateway to a channel."""
    data: dict[str, Any] = {"content": content, "done": done, "reply_to": reply_to}
    if provider:
        data["provider"] = provider
    if model:
        data["model"] = model
    return GatewayMessage(
        type=MessageType.RESPONSE,
        session_id=session_id,
        data=data,
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


def capability_request_message(
    channel: str = "",
    user_id: str = "",
) -> GatewayMessage:
    """Create a capability request — asks the gateway what the agent can do."""
    return GatewayMessage(
        type=MessageType.CAPABILITY_REQUEST,
        channel=channel,
        user_id=user_id,
    )


def capability_response_message(
    tools: list[dict[str, Any]],
    skills: list[str],
    providers: list[str],
    version: str,
) -> GatewayMessage:
    """Create a capability response with the agent's available tools, skills, and providers."""
    return GatewayMessage(
        type=MessageType.CAPABILITY_RESPONSE,
        data={
            "protocol_version": "1.0",
            "tools": tools,
            "skills": skills,
            "providers": providers,
            "version": version,
        },
    )


# ---------------------------------------------------------------------------
# Agent-to-agent identity (IDENTIFY handshake)
#
# Either side can initiate. The challenge is opaque bytes the receiver
# previously emitted (in a prior IDENTIFY or via a STATUS challenge field
# on connect). The signature must validate against the claimed public_key
# and the receiver's challenge, proving liveness + key ownership.
#
# Backward compatible: peers that don't speak this stay on the legacy
# auth-token-only path; the gateway records them as session.peer_verified
# = False, and tools that need verified peers refuse them.
# ---------------------------------------------------------------------------


def identify_message(
    agent_id: str,
    public_key_b64: str,
    challenge_b64: str,
    signature_b64: str,
) -> GatewayMessage:
    """Initiate or respond to an IDENTIFY handshake.

    Args:
        agent_id: stable id derived from the public key (``elo-<12chars>``)
        public_key_b64: 32-byte Ed25519 public key, base64
        challenge_b64: the random nonce we're signing — base64 of bytes
            the *peer* sent us (or our own session-bind nonce on first
            initiator turn). Replay-resistant if both sides challenge.
        signature_b64: base64 Ed25519 signature over the raw challenge bytes
    """
    return GatewayMessage(
        type=MessageType.IDENTIFY,
        data={
            "agent_id": agent_id,
            "public_key": public_key_b64,
            "challenge": challenge_b64,
            "signature": signature_b64,
        },
    )


def identify_response_message(
    *,
    accepted: bool,
    reason: str = "",
    trust_level: str = "",
    challenge_b64: str = "",
) -> GatewayMessage:
    """Respond to an IDENTIFY claim.

    Args:
        accepted: whether the signature verified AND the trust ledger
            allows this peer
        reason: short human-readable explanation when refused
            (``"signature_invalid"``, ``"public_key_conflict"``,
            ``"blocked"``)
        trust_level: peer's recorded level after this handshake
            (``tofu`` / ``verified`` / ``blocked``)
        challenge_b64: when accepting, the receiver MAY include its own
            random nonce so the peer can prove liveness back the other
            way (mutual auth)
    """
    return GatewayMessage(
        type=MessageType.IDENTIFY_RESPONSE,
        data={
            "accepted": accepted,
            "reason": reason,
            "trust_level": trust_level,
            "challenge": challenge_b64,
        },
    )
