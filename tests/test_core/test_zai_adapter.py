"""Z.ai adapter message reformatting tests.

Tests the 6 GLM message constraints without making actual API calls.
"""

from __future__ import annotations

import pytest

from core.config import Config, LLMConfig, ProviderConfig
from core.zai_adapter import ZaiAdapter


@pytest.fixture
def adapter() -> ZaiAdapter:
    config = Config(
        llm=LLMConfig(
            providers={
                "zai": ProviderConfig(
                    api_key="test-key",
                    enabled=True,
                    base_url_coding="https://api.z.ai/api/coding/paas/v4",
                    base_url_paygo="https://api.z.ai/api/paas/v4",
                    coding_plan=False,
                ),
            }
        )
    )
    return ZaiAdapter(config)


class TestZaiMessageFormatting:
    def test_system_message_at_index_0(self, adapter: ZaiAdapter) -> None:
        """System message is always at index 0."""
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "system", "content": "you are helpful"},
        ]
        result = adapter._reformat_messages(messages)
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "you are helpful"

    def test_multiple_system_messages_merged(self, adapter: ZaiAdapter) -> None:
        """Multiple system messages are merged into one at index 0."""
        messages = [
            {"role": "system", "content": "rule 1"},
            {"role": "user", "content": "hello"},
            {"role": "system", "content": "rule 2"},
        ]
        result = adapter._reformat_messages(messages)
        system_msgs = [m for m in result if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert "rule 1" in system_msgs[0]["content"]
        assert "rule 2" in system_msgs[0]["content"]

    def test_assistant_tool_calls_null_content(self, adapter: ZaiAdapter) -> None:
        """Assistant messages with tool_calls get content set to null."""
        messages = [
            {"role": "user", "content": "do something"},
            {
                "role": "assistant",
                "content": "I'll use a tool",
                "tool_calls": [{"id": "call_1", "function": {"name": "test"}}],
            },
        ]
        result = adapter._reformat_messages(messages)
        assistant_msg = [m for m in result if m["role"] == "assistant"][0]
        assert assistant_msg["content"] is None

    def test_assistant_without_tool_calls_keeps_content(
        self, adapter: ZaiAdapter
    ) -> None:
        """Assistant messages without tool_calls keep their content."""
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        result = adapter._reformat_messages(messages)
        assistant_msg = [m for m in result if m["role"] == "assistant"][0]
        assert assistant_msg["content"] == "hi there"

    def test_ensures_user_message_exists(self, adapter: ZaiAdapter) -> None:
        """A user message is injected if none exists."""
        messages = [
            {"role": "system", "content": "be helpful"},
            {"role": "assistant", "content": "ok"},
        ]
        result = adapter._reformat_messages(messages)
        has_user = any(m["role"] == "user" for m in result)
        assert has_user

    def test_user_message_not_injected_when_present(self, adapter: ZaiAdapter) -> None:
        """No extra user message if one already exists."""
        messages = [
            {"role": "system", "content": "be helpful"},
            {"role": "user", "content": "hello"},
        ]
        result = adapter._reformat_messages(messages)
        user_msgs = [m for m in result if m["role"] == "user"]
        assert len(user_msgs) == 1

    def test_tool_result_preserved(self, adapter: ZaiAdapter) -> None:
        """Tool result messages are passed through with tool_call_id."""
        messages = [
            {"role": "user", "content": "do something"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "test", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": '{"result": "ok"}',
            },
        ]
        result = adapter._reformat_messages(messages)
        tool_msg = [m for m in result if m["role"] == "tool"][0]
        assert tool_msg["tool_call_id"] == "call_1"
        assert tool_msg["content"] == '{"result": "ok"}'

    def test_empty_messages_handled(self, adapter: ZaiAdapter) -> None:
        """Empty message list produces at least a user message."""
        result = adapter._reformat_messages([])
        assert len(result) >= 1
        has_user = any(m["role"] == "user" for m in result)
        assert has_user

    def test_system_at_index_0_user_at_index_1(self, adapter: ZaiAdapter) -> None:
        """With system message, user message comes right after."""
        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "user message"},
        ]
        result = adapter._reformat_messages(messages)
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"
