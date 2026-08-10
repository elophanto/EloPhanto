"""Node registry and agent packages.

Nodes: advertising a capability is not the same as being permitted to run
it, and a device that walks out of the room must stop being offered.

Packages: import is inert until confirmed, and a package must never carry
live credentials off the machine that exported it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.nodes import NodeError, NodeRegistry
from core.package import (
    PackageError,
    check_requirements,
    export_package,
    install_package,
    parse_manifest,
)


def _phone(registry: NodeRegistry, node_id: str = "phone-1") -> None:
    registry.register(
        node_id,
        "Petr's iPhone",
        "ios",
        [
            {"name": "camera.snap", "description": "take a photo"},
            {"name": "screen.snapshot", "description": "screenshot"},
            {"name": "battery.status", "description": "battery level"},
        ],
        connection=object(),
    )


class TestNodePermissions:
    def test_non_sensitive_capabilities_are_permitted_by_default(self) -> None:
        registry = NodeRegistry()
        _phone(registry)
        assert "battery.status" in registry.permitted_capabilities("phone-1")

    def test_sensitive_capabilities_need_explicit_opt_in(self) -> None:
        registry = NodeRegistry()
        _phone(registry)
        permitted = registry.permitted_capabilities("phone-1")
        assert "camera.snap" not in permitted
        assert "screen.snapshot" not in permitted

    def test_opt_in_permits_only_what_was_listed(self) -> None:
        registry = NodeRegistry(allowed={"phone-1": ["camera.snap"]})
        _phone(registry)
        permitted = registry.permitted_capabilities("phone-1")
        assert "camera.snap" in permitted
        assert "screen.snapshot" not in permitted

    def test_wildcard_node_key_applies_to_all_devices(self) -> None:
        registry = NodeRegistry(allowed={"*": ["camera.snap"]})
        _phone(registry, "phone-2")
        assert "camera.snap" in registry.permitted_capabilities("phone-2")

    def test_advertising_a_capability_does_not_grant_it(self) -> None:
        """A device claiming shell.run must not thereby get shell.run."""
        registry = NodeRegistry()
        registry.register(
            "rogue",
            "Rogue device",
            "linux",
            [{"name": "shell.run"}],
            connection=object(),
        )
        assert "shell.run" not in registry.permitted_capabilities("rogue")


class TestNodeInvocation:
    @pytest.mark.asyncio
    async def test_unpermitted_capability_refused(self) -> None:
        registry = NodeRegistry()
        _phone(registry)
        with pytest.raises(NodeError, match="sensitive capability"):
            await registry.invoke("camera.snap", node_id="phone-1")

    @pytest.mark.asyncio
    async def test_unknown_capability_lists_what_exists(self) -> None:
        registry = NodeRegistry()
        _phone(registry)
        with pytest.raises(NodeError, match="does not offer"):
            await registry.invoke("mic.record", node_id="phone-1")

    @pytest.mark.asyncio
    async def test_no_connected_node_says_so(self) -> None:
        registry = NodeRegistry()
        with pytest.raises(NodeError, match="No nodes are connected"):
            await registry.invoke("camera.snap")


class TestNodeLifecycle:
    def test_disconnect_removes_the_devices_on_that_connection(self) -> None:
        registry = NodeRegistry()
        connection = object()
        registry.register("a", "A", "ios", [{"name": "x"}], connection=connection)
        registry.register("b", "B", "ios", [{"name": "x"}], connection=object())

        gone = registry.unregister_connection(connection)
        assert gone == ["a"]
        assert registry.get("a") is None
        assert registry.get("b") is not None

    def test_find_node_skips_devices_lacking_permission(self) -> None:
        registry = NodeRegistry()
        _phone(registry)
        assert registry.find_node_for("camera.snap") is None
        assert registry.find_node_for("battery.status") is not None

    def test_resolve_unknown_request_is_a_no_op(self) -> None:
        assert NodeRegistry().resolve_result("nope", {}) is False


class TestPackages:
    def test_export_writes_a_parseable_manifest(self, tmp_path: Path) -> None:
        source = tmp_path / "project"
        (source / "skills" / "demo-skill").mkdir(parents=True)
        (source / "skills" / "demo-skill" / "SKILL.md").write_text(
            "---\ndescription: demo\n---\n\n## Description\n\ndemo\n",
            encoding="utf-8",
        )

        out = tmp_path / "pkg"
        export_package(
            out,
            name="demo",
            version="1.2.3",
            author="Petr Royce",
            skills=["demo-skill"],
            required_credentials=["gmail"],
            project_root=source,
        )

        pkg = parse_manifest(out)
        assert pkg.name == "demo"
        assert pkg.version == "1.2.3"
        assert pkg.skills == ["demo-skill"]
        assert pkg.required_credentials == ["gmail"]

    def test_export_never_carries_secrets(self, tmp_path: Path) -> None:
        """Only the *names* of needed credentials travel, never values."""
        out = tmp_path / "pkg"
        export_package(
            out,
            name="demo",
            required_credentials=["gym_token"],
            project_root=tmp_path,
        )
        text = (out / "PHANTO.md").read_text(encoding="utf-8")
        assert "gym_token" in text
        assert "vault" not in text.lower()

    def test_missing_manifest_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(PackageError, match="No PHANTO.md"):
            parse_manifest(tmp_path)

    def test_manifest_without_frontmatter_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "PHANTO.md").write_text("just prose", encoding="utf-8")
        with pytest.raises(PackageError, match="frontmatter"):
            parse_manifest(tmp_path)

    def test_bad_version_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "PHANTO.md").write_text(
            "---\nname: x\nversion: not-semver\n---\n\nbody\n", encoding="utf-8"
        )
        with pytest.raises(PackageError, match="semver"):
            parse_manifest(tmp_path)

    def test_requirements_check_reports_gaps(self, tmp_path: Path) -> None:
        (tmp_path / "PHANTO.md").write_text(
            "---\nname: x\nrequires:\n  tools: [http_request, nonexistent_tool]\n"
            "  credentials: [gmail]\n---\n\nbody\n",
            encoding="utf-8",
        )
        pkg = parse_manifest(tmp_path)
        missing = check_requirements(
            pkg,
            available_tools={"http_request"},
            available_credentials=set(),
        )
        assert missing["tools"] == ["nonexistent_tool"]
        assert missing["credentials"] == ["gmail"]

    def test_dry_run_changes_nothing_on_disk(self, tmp_path: Path) -> None:
        source = tmp_path / "project"
        (source / "skills" / "s1").mkdir(parents=True)
        (source / "skills" / "s1" / "SKILL.md").write_text("x", encoding="utf-8")
        out = tmp_path / "pkg"
        export_package(out, name="demo", skills=["s1"], project_root=source)

        target = tmp_path / "target"
        target.mkdir()
        report = install_package(parse_manifest(out), project_root=target, dry_run=True)
        assert report["skills_installed"] == ["s1"]
        assert not (target / "skills" / "s1").exists()

    def test_install_copies_skills_and_records_the_package(
        self, tmp_path: Path
    ) -> None:
        source = tmp_path / "project"
        (source / "skills" / "s1").mkdir(parents=True)
        (source / "skills" / "s1" / "SKILL.md").write_text("x", encoding="utf-8")
        out = tmp_path / "pkg"
        export_package(out, name="demo", skills=["s1"], project_root=source)

        target = tmp_path / "target"
        target.mkdir()
        install_package(parse_manifest(out), project_root=target)
        assert (target / "skills" / "s1" / "SKILL.md").exists()
        assert (target / "data" / "installed_packages.json").exists()

    def test_mcp_and_schedules_are_reported_not_applied(self, tmp_path: Path) -> None:
        """Both execute code, so import must not arm them silently."""
        (tmp_path / "PHANTO.md").write_text(
            "---\nname: x\nmcp_servers:\n  linear: {command: linear-mcp}\n"
            "schedules:\n  - {name: brief, cron: '0 8 * * *', goal: 'Summarise'}\n"
            "---\n\nbody\n",
            encoding="utf-8",
        )
        pkg = parse_manifest(tmp_path)
        target = tmp_path / "target"
        target.mkdir()
        report = install_package(pkg, project_root=target, dry_run=True)
        assert report["mcp_servers_to_add"] == ["linear"]
        assert len(report["schedules_to_create"]) == 1
