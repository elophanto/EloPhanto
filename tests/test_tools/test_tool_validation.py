"""BaseTool.validate_input — optional fields tolerate explicit null.

LLMs routinely pass `field: null` for optional params they have no value for.
Rejecting that as a type error (the cause of a real company_onboard failure:
"Field 'price' expected type 'object', got 'NoneType'") fails otherwise-valid
calls. Optional null = absent; required null + wrong types are still caught.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class _SchemaTool(BaseTool):
    @property
    def name(self) -> str:
        return "schema_tool"

    @property
    def description(self) -> str:
        return "d"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "price": {"type": "object"},
                "kpis": {"type": "array"},
                "count": {"type": "integer"},
            },
            "required": ["slug"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True)


def _t() -> _SchemaTool:
    return _SchemaTool()


def test_optional_null_object_and_array_accepted() -> None:
    assert _t().validate_input({"slug": "x", "price": None, "kpis": None}) == []


def test_optional_null_integer_accepted() -> None:
    assert _t().validate_input({"slug": "x", "count": None}) == []


def test_required_null_still_rejected() -> None:
    errs = _t().validate_input({"slug": None})
    assert errs and "slug" in errs[0]


def test_wrong_type_still_rejected() -> None:
    errs = _t().validate_input({"slug": "x", "price": "not-an-object"})
    assert errs and "price" in errs[0]


def test_valid_values_pass() -> None:
    assert _t().validate_input({"slug": "x", "price": {"amount": 10}, "kpis": []}) == []


def test_missing_required_still_rejected() -> None:
    errs = _t().validate_input({"price": {"amount": 10}})
    assert any("slug" in e for e in errs)
