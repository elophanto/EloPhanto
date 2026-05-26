"""Draft tools — write outreach drafts for operator review (ABE Phase 9).

Six tools in one file:
  - ``email_draft``         (SAFE) — write a proposed email draft
  - ``outreach_draft``      (SAFE) — write a proposed prospect outreach draft
  - ``post_draft``          (SAFE) — write a proposed X / public post draft
  - ``draft_approve``       (MODERATE) — operator approves a draft
  - ``draft_reject``        (MODERATE) — operator rejects a draft (with reason)
  - ``company_trust_set``   (MODERATE) — operator promotes/demotes trust state

Draft files live under ``companies/<slug>/drafts/<kind>/pending/`` and
move to ``approved/`` or ``rejected/`` on resolution. Drafts are
Markdown so the operator can read them in any text tool.

The draft tools are intentionally SAFE — writing a draft is a
local file write that doesn't reach the outside world, so it
shouldn't require operator approval per call. The MODERATE-tier
resolution tools (approve / reject / trust_set) are where the
operator's judgement actually applies.

ABE (Autonomous Business Entity) is a concept originated by Petr
Royce in 2023. See ``docs/76-ABE-FRAMEWORK.md`` §Phase 9.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


_VALID_KINDS: tuple[str, ...] = ("email", "outreach", "post")


def _slug_safe(text: str, max_len: int = 40) -> str:
    """Filename-safe slug derived from text (subject, prospect_id,
    first line of post, etc.). Always non-empty (falls back to
    short uuid)."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    cleaned = cleaned[:max_len].strip("-")
    return cleaned or uuid.uuid4().hex[:8]


def _draft_dir(project_root: Path, company_id: str, kind: str) -> Path:
    return project_root / "companies" / company_id / "drafts" / kind / "pending"


def _resolved_dir(project_root: Path, company_id: str, kind: str, status: str) -> Path:
    return project_root / "companies" / company_id / "drafts" / kind / status


def _find_draft(project_root: Path, draft_id: str) -> tuple[Path, str, str] | None:
    """Locate a draft by id across all companies + kinds + pending
    folders. Returns ``(path, company_id, kind)`` or None.

    Draft id is the filename stem; we walk the companies tree for a
    match. O(n) over total drafts — fine in practice.
    """
    companies_root = project_root / "companies"
    if not companies_root.is_dir():
        return None
    for company_dir in companies_root.iterdir():
        drafts_dir = company_dir / "drafts"
        if not drafts_dir.is_dir():
            continue
        for kind_dir in drafts_dir.iterdir():
            pending = kind_dir / "pending"
            if not pending.is_dir():
                continue
            candidate = pending / f"{draft_id}.md"
            if candidate.is_file():
                return candidate, company_dir.name, kind_dir.name
    return None


def _write_draft(
    project_root: Path,
    company_id: str,
    kind: str,
    title: str,
    body: str,
    metadata: dict[str, Any],
) -> tuple[Path, str]:
    """Write a draft Markdown file. Returns ``(path, draft_id)``."""
    if kind not in _VALID_KINDS:
        raise ValueError(f"unknown draft kind {kind!r}; expected {_VALID_KINDS}")

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    short = uuid.uuid4().hex[:6]
    slug = _slug_safe(title or kind)
    draft_id = f"{ts}-{slug}-{short}"
    dest = _draft_dir(project_root, company_id, kind) / f"{draft_id}.md"
    dest.parent.mkdir(parents=True, exist_ok=True)

    meta_lines = [f"- **{k}**: {v}" for k, v in metadata.items()]
    contents = (
        f"# {kind.title()} draft — {title}\n\n"
        f"**status**: pending  \n"
        f"**company**: {company_id}  \n"
        f"**kind**: {kind}  \n"
        f"**draft_id**: `{draft_id}`  \n"
        f"**created**: {datetime.now(UTC).isoformat()}\n\n"
        f"## Metadata\n\n" + "\n".join(meta_lines) + "\n\n"
        f"## Body\n\n{body}\n\n"
        f"---\n"
        f"Approve: `elophanto drafts approve {draft_id}` "
        f"(or call `draft_approve({draft_id!r})`).  \n"
        f"Reject:  `elophanto drafts reject {draft_id} <reason>` "
        f"(or call `draft_reject({draft_id!r}, reason=...)`)."
    )
    dest.write_text(contents, encoding="utf-8")
    return dest, draft_id


