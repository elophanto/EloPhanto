"""ABE company-management tools.

See ``docs/76-ABE-FRAMEWORK.md`` §Phase 7. Today: one tool —
``company_set_product`` — that lets the agent (with operator
approval) write or update ``companies/<slug>/company.yaml`` so it
can self-bootstrap its own ABE without the operator hand-writing
every field.
"""

from tools.companies.set_product_tool import CompanySetProductTool

__all__ = ["CompanySetProductTool"]
