"""update_scratchpad — persistent working memory for the autonomous mind."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class UpdateScratchpadTool(BaseTool):
    """Update the autonomous mind's persistent working memory (scratchpad).

    The scratchpad persists across wakeup cycles. Use it to track:
    - Active projects and their status
    - Revenue pipeline (leads, proposals, deliveries)
    - Blocked items and next steps
    - Ideas and opportunities to investigate
    """

    name = "update_scratchpad"
    description = (
        "Replace the contents of your persistent working memory (scratchpad). "
        "This survives across wakeup cycles. Always update it before finishing "
        "a think cycle to maintain continuity."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Full markdown content for the scratchpad (replaces current)",
            },
        },
        "required": ["content"],
    }
    permission_level = PermissionLevel.SAFE

    # Set by AutonomousMind before use
    _project_root: Path | None = None

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        content = params.get("content", "")
        if not self._project_root:
            return ToolResult(success=False, error="Project root not set")

        path = self._project_root / "data" / "scratchpad.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        return ToolResult(
            success=True,
            data={"length": len(content), "path": str(path)},
        )
