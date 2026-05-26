"""ABE draft tools (Phase 9 — docs/76-ABE-FRAMEWORK.md).

When a company is in trust state ``learning``, the live outreach
tools (``email_send``, ``email_reply``, ``prospect_outreach``,
``twitter_post``) refuse. The agent must use these draft tools
instead — they write the proposed message to
``companies/<slug>/drafts/`` for operator review, then move it to
``drafts/approved/`` on approval. Operator promotes the company to
``trial`` or ``operating`` to enable live sends.
"""

from tools.drafts.draft_tools import (
    CompanyTrustSetTool,
    DraftApproveTool,
    DraftRejectTool,
    EmailDraftTool,
    OutreachDraftTool,
    PostDraftTool,
)

__all__ = [
    "EmailDraftTool",
    "OutreachDraftTool",
    "PostDraftTool",
    "DraftApproveTool",
    "DraftRejectTool",
    "CompanyTrustSetTool",
]
