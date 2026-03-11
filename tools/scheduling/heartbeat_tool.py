"""Heartbeat management tool — manage standing orders via chat.

Allows the user (or the agent) to view, add, remove, and clear
standing orders in HEARTBEAT.md without manually editing the file.
Also exposes heartbeat engine status and control (pause/resume/trigger).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class HeartbeatTool(BaseTool):
    """Manage heartbeat standing orders and engine status."""

    def __init__(self) -> None:
        self._heartbeat_engine: Any = None  # Injected by agent
        self._project_root: Path | None = None  # Injected by agent

    @property
    def group(self) -> str:
        return "scheduling"

    @property
    def name(self) -> str:
        return "heartbeat"

    @property
    def description(self) -> str:
        return (
            "Manage heartbeat standing orders (HEARTBEAT.md). "
            "Standing orders run on every heartbeat cycle (default every 30 min) "
            "— they have no per-order timing. "
            "Use this for 'always do X in the background' instructions. "
            "For time-based tasks ('every 2 hours', 'at 9am'), use schedule_task instead. "
            "Actions: add (append order), remove (by number), list, clear, "
            "set (replace all), status (engine info), trigger (run now)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "status",
                        "list",
                        "add",
                        "remove",
                        "clear",
                        "set",
                        "trigger",
                    ],
                    "description": (
                        "Action: status (engine info), list (show orders), "
                        "add (append order), remove (delete by number), "
                        "clear (remove all orders), set (replace all orders), "
                        "trigger (run heartbeat now)"
                    ),
                },
                "order": {
                    "type": "string",
                    "description": "Standing order text (for 'add' action)",
                },
                "orders": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of standing orders (for 'set' action)",
                },
                "number": {
                    "type": "integer",
                    "description": "Order number to remove (for 'remove' action, 1-based)",
                },
            },
            "required": ["action"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        action = params.get("action", "status")
        file_path = self._get_file_path()

        if action == "status":
            return self._status(file_path)
        elif action == "list":
            return self._list_orders(file_path)
        elif action == "add":
            return self._add_order(file_path, params.get("order", ""))
        elif action == "remove":
            return self._remove_order(file_path, params.get("number", 0))
        elif action == "clear":
            return self._clear_orders(file_path)
        elif action == "set":
            return self._set_orders(file_path, params.get("orders", []))
        elif action == "trigger":
            return await self._trigger(file_path)

        return ToolResult(success=False, error=f"Unknown action: {action}")

    # ------------------------------------------------------------------
    # File path resolution
    # ------------------------------------------------------------------

    def _get_file_path(self) -> Path:
        """Resolve HEARTBEAT.md path."""
        if self._heartbeat_engine:
            return self._heartbeat_engine._file_path
        if self._project_root:
            return self._project_root / "HEARTBEAT.md"
        return Path("HEARTBEAT.md")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _status(self, file_path: Path) -> ToolResult:
        """Return heartbeat engine status and file content preview."""
        engine_status = {}
        if self._heartbeat_engine:
            engine_status = self._heartbeat_engine.get_status()

        orders = self._parse_orders(file_path)
        return ToolResult(
            success=True,
            data={
                "engine": engine_status
                or {"running": False, "info": "Engine not initialized"},
                "file_path": str(file_path),
                "file_exists": file_path.exists(),
                "orders_count": len(orders),
                "orders": orders,
            },
        )

    def _list_orders(self, file_path: Path) -> ToolResult:
        """List all current standing orders."""
        orders = self._parse_orders(file_path)
        if not orders:
            return ToolResult(
                success=True,
                data={
                    "orders": [],
                    "message": "No standing orders. Use action 'add' to create one.",
                },
            )
        return ToolResult(
            success=True,
            data={
                "orders": [
                    {"number": i + 1, "text": order} for i, order in enumerate(orders)
                ],
                "total": len(orders),
            },
        )

    def _add_order(self, file_path: Path, order: str) -> ToolResult:
        """Append a new standing order."""
        if not order.strip():
            return ToolResult(success=False, error="Order text is required")

        orders = self._parse_orders(file_path)
        orders.append(order.strip())
        self._write_orders(file_path, orders)

        return ToolResult(
            success=True,
            data={
                "added": order.strip(),
                "total": len(orders),
                "message": f"Added order #{len(orders)}: {order.strip()}",
            },
        )

    def _remove_order(self, file_path: Path, number: int) -> ToolResult:
        """Remove a standing order by number (1-based)."""
        orders = self._parse_orders(file_path)
        if not orders:
            return ToolResult(success=False, error="No standing orders to remove")
        if number < 1 or number > len(orders):
            return ToolResult(
                success=False,
                error=f"Invalid order number {number}. Valid range: 1-{len(orders)}",
            )

        removed = orders.pop(number - 1)
        self._write_orders(file_path, orders)

        return ToolResult(
            success=True,
            data={
                "removed": removed,
                "remaining": len(orders),
                "message": f"Removed order #{number}: {removed}",
            },
        )

    def _clear_orders(self, file_path: Path) -> ToolResult:
        """Clear all standing orders (writes empty template)."""
        self._write_orders(file_path, [])
        return ToolResult(
            success=True,
            data={"message": "All standing orders cleared. Heartbeat will idle."},
        )

    def _set_orders(self, file_path: Path, orders: list[str]) -> ToolResult:
        """Replace all standing orders with a new list."""
        cleaned = [o.strip() for o in orders if o.strip()]
        self._write_orders(file_path, cleaned)
        return ToolResult(
            success=True,
            data={
                "orders": cleaned,
                "total": len(cleaned),
                "message": f"Set {len(cleaned)} standing order(s).",
            },
        )

    async def _trigger(self, file_path: Path) -> ToolResult:
        """Trigger an immediate heartbeat check."""
        if not self._heartbeat_engine:
            return ToolResult(
                success=False,
                error="Heartbeat engine not available. Is heartbeat enabled in config?",
            )

        if not self._heartbeat_engine.is_running:
            return ToolResult(
                success=False,
                error="Heartbeat engine is not running.",
            )

        orders = self._parse_orders(file_path)
        if not orders:
            return ToolResult(
                success=False,
                error="No standing orders to execute. Add orders first.",
            )

        # Schedule the check (don't await — it runs in background)
        import asyncio

        asyncio.create_task(self._heartbeat_engine._check_and_execute())

        return ToolResult(
            success=True,
            data={
                "message": "Heartbeat check triggered. Orders will be executed in background.",
                "orders_count": len(orders),
            },
        )

    # ------------------------------------------------------------------
    # File I/O helpers
    # ------------------------------------------------------------------

    def _parse_orders(self, file_path: Path) -> list[str]:
        """Parse standing orders from HEARTBEAT.md (lines starting with -)."""
        if not file_path.exists():
            return []
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            return []

        orders: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            # Parse lines starting with - (markdown list items)
            if stripped.startswith("- "):
                orders.append(stripped[2:].strip())
            elif stripped.startswith("* "):
                orders.append(stripped[2:].strip())
        return orders

    def _write_orders(self, file_path: Path, orders: list[str]) -> None:
        """Write standing orders to HEARTBEAT.md with template comments."""
        lines = [
            "# Standing Orders",
            "#",
            "# Add tasks below for the agent to execute on each heartbeat cycle.",
            "# The agent checks this file periodically (default: every 30 min).",
            "# When all tasks are done, it responds HEARTBEAT_OK and idles.",
            "# Remove or clear orders to stop background work.",
            "",
        ]

        for order in orders:
            lines.append(f"- {order}")

        # Ensure trailing newline
        lines.append("")

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("\n".join(lines), encoding="utf-8")
