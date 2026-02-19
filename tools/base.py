"""Tool base class and interface definition.

Every tool in EloPhanto -- built-in or self-created -- must inherit from BaseTool
and implement the required interface.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PermissionLevel(StrEnum):
    SAFE = "safe"
    MODERATE = "moderate"
    DESTRUCTIVE = "destructive"
    CRITICAL = "critical"


@dataclass
class ToolResult:
    """Standardized result from tool execution."""

    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"success": self.success}
        result.update(self.data)
        if self.error:
            result["error"] = self.error
        return result


class BaseTool(abc.ABC):
    """Abstract base class for all EloPhanto tools."""

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
