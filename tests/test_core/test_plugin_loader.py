"""Tests for plugin discovery, validation, loading, and hot-reload."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from core.plugin_loader import PluginLoader
from tools.base import BaseTool

# --- Helper: create a valid plugin on disk ---


def _create_plugin(
    plugins_dir: Path,
    name: str = "test_plugin",
    class_name: str = "TestPluginTool",
    perm: str = "safe",
    *,
    valid: bool = True,
) -> Path:
    """Write a minimal valid plugin to plugins_dir/<name>/."""
    plugins_dir.mkdir(parents=True, exist_ok=True)
    # Ensure plugins dir is a Python package
    init_file = plugins_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text("")

    plugin_dir = plugins_dir / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    # Ensure plugin subdir is a Python package
    (plugin_dir / "__init__.py").write_text("")

    # schema.json
    schema = {
        "name": name,
        "description": f"A test plugin called {name}",
        "version": "0.1.0",
        "class_name": class_name,
        "permission_level": perm,
        "dependencies": [],
    }
    (plugin_dir / "schema.json").write_text(json.dumps(schema))

    # plugin.py
    if valid:
        code = f"""\
from tools.base import BaseTool, PermissionLevel, ToolResult
from typing import Any

class {class_name}(BaseTool):
    @property
    def name(self) -> str:
        return "{name}"

    @property
    def description(self) -> str:
        return "Test plugin"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {{"type": "object", "properties": {{}}, "required": []}}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, data={{"hello": "world"}})
