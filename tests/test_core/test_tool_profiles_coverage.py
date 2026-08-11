"""Every PROFILE-tier tool must be reachable by the LLM.

Registering a tool and exposing it to the model are separate steps, and
nothing structural ties them together: a PROFILE-tier tool only reaches the
LLM when its ``group`` appears in the active profile's ``allowed_groups``.
Miss that and the tool exists, imports, passes its unit tests, and is simply
never offered — a silent no-op that looks exactly like a working feature.

``core/tool_profiles.py`` carries four separate comments apologising for
previous instances (ABE management, missions, prospecting, watch). It then
happened again with the whole action layer: ``http_request``, ``gmail``,
``node_*``, ``panel_*`` shipped registered, documented, and unreachable, and
it only surfaced by watching a live log and noticing the model never called
them.

This test is the structural tie that was missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import load_config
from core.registry import ToolRegistry
from core.tool_profiles import DEFAULT_PROFILES, filter_tools_by_profile
from tools.base import ToolTier

PROJECT_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture(scope="module")
def registry() -> ToolRegistry:
    config = load_config(str(PROJECT_ROOT / "config.demo.yaml"))
    reg = ToolRegistry(PROJECT_ROOT)
    reg.load_builtin_tools(config)
    return reg


# Empty, and it should stay that way. It briefly held ambient / polymarket /
# solana / jobs / affect — 33 tools of shipped, documented features that the
# LLM could never call. Shrink this set; never grow it.
KNOWN_UNREACHABLE_GROUPS: set[str] = set()

# Groups declared only by conditionally-registered tools, so they are absent
# from a registry built with the demo config while being perfectly valid in
# a real one: `hub` needs hub.enabled, `mind` needs the autonomous mind.
# Listed so the typo check below does not mistake a real group for a rename.
CONDITIONALLY_REGISTERED_GROUPS: set[str] = {"hub", "mind"}


class TestEveryProfileToolIsReachable:
    def test_no_new_group_becomes_unreachable(self, registry: ToolRegistry) -> None:
        """`full` is the superset — a group missing here reaches nothing."""
        profile_groups = {
            t.group for t in registry.all_tools() if t.tier == ToolTier.PROFILE
        }
        missing = sorted(
            profile_groups - DEFAULT_PROFILES["full"] - KNOWN_UNREACHABLE_GROUPS
        )
        assert not missing, (
            f"PROFILE-tier groups absent from the 'full' profile: {missing}. "
            "Tools in these groups are registered but can never be offered to "
            "the LLM. Add each group to DEFAULT_PROFILES['full'] (and to "
            "'planning' if the agent loop should reach it by default)."
        )

    def test_the_unreachable_backlog_does_not_grow(
        self, registry: ToolRegistry
    ) -> None:
        """Ratchet: a fixed group must be removed from the known set."""
        profile_groups = {
            t.group for t in registry.all_tools() if t.tier == ToolTier.PROFILE
        }
        still_broken = profile_groups - DEFAULT_PROFILES["full"]
        fixed = sorted(KNOWN_UNREACHABLE_GROUPS - still_broken)
        assert not fixed, (
            f"these groups are reachable now: {fixed}. Remove them from "
            "KNOWN_UNREACHABLE_GROUPS so the ratchet keeps tightening."
        )

    def test_no_profile_lists_a_group_that_does_not_exist(
        self, registry: ToolRegistry
    ) -> None:
        """A typo'd group name silently widens nothing — catch it here."""
        real = {t.group for t in registry.all_tools()}
        for profile_name, groups in DEFAULT_PROFILES.items():
            unknown = sorted(groups - real - CONDITIONALLY_REGISTERED_GROUPS)
            assert not unknown, (
                f"profile {profile_name!r} lists group(s) no tool uses: "
                f"{unknown}. Either a rename left this behind or it is a typo."
            )

    @pytest.mark.parametrize(
        "tool_name",
        [
            # The action layer and the tiers built on top of it. Each of
            # these shipped unreachable once; pinned so it cannot happen
            # silently again.
            "http_request",
            "gmail",
            "gcal",
            "node_list",
            "node_invoke",
            "panel_review",
            "panel_refine",
            # NOT media_understand: `media` is deliberately outside the
            # planning prompt diet (see test_prompt_diet). It is reachable
            # under `full` and via tool_discover.
            "preference_record",
            "preference_list",
        ],
    )
    def test_key_tools_reach_the_planning_profile(
        self, registry: ToolRegistry, tool_name: str
    ) -> None:
        """`planning` is the agent loop's default — its surface is what the
        model actually sees when deciding what to do."""
        visible = {
            t.name for t in filter_tools_by_profile(registry.all_tools(), "planning")
        }
        assert tool_name in visible, (
            f"{tool_name!r} is not visible under the 'planning' profile, so "
            "the agent loop can never call it."
        )

    def test_planning_stays_below_the_provider_tool_cap(
        self, registry: ToolRegistry
    ) -> None:
        """Some providers hard-cap tools per request; profiles exist to stay
        under it. This is a ceiling, not a target."""
        count = len(filter_tools_by_profile(registry.all_tools(), "planning"))
        assert count < 250, (
            f"the 'planning' profile now offers {count} tools; trim a group "
            "or move something to DEFERRED before providers start rejecting "
            "the request"
        )
