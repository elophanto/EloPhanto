"""ABE Phase 11 — Strategic Planning & Capability Audit.

Four tools that wire the strategy pipeline:

- ``company_capabilities`` (SAFE, CORE) — read-only audit of vault
  keys, registered tools by group, installed skills. Writes
  ``data/companies/<slug>/capabilities.md``.
- ``company_plan`` (SAFE, CORE) — LLM-driven strategy generation.
  Schema mirrors ``tmp/strategy.js`` 1:1 plus EloPhanto extensions
  (vault_requirements / tool_requirements / voice_seed /
  agent_role_assignments / execution_priority). Writes a versioned
  proposal under ``data/companies/<slug>/strategy/proposed/``.
- ``company_plan_apply`` (MODERATE, PROFILE) — promotes a proposal
  to active, atomically creates the mission + goals + schedules +
  voice_proposed.yaml + blockers.yaml. Archives any prior active.
- ``company_plan_approve`` (MODERATE, PROFILE) — finalizes the
  strategy after operator review: activates the mission, allows
  blocker-driven candidate generators to fire.

See ``docs/76-ABE-FRAMEWORK.md`` §Phase 11.
"""

from tools.strategy.apply_tool import CompanyPlanApplyTool
from tools.strategy.approve_tool import CompanyPlanApproveTool
from tools.strategy.audit_tool import CompanyCapabilitiesTool
from tools.strategy.plan_tool import CompanyPlanTool

__all__ = [
    "CompanyCapabilitiesTool",
    "CompanyPlanTool",
    "CompanyPlanApplyTool",
    "CompanyPlanApproveTool",
]
