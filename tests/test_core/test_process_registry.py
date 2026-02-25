"""Tests for core/process_registry.py — subprocess tracking and reaping."""

from __future__ import annotations

import time

from core.process_registry import ProcessRegistry


class TestProcessRegistry:
    def test_register_and_count(self) -> None:
        """Registering a process increases count."""
        registry = ProcessRegistry(max_concurrent=3)
        assert registry.count == 0
        registry.register(12345, "test command")
        assert registry.count == 1

    def test_unregister(self) -> None:
        """Unregistering a process decreases count."""
        registry = ProcessRegistry(max_concurrent=3)
        registry.register(12345, "test")
        registry.unregister(12345)
        assert registry.count == 0

    def test_unregister_nonexistent_is_noop(self) -> None:
        """Unregistering a PID that was never registered should not raise."""
        registry = ProcessRegistry(max_concurrent=3)
        registry.unregister(99999)  # Should not raise
        assert registry.count == 0

    def test_at_capacity(self) -> None:
        """at_capacity should be True when count equals max."""
        registry = ProcessRegistry(max_concurrent=2)
        registry.register(1, "a")
        assert not registry.at_capacity
        registry.register(2, "b")
        assert registry.at_capacity

    def test_active_processes(self) -> None:
        """active_processes should return all tracked entries."""
        registry = ProcessRegistry(max_concurrent=5)
        registry.register(1, "ls")
        registry.register(2, "cat")
        active = registry.active_processes()
        assert len(active) == 2
        assert {p.pid for p in active} == {1, 2}

    def test_reap_expired(self) -> None:
        """Expired processes should be removed from the registry."""
        registry = ProcessRegistry(max_concurrent=5)
        # Register with a fake old timestamp
        registry.register(99999, "old process")
        entry = registry._processes[99999]
        entry.created_at = time.monotonic() - 999  # Fake old
        reaped = registry.reap_expired(max_age_seconds=10)
        # Process likely doesn't exist, so SIGTERM is harmless
        assert reaped == 1
        assert registry.count == 0

    def test_reap_young_process_not_reaped(self) -> None:
        """Recently registered process should not be reaped."""
        registry = ProcessRegistry(max_concurrent=5)
        registry.register(99999, "young process")
        reaped = registry.reap_expired(max_age_seconds=3600)
        assert reaped == 0
        assert registry.count == 1

    def test_cleanup_dead_removes_nonexistent(self) -> None:
        """cleanup_dead should remove entries for PIDs that don't exist."""
        registry = ProcessRegistry(max_concurrent=5)
        registry.register(99999999, "nonexistent")  # PID that doesn't exist
        removed = registry.cleanup_dead()
        assert removed == 1
        assert registry.count == 0

    def test_default_max_concurrent(self) -> None:
        """Default max_concurrent should be 10."""
        registry = ProcessRegistry()
        assert registry._max == 10
