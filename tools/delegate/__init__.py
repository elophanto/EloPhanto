"""In-process delegation tier — light-weight subagents with isolated
context for parallel research / fan-out, between ``tool_call`` and the
heavier ``swarm_spawn`` / ``kid_spawn`` / ``org_spawn`` tiers.

See docs (and AGENT.md spawn-tier table) for which layer to pick.
"""