# ── Draft authoring tools (SAFE) ───────────────────────────────────────


class _DraftAuthorBase(BaseTool):
    """Shared injection for draft-author tools."""

    def __init__(self) -> None:
        self._project_root: Path | None = None
        # ABE Phase 10 — optional VoiceManager. When unset (test
        # fixtures, missing voice contract) the lint is skipped.
        self._voice_manager: Any = None

    @property
    def group(self) -> str:
        return "companies"

    @property
    def permission_level(self) -> PermissionLevel:
        # SAFE — a local file write that doesn't reach the outside
        # world. The MODERATE gate is on approve/reject where the
        # operator's judgement actually applies.
        return PermissionLevel.SAFE

    def _check_ready(self) -> ToolResult | None:
        if self._project_root is None:
            return ToolResult(
                success=False,
                error=f"{self.name} not initialized (missing project_root)",
            )
        return None

    def _voice_check(
        self, body: str, company_id: str, channel: str
    ) -> ToolResult | None:
        """ABE Phase 10 — lint the draft body against the company's
        voice contract before writing. Returns a fail-ToolResult on
        violation (the LLM sees it and can revise on the next planning
        cycle). Fail-soft: no VoiceManager or no voice.yaml = pass."""
        if self._voice_manager is None:
            return None
        result = self._voice_manager.lint(body, company_id=company_id, channel=channel)
        if result.passed:
            return None
        msg = "voice lint failed: " + "; ".join(result.violations)
        if result.suggestions:
            msg += " | suggestions: " + "; ".join(result.suggestions)
        msg += (
            " | call voice_show to see the full contract, then revise "
            "the body and re-call this draft tool."
        )
        return ToolResult(success=False, error=msg)


class EmailDraftTool(_DraftAuthorBase):
    @property
    def name(self) -> str:
        return "email_draft"

    @property
    def description(self) -> str:
        return (
            "Write a proposed email draft for operator review when "
            "the active company is in trust state 'learning' (live "
            "send is refused by the trust gate). Drafts land at "
            "companies/<slug>/drafts/email/pending/<id>.md as Markdown "
            "the operator can read in any tool. Operator approves via "
            "`draft_approve(id)` or rejects with reason."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient address."},
                "subject": {"type": "string"},
                "body": {
                    "type": "string",
                    "description": "Full email body (plain text or Markdown).",
                },
                "company_id": {
                    "type": "string",
                    "description": "Defaults to the active company.",
                },
                "in_reply_to": {
                    "type": "string",
                    "description": "Optional — message-id this drafts as a reply to.",
                },
            },
            "required": ["to", "subject", "body"],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        gate = self._check_ready()
        if gate is not None:
            return gate
        from core.company import current_company_id

        company_id = str(params.get("company_id") or current_company_id())
        to = str(params["to"]).strip()
        subject = str(params["subject"]).strip()
        body = str(params["body"]).strip()
        if not body:
            return ToolResult(success=False, error="body must be non-empty")
        voice_fail = self._voice_check(body, company_id, "email")
        if voice_fail is not None:
            return voice_fail

        path, draft_id = _write_draft(
            self._project_root,  # type: ignore[arg-type]
            company_id,
            "email",
            title=subject,
            body=body,
            metadata={
                "to": to,
                "subject": subject,
                "in_reply_to": params.get("in_reply_to") or "(none)",
            },
        )
        return ToolResult(
            success=True,
            data={
                "draft_id": draft_id,
                "path": str(path),
                "kind": "email",
                "company_id": company_id,
                "next": (
                    "Present this draft to the operator and wait for "
                    "approval via `draft_approve(draft_id=...)` or a "
                    "rejection. Do NOT call email_send for this company "
                    "until trust state is promoted out of 'learning'."
                ),
            },
        )


