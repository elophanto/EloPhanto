"""Agent loop basic flow tests.

Tests the plan-execute-reflect cycle with mocked LLM responses.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.agent import _MAX_CONVERSATION_HISTORY, Agent
from core.config import Config
from core.router import LLMResponse


class TestAgentLoop:
    @pytest.mark.asyncio
    async def test_simple_text_response(self, test_config: Config) -> None:
        """LLM responds with text immediately -> task complete in 1 step."""
        agent = Agent(test_config)
        await agent.initialize()

        mock_response = LLMResponse(
            content="There are 5 Python files in your home directory.",
            model_used="test-model",
            provider="test",
            input_tokens=10,
            output_tokens=20,
            cost_estimate=0.0,
            tool_calls=None,
        )

        with patch.object(agent._router, "complete", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            response = await agent.run("list python files")

        assert "Python files" in response.content
        assert response.steps_taken == 1
        assert len(response.tool_calls_made) == 0

    @pytest.mark.asyncio
    async def test_tool_call_then_complete(self, test_config: Config) -> None:
        """LLM calls a tool, then completes on next turn."""
        agent = Agent(test_config)
        await agent.initialize()
        agent.set_approval_callback(lambda *args: True)

        call_count = 0

        async def mock_complete(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content=None,
                    model_used="test",
                    provider="test",
                    input_tokens=10,
                    output_tokens=20,
                    cost_estimate=0.0,
                    tool_calls=[
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "shell_execute",
                                "arguments": '{"command": "echo hello"}',
                            },
                        }
                    ],
                )
            else:
                return LLMResponse(
                    content="Done! The output was: hello",
                    model_used="test",
                    provider="test",
                    input_tokens=30,
                    output_tokens=15,
                    cost_estimate=0.0,
                    tool_calls=None,
                )

        with patch.object(agent._router, "complete", side_effect=mock_complete):
            response = await agent.run("run echo hello")

        assert response.steps_taken == 2
        assert "shell_execute" in response.tool_calls_made
        assert "hello" in response.content.lower() or "done" in response.content.lower()

    @pytest.mark.asyncio
    async def test_tool_denial_continues(self, test_config: Config) -> None:
        """When user denies a tool, the agent gets feedback and tries again."""
        test_config.permission_mode = "ask_always"
        agent = Agent(test_config)
        await agent.initialize()

        denial_count = 0

        def deny_then_approve(tool_name, desc, params):
            nonlocal denial_count
            denial_count += 1
            return denial_count > 1  # Deny first, approve second

        agent.set_approval_callback(deny_then_approve)

        call_count = 0

        async def mock_complete(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return LLMResponse(
                    content=None,
                    model_used="test",
                    provider="test",
                    input_tokens=10,
                    output_tokens=10,
                    cost_estimate=0.0,
                    tool_calls=[
                        {
                            "id": f"call_{call_count}",
                            "type": "function",
                            "function": {
                                "name": "shell_execute",
                                "arguments": '{"command": "echo test"}',
                            },
                        }
                    ],
                )
            else:
                return LLMResponse(
                    content="Task complete after retry.",
                    model_used="test",
                    provider="test",
                    input_tokens=20,
                    output_tokens=10,
                    cost_estimate=0.0,
                    tool_calls=None,
                )

        with patch.object(agent._router, "complete", side_effect=mock_complete):
            response = await agent.run("do something")

        assert response.steps_taken == 3
        assert "complete" in response.content.lower()

    @pytest.mark.asyncio
    async def test_max_steps_safety(self, test_config: Config) -> None:
        """Agent stops after max_steps even if LLM keeps calling tools."""
        test_config.max_steps = 3
        agent = Agent(test_config)
        await agent.initialize()
        agent.set_approval_callback(lambda *args: True)

        step = 0

        async def infinite_tool_calls(*args, **kwargs):
            nonlocal step
            step += 1
            return LLMResponse(
                content=None,
                model_used="test",
                provider="test",
                input_tokens=10,
                output_tokens=10,
                cost_estimate=0.0,
                tool_calls=[
                    {
                        "id": f"call_{step}",
                        "type": "function",
                        "function": {
                            "name": "shell_execute",
                            "arguments": '{"command": "echo loop"}',
                        },
                    }
                ],
            )

        with patch.object(agent._router, "complete", side_effect=infinite_tool_calls):
            response = await agent.run("do something forever")

        assert (
            "stopped" in response.content.lower() or "step" in response.content.lower()
        )
        assert response.steps_taken == 3

    @pytest.mark.asyncio
    async def test_safe_tool_auto_approved(self, test_config: Config) -> None:
        """Safe tools (file_list) auto-approve even in ask_always mode."""
        test_config.permission_mode = "ask_always"
        agent = Agent(test_config)
        await agent.initialize()

        # No approval callback set — safe tools should still work
        call_count = 0

        async def mock_complete(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content=None,
                    model_used="test",
                    provider="test",
                    input_tokens=10,
                    output_tokens=10,
                    cost_estimate=0.0,
                    tool_calls=[
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "file_list",
                                "arguments": '{"path": "/tmp"}',
                            },
                        }
                    ],
                )
            else:
                return LLMResponse(
                    content="Found files in /tmp.",
                    model_used="test",
                    provider="test",
                    input_tokens=20,
                    output_tokens=10,
                    cost_estimate=0.0,
                    tool_calls=None,
                )

        with patch.object(agent._router, "complete", side_effect=mock_complete):
            response = await agent.run("list files in /tmp")

        assert response.steps_taken == 2
        assert "file_list" in response.tool_calls_made

    @pytest.mark.asyncio
    async def test_llm_error_handled(self, test_config: Config) -> None:
        """Agent handles LLM call errors gracefully."""
        agent = Agent(test_config)
        await agent.initialize()

        with patch.object(agent._router, "complete", new_callable=AsyncMock) as mock:
            mock.side_effect = RuntimeError("No LLM provider available")
            response = await agent.run("do something")

        assert "error" in response.content.lower()
        assert response.steps_taken == 1


class TestConversationHistory:
    @pytest.mark.asyncio
    async def test_history_persists_across_runs(self, test_config: Config) -> None:
        """Conversation history carries user/assistant pairs between run() calls."""
        agent = Agent(test_config)
        await agent.initialize()

        mock_response = LLMResponse(
            content="I see 5 files.",
            model_used="test-model",
            provider="test",
            input_tokens=10,
            output_tokens=20,
            cost_estimate=0.0,
            tool_calls=None,
        )

        with patch.object(agent._router, "complete", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            await agent.run("list files")

        # After first run, history should have user + assistant
        assert len(agent._conversation_history) == 2
        assert agent._conversation_history[0]["role"] == "user"
        assert agent._conversation_history[0]["content"] == "list files"
        assert agent._conversation_history[1]["role"] == "assistant"
        assert "5 files" in agent._conversation_history[1]["content"]

    @pytest.mark.asyncio
    async def test_history_included_in_next_run(self, test_config: Config) -> None:
        """Prior conversation history is sent to LLM on subsequent runs."""
        agent = Agent(test_config)
        await agent.initialize()

        captured_messages: list[list[dict]] = []

        async def capture_complete(*args, **kwargs):
            captured_messages.append(kwargs.get("messages", args[0] if args else []))
            return LLMResponse(
                content="Done.",
                model_used="test",
                provider="test",
                input_tokens=10,
                output_tokens=10,
                cost_estimate=0.0,
                tool_calls=None,
            )

        with patch.object(agent._router, "complete", side_effect=capture_complete):
            await agent.run("first message")
            await agent.run("second message")

        # Second call should include prior history
        second_call_messages = captured_messages[1]
        # Find user messages (excluding system)
        user_msgs = [m for m in second_call_messages if m["role"] == "user"]
        assert len(user_msgs) == 2  # "first message" + "second message"
        assert user_msgs[0]["content"] == "first message"
        assert user_msgs[1]["content"] == "second message"

    @pytest.mark.asyncio
    async def test_clear_conversation(self, test_config: Config) -> None:
        """clear_conversation() resets history."""
        agent = Agent(test_config)
        await agent.initialize()

        mock_response = LLMResponse(
            content="OK.",
            model_used="test",
            provider="test",
            input_tokens=10,
            output_tokens=10,
            cost_estimate=0.0,
            tool_calls=None,
        )

        with patch.object(agent._router, "complete", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            await agent.run("remember this")

        assert len(agent._conversation_history) == 2
        agent.clear_conversation()
        assert len(agent._conversation_history) == 0

    @pytest.mark.asyncio
    async def test_history_capped_at_max(self, test_config: Config) -> None:
        """History is trimmed to _MAX_CONVERSATION_HISTORY messages."""
        agent = Agent(test_config)
        await agent.initialize()

        mock_response = LLMResponse(
            content="OK.",
            model_used="test",
            provider="test",
            input_tokens=10,
            output_tokens=10,
            cost_estimate=0.0,
            tool_calls=None,
        )

        with patch.object(agent._router, "complete", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            # Run enough times to exceed the cap
            for i in range(_MAX_CONVERSATION_HISTORY):
                await agent.run(f"message {i}")

        assert len(agent._conversation_history) <= _MAX_CONVERSATION_HISTORY
