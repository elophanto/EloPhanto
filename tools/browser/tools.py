"""Browser tool classes — 47 tools via Node.js bridge to BrowserPlugin.

All tools are thin wrappers that call browser_manager.call_tool(name, args).
Tool metadata (name, description, schema, permission) is defined statically
so tools can be registered before the browser starts.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class BridgeBrowserTool(BaseTool):
    """Generic bridge-backed browser tool.

    Each instance wraps a single browser tool from the Node.js BrowserPlugin.
    The tool forwards its args to ``browser_manager.call_tool(name, args)``.
    """

    def __init__(
        self,
        tool_name: str,
        tool_description: str,
        tool_schema: dict[str, Any],
        tool_permission: PermissionLevel,
    ) -> None:
        self._name = tool_name
        self._description = tool_description
        self._schema = tool_schema
        self._permission = tool_permission
        self._browser_manager: Any = None  # Injected by agent

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._schema

    @property
    def permission_level(self) -> PermissionLevel:
        return self._permission

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._browser_manager:
            return ToolResult(success=False, error="Browser not available")
        try:
            result = await self._browser_manager.call_tool(self._name, params)
            return ToolResult(success=True, data=result)
        except Exception as e:
            return ToolResult(success=False, error=str(e))


# ------------------------------------------------------------------
# Tool definitions — metadata for all 47 browser tools
# ------------------------------------------------------------------
# Each tuple: (name, description, schema, permission_level)

_TOOL_DEFS: list[tuple[str, str, dict[str, Any], PermissionLevel]] = [
    # --- Navigation ---
    (
        "browser_navigate",
        "Navigate to a URL. Opens Chrome browser if not already open. "
        "Returns the page URL, title, and interactive elements. "
        "Use the element indices with browser_click and browser_type.",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to navigate to"},
            },
            "required": ["url"],
        },
        PermissionLevel.MODERATE,
    ),
    (
        "browser_go_back",
        "Navigate back to previous page.",
        {"type": "object", "properties": {}},
        PermissionLevel.MODERATE,
    ),
    # --- Clicking ---
    (
        "browser_click",
        "Click an element by its index from browser_navigate output. "
        "Indices are shown as [0], [1], [2] etc.",
        {
            "type": "object",
            "properties": {
                "index": {"type": "number", "description": "Element index to click"},
            },
            "required": ["index"],
        },
        PermissionLevel.MODERATE,
    ),
    (
        "browser_click_text",
        "Click an INTERACTIVE element (button, link, input, select, etc.) by matching its visible text "
        "(or aria-label/title). Only matches clickable elements — NOT plain page text. "
        "Use browser_get_elements first to see what's clickable. Use browser_click (by index) when you know the index.",
        {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to match (substring match by default)",
                },
                "exact": {
                    "type": "boolean",
                    "description": "If true, require an exact match (default: false)",
                },
                "caseSensitive": {
                    "type": "boolean",
                    "description": "If true, match case-sensitively (default: false)",
                },
                "nth": {
                    "type": "number",
                    "description": "If multiple matches, pick nth (0-based, default: 0)",
                },
            },
            "required": ["text"],
        },
        PermissionLevel.MODERATE,
    ),
    (
        "browser_click_batch",
        "Click multiple elements in rapid succession within a single tool call. "
        "Use when the page requires clicking several elements quickly. "
        "Each target can be specified by text match or element index.",
        {
            "type": "object",
            "properties": {
                "texts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Array of text labels to click (substring match). Order matters.",
                },
                "indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Array of element indices to click. Order matters.",
                },
                "exact": {
                    "type": "boolean",
                    "description": "Require exact text match (default: false)",
                },
            },
        },
        PermissionLevel.MODERATE,
    ),
    (
        "browser_click_at",
        "Click at specific x,y coordinates on the page. Use for canvas elements or custom widgets.",
        {
            "type": "object",
            "properties": {
                "x": {
                    "type": "number",
                    "description": "X coordinate (pixels from left)",
                },
                "y": {
                    "type": "number",
                    "description": "Y coordinate (pixels from top)",
                },
            },
            "required": ["x", "y"],
        },
        PermissionLevel.MODERATE,
    ),
    # --- Typing & Input ---
    (
        "browser_type",
        "Type text into an input field by its index. Set 'enter' to true to submit forms after typing.",
        {
            "type": "object",
            "properties": {
                "index": {"type": "number", "description": "Input element index"},
                "text": {"type": "string", "description": "Text to type"},
                "enter": {"type": "boolean", "description": "Press Enter after typing"},
            },
            "required": ["index", "text"],
        },
        PermissionLevel.MODERATE,
    ),
    (
        "browser_type_text",
        "Type text using keyboard without targeting a specific element. "
        "Useful when focus is already set or for canvas/custom inputs.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type"},
                "pressEnter": {
                    "type": "boolean",
                    "description": "Press Enter after typing (default: false)",
                },
            },
            "required": ["text"],
        },
        PermissionLevel.MODERATE,
    ),
    (
        "browser_press_key",
        "Press a keyboard key. Use for hotkeys, Enter, Escape, Tab, arrow keys, etc. "
        'Key names follow Playwright conventions (e.g. "Enter", "Escape", "Control+a").',
        {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": 'Key to press (e.g. "Enter", "Escape", "Tab", "Control+c")',
                },
            },
            "required": ["key"],
        },
        PermissionLevel.MODERATE,
    ),
    (
        "browser_select_option",
        "Select an option from a <select> dropdown, or check/uncheck a radio button or checkbox. "
        "Uses Playwright's native APIs which properly trigger framework events.",
        {
            "type": "object",
            "properties": {
                "index": {
                    "type": "number",
                    "description": "Element index from browser_get_elements (preferred)",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector (fallback)",
                },
                "value": {
                    "type": "string",
                    "description": "For <select>: option value or label to select",
                },
                "label": {
                    "type": "string",
                    "description": "For <select>: option label text",
                },
                "checked": {
                    "type": "boolean",
                    "description": "For checkbox: true to check, false to uncheck",
                },
            },
        },
        PermissionLevel.MODERATE,
    ),
    # --- Scrolling ---
    (
        "browser_scroll",
        "Scroll the page up or down.",
        {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down"],
                    "description": "Scroll direction",
                },
                "amount": {
                    "type": "number",
                    "description": "Pixels to scroll (default: 500)",
                },
            },
            "required": ["direction"],
        },
        PermissionLevel.SAFE,
    ),
    (
        "browser_scroll_container",
        "Scroll within a modal, dialog, sidebar, or other scrollable container. "
        "Auto-detects common modal patterns, or you can specify a CSS selector.",
        {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down"],
                    "description": "Scroll direction",
                },
                "amount": {
                    "type": "number",
                    "description": "Pixels to scroll (default: 300)",
                },
                "container": {
                    "type": "string",
                    "description": "CSS selector for the container (auto-detects if omitted)",
                },
            },
            "required": ["direction"],
        },
        PermissionLevel.SAFE,
    ),
    # --- Content extraction ---
    (
        "browser_extract",
        "Extract text content from the current page.",
        {"type": "object", "properties": {}},
        PermissionLevel.SAFE,
    ),
    (
        "browser_read_semantic",
        "High-signal, screen-reader-style compressed page view. Returns headings, landmarks, "
        "form fields, and buttons — LLM-friendly for long/dense pages.",
        {"type": "object", "properties": {}},
        PermissionLevel.SAFE,
    ),
    (
        "browser_screenshot",
        "Take a screenshot of the current page and analyze it. "
        "Returns a detailed description of what's visible. "
        "Use highlight=true to overlay element indices on the screenshot.",
        {
            "type": "object",
            "properties": {
                "highlight": {
                    "type": "boolean",
                    "description": "Overlay element index labels (default: false)",
                },
                "forceVision": {
                    "type": "boolean",
                    "description": "Always run vision analysis (default: false)",
                },
            },
        },
        PermissionLevel.SAFE,
    ),
    # --- Element inspection ---
    (
        "browser_get_elements",
        "Get list of interactive elements on the current page with their indices. "
        "Use showAll=true to see ALL offscreen/hidden elements.",
        {
            "type": "object",
            "properties": {
                "showAll": {
                    "type": "boolean",
                    "description": "Show all offscreen/hidden elements (default: false)",
                },
                "compact": {
                    "type": "boolean",
                    "description": "Compact one-line output (default: false)",
                },
            },
        },
        PermissionLevel.SAFE,
    ),
    (
        "browser_get_html",
        "Get the full HTML source code of the current page. Useful for finding hidden codes in "
        "data-* attributes, meta tags, HTML comments, or script variables.",
        {
            "type": "object",
            "properties": {
                "maxLength": {
                    "type": "number",
                    "description": "Truncate HTML to this length (default: 50000)",
                },
            },
        },
        PermissionLevel.SAFE,
    ),
    (
        "browser_get_element_html",
        "Get the HTML source of a specific element by index. "
        "Useful for inspecting data-* attributes, ARIA labels, or inner HTML.",
        {
            "type": "object",
            "properties": {
                "index": {
                    "type": "number",
                    "description": "Element index from browser_get_elements",
                },
            },
            "required": ["index"],
        },
        PermissionLevel.SAFE,
    ),
    (
        "browser_inspect_element",
        "Inspect an interactive element by index — returns attributes and outerHTML preview. "
        "Use for debugging labels, roles, data-* attributes, and DOM structure.",
        {
            "type": "object",
            "properties": {
                "index": {"type": "number", "description": "Element index to inspect"},
            },
            "required": ["index"],
        },
        PermissionLevel.SAFE,
    ),
    (
        "browser_get_meta",
        "Get page meta tags (name/property/content). Useful for debugging SEO/OG tags and app metadata.",
        {"type": "object", "properties": {}},
        PermissionLevel.SAFE,
    ),
    (
        "browser_get_element_box",
        "Get the bounding box of an element by index. Returns x, y, width, height in viewport pixels.",
        {
            "type": "object",
            "properties": {
                "index": {
                    "type": "number",
                    "description": "Element index from browser_get_elements",
                },
            },
            "required": ["index"],
        },
        PermissionLevel.SAFE,
    ),
    # --- Deep inspection ---
    (
        "browser_read_scripts",
        "Read ALL page scripts (inline + external JS bundles) and search for patterns. "
        "CRITICAL for SPAs/React apps where logic is in bundled JS files.",
        {
            "type": "object",
            "properties": {
                "patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Regex patterns to search for in script content",
                },
                "maxLength": {
                    "type": "number",
                    "description": "Max output characters (default: 15000)",
                },
                "includeInline": {
                    "type": "boolean",
                    "description": "Include inline script content (default: true)",
                },
            },
        },
        PermissionLevel.SAFE,
    ),
    (
        "browser_deep_inspect",
        "Deep DOM inspection — scans ALL elements for hidden data. "
        "Checks data-* attributes, aria-* labels, HTML comments, CSS pseudo-content, hidden elements.",
        {"type": "object", "properties": {}},
        PermissionLevel.SAFE,
    ),
    (
        "browser_extract_hidden_code",
        "Extract hidden codes from the page DOM. Scans for codes in data-* attributes, "
        "aria-label, text content, and dynamically revealed elements.",
        {
            "type": "object",
            "properties": {
                "elementIndex": {
                    "type": "number",
                    "description": "Specific element index to scan",
                },
                "scanAll": {
                    "type": "boolean",
                    "description": "Scan entire page (default: true)",
                },
            },
        },
        PermissionLevel.SAFE,
    ),
    (
        "browser_full_audit",
        "ONE-CALL page audit: runs deep DOM inspection + JS source search + storage + meta + cookies "
        "in parallel. Returns a combined report in a SINGLE tool call, replacing 5+ separate calls.",
        {
            "type": "object",
            "properties": {
                "patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Regex patterns for JS source search",
                },
            },
        },
        PermissionLevel.SAFE,
    ),
    (
        "browser_dom_search",
        "Search the DOM (including non-interactive elements) for text or attribute matches. "
        "Similar to DevTools Elements search (Ctrl+F).",
        {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Substring to search for (case-insensitive)",
                },
                "in": {
                    "type": "string",
                    "enum": ["text", "attributes", "all"],
                    "description": "Where to search (default: all)",
                },
                "includeHidden": {
                    "type": "boolean",
                    "description": "Include hidden elements (default: true)",
                },
                "maxResults": {
                    "type": "number",
                    "description": "Max matches (default: 20)",
                },
                "maxSnippetLength": {
                    "type": "number",
                    "description": "Max snippet chars (default: 240)",
                },
                "includeAllAttributes": {
                    "type": "boolean",
                    "description": "Return all attributes (default: false)",
                },
            },
            "required": ["query"],
        },
        PermissionLevel.SAFE,
    ),
    # --- Console & Network ---
    (
        "browser_get_console",
        "Get recent browser console logs (console.log/warn/error) and page errors.",
        {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "number",
                    "description": "Max entries to return (default: 50)",
                },
                "clear": {
                    "type": "boolean",
                    "description": "Clear logs after returning (default: false)",
                },
                "types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'Filter by types (e.g., ["error","warning","log"])',
                },
            },
        },
        PermissionLevel.SAFE,
    ),
    (
        "browser_get_network",
        "Get recent network request/response log (HAR-like). "
        "Use like DevTools Network to find hidden API responses and redirects.",
        {
            "type": "object",
            "properties": {
                "limit": {"type": "number", "description": "Max records (default: 30)"},
                "clear": {
                    "type": "boolean",
                    "description": "Clear log after returning (default: false)",
                },
                "urlContains": {
                    "type": "string",
                    "description": "Only include URLs containing this substring",
                },
                "onlyErrors": {
                    "type": "boolean",
                    "description": "Only show errors and 4xx/5xx (default: false)",
                },
                "includeHeaders": {
                    "type": "boolean",
                    "description": "Include redacted headers (default: false)",
                },
                "includeResponseBody": {
                    "type": "boolean",
                    "description": "Include truncated response body (default: false)",
                },
                "maxBodyLength": {
                    "type": "number",
                    "description": "Max response body chars (default: 4000)",
                },
            },
        },
        PermissionLevel.SAFE,
    ),
    (
        "browser_get_response_body",
        "Get the response body for a specific network record ID from browser_get_network.",
        {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": 'Network record id (e.g., "net_...")',
                },
                "maxLength": {
                    "type": "number",
                    "description": "Max characters to return (default: 8000)",
                },
            },
            "required": ["id"],
        },
        PermissionLevel.SAFE,
    ),
    # --- Storage & Cookies ---
    (
        "browser_get_storage",
        "Get localStorage/sessionStorage snapshot (keys by default; values optional).",
        {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["local", "session", "all"],
                    "description": "Which storage (default: all)",
                },
                "includeValues": {
                    "type": "boolean",
                    "description": "Include values (default: false)",
                },
                "maxValueLength": {
                    "type": "number",
                    "description": "Max chars per value (default: 200)",
                },
            },
        },
        PermissionLevel.MODERATE,
    ),
    (
        "browser_get_cookies",
        "Get cookies for the current page/domain (names by default; values optional).",
        {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to scope cookies to (defaults to current page)",
                },
                "includeValues": {
                    "type": "boolean",
                    "description": "Include cookie values (default: false)",
                },
                "maxValueLength": {
                    "type": "number",
                    "description": "Max chars per value (default: 120)",
                },
            },
        },
        PermissionLevel.MODERATE,
    ),
    # --- Tabs ---
    (
        "browser_new_tab",
        "Open a new browser tab, optionally navigating to a URL.",
        {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to open in new tab (optional)",
                },
            },
        },
        PermissionLevel.MODERATE,
    ),
    (
        "browser_list_tabs",
        "List all open browser tabs with their URLs and titles.",
        {"type": "object", "properties": {}},
        PermissionLevel.SAFE,
    ),
    (
        "browser_switch_tab",
        "Switch to a different tab by its index number.",
        {
            "type": "object",
            "properties": {
                "index": {"type": "number", "description": "Tab index to switch to"},
            },
            "required": ["index"],
        },
        PermissionLevel.MODERATE,
    ),
    (
        "browser_close_tab",
        "Close a tab by index, or close the current tab if no index provided.",
        {
            "type": "object",
            "properties": {
                "index": {
                    "type": "number",
                    "description": "Tab index to close (optional)",
                },
            },
        },
        PermissionLevel.MODERATE,
    ),
    # --- Hover ---
    (
        "browser_hover",
        "Hover over a specific position on the page. Use for tooltips, dropdown menus, hover-reveal effects.",
        {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "X coordinate to hover over"},
                "y": {"type": "number", "description": "Y coordinate to hover over"},
                "durationMs": {
                    "type": "number",
                    "description": "How long to hover in ms (default: 500)",
                },
            },
            "required": ["x", "y"],
        },
        PermissionLevel.MODERATE,
    ),
    (
        "browser_hover_element",
        "Hover over an interactive element by index from browser_get_elements. "
        "Preferred over browser_hover because it's deterministic (no coordinate guessing).",
        {
            "type": "object",
            "properties": {
                "index": {
                    "type": "number",
                    "description": "Element index from browser_get_elements",
                },
                "durationMs": {
                    "type": "number",
                    "description": "Hover hold duration in ms (default: 1200)",
                },
            },
            "required": ["index"],
        },
        PermissionLevel.MODERATE,
    ),
    # --- Drag & Drop ---
    (
        "browser_drag_drop",
        "Drag an element from one position to another. Supports index-based (preferred) "
        "and coordinate-based dragging. Dispatches both pointer events and HTML5 drag events.",
        {
            "type": "object",
            "properties": {
                "fromIndex": {
                    "type": "number",
                    "description": "Source element index (preferred)",
                },
                "toIndex": {
                    "type": "number",
                    "description": "Target element index (preferred)",
                },
                "fromX": {
                    "type": "number",
                    "description": "Source X coordinate (fallback)",
                },
                "fromY": {
                    "type": "number",
                    "description": "Source Y coordinate (fallback)",
                },
                "toX": {
                    "type": "number",
                    "description": "Target X coordinate (fallback)",
                },
                "toY": {
                    "type": "number",
                    "description": "Target Y coordinate (fallback)",
                },
                "steps": {
                    "type": "number",
                    "description": "Intermediate mouse move steps (default: 10)",
                },
            },
        },
        PermissionLevel.MODERATE,
    ),
    (
        "browser_drag_solve",
        "Deterministic drag-and-drop solver. Scans ALL draggable elements and target slots, "
        "maps them, and executes all drag-drops in one atomic call.",
        {
            "type": "object",
            "properties": {
                "slotSelector": {
                    "type": "string",
                    "description": "CSS selector for target drop slots (auto-detects if omitted)",
                },
                "maxDrops": {
                    "type": "number",
                    "description": "Max drops to execute (default: 20)",
                },
                "strategy": {
                    "type": "string",
                    "enum": ["sequential", "textMatch", "positional"],
                    "description": "Pairing strategy (default: sequential)",
                },
            },
        },
        PermissionLevel.MODERATE,
    ),
    (
        "browser_drag_brute_force",
        "Brute-force drag-and-drop solver. Tries dropping every draggable onto every target. "
        "Use when browser_drag_solve fails.",
        {"type": "object", "properties": {}},
        PermissionLevel.MODERATE,
    ),
    # --- Pointer path (drawing) ---
    (
        "browser_pointer_path",
        "Execute a continuous pointer path (drawing/gesture). Sends real pointer events. "
        "Use for drawing on canvas, gesture recognition, signature pads, sliders.",
        {
            "type": "object",
            "properties": {
                "elementIndex": {
                    "type": "number",
                    "description": "Target element index (optional)",
                },
                "points": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number", "description": "X coordinate"},
                            "y": {"type": "number", "description": "Y coordinate"},
                        },
                        "required": ["x", "y"],
                    },
                    "description": "Ordered waypoints (minimum 2 points)",
                },
                "relative": {
                    "type": "boolean",
                    "description": "If true, points are 0..1 normalized within element box (default: false)",
                },
                "pointerType": {
                    "type": "string",
                    "enum": ["mouse", "touch"],
                    "description": "Pointer type (default: mouse)",
                },
                "durationMs": {
                    "type": "number",
                    "description": "Total path duration in ms (default: 300)",
                },
            },
            "required": ["points"],
        },
        PermissionLevel.MODERATE,
    ),
    # --- Wait ---
    (
        "browser_wait",
        "Wait for a specified time in milliseconds.",
        {
            "type": "object",
            "properties": {
                "ms": {"type": "number", "description": "Milliseconds to wait"},
            },
            "required": ["ms"],
        },
        PermissionLevel.SAFE,
    ),
    (
        "browser_wait_for_selector",
        "Wait for a CSS selector to appear/disappear, or wait for a JS condition to become truthy. "
        "Much more reliable than fixed-ms browser_wait for dynamic content.",
        {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector to wait for",
                },
                "state": {
                    "type": "string",
                    "enum": ["visible", "hidden", "attached"],
                    "description": 'Wait condition (default: "visible")',
                },
                "expression": {
                    "type": "string",
                    "description": "JS expression to wait for (instead of selector)",
                },
                "timeout": {
                    "type": "number",
                    "description": "Max wait time in ms (default: 5000)",
                },
            },
        },
        PermissionLevel.SAFE,
    ),
    # --- JavaScript execution ---
    (
        "browser_eval",
        "Execute JavaScript in the page context (like DevTools console). "
        "Primary use: READ and INSPECT — variables, DOM attributes, storage, computed styles. "
        "Do NOT override validation functions or set innerHTML.",
        {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "JavaScript expression to evaluate",
                },
                "maxLength": {
                    "type": "number",
                    "description": "Max characters of returned JSON (default: 8000)",
                },
            },
            "required": ["expression"],
        },
        PermissionLevel.CRITICAL,
    ),
    (
        "browser_inject",
        "Inject PERSISTENT JavaScript into the page (survives across tool calls). "
        "Use for: setInterval watchers, MutationObservers, event listeners. "
        "Re-injecting the same id replaces the previous script.",
        {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Unique script identifier"},
                "script": {"type": "string", "description": "JavaScript to inject"},
                "maxLength": {
                    "type": "number",
                    "description": "Max returned JSON chars (default: 8000)",
                },
            },
            "required": ["id", "script"],
        },
        PermissionLevel.CRITICAL,
    ),
    # --- Close ---
    (
        "browser_close",
        "Close the browser completely.",
        {"type": "object", "properties": {}},
        PermissionLevel.CRITICAL,
    ),
]


def create_browser_tools() -> list[BridgeBrowserTool]:
    """Create all 47 browser tool instances.

    Returns a list of BridgeBrowserTool instances, each wrapping a single
    browser tool from the BrowserPlugin. The browser_manager dependency
    is injected later by the agent.
    """
    return [
        BridgeBrowserTool(name, description, schema, permission)
        for name, description, schema, permission in _TOOL_DEFS
    ]
