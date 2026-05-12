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

        # Find the call that contains "second message" (skip identity reflection calls)
        second_run_messages = None
        for msgs in captured_messages:
            user_msgs = [m for m in msgs if m["role"] == "user"]
            if any("second message" in m["content"] for m in user_msgs):
                second_run_messages = msgs
                break
        assert second_run_messages is not None, "Could not find second run call"
        user_msgs = [m for m in second_run_messages if m["role"] == "user"]
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


# ---------------------------------------------------------------------------
# Phase A — _execute_scheduled_task no longer wraps in the global action_queue.
# Two parallel scheduled-task invocations must overlap in agent.run, not
# serialize on a single asyncio.Lock. See docs/74-CONCURRENCY-MIGRATION.md.
# ---------------------------------------------------------------------------


class TestPhaseAScheduledTaskUnwrapped:
    @pytest.mark.asyncio
    async def test_two_scheduled_tasks_overlap(self, test_config: Config) -> None:
        import asyncio

        agent = Agent(test_config)
        await agent.initialize()

        # Replace run() with a slow no-op that signals when it has started
        # and only returns after both have started. If _execute_scheduled_task
        # still wrapped in the global action_queue, the second call would
        # never start until the first returned, and we'd deadlock.
        started = asyncio.Event()
        both_started = asyncio.Event()
        in_flight = 0

        async def slow_run(goal: str, is_user_input: bool = False, **kw):
            nonlocal in_flight
            in_flight += 1
            started.set()
            if in_flight >= 2:
                both_started.set()
            # Wait for both to be in-flight before completing — proves overlap.
            await asyncio.wait_for(both_started.wait(), timeout=1.0)
            in_flight -= 1
            return type("R", (), {"content": goal, "steps_taken": 1})()

        with patch.object(agent, "run", side_effect=slow_run):
            results = await asyncio.gather(
                agent._execute_scheduled_task("task-a"),
                agent._execute_scheduled_task("task-b"),
            )

        assert {r.content for r in results} == {"task-a", "task-b"}

    @pytest.mark.asyncio
    async def test_does_not_acquire_action_queue(self, test_config: Config) -> None:
        """Belt-and-suspenders: the action_queue lock must not be touched
        by _execute_scheduled_task. If it were, a held lock would block
        the call entirely."""
        import asyncio

        from core.action_queue import TaskPriority

        agent = Agent(test_config)
        await agent.initialize()

        async def quick_run(goal: str, is_user_input: bool = False, **kw):
            return type("R", (), {"content": goal, "steps_taken": 0})()

        # Hold the action_queue with a higher-priority slot in the background.
        # If _execute_scheduled_task still acquired the lock, it would wait
        # forever for this hold to release.
        hold_release = asyncio.Event()

        async def hold_lock():
            async with agent._action_queue.acquire(TaskPriority.USER):
                await hold_release.wait()

        holder = asyncio.create_task(hold_lock())
        try:
            # Yield once so holder actually acquires before we proceed.
            await asyncio.sleep(0)
            with patch.object(agent, "run", side_effect=quick_run):
                result = await asyncio.wait_for(
                    agent._execute_scheduled_task("not-blocked"), timeout=1.0
                )
            assert result.content == "not-blocked"
        finally:
            hold_release.set()
            await holder


# ---------------------------------------------------------------------------
# Phase C — mid-turn user-message interrupt checkpoint. The run loop folds
# pending messages into the next plan call as "[user added mid-turn: ...]".
# See docs/74-CONCURRENCY-MIGRATION.md Phase C.
# ---------------------------------------------------------------------------


