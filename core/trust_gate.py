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

Trust promotion is **propose-then-confirm** — never silently
auto-promote under ``full_auto``. See ``propose_trust_promotion`` /
``confirm_trust_promotion``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

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

_MIN_APPROVED_DRAFTS = 3
_NEXT_STATE = {"learning": "trial", "trial": "operating"}


@dataclass
class TrustEvidence:
    company_id: str
    current_state: str
    proposed_state: str
    approved_drafts: int
    pending_drafts: int
    rejected_drafts: int
    sample_ids: list[str]
    ready: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _drafts_base(project_root: Path, company_id: str) -> Path:
    return project_root / "companies" / company_id / "drafts"


def _count_drafts(
    project_root: Path, company_id: str, status: str
) -> tuple[int, list[str]]:
    base = _drafts_base(project_root, company_id)
    if not base.is_dir():
        return 0, []
    ids: list[str] = []
    for kind_dir in base.iterdir():
        if not kind_dir.is_dir():
            continue
        folder = kind_dir / status
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            ids.append(path.stem)
    return len(ids), ids


def collect_trust_evidence(
    project_root: Path,
    company_id: str,
    *,
    current_state: str = "learning",
) -> TrustEvidence:
    """Build an evidence packet for trust promotion (no side effects)."""
    approved_n, approved_ids = _count_drafts(project_root, company_id, "approved")
    pending_n, _ = _count_drafts(project_root, company_id, "pending")
    rejected_n, _ = _count_drafts(project_root, company_id, "rejected")
    proposed = _NEXT_STATE.get(current_state, "")
    ready = bool(proposed) and approved_n >= _MIN_APPROVED_DRAFTS and rejected_n == 0
    if not proposed:
        reason = f"already at {current_state!r} — no further promotion"
    elif rejected_n > 0:
        reason = (
            f"{rejected_n} rejected draft(s) — counters reset; revise voice "
            f"before proposing promotion"
        )
        ready = False
    elif approved_n < _MIN_APPROVED_DRAFTS:
        reason = (
            f"need {_MIN_APPROVED_DRAFTS} approved drafts "
            f"(have {approved_n}) before proposing {proposed}"
        )
    else:
        reason = (
            f"ready to propose {current_state}→{proposed} "
            f"({approved_n} clean approved drafts)"
        )
    return TrustEvidence(
        company_id=company_id,
        current_state=current_state,
        proposed_state=proposed or current_state,
        approved_drafts=approved_n,
        pending_drafts=pending_n,
        rejected_drafts=rejected_n,
        sample_ids=approved_ids[:8],
        ready=ready,
        reason=reason,
    )


def propose_trust_promotion(
    project_root: Path,
    company_id: str,
    *,
    current_state: str = "learning",
) -> tuple[bool, TrustEvidence, Path | None]:
    """Write a one-click trust proposal file. Never changes trust_state.

    Returns (ok, evidence, proposal_path).
    """
    evidence = collect_trust_evidence(
        project_root, company_id, current_state=current_state
    )
    if not evidence.ready:
        return False, evidence, None
    dest_dir = project_root / "companies" / company_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / "trust_proposal.json"
    payload = {
        **evidence.to_dict(),
        "created_at": datetime.now(UTC).isoformat(),
        "status": "pending",
        "confirm_hint": f"elophanto company trust {company_id} confirm",
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return True, evidence, path


def confirm_trust_promotion(
    project_root: Path, company_id: str
) -> tuple[bool, str, str]:
    """Apply a pending proposal. Returns (ok, new_state, message).

    Does not itself write DB — caller must ``set_trust_state``.
    """
    path = project_root / "companies" / company_id / "trust_proposal.json"
    if not path.is_file():
        return False, "", "no pending trust_proposal.json — run propose first"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return False, "", f"corrupt trust_proposal.json: {e}"
    if data.get("status") != "pending":
        return False, "", f"proposal status is {data.get('status')!r}, not pending"
    new_state = str(data.get("proposed_state") or "")
    if new_state not in ("trial", "operating"):
        return False, "", f"invalid proposed_state {new_state!r}"
    data["status"] = "confirmed"
    data["confirmed_at"] = datetime.now(UTC).isoformat()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True, new_state, f"confirmed promotion → {new_state}"


def reject_trust_promotion(
    project_root: Path, company_id: str, reason: str = ""
) -> bool:
    """Operator rejection — clear proposal and note spam/reject signal."""
    path = project_root / "companies" / company_id / "trust_proposal.json"
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data["status"] = "rejected"
    data["rejected_at"] = datetime.now(UTC).isoformat()
    data["reject_reason"] = reason or "operator rejected"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True


def reset_trust_counters_on_reject(project_root: Path, company_id: str) -> None:
    """Any operator rejection / spam signal clears a pending promotion."""
    reject_trust_promotion(
        project_root, company_id, reason="draft rejected / spam signal"
    )


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
        f"command: `elophanto company trust {target} trial` "
        f"(or propose via trust evidence packet)."
    )
    return False, reason
