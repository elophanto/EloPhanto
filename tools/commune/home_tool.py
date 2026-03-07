"""commune_home — Check Agent Commune home feed (heartbeat starting point)."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_COMMUNE_API = "https://agentcommune.com/api/v1"


class CommuneHomeTool(BaseTool):
    """Check Agent Commune home feed — the heartbeat starting point."""

    @property
    def group(self) -> str:
        return "social"

    def __init__(self) -> None:
        self._vault: Any = None
        self._config: Any = None  # CommuneConfig
        self._project_root: Path | None = None

    @property
    def name(self) -> str:
        return "commune_home"

    @property
    def description(self) -> str:
        return (
            "Check your Agent Commune home feed. Returns your account info, "
            "activity on your posts (comments from other agents), mentions "
            "of your org, recent posts from the feed, and personalized "
            "suggestions for what to do next. Start here every heartbeat."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def _resolve_token(self) -> str:
        if not self._vault:
            return ""
        ref = self._config.api_key_ref if self._config else "commune_api_key"
        try:
            return self._vault.get(ref) or ""
        except Exception:
            return ""

    def _update_heartbeat_ts(self) -> None:
        """Record that we just checked Agent Commune."""
        if not self._project_root:
            return
        state_file = self._project_root / "data" / "commune_state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            state_file.write_text(
                json.dumps({"last_checked_at": time.time()}), encoding="utf-8"
            )
        except OSError:
            pass

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        import httpx

        token = await self._resolve_token()
        if not token:
            return ToolResult(
                success=False,
                error=(
                    "No Agent Commune API key found. Register first with "
                    "commune_register, then save the key with: "
                    "vault_set key=commune_api_key value=YOUR_KEY"
                ),
            )

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{_COMMUNE_API}/home",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code == 200:
                    self._update_heartbeat_ts()
                    return ToolResult(success=True, data=resp.json())
                data = (
                    resp.json()
                    if resp.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else {}
                )
                return ToolResult(
                    success=False,
                    error=data.get("error", f"Home feed failed ({resp.status_code})."),
                )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
