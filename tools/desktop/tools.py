"""Desktop GUI automation tools — pixel-level control of a desktop.

Two modes:
- **local**: controls the host machine directly via pyautogui (no VM needed).
- **remote**: communicates with an OSWorld HTTP server running inside a VM.

The controller is injected by the agent at startup.
"""

from __future__ import annotations

import base64
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

# ---------------------------------------------------------------------------
# Base class for all desktop tools
# ---------------------------------------------------------------------------


class _DesktopTool(BaseTool):
    """Shared base for desktop tools with controller injection slot."""

    def __init__(self) -> None:
        self._desktop_controller: Any = None  # injected by agent

    def _require_controller(self) -> Any:
        if not self._desktop_controller:
            raise RuntimeError("Desktop controller not connected")
        return self._desktop_controller


# ---------------------------------------------------------------------------
# desktop_connect
# ---------------------------------------------------------------------------


class DesktopConnectTool(_DesktopTool):
    """Connect to a desktop — local machine or remote VM."""

    @property
    def name(self) -> str:
        return "desktop_connect"

    @property
    def description(self) -> str:
        return (
            "Connect to a desktop for GUI control. Use mode='local' to control "
            "this machine directly, or mode='remote' with a vm_ip to connect to "
            "a VM running the OSWorld HTTP server."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["local", "remote"],
                    "description": "Connection mode: 'local' for this machine, 'remote' for a VM",
                },
                "vm_ip": {
                    "type": "string",
                    "description": "IP address of the VM (required for remote mode)",
                },
                "port": {
                    "type": "integer",
                    "description": "Server port for remote mode (default 5000)",
                },
            },
            "required": ["mode"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        mode = params["mode"]

        if mode == "local":
            from core.desktop_controller import LocalDesktopController

            ctrl = LocalDesktopController()
            if not await ctrl.ping():
                return ToolResult(
                    success=False,
                    error="pyautogui not available — install with: pip install pyautogui",
                )
            size = await ctrl.screen_size()
            self._desktop_controller = ctrl
            return ToolResult(
                success=True,
                data={
                    "message": "Connected to local desktop",
                    "mode": "local",
                    "screen": size or {"width": "unknown", "height": "unknown"},
                },
            )

        # Remote mode
        from core.desktop_controller import DesktopController

        vm_ip = params.get("vm_ip")
        if not vm_ip:
            return ToolResult(success=False, error="vm_ip is required for remote mode")
        port = params.get("port", 5000)
        ctrl = DesktopController(vm_ip, port)

        if not await ctrl.ping():
            await ctrl.close()
            return ToolResult(
                success=False,
                error=f"Cannot reach desktop server at {vm_ip}:{port}",
            )

        size = await ctrl.screen_size()
        self._desktop_controller = ctrl
        return ToolResult(
            success=True,
            data={
                "message": f"Connected to VM desktop at {vm_ip}:{port}",
                "mode": "remote",
                "screen": size or {"width": "unknown", "height": "unknown"},
            },
        )


# ---------------------------------------------------------------------------
# desktop_screenshot
# ---------------------------------------------------------------------------


class DesktopScreenshotTool(_DesktopTool):
    @property
    def name(self) -> str:
        return "desktop_screenshot"

    @property
    def description(self) -> str:
        return (
            "Capture a screenshot of the desktop. Returns a base64-encoded "
            "PNG image that you can analyze visually to understand the current "
            "screen state before choosing your next action."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        ctrl = self._require_controller()
        b64 = await ctrl.screenshot_base64()
        if not b64:
            return ToolResult(success=False, error="Failed to capture screenshot")
        return ToolResult(
            success=True,
            data={"image_base64": b64, "media_type": "image/png"},
        )


# ---------------------------------------------------------------------------
# desktop_click
# ---------------------------------------------------------------------------


class DesktopClickTool(_DesktopTool):
    @property
    def name(self) -> str:
        return "desktop_click"

    @property
    def description(self) -> str:
        return (
            "Click at a specific x,y coordinate on the desktop. "
            "Supports left, right, and double-click."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate"},
                "y": {"type": "integer", "description": "Y coordinate"},
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "description": "Mouse button (default left)",
                },
                "num_clicks": {
                    "type": "integer",
                    "enum": [1, 2, 3],
                    "description": "Number of clicks (default 1, use 2 for double-click)",
                },
            },
            "required": ["x", "y"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        ctrl = self._require_controller()
        x, y = params["x"], params["y"]
        button = params.get("button", "left")
        clicks = params.get("num_clicks", 1)
        cmd = f"pyautogui.click(x={x}, y={y}, button='{button}', clicks={clicks})"
        result = await ctrl.execute_pyautogui(cmd)
        return ToolResult(
            success=result is not None,
            data={"action": f"click({x},{y})", "result": result or {}},
            error=None if result else "Click command failed",
        )


# ---------------------------------------------------------------------------
# desktop_type
# ---------------------------------------------------------------------------


class DesktopTypeTool(_DesktopTool):
    @property
    def name(self) -> str:
        return "desktop_type"

    @property
    def description(self) -> str:
        return (
            "Type text, press a key, or send a keyboard shortcut on the desktop. "
            "Use 'text' for typing, 'key' for a single keypress, "
            "'hotkey' for key combinations like ctrl+s."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to type (use this for regular text input)",
                },
                "key": {
                    "type": "string",
                    "description": "Single key to press (e.g. 'enter', 'tab', 'escape', 'backspace')",
                },
                "hotkey": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key combination (e.g. ['ctrl', 's'] for Ctrl+S)",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        ctrl = self._require_controller()
        if "text" in params:
            text = params["text"].replace("'", "\\'")
            cmd = f"pyautogui.typewrite('{text}', interval=0.02)"
        elif "key" in params:
            cmd = f"pyautogui.press('{params['key']}')"
        elif "hotkey" in params:
            keys = ", ".join(f"'{k}'" for k in params["hotkey"])
            cmd = f"pyautogui.hotkey({keys})"
        else:
            return ToolResult(
                success=False,
                error="Provide one of: text, key, or hotkey",
            )
        result = await ctrl.execute_pyautogui(cmd)
        return ToolResult(
            success=result is not None,
            data={"action": cmd, "result": result or {}},
            error=None if result else "Type command failed",
        )


# ---------------------------------------------------------------------------
# desktop_scroll
# ---------------------------------------------------------------------------


class DesktopScrollTool(_DesktopTool):
    @property
    def name(self) -> str:
        return "desktop_scroll"

    @property
    def description(self) -> str:
        return "Scroll the mouse wheel on the desktop. Positive = up, negative = down."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "clicks": {
                    "type": "integer",
                    "description": "Number of scroll clicks (positive=up, negative=down)",
                },
                "x": {
                    "type": "integer",
                    "description": "X coordinate to scroll at (optional)",
                },
                "y": {
                    "type": "integer",
                    "description": "Y coordinate to scroll at (optional)",
                },
            },
            "required": ["clicks"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        ctrl = self._require_controller()
        clicks = params["clicks"]
        x = params.get("x")
        y = params.get("y")
        if x is not None and y is not None:
            cmd = f"pyautogui.scroll({clicks}, x={x}, y={y})"
        else:
            cmd = f"pyautogui.scroll({clicks})"
        result = await ctrl.execute_pyautogui(cmd)
        return ToolResult(
            success=result is not None,
            data={"action": cmd, "result": result or {}},
            error=None if result else "Scroll command failed",
        )


# ---------------------------------------------------------------------------
# desktop_drag
# ---------------------------------------------------------------------------


class DesktopDragTool(_DesktopTool):
    @property
    def name(self) -> str:
        return "desktop_drag"

    @property
    def description(self) -> str:
        return (
            "Drag from one position to another on the desktop (left mouse button held)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "start_x": {"type": "integer", "description": "Starting X coordinate"},
                "start_y": {"type": "integer", "description": "Starting Y coordinate"},
                "end_x": {"type": "integer", "description": "Ending X coordinate"},
                "end_y": {"type": "integer", "description": "Ending Y coordinate"},
                "duration": {
                    "type": "number",
                    "description": "Duration of drag in seconds (default 0.5)",
                },
            },
            "required": ["start_x", "start_y", "end_x", "end_y"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        ctrl = self._require_controller()
        sx, sy = params["start_x"], params["start_y"]
        ex, ey = params["end_x"], params["end_y"]
        dur = params.get("duration", 0.5)
        cmd = (
            f"pyautogui.moveTo({sx}, {sy}); "
            f"pyautogui.drag({ex - sx}, {ey - sy}, duration={dur})"
        )
        result = await ctrl.execute_pyautogui(cmd)
        return ToolResult(
            success=result is not None,
            data={"action": f"drag({sx},{sy})->({ex},{ey})", "result": result or {}},
            error=None if result else "Drag command failed",
        )


# ---------------------------------------------------------------------------
# desktop_cursor
# ---------------------------------------------------------------------------


class DesktopCursorTool(_DesktopTool):
    @property
    def name(self) -> str:
        return "desktop_cursor"

    @property
    def description(self) -> str:
        return "Move the mouse cursor to a position without clicking."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate"},
                "y": {"type": "integer", "description": "Y coordinate"},
            },
            "required": ["x", "y"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        ctrl = self._require_controller()
        x, y = params["x"], params["y"]
        cmd = f"pyautogui.moveTo({x}, {y})"
        result = await ctrl.execute_pyautogui(cmd)
        return ToolResult(
            success=result is not None,
            data={"action": f"moveTo({x},{y})", "result": result or {}},
            error=None if result else "Cursor move failed",
        )


# ---------------------------------------------------------------------------
# desktop_shell
# ---------------------------------------------------------------------------


class DesktopShellTool(_DesktopTool):
    @property
    def name(self) -> str:
        return "desktop_shell"

    @property
    def description(self) -> str:
        return (
            "Run a shell command on the desktop target (local machine or VM). "
            "Returns stdout, stderr, and exit code. Use for file operations, "
            "package installation, or system checks."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to run",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 30)",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory (optional)",
                },
            },
            "required": ["command"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        ctrl = self._require_controller()
        result = await ctrl.run_bash(
            script=params["command"],
            timeout=params.get("timeout", 30),
            working_dir=params.get("working_dir"),
        )
        success = result.get("returncode", -1) == 0
        return ToolResult(success=success, data=result)


# ---------------------------------------------------------------------------
# desktop_file
# ---------------------------------------------------------------------------


class DesktopFileTool(_DesktopTool):
    @property
    def name(self) -> str:
        return "desktop_file"

    @property
    def description(self) -> str:
        return (
            "Download a file from the desktop target for inspection. Returns "
            "the file content as base64. Use for checking task outputs, logs, etc."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file on the VM",
                },
            },
            "required": ["path"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        ctrl = self._require_controller()
        data = await ctrl.get_file(params["path"])
        if data is None:
            return ToolResult(success=False, error="Failed to download file")
        b64 = base64.b64encode(data).decode("ascii")
        return ToolResult(
            success=True,
            data={
                "file_base64": b64,
                "size_bytes": len(data),
                "path": params["path"],
            },
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_desktop_tools() -> list[BaseTool]:
    """Create all desktop tool instances.

    The _desktop_controller dependency is injected later by the agent.
    """
    return [
        DesktopConnectTool(),
        DesktopScreenshotTool(),
        DesktopClickTool(),
        DesktopTypeTool(),
        DesktopScrollTool(),
        DesktopDragTool(),
        DesktopCursorTool(),
        DesktopShellTool(),
        DesktopFileTool(),
    ]
