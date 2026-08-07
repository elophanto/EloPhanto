"""Cost records must carry the task_type that caused them.

Every one of the 40,772 llm_usage rows in production had task_type='unknown':
CostTracker.record() accepted the argument but no call site passed it, so
per-phase cost ("what did dreaming cost? what did the mind cost?") was
unanswerable and any figure had to be reconstructed by timestamp archaeology.
"""

from __future__ import annotations

from core.router import CostTracker


def test_record_stores_the_task_type() -> None:
    t = CostTracker()
    t.record("codex", "gpt-5.5", 100, 20, 0.01, "analysis")
    assert t.calls[-1]["task_type"] == "analysis"


def test_default_is_unknown_not_a_crash() -> None:
    t = CostTracker()
    t.record("codex", "gpt-5.5", 1, 1, 0.0)
    assert t.calls[-1]["task_type"] == "unknown"


def test_distinct_phases_stay_distinguishable() -> None:
    """The whole point: you can attribute spend to the phase that caused it."""
    t = CostTracker()
    t.record("codex", "m", 10, 1, 0.05, "analysis")
    t.record("codex", "m", 10, 1, 0.02, "planning")
    t.record("codex", "m", 10, 1, 0.03, "analysis")
    by_type: dict[str, float] = {}
    for c in t.calls:
        by_type[c["task_type"]] = by_type.get(c["task_type"], 0.0) + c["cost"]
    assert round(by_type["analysis"], 2) == 0.08
    assert round(by_type["planning"], 2) == 0.02


def test_router_threads_task_type_to_every_provider_path() -> None:
    """Signature guard: all four provider calls must accept task_type, or the
    value silently reverts to 'unknown' for that provider only — the hardest
    kind of gap to notice."""
    import inspect

    from core.router import LLMRouter

    for name in ("_call_litellm", "_call_zai", "_call_codex", "_call_kimi"):
        sig = inspect.signature(getattr(LLMRouter, name))
        assert "task_type" in sig.parameters, f"{name} drops task_type"

    for name in ("_call_with_retries",):
        sig = inspect.signature(getattr(LLMRouter, name))
        assert "task_type" in sig.parameters, f"{name} drops task_type"