class TestPhaseCInterruptCheckpoint:
    @pytest.mark.asyncio
    async def test_session_add_pending_and_drain(self) -> None:
        from core.session import Session

        s = Session(session_id="s", channel="cli", user_id="u")
        assert s.has_pending_messages() is False
        assert s.drain_pending_messages() == []

        s.add_pending_message("wait, do Y instead")
        s.add_pending_message("also ignore X")
        assert s.has_pending_messages() is True

        drained = s.drain_pending_messages()
        assert drained == ["wait, do Y instead", "also ignore X"]
        assert s.has_pending_messages() is False
        # Second drain is empty (cleared).
        assert s.drain_pending_messages() == []

    @pytest.mark.asyncio
    async def test_empty_message_is_ignored(self) -> None:
        from core.session import Session

        s = Session(session_id="s", channel="cli", user_id="u")
        s.add_pending_message("")
        assert s.has_pending_messages() is False

    @pytest.mark.asyncio
    async def test_mid_turn_message_folded_into_next_plan(
        self, test_config: Config
    ) -> None:
        """Phase C end-to-end: a message added DURING a tool call appears
        in the next planner's messages list as a synthetic user turn."""
        import asyncio as _asyncio

        from core.session import Session

        agent = Agent(test_config)
        await agent.initialize()
        agent.set_approval_callback(lambda *a, **kw: True)

        session = Session(session_id="t", channel="cli", user_id="u")

        # Two plan responses:
        #  1) calls a tool that signals "now's your chance to interrupt"
        #     and waits for the operator's mid-turn message to land
        #  2) returns text to finish the run
        captured_messages_at_step2: list[dict] = []
        step_idx = 0
        tool_invoked = _asyncio.Event()

        plan_1 = LLMResponse(
            content="",
            model_used="t",
            provider="t",
            input_tokens=1,
            output_tokens=1,
            cost_estimate=0.0,
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "shell_execute",
                        "arguments": '{"command": "echo step1"}',
                    },
                }
            ],
        )
        plan_2 = LLMResponse(
            content="Pivoted based on your update.",
            model_used="t",
            provider="t",
            input_tokens=1,
            output_tokens=1,
            cost_estimate=0.0,
            tool_calls=None,
        )

        async def fake_complete(messages, *a, **kw):
            nonlocal step_idx
            step_idx += 1
            if step_idx == 1:
                # Mid-tool, simulate operator dropping a correction
                # by pushing into the session's inbox. Then the tool
                # returns, the loop iterates, and the next plan call
                # should see the synthetic "user added mid-turn:" turn.
                session.add_pending_message("wait, do Y instead")
                tool_invoked.set()
                return plan_1
            # step 2: capture what the planner sees
            captured_messages_at_step2[:] = list(messages)
            return plan_2

        with patch.object(
            agent._router, "complete", new=AsyncMock(side_effect=fake_complete)
        ):
            response = await agent._run_with_history(
                "do X",
                session.conversation_history,
                session.append_conversation_turn,
                session=session,
            )

        assert response.steps_taken >= 2
        # The synthetic mid-turn message must appear in the step-2 messages.
        synth = [
            m
            for m in captured_messages_at_step2
            if m.get("role") == "user"
            and "user added mid-turn" in str(m.get("content", ""))
        ]
        assert len(synth) == 1
        assert "wait, do Y instead" in synth[0]["content"]


# ---------------------------------------------------------------------------
# Regression: two agent.run() calls on the same Agent must serialize on
# AGENT_LOOP (capacity 1). Pre-fix, run_session and scheduled tasks ran
# concurrently and corrupted shared singletons (browser, executor cb,
# working memory). See docs/74-CONCURRENCY-MIGRATION.md "What shipped".
# ---------------------------------------------------------------------------


class TestAgentLoopSerialization:
    @pytest.mark.asyncio
    async def test_two_run_calls_serialize(self, test_config: Config) -> None:
        import asyncio

        agent = Agent(test_config)
        await agent.initialize()

        # Track concurrent entries into _run_with_history. If AGENT_LOOP
        # serializes, max-concurrency stays at 1.
        concurrent = 0
        max_concurrent = 0
        first_in = asyncio.Event()
        release_first = asyncio.Event()

        async def slow_run_with_history(*args, **kw):
            nonlocal concurrent, max_concurrent
            concurrent += 1
            max_concurrent = max(max_concurrent, concurrent)
            if not first_in.is_set():
                first_in.set()
                await release_first.wait()
            await asyncio.sleep(0.01)
            concurrent -= 1
            return type("R", (), {"content": "ok", "steps_taken": 1})()

        with patch.object(agent, "_run_with_history", side_effect=slow_run_with_history):
            t1 = asyncio.create_task(agent.run("task-1"))
            await asyncio.wait_for(first_in.wait(), timeout=1.0)
            # First is inside the loop. Second starts but must wait
            # at the AGENT_LOOP acquire before _run_with_history fires.
            t2 = asyncio.create_task(agent.run("task-2"))
            await asyncio.sleep(0.05)
            # If serialized, only the first has incremented concurrent.
            assert concurrent == 1, f"expected serialization, got {concurrent}"
            release_first.set()
            await asyncio.gather(t1, t2)

        assert max_concurrent == 1

    @pytest.mark.asyncio
    async def test_run_isolated_reentry_does_not_deadlock(
        self, test_config: Config
    ) -> None:
        """run_isolated is called from inside an agent loop (via the
        delegate tool). It must NOT try to re-acquire AGENT_LOOP — the
        contextvar marker lets the second acquire short-circuit so we
        don't self-deadlock."""
        import asyncio

        agent = Agent(test_config)
        await agent.initialize()
        agent.set_approval_callback(lambda *a, **kw: True)

        # First call is a plain run. Inside it (via patched
        # _run_with_history), we call run again to simulate the
        # delegate path. Must complete without timeout.
        outer_done = False
        inner_done = False

        async def outer_history(*args, **kw):
            nonlocal inner_done
            # Re-enter via run() — should short-circuit AGENT_LOOP.
            with patch.object(
                agent, "_run_with_history", side_effect=inner_history
            ):
                await agent.run("inner")
            inner_done = True
            return type("R", (), {"content": "outer", "steps_taken": 1})()

        async def inner_history(*args, **kw):
            return type("R", (), {"content": "inner", "steps_taken": 1})()

        with patch.object(agent, "_run_with_history", side_effect=outer_history):
            result = await asyncio.wait_for(agent.run("outer"), timeout=2.0)
            outer_done = True

        assert outer_done and inner_done
        assert result.content == "outer"