class OutreachDraftTool(_DraftAuthorBase):
    @property
    def name(self) -> str:
        return "outreach_draft"

    @property
    def description(self) -> str:
        return (
            "Write a proposed prospect outreach draft for operator "
            "review when the company is in trust state 'learning'. "
            "Drafts land at companies/<slug>/drafts/outreach/pending/."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prospect_id": {"type": "string"},
                "channel": {
                    "type": "string",
                    "description": "email | commune | browser | other",
                },
                "body": {
                    "type": "string",
                    "description": "The proposed outreach message body.",
                },
                "company_id": {"type": "string"},
            },
            "required": ["prospect_id", "body"],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        gate = self._check_ready()
        if gate is not None:
            return gate
        from core.company import current_company_id

        company_id = str(params.get("company_id") or current_company_id())
        prospect_id = str(params["prospect_id"]).strip()
        body = str(params["body"]).strip()
        if not body:
            return ToolResult(success=False, error="body must be non-empty")
        channel = str(params.get("channel") or "email")
        voice_fail = self._voice_check(body, company_id, "outreach")
        if voice_fail is not None:
            return voice_fail

        path, draft_id = _write_draft(
            self._project_root,  # type: ignore[arg-type]
            company_id,
            "outreach",
            title=f"{prospect_id}-{channel}",
            body=body,
            metadata={"prospect_id": prospect_id, "channel": channel},
        )
        return ToolResult(
            success=True,
            data={
                "draft_id": draft_id,
                "path": str(path),
                "kind": "outreach",
                "company_id": company_id,
                "prospect_id": prospect_id,
                "next": (
                    "Present to operator and wait for draft_approve. "
                    "Do NOT call prospect_outreach for this company "
                    "until trust state is promoted."
                ),
            },
        )


class PostDraftTool(_DraftAuthorBase):
    @property
    def name(self) -> str:
        return "post_draft"

    @property
    def description(self) -> str:
        return (
            "Write a proposed X / social post draft for operator "
            "review when the company is in trust state 'learning'. "
            "Drafts land at companies/<slug>/drafts/post/pending/."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The proposed post body.",
                },
                "media_path": {
                    "type": "string",
                    "description": "Optional — local media file to attach.",
                },
                "reply_to_url": {
                    "type": "string",
                    "description": "Optional — URL this drafts as a reply to.",
                },
                "company_id": {"type": "string"},
            },
            "required": ["content"],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        gate = self._check_ready()
        if gate is not None:
            return gate
        from core.company import current_company_id

        company_id = str(params.get("company_id") or current_company_id())
        content = str(params["content"]).strip()
        if not content:
            return ToolResult(success=False, error="content must be non-empty")
        voice_fail = self._voice_check(content, company_id, "post")
        if voice_fail is not None:
            return voice_fail

        # Title from first line, capped
        first_line = content.splitlines()[0][:50]
        path, draft_id = _write_draft(
            self._project_root,  # type: ignore[arg-type]
            company_id,
            "post",
            title=first_line,
            body=content,
            metadata={
                "media_path": params.get("media_path") or "(none)",
                "reply_to_url": params.get("reply_to_url") or "(none)",
                "char_count": str(len(content)),
            },
        )
        return ToolResult(
            success=True,
            data={
                "draft_id": draft_id,
                "path": str(path),
                "kind": "post",
                "company_id": company_id,
                "char_count": len(content),
                "next": (
                    "Present to operator and wait for draft_approve. "
                    "Do NOT call twitter_post for this company until "
                    "trust state is promoted."
                ),
            },
        )


# ── Resolution tools (MODERATE) ───────────────────────────────────────


def _move_draft(
    src: Path,
    project_root: Path,
    company_id: str,
    kind: str,
    status: str,
    note: str | None,
) -> Path:
    """Move a draft from pending/ to approved/ or rejected/.
    Appends a resolution footer with the operator's note (if any).

    ``project_root`` is passed in explicitly because walking
    ``src.parent.*N`` is fragile and was off-by-one in the
    original implementation (Phase 9 test caught it).
    """
    dest_dir = _resolved_dir(project_root, company_id, kind, status)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name

    body = src.read_text(encoding="utf-8")
    body += (
        f"\n\n---\n## Resolution ({status})\n\n"
        f"**at**: {datetime.now(UTC).isoformat()}  \n"
        f"**note**: {note or '(no note)'}\n"
    )
    dest.write_text(body, encoding="utf-8")
    src.unlink()
    return dest


class _DraftResolverBase(BaseTool):
    def __init__(self) -> None:
        self._project_root: Path | None = None

    @property
    def group(self) -> str:
        return "companies"

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    def _check_ready(self) -> ToolResult | None:
        if self._project_root is None:
            return ToolResult(
                success=False,
                error=f"{self.name} not initialized (missing project_root)",
            )
        return None


