"""auto_resolve_blockers — close the autonomy loop (2026-05-27).

When self_create_plugin builds a new tool OR skill_promote writes a
new SKILL.md, the corresponding missing_tool / missing_skill blocker
in blockers.yaml would otherwise sit open until the operator manually
ran `elophanto strategy blockers resolve`. The auto-resolver scans
every company's blockers and marks closed ones as resolved.

Sweep runs from two sites:
  1. Top of from_buildable_blockers — defensive, every wakeup
  2. Right after self_create_plugin / skill_promote success — immediate
"""

from __future__ import annotations

from core.strategy import Blocker, auto_resolve_blockers, save_blockers


class FakeTool:
    def __init__(self, name: str, group: str = "test") -> None:
        self.name = name
        self.group = group


class FakeRegistry:
    def __init__(self, tools: list[FakeTool]) -> None:
        self._tools = list(tools)

    def all_tools(self) -> list[FakeTool]:
        return list(self._tools)


def _write_skill(project_root, slug: str) -> None:
    p = project_root / "skills" / slug / "SKILL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# {slug}\n", encoding="utf-8")


class TestAutoResolve:
    def test_no_blockers_returns_empty(self, tmp_path) -> None:
        # No data/companies dir exists yet → nothing to sweep
        result = auto_resolve_blockers(tmp_path, registry=FakeRegistry([]))
        assert result == {}

    def test_missing_tool_resolves_when_tool_registered(self, tmp_path) -> None:
        # Seed a missing_tool blocker mentioning `linkedin_post` in the
        # description (the convention the apply tool writes)
        save_blockers(
            tmp_path,
            "co-1",
            [
                Blocker(
                    id="b001",
                    type="missing_tool",
                    description="Strategy needs tool `linkedin_post` — not registered.",
                    affected_tactics=["t5"],
                    resolution_proposal="build",
                    build_method="self_create_plugin",
                ),
            ],
        )
        # Registry now has linkedin_post
        registry = FakeRegistry([FakeTool("linkedin_post", "social")])
        result = auto_resolve_blockers(tmp_path, registry=registry)
        assert result == {"co-1": 1}
        # Verify the blocker is now marked resolved
        from core.strategy import load_blockers

        blockers = load_blockers(tmp_path, "co-1")
        assert len(blockers) == 1
        assert blockers[0].is_resolved()
        assert blockers[0].resolved_by == "auto"
        assert blockers[0].resolved_method == "registry_check"

    def test_missing_tool_stays_open_when_not_registered(self, tmp_path) -> None:
        save_blockers(
            tmp_path,
            "co-1",
            [
                Blocker(
                    id="b001",
                    type="missing_tool",
                    description="Strategy needs tool `linkedin_post` — not registered.",
                    resolution_proposal="build",
                ),
            ],
        )
        # Registry doesn't have linkedin_post
        registry = FakeRegistry([FakeTool("twitter_post", "social")])
        result = auto_resolve_blockers(tmp_path, registry=registry)
        assert result == {}
        from core.strategy import load_blockers

        assert not load_blockers(tmp_path, "co-1")[0].is_resolved()

    def test_missing_skill_resolves_when_skill_installed(self, tmp_path) -> None:
        save_blockers(
            tmp_path,
            "co-1",
            [
                Blocker(
                    id="b002",
                    type="missing_skill",
                    description="Strategy needs skill `linkedin-marketing`.",
                    resolution_proposal="build",
                    build_method="skill_promote",
                ),
            ],
        )
        _write_skill(tmp_path, "linkedin-marketing")
        result = auto_resolve_blockers(tmp_path, registry=FakeRegistry([]))
        assert result == {"co-1": 1}

    def test_already_resolved_skipped(self, tmp_path) -> None:
        b = Blocker(
            id="b001",
            type="missing_tool",
            description="needs tool `linkedin_post`",
            resolution_proposal="build",
        )
        b.resolved_at = "2026-05-26T10:00:00+00:00"
        b.resolved_by = "operator"
        b.resolved_method = "manual"
        save_blockers(tmp_path, "co-1", [b])
        # Tool exists in registry — but blocker was already operator-
        # resolved; don't overwrite the resolution record.
        result = auto_resolve_blockers(
            tmp_path, registry=FakeRegistry([FakeTool("linkedin_post")])
        )
        assert result == {}
        from core.strategy import load_blockers

        assert load_blockers(tmp_path, "co-1")[0].resolved_by == "operator"

    def test_multi_company_sweep(self, tmp_path) -> None:
        save_blockers(
            tmp_path,
            "co-a",
            [
                Blocker(
                    id="ba",
                    type="missing_tool",
                    description="needs `tool_a`",
                    resolution_proposal="build",
                ),
            ],
        )
        save_blockers(
            tmp_path,
            "co-b",
            [
                Blocker(
                    id="bb",
                    type="missing_tool",
                    description="needs `tool_b`",
                    resolution_proposal="build",
                ),
            ],
        )
        registry = FakeRegistry([FakeTool("tool_a"), FakeTool("tool_b")])
        result = auto_resolve_blockers(tmp_path, registry=registry)
        assert result == {"co-a": 1, "co-b": 1}

    def test_other_blocker_types_unaffected(self, tmp_path) -> None:
        save_blockers(
            tmp_path,
            "co-1",
            [
                Blocker(
                    id="vc",
                    type="missing_vault_credential",
                    description="needs vault key `smtp`",
                    resolution_proposal="ask",
                ),
            ],
        )
        # Registry irrelevant for vault blockers; resolver should leave alone
        result = auto_resolve_blockers(
            tmp_path, registry=FakeRegistry([FakeTool("smtp")])
        )
        assert result == {}

    def test_no_registry_no_resolutions_for_tools(self, tmp_path) -> None:
        # Tool blocker but no registry → can't verify → stay open
        save_blockers(
            tmp_path,
            "co-1",
            [
                Blocker(
                    id="b001",
                    type="missing_tool",
                    description="needs tool `x`",
                    resolution_proposal="build",
                ),
            ],
        )
        result = auto_resolve_blockers(tmp_path, registry=None)
        assert result == {}

    def test_none_project_root_safe(self) -> None:
        # Defensive: should not crash with None project_root
        result = auto_resolve_blockers(None, registry=FakeRegistry([]))  # type: ignore[arg-type]
        assert result == {}
