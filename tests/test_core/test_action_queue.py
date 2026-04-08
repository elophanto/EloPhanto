"""Tests for action queue — serialized task execution with priority."""

from __future__ import annotations

import asyncio

import pytest

from core.action_queue import ActionQueue, TaskPriority, _Slot


class TestTaskPriority:
    def test_user_highest(self) -> None:
        assert TaskPriority.USER < TaskPriority.SCHEDULED
        assert TaskPriority.USER < TaskPriority.MIND

    def test_ordering(self) -> None:
        assert TaskPriority.USER < TaskPriority.HEARTBEAT
        assert TaskPriority.HEARTBEAT < TaskPriority.SCHEDULED
        assert TaskPriority.SCHEDULED < TaskPriority.MIND
        assert TaskPriority.MIND < TaskPriority.GOAL


class TestActionQueue:
    @pytest.mark.asyncio
    async def test_acquire_release(self) -> None:
        q = ActionQueue()
        assert not q.is_busy
        async with q.acquire(TaskPriority.USER):
            assert q.is_busy
            assert q.current_priority == TaskPriority.USER
        assert not q.is_busy
        assert q.current_priority is None

    @pytest.mark.asyncio
    async def test_serialization(self) -> None:
        """Two tasks should not run concurrently."""
        q = ActionQueue()
        order: list[str] = []

        async def task_a() -> None:
            async with q.acquire(TaskPriority.SCHEDULED):
                order.append("a_start")
                await asyncio.sleep(0.05)
                order.append("a_end")

        async def task_b() -> None:
            await asyncio.sleep(0.01)  # Let A start first
            async with q.acquire(TaskPriority.SCHEDULED):
                order.append("b_start")
                order.append("b_end")

        await asyncio.gather(task_a(), task_b())
        assert order == ["a_start", "a_end", "b_start", "b_end"]

    @pytest.mark.asyncio
    async def test_preemption_signal(self) -> None:
        """Higher-priority task signals preemption to lower-priority holder."""
        q = ActionQueue()
        preempted = False

        async def background() -> None:
            nonlocal preempted
            async with q.acquire(TaskPriority.MIND) as slot:
                await asyncio.sleep(0.05)
                preempted = slot.preempted.is_set()

        async def user_task() -> None:
            await asyncio.sleep(0.01)  # Let background start first
            async with q.acquire(TaskPriority.USER):
                pass

        await asyncio.gather(background(), user_task())
        assert preempted

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        q = ActionQueue()
        async with q.acquire(TaskPriority.SCHEDULED):
            with pytest.raises(TimeoutError):
                async with q.acquire(TaskPriority.SCHEDULED, timeout=0.01):
                    pass  # Should never reach here

    @pytest.mark.asyncio
    async def test_slot_properties(self) -> None:
        q = ActionQueue()
        async with q.acquire(TaskPriority.HEARTBEAT) as slot:
            assert isinstance(slot, _Slot)
            assert slot.priority == TaskPriority.HEARTBEAT
            assert not slot.preempted.is_set()
