"""Tool base class and interface definition.

Every tool in EloPhanto -- built-in or self-created -- must inherit from BaseTool
and implement the required interface.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    # Imported only for type hints — kept under TYPE_CHECKING to
    # avoid the circular import that would otherwise happen because
    # core/task_resources.py imports nothing from tools, and we want
    # to keep it that way.
    from core.task_resources import TaskResource


class PermissionLevel(StrEnum):
    SAFE = "safe"
    MODERATE = "moderate"
    DESTRUCTIVE = "destructive"
    CRITICAL = "critical"


class ToolTier(StrEnum):
    """Loading tier for deferred tool loading.

    CORE (tier 0) — always sent to the LLM.
    PROFILE (tier 1) — sent when the tool's group matches the task profile.
    DEFERRED (tier 2) — only sent after explicit discovery via tool_discover.
    """

    CORE = "core"
    PROFILE = "profile"
    DEFERRED = "deferred"


@dataclass
class ToolResult:
    """Standardized result from tool execution."""

    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"success": self.success}
        if isinstance(self.data, dict):
            result.update(self.data)
        else:
            result["data"] = self.data
        if self.error:
            result["error"] = self.error
        return result


class BaseTool(abc.ABC):
    """Abstract base class for all EloPhanto tools."""

    _tier_override: ToolTier | None = None

    # Resources this tool contends for. Read by the executor before
    # invocation to acquire the right semaphores. Default empty —
    # tools with no real contention (pure-API, knowledge_search, etc.)
    # need no protection. Tools that touch Chrome must declare
    # ``frozenset({TaskResource.BROWSER})``; desktop tools declare
    # DESKTOP; vault writers declare VAULT_WRITE; LLM-heavy tools
    # that should count toward the soft cap declare LLM_BURST.
    #
    # BROWSER and DESKTOP are *session-lazy*: the executor acquires
    # them on first use within an ``agent.run()`` call and holds them
    # for the rest of that run — multi-step browser workflows
    # (twitter_post, reddit posting, research loops) stay coherent
    # because Chrome doesn't get navigated away by another session
    # between the LLM's tool calls. Other tools declared as needing
    # those resources reuse the existing hold without re-acquiring.
    #
    # VAULT_WRITE and LLM_BURST are *per-call*: acquired around each
    # invocation, released after. They have no state continuity
    # requirement across calls.
    #
    # Forward-reference annotation keeps tools/base.py independent of
    # core/task_resources.py (no import cycle).
    resources: ClassVar[frozenset[TaskResource]] = frozenset()

    @property
    def tier(self) -> ToolTier:
        """Loading tier for deferred tool loading. Default: PROFILE (tier 1).

        The registry may set ``_tier_override`` to change the tier after
        construction without requiring each tool class to declare it.
        """
        if self._tier_override is not None:
            return self._tier_override
        return ToolTier.PROFILE

    @property
    def group(self) -> str:
        """Tool group for profile-based filtering (e.g. 'system', 'browser')."""
        return "system"

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique snake_case identifier."""
        ...

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """Natural language description for LLM tool selection."""
        ...

    @property
    @abc.abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for input parameters."""
        ...

    @property
    def output_schema(self) -> dict[str, Any]:
        """JSON Schema for output format."""
        return {"type": "object"}

    @property
    @abc.abstractmethod
    def permission_level(self) -> PermissionLevel:
        """Permission tier for this tool."""
        ...

    @abc.abstractmethod
    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Execute the tool with validated parameters."""
        ...

    def validate_input(self, params: dict[str, Any]) -> list[str]:
        """Validate input against schema. Returns list of errors (empty = valid)."""
        errors: list[str] = []
        schema = self.input_schema
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        for req_field in required:
            if req_field not in params:
                errors.append(f"Missing required field: {req_field}")

        for param_name, value in params.items():
            if param_name in properties:
                expected_type = properties[param_name].get("type")
                if expected_type and not _check_type(value, expected_type):
                    errors.append(
                        f"Field '{param_name}' expected type '{expected_type}', "
                        f"got '{type(value).__name__}'"
                    )

        return errors

    def to_llm_schema(self) -> dict[str, Any]:
        """Return OpenAI function-calling compatible schema for LLM."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


def _check_type(value: Any, expected: str) -> bool:
    """Check if a value matches the expected JSON Schema type."""
    type_map: dict[str, type | tuple[type, ...]] = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    expected_types = type_map.get(expected)
    if expected_types is None:
        return True
    return isinstance(value, expected_types)
