"""Desktop GUI automation tools — pixel-level control of a desktop.

Two modes:
- **local**: controls the host machine directly via pyautogui (no VM needed).
- **remote**: communicates with an OSWorld HTTP server running inside a VM.

The controller is injected by the agent at startup.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)

from tools.base import BaseTool, PermissionLevel, ToolResult

# ---------------------------------------------------------------------------
# Base class for all desktop tools
# ---------------------------------------------------------------------------


class _DesktopTool(BaseTool):
    """Shared base for desktop tools with controller injection slot."""

    @property
    def group(self) -> str:
        return "desktop"

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
        from core.desktop_controller import BaseDesktopController

        mode = params["mode"]
        ctrl: BaseDesktopController

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
# desktop_osascript (macOS only)
# ---------------------------------------------------------------------------


class DesktopOsascriptTool(_DesktopTool):
    @property
    def name(self) -> str:
        return "desktop_osascript"

    @property
    def description(self) -> str:
        return (
            "Run an AppleScript command on macOS. Use this to control apps like "
            "Microsoft Word, Excel, Pages, Finder, Safari, and System Events "
            "directly via their scripting dictionaries. This is MUCH faster and "
            "more reliable than screenshot-based clicking. Examples:\n"
            '- Open app: tell application "Microsoft Word" to activate\n'
            '- New doc: tell application "Microsoft Word" to make new document\n'
            '- Insert text: tell application "Microsoft Word" to insert text '
            '"Hello" at selection\n'
            '- Save: tell application "Microsoft Word" to save active document\n'
            '- Dismiss dialog: tell application "System Events" to key code 53'
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "AppleScript code to execute",
                },
            },
            "required": ["script"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if sys.platform != "darwin":
            return ToolResult(
                success=False,
                error="desktop_osascript is only available on macOS",
            )
        script = params["script"]
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            out = stdout.decode(errors="replace").strip()
            err = stderr.decode(errors="replace").strip()
            if proc.returncode == 0:
                return ToolResult(
                    success=True,
                    data={"output": out or "(no output)"},
                )
            return ToolResult(
                success=False,
                error=f"osascript failed (exit {proc.returncode}): {err or out}",
            )
        except TimeoutError:
            return ToolResult(success=False, error="osascript timed out (30s)")
        except Exception as e:
            return ToolResult(success=False, error=f"osascript error: {e}")


# ---------------------------------------------------------------------------
# desktop_accessibility (macOS only)
# ---------------------------------------------------------------------------

_A11Y_SCRIPT = """\
on run argv
    set appName to "%APP_NAME%"
    tell application "System Events"
        set targetProcess to first process whose frontmost is true
        if appName is not "" then
            try
                set targetProcess to process appName
            end try
        end if
        set procName to name of targetProcess
        set output to "App: " & procName & linefeed
        set winList to windows of targetProcess
        repeat with w in winList
            set output to output & "Window: " & (name of w) & linefeed
            try
                set uiElems to entire contents of w
                set elemCount to 0
                repeat with elem in uiElems
                    if elemCount > 150 then
                        set output to output & "  [truncated — too many elements]" & linefeed
                        exit repeat
                    end if
                    try
                        set r to role of elem
                        set d to description of elem
                        set t to ""
                        try
                            set t to value of elem
                        end try
                        set tl to ""
                        try
                            set tl to title of elem
                        end try
                        set p to ""
                        try
                            set p to position of elem as text
                        end try
                        if tl is not "" or d is not "" or t is not "" then
                            set line_ to "  [" & r & "]"
                            if tl is not "" then set line_ to line_ & " title=" & tl
                            if d is not "" then set line_ to line_ & " desc=" & d
                            if t is not "" and (length of t) < 200 then set line_ to line_ & " value=" & t
                            if p is not "" then set line_ to line_ & " pos=" & p
                            set output to output & line_ & linefeed
                        end if
                    end try
                    set elemCount to elemCount + 1
                end repeat
            on error errMsg
                set output to output & "  [error reading elements: " & errMsg & "]" & linefeed
            end try
        end repeat
    end tell
    return output
end run
"""


class DesktopAccessibilityTool(_DesktopTool):
    @property
    def name(self) -> str:
        return "desktop_accessibility"

    @property
    def description(self) -> str:
        return (
            "Query the macOS accessibility tree to get a structured list of "
            "UI elements (windows, buttons, menus, text fields) with their "
            "labels and positions. Much cheaper than a screenshot — use this "
            "to find elements before clicking, or to verify state changes. "
            "Works only on macOS in local mode."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": (
                        "Name of the app to inspect (e.g. 'Microsoft Word'). "
                        "If omitted, inspects the frontmost app."
                    ),
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if sys.platform != "darwin":
            return ToolResult(
                success=False,
                error="desktop_accessibility is only available on macOS",
            )
        app_name = params.get("app_name", "")
        script = _A11Y_SCRIPT.replace("%APP_NAME%", app_name)
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            out = stdout.decode(errors="replace").strip()
            err = stderr.decode(errors="replace").strip()
            if proc.returncode == 0 and out:
                return ToolResult(success=True, data={"tree": out})
            return ToolResult(
                success=False,
                error=f"accessibility query failed: {err or 'empty response'}",
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                error="accessibility query timed out (15s)",
            )
        except Exception as e:
            return ToolResult(success=False, error=f"accessibility error: {e}")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_desktop_tools() -> list[BaseTool]:
    """Create all desktop tool instances.

    The _desktop_controller dependency is injected later by the agent.
    """
    tools: list[BaseTool] = [
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
    # macOS-only tools
    if sys.platform == "darwin":
        tools.append(DesktopOsascriptTool())
        tools.append(DesktopAccessibilityTool())
    return tools
