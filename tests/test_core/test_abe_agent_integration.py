"""End-to-end ABE init test — would have caught the silent
self._project_root bug (Phase 2 / 7 / 8 broken in production).

The bug: I introduced ``self._project_root`` in three sites inside
Agent's goal-init block, but Agent only sets
``self._config.project_root`` — never ``self._project_root``.
AttributeError raised, swallowed by the outer try/except, every
ABE manager stayed None, every ABE tool failed at runtime with
"not initialized". CLI worked because it has its own process that
constructs managers directly from ``config.project_root``. Unit
tests passed because they bypassed Agent.initialize() and built
managers by hand.

This test exercises ``Agent(test_config).initialize()`` end-to-end
and asserts the agent-side ABE machinery actually wires up. A
regression here means future-me has re-introduced the same class
of failure: dependency-injection-through-uninitialized-attribute.
"""

from __future__ import annotations

import pytest

from core.agent import Agent
from core.config import Config


class TestAbeAgentInitialization:
    """All assertions are positive (X is not None), not behavioural.
    The class of bug this test catches is 'silent failure during
    init'; once the managers exist, the unit tests in
    test_company.py / test_role_manager.py / test_company_set_product.py
    cover their behaviour."""

    @pytest.mark.asyncio
    async def test_initialize_wires_role_and_company_managers(
        self, test_config: Config
    ) -> None:
        agent = Agent(test_config)
        await agent.initialize()
        # The actual failure mode: these were None in production
        # because self._project_root raised AttributeError during
        # construction and the outer try/except swallowed it.
        assert agent._role_manager is not None, (
            "role_manager construction failed silently — likely a "
            "self._project_root AttributeError in agent init"
        )
        assert agent._company_manager is not None, (
            "company_manager construction failed silently — likely a "
            "self._project_root AttributeError in agent init"
        )

    @pytest.mark.asyncio
    async def test_initialize_injects_company_tool_deps(
        self, test_config: Config
    ) -> None:
        """When _inject_company_deps runs, every ABE tool's _db and
        _company_manager attributes must be set. If they're None,
        the tool fails at runtime with 'not initialized' — exactly
        the user-visible symptom of the bug."""
        agent = Agent(test_config)
        await agent.initialize()
        company_tools = (
            "company_set_product",
            "company_list",
            "company_report",
            "company_create",
            "company_use",
            "company_pause",
            "company_resume",
        )
        for tool_name in company_tools:
            tool = agent._registry.get(tool_name)
            assert tool is not None, f"{tool_name} not registered"
            assert (
                getattr(tool, "_db", None) is not None
            ), f"{tool_name}._db not injected"
            if hasattr(tool, "_company_manager"):
                assert (
                    tool._company_manager is not None
                ), f"{tool_name}._company_manager not injected"

    @pytest.mark.asyncio
    async def test_initialize_injects_role_tool_deps(self, test_config: Config) -> None:
        agent = Agent(test_config)
        await agent.initialize()
        for tool_name in ("role_list", "role_show", "role_use", "role_sync"):
            tool = agent._registry.get(tool_name)
            assert tool is not None, f"{tool_name} not registered"
            assert (
                getattr(tool, "_role_manager", None) is not None
            ), f"{tool_name}._role_manager not injected"

    @pytest.mark.asyncio
    async def test_abe_tools_visible_to_llm(self, test_config: Config) -> None:
        """The load-bearing technical contract: the ABE tools must
        actually reach the LLM's tool list. Phase 8.5 verification
        round (2026-05-26) found that all 12 ABE tools were tier
        PROFILE with groups (companies, roles) not in any default
        profile — so the LLM never saw them. The fix promoted four
        canonical entry points to CORE (always visible) and added
        the groups to the `full` profile (visible during planning).
        This test pins both legs so neither can silently regress.
        """
        from core.tool_profiles import (
            DEFAULT_PROFILES,
            filter_tools_by_profile,
        )

        agent = Agent(test_config)
        await agent.initialize()
        all_tools = list(agent._registry._tools.values())

        # Leg 1: canonical entry points always visible (CORE tier).
        # CORE-tier list audited 2026-05-26 — kept tight after the
        # 65 KB tool-schema-per-call profiling: only the entry points
        # the LLM MUST see to route correctly stay CORE. Role tools
        # + workflow-specific tools (capabilities / plan / voice) drop
        # to PROFILE — they ship under the "companies" / "roles" groups
        # which the planner activates on relevant intents.
        core_names = {t.name for t in agent._registry.get_core_tools()}
        for entry in (
            "company_list",
            "company_report",
            "company_onboard",
        ):
            assert entry in core_names, (
                f"{entry} must be CORE-tier — otherwise the LLM never "
                f"sees the canonical-source tool for the operator's "
                f"question and falls back to scratchpad memory."
            )

        # Leg 2: `full` profile includes the rest of the ABE surface
        full = filter_tools_by_profile(all_tools, "full", DEFAULT_PROFILES)
        full_names = {t.name for t in full}
        for full_only in (
            "company_create",
            "company_use",
            "company_pause",
            "company_resume",
            "company_set_product",
            "role_list",
            "role_show",
            "role_use",
            "role_sync",
        ):
            assert full_only in full_names, (
                f"{full_only} must be in the `full` profile — the "
                f"`companies` and `roles` groups need to be in "
                f"DEFAULT_PROFILES['full']."
            )

    @pytest.mark.asyncio
    async def test_company_list_executes_after_init(self, test_config: Config) -> None:
        """The actual user-visible contract: after Agent.initialize(),
        calling company_list returns success (not the
        'not initialized' error the user saw on the live system)."""
        agent = Agent(test_config)
        await agent.initialize()
        tool = agent._registry.get("company_list")
        assert tool is not None
        result = await tool.execute({})
        assert result.success is True, (
            f"company_list returned not-initialized after Agent.initialize() "
            f"— deps were never injected. Error: {result.error}"
        )
        # At minimum the default seed company should be in the list
        slugs = [c["slug"] for c in result.data["companies"]]
        assert "elophanto-self" in slugs