class DraftApproveTool(_DraftResolverBase):
    @property
    def name(self) -> str:
        return "draft_approve"

    @property
    def description(self) -> str:
        return (
            "Operator approves a pending draft. Moves it to "
            "companies/<slug>/drafts/<kind>/approved/. Approval does "
            "NOT auto-send — the agent must still call the live "
            "outreach tool, and the company must be in 'trial' or "
            "'operating' trust state for that to succeed."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "note": {
                    "type": "string",
                    "description": "Optional approval note (e.g. edits applied).",
                },
            },
            "required": ["draft_id"],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        gate = self._check_ready()
        if gate is not None:
            return gate
        draft_id = str(params["draft_id"]).strip()
        found = _find_draft(self._project_root, draft_id)  # type: ignore[arg-type]
        if found is None:
            return ToolResult(
                success=False,
                error=(
                    f"draft {draft_id!r} not found in any "
                    f"companies/*/drafts/*/pending/. May be already "
                    f"resolved (check approved/ or rejected/)."
                ),
            )
        src, company_id, kind = found
        dest = _move_draft(
            src,
            self._project_root,  # type: ignore[arg-type]
            company_id,
            kind,
            "approved",
            params.get("note"),
        )
        return ToolResult(
            success=True,
            data={
                "draft_id": draft_id,
                "company_id": company_id,
                "kind": kind,
                "status": "approved",
                "path": str(dest),
            },
        )


class DraftRejectTool(_DraftResolverBase):
    @property
    def name(self) -> str:
        return "draft_reject"

    @property
    def description(self) -> str:
        return (
            "Operator rejects a pending draft. Moves it to "
            "companies/<slug>/drafts/<kind>/rejected/ with the reason. "
            "Agent should read the reason and revise before drafting "
            "again."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "reason": {
                    "type": "string",
                    "description": "Why the draft was rejected (operator feedback).",
                },
            },
            "required": ["draft_id", "reason"],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        gate = self._check_ready()
        if gate is not None:
            return gate
        draft_id = str(params["draft_id"]).strip()
        reason = str(params["reason"]).strip()
        if not reason:
            return ToolResult(success=False, error="reason must be non-empty")
        found = _find_draft(self._project_root, draft_id)  # type: ignore[arg-type]
        if found is None:
            return ToolResult(success=False, error=f"draft {draft_id!r} not found")
        src, company_id, kind = found
        dest = _move_draft(
            src,
            self._project_root,  # type: ignore[arg-type]
            company_id,
            kind,
            "rejected",
            reason,
        )
        return ToolResult(
            success=True,
            data={
                "draft_id": draft_id,
                "company_id": company_id,
                "kind": kind,
                "status": "rejected",
                "path": str(dest),
                "reason": reason,
            },
        )


class CompanyTrustSetTool(BaseTool):
    """Promote / demote a company's trust state (operator-controlled)."""

    def __init__(self) -> None:
        self._company_manager: Any = None

    @property
    def group(self) -> str:
        return "companies"

    @property
    def name(self) -> str:
        return "company_trust_set"

    @property
    def description(self) -> str:
        return (
            "Set the trust state on a company. Operator-controlled "
            "promotion through the ladder: learning → trial → "
            "operating. learning blocks live outreach (agent must "
            "draft). trial allows outreach but each call still gates "
            "through MODERATE permission. operating is autonomous "
            "within budget. No auto-promotion — operator chooses."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "state": {
                    "type": "string",
                    "enum": ["learning", "trial", "operating"],
                },
                "reason": {
                    "type": "string",
                    "description": "Optional note (e.g. 'voice approved after 3 sample emails').",
                },
            },
            "required": ["slug", "state"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._company_manager is None:
            return ToolResult(
                success=False,
                error="company_trust_set not initialized (missing company_manager)",
            )
        slug = str(params["slug"]).strip()
        state = str(params["state"]).strip()
        try:
            ok = await self._company_manager.set_trust_state(slug, state)
        except ValueError as e:
            return ToolResult(success=False, error=str(e))
        if not ok:
            return ToolResult(success=False, error=f"No such company: {slug}")
        return ToolResult(
            success=True,
            data={
                "slug": slug,
                "trust_state": state,
                "reason": params.get("reason") or "(no note)",
            },
        )
