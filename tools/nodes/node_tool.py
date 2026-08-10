"""Tools for invoking capabilities on the operator's companion devices."""

from __future__ import annotations

import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class NodeListTool(BaseTool):
    """List connected companion devices and what they can do."""

    def __init__(self) -> None:
        self._node_registry: Any = None  # injected

    @property
    def name(self) -> str:
        return "node_list"

    @property
    def group(self) -> str:
        return "nodes"

    @property
    def description(self) -> str:
        return (
            "List the operator's connected companion devices (phone, laptop) "
            "and the capabilities each currently permits — camera, screen, "
            "location, speech. Check this before promising anything that needs "
            "a device: a capability the device offers may still be disabled."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._node_registry is None:
            return ToolResult(
                success=True,
                data={
                    "nodes": [],
                    "note": (
                        "Node support is not active — no gateway is running, "
                        "or no companion device has connected."
                    ),
                },
            )
        nodes = self._node_registry.list_nodes()
        for node in nodes:
            node["permitted"] = self._node_registry.permitted_capabilities(
                node["node_id"]
            )
        return ToolResult(success=True, data={"nodes": nodes, "count": len(nodes)})


class NodeInvokeTool(BaseTool):
    """Run a capability on a connected companion device."""

    def __init__(self) -> None:
        self._node_registry: Any = None  # injected

    @property
    def name(self) -> str:
        return "node_invoke"

    @property
    def group(self) -> str:
        return "nodes"

    @property
    def description(self) -> str:
        return (
            "Run a capability on one of the operator's companion devices — "
            "e.g. 'camera.snap', 'screen.snapshot', 'location.get', "
            "'talk.speak'. Use node_list first to see what is connected and "
            "permitted. Capabilities that observe the operator (camera, "
            "screen, microphone, location) always ask before running."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "capability": {
                    "type": "string",
                    "description": "Capability name, e.g. 'camera.snap'.",
                },
                "params": {
                    "type": "object",
                    "description": "Capability-specific parameters.",
                },
                "node_id": {
                    "type": "string",
                    "description": (
                        "Target a specific device. Omit to use the first "
                        "connected device that offers the capability."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "Why this is needed — shown to the operator on the "
                        "approval prompt for sensitive capabilities."
                    ),
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "How long to wait for the device (default 60).",
                },
            },
            "required": ["capability"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    def dynamic_permission_level(
        self, params: dict[str, Any]
    ) -> PermissionLevel | None:
        """Anything that can watch or listen to the operator asks first.

        A phone that can be told to take a photo is a camera in someone's
        pocket; the difference between an assistant and a surveillance
        device is entirely in whether that fires without asking.
        """
        from core.nodes import SENSITIVE_CAPABILITIES

        capability = str(params.get("capability", "") or "")
        if capability in SENSITIVE_CAPABILITIES:
            return PermissionLevel.CRITICAL
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._node_registry is None:
            return ToolResult(
                success=False,
                error=(
                    "Node support is not active. Companion devices connect "
                    "through a running gateway (`elophanto gateway`)."
                ),
            )

        from core.nodes import NodeError

        capability = str(params.get("capability", "") or "").strip()
        if not capability:
            return ToolResult(success=False, error="`capability` is required.")

        try:
            result = await self._node_registry.invoke(
                capability,
                params=dict(params.get("params") or {}),
                node_id=str(params.get("node_id", "") or ""),
                timeout=float(params.get("timeout_seconds") or 60.0),
            )
        except NodeError as exc:
            return ToolResult(success=False, error=str(exc))
        except Exception as exc:
            logger.error("node_invoke %s failed: %s", capability, exc)
            return ToolResult(success=False, error=f"Node invocation failed: {exc}")

        if not result.get("success", False):
            return ToolResult(
                success=False,
                error=result.get("error") or f"{capability} failed on the device.",
                data={"capability": capability},
            )
        return ToolResult(
            success=True,
            data={"capability": capability, **(result.get("result") or {})},
        )
