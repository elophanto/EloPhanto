"""Capability audit synthesis (ABE Phase 11)."""

from __future__ import annotations

from core.capability_audit import (
    collect_capabilities,
    render_capabilities_md,
    write_capabilities_md,
)


class FakeTool:
    def __init__(self, name: str, group: str) -> None:
        self.name = name
        self.group = group


class FakeRegistry:
    def __init__(self, tools: list[FakeTool]) -> None:
        self._tools = tools

    def all_tools(self) -> list[FakeTool]:
        return self._tools


class FakeVault:
    def __init__(self, keys: list[str], *, raise_on_list: bool = False) -> None:
        self._keys = keys
        self._raise = raise_on_list

    def list_keys(self) -> list[str]:
        if self._raise:
            raise RuntimeError("vault locked")
        return list(self._keys)


def _write_skill(path, slug: str) -> None:
    sk = path / "skills" / slug / "SKILL.md"
    sk.parent.mkdir(parents=True, exist_ok=True)
    sk.write_text("---\nname: " + slug + "\n---\n# " + slug, encoding="utf-8")


class TestCollect:
    def test_all_empty(self) -> None:
        cap = collect_capabilities()
        assert cap.vault_keys == []
        assert cap.vault_locked is True  # no vault provided
        assert cap.tools_by_group == {}
        assert cap.skills == []

    def test_vault_locked_when_list_fails(self) -> None:
        cap = collect_capabilities(vault=FakeVault([], raise_on_list=True))
        assert cap.vault_locked is True
        assert cap.vault_keys == []

    def test_tools_grouped(self) -> None:
        registry = FakeRegistry(
            [
                FakeTool("email_send", "email"),
                FakeTool("email_reply", "email"),
                FakeTool("twitter_post", "social"),
                FakeTool("prospect_search", "prospecting"),
            ]
        )
        cap = collect_capabilities(registry=registry)
        assert cap.tools_by_group["email"] == ["email_reply", "email_send"]
        assert cap.tools_by_group["social"] == ["twitter_post"]
        assert "prospect_search" in cap.tools_by_group["prospecting"]

    def test_vault_unlocked(self) -> None:
        cap = collect_capabilities(vault=FakeVault(["smtp", "twitter"]))
        assert cap.vault_locked is False
        assert cap.vault_keys == ["smtp", "twitter"]

    def test_skills_walk(self, tmp_path) -> None:
        _write_skill(tmp_path, "voice-foundations")
        _write_skill(tmp_path, "b2c-marketing")
        # A dir without SKILL.md is ignored
        (tmp_path / "skills" / "empty").mkdir(parents=True)
        cap = collect_capabilities(project_root=tmp_path)
        assert cap.skills == ["b2c-marketing", "voice-foundations"]


class TestMembership:
    def test_helpers(self) -> None:
        cap = collect_capabilities(
            registry=FakeRegistry([FakeTool("x", "g")]),
            vault=FakeVault(["k"]),
        )
        assert cap.has_vault_key("k") is True
        assert cap.has_vault_key("missing") is False
        assert cap.has_tool("x") is True
        assert cap.has_tool("y") is False
        assert cap.has_skill("anything") is False


class TestRender:
    def test_renders_with_data(self, tmp_path) -> None:
        cap = collect_capabilities(
            registry=FakeRegistry([FakeTool("email_send", "email")]),
            vault=FakeVault(["smtp"]),
            project_root=tmp_path,
        )
        md = render_capabilities_md(cap, company_id="co")
        assert "# Capabilities — co" in md
        assert "`smtp`" in md
        assert "email_send" in md

    def test_renders_when_locked(self) -> None:
        cap = collect_capabilities()
        md = render_capabilities_md(cap, company_id="co")
        assert "Vault is locked" in md
        assert "No tools registered" in md

    def test_write_markdown(self, tmp_path) -> None:
        cap = collect_capabilities()
        path = write_capabilities_md(cap, tmp_path, "co")
        assert path.is_file()
        assert "Capabilities" in path.read_text()
