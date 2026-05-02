"""kid_spawn — Spawn a sandboxed kid container."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class KidSpawnTool(BaseTool):
    """Spawn a sandboxed kid: a child EloPhanto in a hardened container."""

    @property
    def group(self) -> str:
        return "kids"

    def __init__(self) -> None:
        self._kid_manager: Any = None

    @property
    def name(self) -> str:
        return "kid_spawn"

    @property
    def description(self) -> str:
        return (
            "Spawn a sandboxed kid agent: a child EloPhanto running inside a "
            "hardened container. Safe for dangerous shell commands (rm -rf, "
            "package installs, fork bombs) — they cannot touch the host. "
            "The kid connects back to your gateway as a client. "
            "Default vault scope: empty. Default network: outbound-only. "
            "Use kid_list to see existing kids before spawning a new one."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "purpose": {
                    "type": "string",
                    "description": "What the kid is for. Becomes its identity.",
                },
                "name": {
                    "type": "string",
                    "description": "Optional human-friendly slug (auto-derived if omitted).",
                },
                "vault_scope": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Vault keys to expose to the kid. Empty by default. "
                        "Only grant keys the kid actually needs."
                    ),
                },
                "memory_mb": {
                    "type": "integer",
                    "description": "Memory cap in MB (default from KidConfig).",
                },
                "cpus": {
                    "type": "number",
                    "description": "CPU cap (default from KidConfig).",
                },
                "network": {
                    "type": "string",
                    "enum": ["outbound-only", "none", "host"],
                    "description": (
                        "Network policy. 'host' requires explicit user "
                        "authorization — never default."
                    ),
                },
            },
            "required": ["purpose"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._kid_manager:
            return ToolResult(
                success=False,
                data={},
                error=(
                    "Kid manager not available. Either kids are disabled in "
                    "config (set kids.enabled: true) or no container runtime "
                    "is installed (run `elophanto doctor` for setup help)."
                ),
            )
        purpose = (params.get("purpose") or "").strip()
        if not purpose:
            return ToolResult(success=False, data={}, error="purpose is required")

        try:
            kid = await self._kid_manager.spawn(
                purpose=purpose,
                name=params.get("name"),
                vault_scope=params.get("vault_scope"),
                memory_mb=params.get("memory_mb"),
                cpus=params.get("cpus"),
                network=params.get("network"),
            )
            return ToolResult(
                success=True,
                data={
                    "kid_id": kid.kid_id,
                    "name": kid.name,
                    "image": kid.image,
                    "runtime": kid.runtime,
                    "container_id": kid.container_id,
                    "vault_scope": kid.vault_scope,
                    "message": (
                        f"Kid '{kid.name}' (kid_id={kid.kid_id}) spawned in "
                        f"runtime={kid.runtime}, image={kid.image}. "
                        "Use kid_exec to send tasks; kid_destroy when done."
                    ),
                },
            )
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"Spawn failed: {e}")
