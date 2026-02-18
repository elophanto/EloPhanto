"""Plugin discovery, validation, loading, and hot-reload.

Scans the plugins/ directory for valid plugin folders, validates their
schema.json, dynamically imports their modules, and registers tool instances.
"""

from __future__ import annotations

import importlib
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.base import BaseTool

logger = logging.getLogger(__name__)


@dataclass
class PluginManifestEntry:
    """Metadata parsed from a plugin's schema.json."""

    name: str
    description: str
    version: str
    module_path: str
    class_name: str
    permission_level: str
    dependencies: list[str] = field(default_factory=list)
    created_at: str = ""
    plugin_dir: Path = field(default_factory=lambda: Path("."))


@dataclass
class PluginLoadResult:
    """Result of attempting to load a single plugin."""

    name: str
    success: bool
    error: str | None = None
    tool: BaseTool | None = None


class PluginLoader:
    """Discovers, validates, and loads plugins from the plugins/ directory."""

    REQUIRED_SCHEMA_FIELDS = {"name", "class_name", "permission_level"}

    def __init__(self, plugins_dir: Path, project_root: Path) -> None:
        self._plugins_dir = plugins_dir
        self._project_root = project_root
        self._loaded: dict[str, BaseTool] = {}
        self._modules: dict[str, Any] = {}

    def discover(self) -> list[PluginManifestEntry]:
        """Scan plugins/ for directories containing plugin.py + schema.json.

        Skips directories starting with '_' or '.'.
        """
        if not self._plugins_dir.exists():
            return []

        entries: list[PluginManifestEntry] = []
        for child in sorted(self._plugins_dir.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith("_") or child.name.startswith("."):
                continue

            schema_path = child / "schema.json"
            plugin_path = child / "plugin.py"

            if not schema_path.exists() or not plugin_path.exists():
                logger.debug(f"Skipping {child.name}: missing plugin.py or schema.json")
                continue

            valid, errors = self.validate_schema(schema_path)
            if not valid:
                logger.warning(
                    f"Invalid schema for plugin {child.name}: {'; '.join(errors)}"
                )
                continue

            with open(schema_path) as f:
                data = json.load(f)

            entry = PluginManifestEntry(
                name=data["name"],
                description=data.get("description", ""),
                version=data.get("version", "0.1.0"),
                module_path=f"plugins.{child.name}.plugin",
                class_name=data["class_name"],
                permission_level=data["permission_level"],
                dependencies=data.get("dependencies", []),
                created_at=data.get("created_at", ""),
                plugin_dir=child,
            )
            entries.append(entry)

        return entries

    def validate_schema(self, schema_path: Path) -> tuple[bool, list[str]]:
        """Validate a plugin's schema.json has required fields.

        Returns:
            Tuple of (valid, list_of_errors).
        """
        errors: list[str] = []
        try:
            with open(schema_path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            return False, [f"Cannot read schema.json: {e}"]

        if not isinstance(data, dict):
            return False, ["schema.json must be a JSON object"]

        for field_name in self.REQUIRED_SCHEMA_FIELDS:
            if field_name not in data or not data[field_name]:
                errors.append(f"Missing required field: {field_name}")

        valid_levels = {"safe", "moderate", "destructive", "critical"}
        level = data.get("permission_level", "")
        if level and level not in valid_levels:
            errors.append(
                f"Invalid permission_level '{level}', must be one of: {valid_levels}"
            )

        return len(errors) == 0, errors

    def load_plugin(self, entry: PluginManifestEntry) -> PluginLoadResult:
        """Dynamically import a plugin module and instantiate the tool class.

        Validates the class is a BaseTool subclass and the tool name matches.
        """
        try:
            # Ensure project root is on sys.path for imports
            root_str = str(self._project_root)
            if root_str not in sys.path:
                sys.path.insert(0, root_str)

            module = importlib.import_module(entry.module_path)
            self._modules[entry.name] = module

            tool_class = getattr(module, entry.class_name, None)
            if tool_class is None:
                return PluginLoadResult(
                    name=entry.name,
                    success=False,
                    error=f"Class '{entry.class_name}' not found in {entry.module_path}",
                )

            if not (isinstance(tool_class, type) and issubclass(tool_class, BaseTool)):
                return PluginLoadResult(
                    name=entry.name,
                    success=False,
                    error=f"Class '{entry.class_name}' is not a BaseTool subclass",
                )

            tool_instance = tool_class()

            if tool_instance.name != entry.name:
                logger.warning(
                    f"Plugin name mismatch: schema says '{entry.name}', "
                    f"tool reports '{tool_instance.name}'. Using schema name."
                )

            self._loaded[entry.name] = tool_instance
            return PluginLoadResult(name=entry.name, success=True, tool=tool_instance)

        except Exception as e:
            return PluginLoadResult(
                name=entry.name,
                success=False,
                error=f"Failed to load: {e}",
            )

    def load_all(self) -> list[PluginLoadResult]:
        """Discover and load all plugins.

        Returns:
            List of PluginLoadResult for each discovered plugin.
        """
        entries = self.discover()
        results: list[PluginLoadResult] = []
        for entry in entries:
            result = self.load_plugin(entry)
            results.append(result)
        return results

    def reload_plugin(self, name: str) -> PluginLoadResult:
        """Hot-reload a single plugin by name.

        Re-imports the module and re-instantiates the tool class.
        """
        if name not in self._modules:
            return PluginLoadResult(
                name=name,
                success=False,
                error=f"Plugin '{name}' not previously loaded",
            )

        # Find the entry again from schema.json
        plugin_dir = self._plugins_dir / name
        schema_path = plugin_dir / "schema.json"
        if not schema_path.exists():
            return PluginLoadResult(
                name=name, success=False, error="schema.json not found"
            )

        with open(schema_path) as f:
            data = json.load(f)

        entry = PluginManifestEntry(
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "0.1.0"),
            module_path=f"plugins.{name}.plugin",
            class_name=data["class_name"],
            permission_level=data["permission_level"],
            dependencies=data.get("dependencies", []),
            plugin_dir=plugin_dir,
        )

        # Reload the module
        try:
            old_module = self._modules[name]
            module = importlib.reload(old_module)
            self._modules[name] = module

            tool_class = getattr(module, entry.class_name, None)
            if tool_class is None:
                return PluginLoadResult(
                    name=name,
                    success=False,
                    error=f"Class '{entry.class_name}' not found after reload",
                )

            tool_instance = tool_class()
            self._loaded[name] = tool_instance
            return PluginLoadResult(name=name, success=True, tool=tool_instance)

        except Exception as e:
            return PluginLoadResult(
                name=name, success=False, error=f"Reload failed: {e}"
            )

    def get_loaded(self) -> dict[str, BaseTool]:
        """Return all successfully loaded plugin tools."""
        return dict(self._loaded)