"""
    else:
        code = "# broken plugin — not a BaseTool subclass\nclass Foo:\n    pass\n"

    (plugin_dir / "plugin.py").write_text(code)
    return plugin_dir


def _cleanup_plugin_modules() -> None:
    """Remove test plugin entries from sys.modules to avoid import caching."""
    to_remove = [
        key for key in sys.modules if key.startswith("plugins.") and key != "plugins"
    ]
    for key in to_remove:
        del sys.modules[key]
    # Remove the 'plugins' package itself so it can be re-discovered
    # from a different tmp_path location
    sys.modules.pop("plugins", None)


class TestPluginDiscovery:
    def test_discover_empty_dir(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        loader = PluginLoader(plugins_dir, tmp_path)
        assert loader.discover() == []

    def test_discover_skips_underscore_dirs(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _create_plugin(plugins_dir, "_template")
        loader = PluginLoader(plugins_dir, tmp_path)
        assert loader.discover() == []

    def test_discover_skips_dot_dirs(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _create_plugin(plugins_dir, ".hidden")
        loader = PluginLoader(plugins_dir, tmp_path)
        assert loader.discover() == []

    def test_discover_valid_plugin(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _create_plugin(plugins_dir, "my_tool")
        loader = PluginLoader(plugins_dir, tmp_path)
        entries = loader.discover()
        assert len(entries) == 1
        assert entries[0].name == "my_tool"
        assert entries[0].class_name == "TestPluginTool"

    def test_discover_skips_missing_schema(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        d = plugins_dir / "no_schema"
        d.mkdir(parents=True)
        (d / "plugin.py").write_text("pass")
        loader = PluginLoader(plugins_dir, tmp_path)
        assert loader.discover() == []

    def test_discover_skips_missing_plugin_py(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        d = plugins_dir / "no_code"
        d.mkdir(parents=True)
        (d / "schema.json").write_text(
            json.dumps({"name": "x", "class_name": "X", "permission_level": "safe"})
        )
        loader = PluginLoader(plugins_dir, tmp_path)
        assert loader.discover() == []

    def test_discover_nonexistent_dir(self, tmp_path: Path) -> None:
        loader = PluginLoader(tmp_path / "nope", tmp_path)
        assert loader.discover() == []


class TestPluginValidation:
    def test_valid_schema(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _create_plugin(plugins_dir, "ok")
        schema_path = plugins_dir / "ok" / "schema.json"
        loader = PluginLoader(plugins_dir, tmp_path)
        valid, errors = loader.validate_schema(schema_path)
        assert valid is True
        assert errors == []

    def test_missing_required_field(self, tmp_path: Path) -> None:
        schema_path = tmp_path / "schema.json"
        schema_path.write_text(json.dumps({"name": "x"}))
        loader = PluginLoader(tmp_path, tmp_path)
        valid, errors = loader.validate_schema(schema_path)
        assert valid is False
        assert any("class_name" in e for e in errors)

    def test_invalid_permission_level(self, tmp_path: Path) -> None:
        schema_path = tmp_path / "schema.json"
        schema_path.write_text(
            json.dumps(
                {"name": "x", "class_name": "X", "permission_level": "superadmin"}
            )
        )
        loader = PluginLoader(tmp_path, tmp_path)
        valid, errors = loader.validate_schema(schema_path)
        assert valid is False
        assert any("permission_level" in e for e in errors)

    def test_broken_json(self, tmp_path: Path) -> None:
        schema_path = tmp_path / "schema.json"
        schema_path.write_text("{not valid json")
        loader = PluginLoader(tmp_path, tmp_path)
        valid, errors = loader.validate_schema(schema_path)
        assert valid is False
        assert len(errors) == 1


class TestPluginLoading:
    """Tests for loading plugins via importlib.

    Each test cleans up sys.modules to avoid caching from previous tests,
    since each test gets a different tmp_path.
    """

    def setup_method(self) -> None:
        _cleanup_plugin_modules()

    def teardown_method(self) -> None:
        _cleanup_plugin_modules()

    def test_load_valid_plugin(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _create_plugin(plugins_dir, "good_plugin", "GoodPluginTool")
        loader = PluginLoader(plugins_dir, tmp_path)
        entries = loader.discover()
        result = loader.load_plugin(entries[0])
        assert result.success is True
        assert result.tool is not None
        assert isinstance(result.tool, BaseTool)
        assert result.tool.name == "good_plugin"

    def test_load_invalid_class(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _create_plugin(plugins_dir, "bad_plugin", "BadPluginTool", valid=False)
        # Override schema to use correct class name that exists but isn't BaseTool
        schema = {
            "name": "bad_plugin",
            "class_name": "Foo",
            "permission_level": "safe",
        }
        (plugins_dir / "bad_plugin" / "schema.json").write_text(json.dumps(schema))
        loader = PluginLoader(plugins_dir, tmp_path)
        entries = loader.discover()
        result = loader.load_plugin(entries[0])
        assert result.success is False
        assert "not a BaseTool subclass" in (result.error or "")

    def test_load_all(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _create_plugin(plugins_dir, "alpha", "AlphaTool")
        _create_plugin(plugins_dir, "beta", "BetaTool")
        loader = PluginLoader(plugins_dir, tmp_path)
        results = loader.load_all()
        assert len(results) == 2
        assert all(r.success for r in results)

    def test_get_loaded(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _create_plugin(plugins_dir, "tool_x", "ToolXTool")
        loader = PluginLoader(plugins_dir, tmp_path)
        loader.load_all()
        loaded = loader.get_loaded()
        assert "tool_x" in loaded


class TestPluginReload:
    def setup_method(self) -> None:
        _cleanup_plugin_modules()

    def teardown_method(self) -> None:
        _cleanup_plugin_modules()

    def test_reload_not_loaded(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        loader = PluginLoader(plugins_dir, tmp_path)
        result = loader.reload_plugin("nonexistent")
        assert result.success is False
        assert "not previously loaded" in (result.error or "")

    def test_reload_loaded_plugin(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _create_plugin(plugins_dir, "reloadable", "ReloadableTool")
        loader = PluginLoader(plugins_dir, tmp_path)
        loader.load_all()
        result = loader.reload_plugin("reloadable")
        assert result.success is True
        assert result.tool is not None
