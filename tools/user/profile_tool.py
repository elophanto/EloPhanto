"""User profile view tool: lets the agent check what it knows about the current user."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class UserProfileViewTool(BaseTool):
    """View the current user's profile (role, expertise, preferences)."""

    @property
    def group(self) -> str:
        return "identity"

    def __init__(self) -> None:
        self._user_profile_manager: Any = None  # Injected by agent

    @property
    def name(self) -> str:
        return "user_profile_view"

    @property
    def description(self) -> str:
        return (
            "View what you know about the current user — their role, expertise, "
            "preferences, and past observations. Use this to tailor your responses."
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

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._user_profile_manager:
            return ToolResult(success=False, error="User profile system not configured")

        # Channel/user_id injected at runtime by executor
        channel = params.get("_channel", "cli")
        user_id = params.get("_user_id", "")

        if not user_id:
            return ToolResult(success=False, error="No user context available")

        try:
            profile = await self._user_profile_manager.get_or_create(channel, user_id)
            return ToolResult(
                success=True,
                data={
                    "user_id": profile.user_id,
                    "channel": profile.channel,
                    "display_name": profile.display_name,
                    "role": profile.role,
                    "expertise": profile.expertise,
                    "preferences": profile.preferences,
                    "observations": profile.observations[-10:],
                    "interaction_count": profile.interaction_count,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to load profile: {e}")
