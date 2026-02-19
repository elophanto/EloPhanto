"""Tests for gateway protocol — messages, enums, serialization."""

from __future__ import annotations

import json

from core.protocol import (
    EventType,
    GatewayMessage,
    MessageType,
    approval_request_message,
    approval_response_message,
    chat_message,
    command_message,
    error_message,
    event_message,
    response_message,
    status_message,
)

# ─── Enums ───


class TestMessageType:
    def test_chat_value(self) -> None:
        assert MessageType.CHAT == "chat"

    def test_response_value(self) -> None:
        assert MessageType.RESPONSE == "response"

    def test_approval_request_value(self) -> None:
        assert MessageType.APPROVAL_REQUEST == "approval_request"

    def test_approval_response_value(self) -> None:
        assert MessageType.APPROVAL_RESPONSE == "approval_response"

    def test_command_value(self) -> None:
        assert MessageType.COMMAND == "command"

    def test_event_value(self) -> None:
        assert MessageType.EVENT == "event"

    def test_status_value(self) -> None:
        assert MessageType.STATUS == "status"

    def test_error_value(self) -> None:
        assert MessageType.ERROR == "error"


class TestEventType:
    def test_task_complete(self) -> None:
        assert EventType.TASK_COMPLETE == "task_complete"

    def test_task_error(self) -> None:
        assert EventType.TASK_ERROR == "task_error"

    def test_step_progress(self) -> None:
        assert EventType.STEP_PROGRESS == "step_progress"

    def test_notification(self) -> None:
        assert EventType.NOTIFICATION == "notification"


# ─── GatewayMessage ───


class TestGatewayMessage:
    def test_default_fields(self) -> None:
        msg = GatewayMessage(type="chat")
        assert msg.type == "chat"
        assert isinstance(msg.id, str)
        assert len(msg.id) > 0
        assert msg.session_id == ""
        assert msg.channel == ""
        assert msg.user_id == ""
        assert msg.data == {}

    def test_custom_fields(self) -> None:
        msg = GatewayMessage(
            type="response",
            session_id="s1",
            channel="telegram",
            user_id="u1",
            data={"content": "hello"},
        )
        assert msg.type == "response"
        assert msg.session_id == "s1"
        assert msg.channel == "telegram"
        assert msg.user_id == "u1"
        assert msg.data["content"] == "hello"


# ─── JSON Serialization ───


class TestSerialization:
    def test_to_json_returns_string(self) -> None:
        msg = GatewayMessage(type="status")
        result = msg.to_json()
        assert isinstance(result, str)

    def test_to_json_is_valid_json(self) -> None:
        msg = GatewayMessage(type="chat", data={"content": "hi"})
        parsed = json.loads(msg.to_json())
        assert parsed["type"] == "chat"
        assert parsed["data"]["content"] == "hi"

    def test_from_json_roundtrip(self) -> None:
        original = GatewayMessage(
            type="chat",
            session_id="sess-1",
            channel="cli",
            user_id="user-1",
            data={"content": "test message"},
        )
        raw = original.to_json()
        restored = GatewayMessage.from_json(raw)
        assert restored.type == original.type
        assert restored.session_id == original.session_id
        assert restored.channel == original.channel
        assert restored.user_id == original.user_id
        assert restored.data == original.data

    def test_from_json_preserves_id(self) -> None:
        msg = GatewayMessage(type="status", id="custom-id")
        raw = msg.to_json()
        restored = GatewayMessage.from_json(raw)
        assert restored.id == "custom-id"


# ─── Factory Functions ───


class TestChatMessage:
    def test_creates_chat_type(self) -> None:
        msg = chat_message("hello", "cli", "user1")
        assert msg.type == MessageType.CHAT
        assert msg.data["content"] == "hello"
        assert msg.channel == "cli"
        assert msg.user_id == "user1"

    def test_with_session_id(self) -> None:
        msg = chat_message("hi", "telegram", "u2", session_id="s1")
        assert msg.session_id == "s1"

    def test_with_attachments(self) -> None:
        attachments = [{"filename": "doc.pdf", "mime_type": "application/pdf"}]
        msg = chat_message("analyze this", "telegram", "u1", attachments=attachments)
        assert msg.data.get("attachments") == attachments

    def test_without_attachments(self) -> None:
        msg = chat_message("plain text", "cli", "u1")
        assert msg.data.get("attachments") is None


class TestResponseMessage:
    def test_creates_response_type(self) -> None:
        msg = response_message("s1", "Here is the answer")
        assert msg.type == MessageType.RESPONSE
        assert msg.data["content"] == "Here is the answer"
        assert msg.session_id == "s1"

    def test_done_flag(self) -> None:
        msg = response_message("s1", "partial", done=False)
        assert msg.data["done"] is False

    def test_reply_to(self) -> None:
        msg = response_message("s1", "reply", reply_to="msg-123")
        assert msg.data["reply_to"] == "msg-123"


class TestApprovalMessages:
    def test_approval_request(self) -> None:
        msg = approval_request_message(
            "s1", "shell_execute", "Run ls -la", {"command": "ls -la"}
        )
        assert msg.type == MessageType.APPROVAL_REQUEST
        assert msg.data["tool_name"] == "shell_execute"
        assert msg.data["description"] == "Run ls -la"
        assert msg.data["params"] == {"command": "ls -la"}

    def test_approval_response_approved(self) -> None:
        msg = approval_response_message("req-1", True)
        assert msg.type == MessageType.APPROVAL_RESPONSE
        assert msg.data["approved"] is True
        assert msg.id == "req-1"

    def test_approval_response_denied(self) -> None:
        msg = approval_response_message("req-2", False)
        assert msg.data["approved"] is False


class TestEventMessage:
    def test_creates_event_type(self) -> None:
        msg = event_message("s1", EventType.TASK_COMPLETE, {"steps": 3})
        assert msg.type == MessageType.EVENT
        assert msg.data["event"] == EventType.TASK_COMPLETE
        assert msg.data["steps"] == 3

    def test_event_without_data(self) -> None:
        msg = event_message("s1", EventType.NOTIFICATION)
        assert msg.type == MessageType.EVENT


class TestErrorMessage:
    def test_creates_error_type(self) -> None:
        msg = error_message("Something went wrong")
        assert msg.type == MessageType.ERROR
        assert msg.data["detail"] == "Something went wrong"

    def test_with_session_and_reply(self) -> None:
        msg = error_message("fail", session_id="s1", reply_to="m1")
        assert msg.session_id == "s1"
        assert msg.data["reply_to"] == "m1"


class TestStatusMessage:
    def test_default_ok(self) -> None:
        msg = status_message()
        assert msg.type == MessageType.STATUS
        assert msg.data["status"] == "ok"

    def test_custom_status(self) -> None:
        msg = status_message("connected", {"client_id": "abc"})
        assert msg.data["status"] == "connected"
        assert msg.data["client_id"] == "abc"


class TestCommandMessage:
    def test_creates_command_type(self) -> None:
        msg = command_message("status")
        assert msg.type == MessageType.COMMAND
        assert msg.data["command"] == "status"

    def test_with_args(self) -> None:
        msg = command_message("sessions", args={"limit": 5}, channel="cli")
        assert msg.data["args"] == {"limit": 5}
        assert msg.channel == "cli"
