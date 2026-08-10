"""Tools for reading and writing the operator's standing preferences."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class PreferenceRecordTool(BaseTool):
    """Record a durable instruction the operator has given."""

    def __init__(self) -> None:
        self._preference_store: Any = None  # injected
        self._current_user_key: str = "cli:default"

    @property
    def name(self) -> str:
        return "preference_record"

    @property
    def group(self) -> str:
        return "identity"

    @property
    def description(self) -> str:
        return (
            "Record a standing instruction the user has given you ('always X', "
            "'never Y', 'I prefer Z'). Use this the moment they state a rule "
            "that should outlive this conversation — it is injected into every "
            "future turn. A new directive on the same subject automatically "
            "supersedes the old one, so record the correction rather than "
            "worrying about the contradiction."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "directive": {
                    "type": "string",
                    "description": (
                        "The instruction, in the user's own terms, e.g. "
                        "'never push to main without asking'."
                    ),
                },
                "kind": {
                    "type": "string",
                    "description": "always | never | preference | fact (inferred if omitted).",
                },
                "inferred": {
                    "type": "boolean",
                    "description": (
                        "True if you inferred this from behaviour rather than "
                        "the user stating it. Inferred preferences are marked "
                        "as such so you know to confirm before relying on them."
                    ),
                },
            },
            "required": ["directive"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._preference_store is None:
            return ToolResult(success=False, error="Preference store is not available.")
        from core.preferences import Provenance

        directive = str(params.get("directive", "") or "").strip()
        if not directive:
            return ToolResult(success=False, error="`directive` is required.")

        provenance = Provenance.AGENT if params.get("inferred") else Provenance.OWNER
        try:
            pref_id = await self._preference_store.record(
                self._current_user_key,
                directive,
                kind=params.get("kind") or None,
                provenance=provenance,
                evidence="recorded via preference_record",
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Could not record: {exc}")

        return ToolResult(
            success=True,
            data={
                "id": pref_id,
                "directive": directive,
                "provenance": str(provenance),
                "note": "Any previous directive on this subject was superseded.",
            },
        )


class PreferenceListTool(BaseTool):
    """List the operator's active standing preferences."""

    def __init__(self) -> None:
        self._preference_store: Any = None  # injected
        self._current_user_key: str = "cli:default"

    @property
    def name(self) -> str:
        return "preference_list"

    @property
    def group(self) -> str:
        return "identity"

    @property
    def description(self) -> str:
        return (
            "List the standing instructions currently in force for this user, "
            "including which were stated versus inferred. Use it when the user "
            "asks what you remember about how they want things done."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "Optional topic key — returns the full history for that "
                        "subject, including superseded directives."
                    ),
                }
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._preference_store is None:
            return ToolResult(success=False, error="Preference store is not available.")
        topic = str(params.get("topic", "") or "").strip()
        try:
            if topic:
                prefs = await self._preference_store.history(
                    self._current_user_key, topic
                )
            else:
                prefs = await self._preference_store.active(self._current_user_key)
        except Exception as exc:
            return ToolResult(success=False, error=f"Could not read: {exc}")

        return ToolResult(
            success=True,
            data={
                "preferences": [
                    {
                        "id": p.id,
                        "directive": p.directive,
                        "kind": p.kind,
                        "provenance": p.provenance,
                        "status": p.status,
                        "topic": p.topic,
                        "created_at": p.created_at,
                    }
                    for p in prefs
                ],
                "count": len(prefs),
            },
        )
