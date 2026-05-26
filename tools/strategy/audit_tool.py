"""company_capabilities — read-only audit (Phase 11)."""

from __future__ import annotations

from typing import Any

from core.capability_audit import (
    collect_capabilities,
    render_capabilities_md,
    write_capabilities_md,
)
from tools.base import BaseTool, PermissionLevel, ToolResult


class CompanyCapabilitiesTool(BaseTool):
    """Synthesizes vault keys + registered tools (by group) +
    installed skills into a CapabilityMap, writes
    ``data/companies/<slug>/capabilities.md``, and returns the
    structured map for downstream consumption (the plan + apply
    tools use it to detect blockers)."""

    def __init__(self) -> None:
        self._registry: Any = None
        self._vault: Any = None
        self._project_root: Any = None

    @property
    def name(self) -> str:
        return "company_capabilities"

    @property
    def group(self) -> str:
        return "companies"

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def description(self) -> str:
        return (
            "Audit agent capabilities (vault keys, registered tools by "
            "group, installed skills) and write capabilities.md. Call "
            "before company_plan so the strategy is grounded in what's "
            "actually available. See strategy-pipeline skill."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "company_id": {
                    "type": "string",
                    "description": "Defaults to the active company.",
                },
                "write_markdown": {
                    "type": "boolean",
                    "description": "When true (default), writes capabilities.md.",
                },
            },
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._project_root is None or self._registry is None:
            return ToolResult(
                success=False,
                error=(
                    "company_capabilities not initialized "
                    "(missing project_root or registry)"
                ),
            )
        from core.company import current_company_id

        company_id = str(params.get("company_id") or current_company_id())
        write_md = bool(params.get("write_markdown", True))

        cap = collect_capabilities(
            registry=self._registry,
            vault=self._vault,
            project_root=self._project_root,
        )

        md_path = None
        if write_md:
            try:
                md_path = write_capabilities_md(cap, self._project_root, company_id)
            except Exception as e:
                return ToolResult(
                    success=False,
                    error=f"capabilities.md write failed: {e}",
                )

        return ToolResult(
            success=True,
            data={
                "company_id": company_id,
                "vault_keys_count": len(cap.vault_keys),
                "vault_locked": cap.vault_locked,
                "tool_groups": sorted(cap.tools_by_group.keys()),
                "tool_count": sum(len(v) for v in cap.tools_by_group.values()),
                "skill_count": len(cap.skills),
                "capabilities_md": str(md_path) if md_path else None,
                "capability_map": cap.as_dict(),
                "preview": render_capabilities_md(cap, company_id=company_id)[:600],
                "next": (
                    "Call company_plan with the strategy_inputs (from "
                    "company.yaml strategy_inputs section) to generate "
                    "a proposed strategy that respects what's available "
                    "here."
                ),
            },
        )
