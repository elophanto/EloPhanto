"""agent_discover — Find peer agents on networks you can reach (Tailscale)."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class AgentDiscoverTool(BaseTool):
    """Enumerate candidate peer agents reachable from this host."""

    @property
    def group(self) -> str:
        return "agent_identity"

    def __init__(self) -> None:
        # No external manager dependency — calls discover_peers() directly.
        # Kept here for parity with the other tools' constructor shape.
        pass

    @property
    def name(self) -> str:
        return "agent_discover"

    @property
    def description(self) -> str:
        return (
            "Find peer EloPhanto agents reachable on your networks. "
            "v1 backend: Tailscale (calls `tailscale status --json` and "
            "probes each peer's /capabilities endpoint). Returns candidate "
            "URLs; no automatic connection. Pair with agent_connect to "
            "actually open a verified session. Set tagged_only=true to "
            "only return peers explicitly tagged 'tag:elophanto-agent' "
            "in your tailnet ACLs (highest signal, zero false positives). "
            "Returns empty list if Tailscale isn't installed or running."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["tailscale"],
                    "description": "Discovery backend (only 'tailscale' in v1).",
                },
                "tagged_only": {
                    "type": "boolean",
                    "description": (
                        "Only return Tailscale peers with the "
                        "'tag:elophanto-agent' ACL tag. Default false "
                        "(returns all peers + probes /capabilities)."
                    ),
                },
                "probe": {
                    "type": "boolean",
                    "description": (
                        "When true (default), HTTP-probe each peer's "
                        "/capabilities endpoint to confirm it's an "
                        "EloPhanto. When false, return all reachable "
                        "tailnet peers as candidates without verification."
                    ),
                },
                "port": {
                    "type": "integer",
                    "description": "Gateway port to probe. Default 18789.",
                },
            },
            "required": [],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        from core.peer_discovery import (
            discover_peers,
            is_tailscale_available,
        )

        method = (params.get("method") or "tailscale").strip()
        if method == "tailscale" and not is_tailscale_available():
            return ToolResult(
                success=False,
                data={"available_backends": []},
                error=(
                    "Tailscale CLI not found. Install Tailscale "
                    "(https://tailscale.com/download), join your tailnet, "
                    "then retry. mDNS / registry backends will come in v2."
                ),
            )
        try:
            peers = await discover_peers(
                method=method,
                port=int(params.get("port") or 18789),
                probe=bool(params.get("probe", True)),
                tagged_only=bool(params.get("tagged_only", False)),
            )
            return ToolResult(
                success=True,
                data={
                    "method": method,
                    "count": len(peers),
                    "peers": [
                        {
                            "hostname": p.hostname,
                            "address": p.address,
                            "url": p.url,
                            "method": p.method,
                            "tagged": p.tagged,
                            "capabilities": p.capabilities,
                        }
                        for p in peers
                    ],
                    "next_step": (
                        "Use agent_connect(url=<peer.url>) to open a verified "
                        "session, then agent_message(agent_id, content)."
                    ),
                },
            )
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"Discovery failed: {e}")
