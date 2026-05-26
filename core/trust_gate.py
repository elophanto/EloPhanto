"""Trust gate — refuses live outreach in `learning` state.

ABE Phase 9 (docs/76-ABE-FRAMEWORK.md). The substrate enables real
external communication (email, prospect outreach, X posts) — without
this gate the agent can spam an unproductized company's audience
before the operator has approved its voice or messaging. The gate
mirrors how an operator would onboard a new sales hire: learn,
draft, get reviewed, then earn autonomy.

The four currently-gated tools:

  - ``email_send``        → draft via ``email_draft``
  - ``email_reply``       → draft via ``email_draft`` (mark as reply)
  - ``prospect_outreach`` → draft via ``outreach_draft``
  - ``twitter_post``      → draft via ``post_draft``

States:

  - ``learning`` (default for new companies): gate DENIES live
    outreach with a pointer to the draft equivalent.
  - ``trial``: gate ALLOWS; the existing MODERATE permission tier
    still requires per-call operator approval. Named explicitly
    so the agent + operator know the company is mid-promotion.
  - ``operating``: gate ALLOWS; standard permission_mode applies.

Failures degrade open with a logged warning. The gate is a safety
layer over an existing safety system (permission_mode) — losing
the gate's signal must NEVER break the underlying production flow.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.database import Database

logger = logging.getLogger(__name__)


# Tool name → the draft tool the LLM should call instead.
# Kept here so the deny message can name the canonical alternative
# without each gated tool duplicating the lookup.
_DRAFT_REPLACEMENT: dict[str, str] = {
    "email_send": "email_draft",
    "email_reply": "email_draft",
    "prospect_outreach": "outreach_draft",
    "twitter_post": "post_draft",
}


async def check_outreach_allowed(
    db: Database, tool_name: str, company_id: str | None = None
) -> tuple[bool, str]:
    """Whether the calling outreach tool may execute right now.

    Returns ``(allowed, reason)``. When ``allowed=False`` the calling
    tool MUST refuse and return the ``reason`` as its error so the
    LLM is told what to do instead (call the draft equivalent).

    ``company_id`` defaults to ``current_company_id()`` when None.
    Falls through to ``learning`` (deny) when the company doesn't
    exist or the lookup fails — fail-safe by design. The previous
    bug pattern (silent except + None default = permissive) was
    explicitly avoided here.
    """
    try:
        from core.company import CompanyManager, current_company_id

        target = company_id or current_company_id()
        mgr = CompanyManager(db=db)  # no project_root needed for read
        state = await mgr.get_trust_state(target)
    except Exception as e:
        # Unknown state → fail safe (deny). Log so the next failure
        # has a real trace; we DO NOT want a silent open-fail here.
        logger.warning(
            "trust_gate: lookup failed for tool=%s company=%s (%s) — "
            "denying as fail-safe",
            tool_name,
            company_id,
            e,
        )
        return False, (
            f"trust_gate: could not verify company trust state — "
            f"refusing {tool_name} as fail-safe. Run `elophanto company "
            f"report` to inspect."
        )

    if state in ("trial", "operating"):
        return True, ""

    # learning (or any unrecognised state) → deny + point at draft.
    replacement = _DRAFT_REPLACEMENT.get(tool_name)
    suggestion = (
        f" Use `{replacement}` instead — it writes the draft to "
        f"`companies/{target}/drafts/` for operator review."
        if replacement
        else ""
    )
    reason = (
        f"{tool_name} blocked: company {target!r} is in trust state "
        f"{state!r} (learning), which forbids live outreach until the "
        f"operator approves your voice + samples and promotes the "
        f"company to 'trial' or 'operating'.{suggestion} Operator "
        f"command: `elophanto company trust set {target} trial`."
    )
    return False, reason
