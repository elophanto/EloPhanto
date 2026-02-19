"""Planner goal integration tests — verifies XML sections are included correctly."""

from __future__ import annotations

from core.planner import build_system_prompt


class TestPlannerGoals:
    def test_goals_disabled_by_default(self) -> None:
        prompt = build_system_prompt()
        assert "<goals>" not in prompt
        assert "goal_create" not in prompt

    def test_goals_enabled(self) -> None:
        prompt = build_system_prompt(goals_enabled=True)
        assert "<goals>" in prompt
        assert "goal_create" in prompt
        assert "goal_status" in prompt
        assert "goal_manage" in prompt
        assert "</goals>" in prompt

    def test_goal_context_excluded_when_empty(self) -> None:
        prompt = build_system_prompt(goals_enabled=True, goal_context="")
        assert "<active_goal>" not in prompt

    def test_goal_context_included(self) -> None:
        ctx = "<active_goal>\n  <goal_id>abc123</goal_id>\n  <goal>Test goal</goal>\n</active_goal>"
        prompt = build_system_prompt(goals_enabled=True, goal_context=ctx)
        assert "<active_goal>" in prompt
        assert "abc123" in prompt
        assert "Test goal" in prompt

    def test_goal_context_after_knowledge(self) -> None:
        ctx = "<active_goal><goal_id>g1</goal_id></active_goal>"
        knowledge = "Some knowledge chunks here"
        prompt = build_system_prompt(
            goals_enabled=True,
            knowledge_context=knowledge,
            goal_context=ctx,
        )
        # goal_context should appear after knowledge
        k_pos = prompt.find("relevant_knowledge")
        g_pos = prompt.find("<active_goal>")
        assert k_pos < g_pos

    def test_goals_section_xml_wellformed(self) -> None:
        prompt = build_system_prompt(goals_enabled=True)
        # Check XML tags are properly opened and closed
        assert prompt.count("<goals>") == 1
        assert prompt.count("</goals>") == 1
        assert prompt.count("<when_to_create_goals>") == 1
        assert prompt.count("</when_to_create_goals>") == 1
        assert prompt.count("<checkpoint_execution>") == 1
        assert prompt.count("</checkpoint_execution>") == 1
        assert prompt.count("<self_evaluation>") == 1
        assert prompt.count("</self_evaluation>") == 1
