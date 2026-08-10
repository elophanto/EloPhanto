"""Pin knowledge/system/capabilities.md to the live tool registry.

capabilities.md is the agent's self-knowledge: it is injected into
prompts and used for visibility posts, so a stale count there is the
agent believing something false about itself. It drifted badly once
(147 skills when 178 loaded, 49 browser tools when 47 registered, 5 LLM
providers when 7 were configured), which is exactly the silent-doc-drift
failure mode recorded in docs/76-ABE-FRAMEWORK.md.

Every ``## Name — `group` (N)`` heading is checked against the registry,
so adding a tool without updating the doc fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.config import load_config
from core.registry import ToolRegistry
from core.skills import SkillManager

PROJECT_ROOT = Path(__file__).parent.parent.parent
CAPABILITIES = PROJECT_ROOT / "knowledge" / "system" / "capabilities.md"

# "## Browser — `browser` (47)" -> ("browser", 47)
HEADING = re.compile(r"^## .+? — `([a-z_]+)` \((\d+)\)", re.MULTILINE)


@pytest.fixture(scope="module")
def registry_groups() -> dict[str, int]:
    config = load_config(str(PROJECT_ROOT / "config.demo.yaml"))
    registry = ToolRegistry(PROJECT_ROOT)
    registry.load_builtin_tools(config)
    counts: dict[str, int] = {}
    for tool in registry.all_tools():
        group = getattr(tool, "group", "?")
        counts[group] = counts.get(group, 0) + 1
    return counts


@pytest.fixture(scope="module")
def doc() -> str:
    return CAPABILITIES.read_text()


class TestCapabilitiesCounts:
    def test_group_counts_match_registry(
        self, doc: str, registry_groups: dict[str, int]
    ) -> None:
        """Every documented group count equals the registry count."""
        documented = {m.group(1): int(m.group(2)) for m in HEADING.finditer(doc)}
        assert documented, "no '## Name — `group` (N)' headings found"

        wrong = {
            group: (claimed, registry_groups.get(group))
            for group, claimed in documented.items()
            if registry_groups.get(group) != claimed
        }
        assert not wrong, (
            "capabilities.md group counts drifted from the registry "
            f"(group: doc_says, registry_has): {wrong}"
        )

    def test_every_registry_group_is_documented(
        self, doc: str, registry_groups: dict[str, int]
    ) -> None:
        """A new tool group cannot ship undocumented.

        Without this, adding a group silently shrinks the agent's
        self-knowledge while every other assertion still passes.
        """
        documented = {m.group(1) for m in HEADING.finditer(doc)}
        missing = sorted(set(registry_groups) - documented)
        assert not missing, (
            "tool groups missing a '## Name — `group` (N)' section in "
            f"capabilities.md: {missing}"
        )

    def test_total_tool_count_matches(
        self, doc: str, registry_groups: dict[str, int]
    ) -> None:
        total = sum(registry_groups.values())
        assert f"**{total} tools across {len(registry_groups)} groups.**" in doc, (
            f"capabilities.md must state '{total} tools across "
            f"{len(registry_groups)} groups'"
        )

    def test_skill_count_matches(self, doc: str) -> None:
        """The doc counts the skills this repo *ships*, not local installs.

        A developer can symlink a skill into ``skills/`` for their own use —
        the agent loads it, but it is not repo content and must not force a
        doc edit or fail CI, where the symlink does not exist. Symlinked
        entries are therefore excluded from the count on both sides.
        """
        skills_dir = PROJECT_ROOT / "skills"
        loaded = SkillManager(skills_dir).discover()
        symlinked = sum(
            1
            for d in skills_dir.iterdir()
            if d.is_symlink() and (d / "SKILL.md").exists()
        )
        shipped = loaded - symlinked
        assert f"## Skills ({shipped})" in doc, (
            f"capabilities.md must state '## Skills ({shipped})' "
            f"({loaded} loaded, {symlinked} symlinked local install(s) excluded)"
        )

    def test_provider_count_matches(self, doc: str) -> None:
        config = load_config(str(PROJECT_ROOT / "config.demo.yaml"))
        count = len(config.llm.providers)
        assert (
            f"## LLM Providers ({count})" in doc
        ), f"capabilities.md must state '## LLM Providers ({count})'"

    def test_critical_tools_listed(self, registry_groups: dict[str, int]) -> None:
        """The CRITICAL list in capabilities.md is complete.

        The permission spine is the load-bearing safety claim in the
        README; an undocumented CRITICAL tool means the published list
        is wrong.
        """
        config = load_config(str(PROJECT_ROOT / "config.demo.yaml"))
        registry = ToolRegistry(PROJECT_ROOT)
        registry.load_builtin_tools(config)
        critical = {
            t.name
            for t in registry.all_tools()
            if "critical" in str(getattr(t, "permission_level", "")).lower()
        }
        body = CAPABILITIES.read_text()
        missing = sorted(name for name in critical if f"`{name}`" not in body)
        assert not missing, f"CRITICAL tools absent from capabilities.md: {missing}"

        claimed = re.search(r"\*\*(\d+) CRITICAL tools\s*\n?\s*always ask\*\*", body)
        assert claimed, "capabilities.md must state the CRITICAL tool count"
        assert int(claimed.group(1)) == len(critical), (
            f"capabilities.md says {claimed.group(1)} CRITICAL tools, "
            f"registry has {len(critical)}"
        )
