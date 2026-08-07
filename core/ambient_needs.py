"""Ambient need contract — signal → need → action → risk → why.

Turns raw ambient signals into operator-readable proposals
(notice → know → help with a refuseable brake).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_DEADLINE_RE = re.compile(
    r"\b(asap|urgent|deadline|due\s+(today|tomorrow|monday|friday)|"
    r"eod|eow|by\s+\d|respond\s+by|time[- ]sensitive)\b",
    re.I,
)
_VIP_RE = re.compile(
    r"\b(ceo|founder|board|investor|legal|compliance|security|"
    r"incident|outage|production\s+down)\b",
    re.I,
)
_REPLY_RE = re.compile(
    r"\b(please\s+reply|can\s+you|could\s+you|need\s+your|"
    r"waiting\s+on\s+you|rsvp|confirm)\b",
    re.I,
)


@dataclass
class NeedProposal:
    need: str
    action: str
    risk: str
    why: str
    strength: str
    evidence_ids: list[str] = field(default_factory=list)
    claim_type: str | None = None
    p_hat: float | None = None
    kill: str = "deny or /stop"

    def as_dict(self) -> dict[str, Any]:
        return {
            "need": self.need,
            "action": self.action,
            "risk": self.risk,
            "why": self.why,
            "strength": self.strength,
            "evidence_ids": list(self.evidence_ids),
            "claim_type": self.claim_type,
            "p_hat": self.p_hat,
            "kill": self.kill,
            "summary": f"{self.need} → {self.action}",
            "requires_approval": self.strength in ("act", "escalate"),
        }

    def action_spec(self, *, signal_id: str = "", intervention_id: str = "") -> str:
        parts = [
            f"NEED: {self.need}",
            f"ACTION: {self.action}",
            f"RISK: {self.risk}",
            f"WHY: {self.why}",
            f"STRENGTH: {self.strength}",
            f"KILL: {self.kill}",
        ]
        if self.p_hat is not None:
            parts.append(f"p_hat={self.p_hat:.2f}")
        if self.claim_type:
            parts.append(f"claim_type={self.claim_type}")
        if signal_id:
            parts.append(f"signal_id={signal_id}")
        if intervention_id:
            parts.append(f"intervention_id={intervention_id}")
        parts.append("Present via ambient_intervention_decide — do not silently act.")
        return " | ".join(parts)


def score_email_urgency(payload: dict[str, Any] | None) -> float:
    """0.3–0.95 urgency from subject/body/from heuristics."""
    payload = payload or {}
    subject = str(payload.get("subject") or "")
    body = str(payload.get("preview") or payload.get("body") or "")[:800]
    sender = str(payload.get("from") or payload.get("sender") or "")
    blob = f"{subject}\n{body}\n{sender}"
    score = 0.45
    if _DEADLINE_RE.search(blob):
        score += 0.25
    if _VIP_RE.search(blob):
        score += 0.2
    if _REPLY_RE.search(blob):
        score += 0.1
    return round(max(0.3, min(0.95, score)), 2)


def proposal_from_signal(
    *,
    kind: str,
    source: str,
    urgency: float,
    payload: dict[str, Any] | None,
    signal_id: str,
    instinct_hint: str = "",
) -> NeedProposal:
    payload = payload or {}
    if kind == "email":
        subject = str(payload.get("subject") or "(no subject)")[:120]
        sender = str(payload.get("from") or payload.get("sender") or "unknown")[:80]
        u = max(urgency, score_email_urgency(payload))
        need = f"Reply due on email from {sender}: {subject}"
        action = "Draft a short reply outline (do not send) and surface it for approval"
        risk = "low — draft only; send still gated"
        why = f"Inbound email urgency={u:.2f} from {source}"
        if instinct_hint:
            why += f"; instinct: {instinct_hint[:80]}"
        strength = "escalate" if u >= 0.85 else "nudge"
        return NeedProposal(
            need=need,
            action=action,
            risk=risk,
            why=why,
            strength=strength,
            evidence_ids=[signal_id],
            claim_type="reply_due",
            p_hat=u,
        )
    if kind == "calendar":
        title = str(payload.get("title") or payload.get("name") or "event")[:120]
        when = str(payload.get("starts_at") or payload.get("window_start") or "")[:40]
        # Scheduler-sourced rows are cron tasks, not calendar meetings.
        from_scheduler = source == "scheduler" or bool(payload.get("schedule_id"))
        if from_scheduler:
            need = f"Prep before scheduled task: {title}" + (
                f" @ {when}" if when else ""
            )
            claim_type = "prep_before_schedule"
            action = "Assemble a 5-bullet prep pack for the upcoming scheduled task"
            why = f"Scheduler calendar signal urgency={urgency:.2f}"
        else:
            need = f"Prep before meeting: {title}" + (f" @ {when}" if when else "")
            claim_type = "prep_before_meeting"
            action = "Assemble a 5-bullet prep pack (agenda, open threads, asks)"
            why = f"Calendar signal from {source} urgency={urgency:.2f}"
        return NeedProposal(
            need=need,
            action=action,
            risk="low — prep notes only",
            why=why,
            strength="nudge",
            evidence_ids=[signal_id],
            claim_type=claim_type,
            p_hat=urgency,
        )
    if kind == "schedule_fail":
        task = str(payload.get("task_name") or "schedule")[:80]
        return NeedProposal(
            need=f"Recover failed schedule: {task}",
            action="Diagnose last_result and propose a one-step fix (no silent re-run)",
            risk="medium — retry may burn budget",
            why=f"Scheduler reported failure via {source}",
            strength="nudge",
            evidence_ids=[signal_id],
            claim_type="schedule_recover",
            p_hat=urgency,
        )
    if kind == "crisis":
        return NeedProposal(
            need="Operator crisis signal — pause and prepare response pack",
            action="Propose pause + approved response pack (never auto-send)",
            risk="high — escalate only with approval",
            why=f"Crisis kind from {source}",
            strength="escalate",
            evidence_ids=[signal_id],
            claim_type="crisis",
            p_hat=max(urgency, 0.9),
        )
    # Generic wake / other
    event = str(payload.get("event") or payload.get("summary") or kind)[:120]
    return NeedProposal(
        need=f"Review ambient signal: {event}",
        action="Summarize what changed and one recommended next step",
        risk="low — observe/nudge only",
        why=f"{kind} from {source} urgency={urgency:.2f}",
        strength="observe" if urgency < 0.45 else "nudge",
        evidence_ids=[signal_id],
        claim_type=kind,
        p_hat=urgency,
    )


def proposal_from_prediction(
    *,
    claim: str,
    claim_type: str,
    p_hat: float,
    prediction_id: str,
) -> NeedProposal:
    if claim_type == "reply_due":
        action = "Draft reply outline for approval (do not send)"
    elif claim_type == "prep_before_schedule":
        action = "Build a short prep pack for the scheduled task"
    elif claim_type == "prep_before_meeting":
        action = "Build a short meeting prep pack"
    elif claim_type == "stale_goal_resume":
        action = "Propose the smallest next checkpoint to resume the stale goal"
    elif claim_type == "standing_coach":
        action = "Surface today’s standing-coach check-in (refuseable)"
    elif claim_type == "chore_due":
        action = "Nudge the chore with a one-line checklist"
    else:
        action = "Nudge leave/prep for the routine window"
    return NeedProposal(
        need=claim,
        action=action,
        risk="low — nudge only; act/escalate needs approval",
        why=f"Prediction {claim_type} p_hat={p_hat:.2f}",
        strength="nudge",
        evidence_ids=[prediction_id],
        claim_type=claim_type,
        p_hat=p_hat,
    )


def build_help_artifact(
    *,
    need: str,
    action: str,
    why: str,
    claim_type: str | None = None,
    payload: dict[str, Any] | None = None,
    intervention_id: str = "",
) -> str:
    """Filled refuseable help markdown (draft/prep/resume) — never sends."""
    payload = payload or {}
    lines = [
        "# Ambient help",
        "",
        f"**Need:** {need}",
        f"**Action:** {action}",
        f"**Why:** {why}",
    ]
    if claim_type:
        lines.append(f"**Claim:** {claim_type}")
    if intervention_id:
        lines.append(f"**Intervention:** {intervention_id}")
    lines.append("")
    lines.append(
        "_Refuseable — deny or `/stop`. Do not send or execute irreversible steps._"
    )
    lines.append("")

    ct = (claim_type or "").strip()
    if ct == "reply_due" or "reply" in (need or "").lower():
        lines.extend(_filled_reply_draft(payload))
    elif (
        ct in ("prep_before_schedule", "prep_before_meeting")
        or "prep" in (need or "").lower()
    ):
        lines.extend(_filled_prep_pack(payload, claim_type=ct, need=need))
    elif ct == "stale_goal_resume" or "stale" in (need or "").lower():
        lines.extend(_filled_resume_checkpoint(payload, need=need))
    elif ct == "standing_coach" or "standing coach" in (need or "").lower():
        lines.extend(_filled_coach_checkin(payload, need=need))
    elif ct == "schedule_recover" or "recover" in (need or "").lower():
        lines.extend(_filled_schedule_recover(payload))
    else:
        lines.extend(
            [
                "## Recommended next step",
                f"1. {action}",
                "2. Confirm with operator before any irreversible step.",
                "3. Log receipt when done.",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _extract_asks(text: str) -> list[str]:
    asks: list[str] = []
    for raw in re.split(r"(?<=[.?!\n])\s+", text or ""):
        s = raw.strip()
        if not s:
            continue
        if "?" in s or _REPLY_RE.search(s) or _DEADLINE_RE.search(s):
            asks.append(s[:180])
        if len(asks) >= 3:
            break
    return asks


def _filled_reply_draft(payload: dict[str, Any]) -> list[str]:
    subject = str(payload.get("subject") or "(no subject)")[:160]
    sender = str(payload.get("from") or payload.get("sender") or "unknown")[:80]
    preview = str(payload.get("preview") or payload.get("body") or "")[:600]
    asks = _extract_asks(f"{subject}. {preview}")
    ask_line = (
        asks[0]
        if asks
        else (
            f"your note on “{subject}”" if subject != "(no subject)" else "your message"
        )
    )
    first_name = sender.split("@")[0].split("<")[0].strip().split()[0] or "there"
    if "<" in first_name:
        first_name = "there"
    deadline_hint = ""
    if _DEADLINE_RE.search(f"{subject}\n{preview}"):
        deadline_hint = (
            " I can confirm a concrete ETA once I’ve checked the open threads."
        )
    draft = (
        f"Hi {first_name},\n\n"
        f"Thanks for the note — I saw {ask_line}.\n\n"
        f"Proposed reply (edit before sending):\n"
        f"- Acknowledge the ask and the urgency.\n"
        f"- Answer: I’ll take the next step on this today and reply with "
        f"status{deadline_hint}\n"
        f"- Ask: Is there a hard deadline or preferred format for the response?\n\n"
        f"Best,\n[your name]"
    )
    lines = [
        "## Draft reply (do not send)",
        f"**To:** {sender}",
        f"**Subject:** Re: {subject}",
        "",
        "```",
        draft,
        "```",
    ]
    if asks[1:]:
        lines.append("")
        lines.append("### Other asks detected")
        for a in asks[1:]:
            lines.append(f"- {a}")
    if preview:
        lines.extend(["", "### Source excerpt", preview[:400]])
    return lines


def _filled_prep_pack(
    payload: dict[str, Any], *, claim_type: str, need: str
) -> list[str]:
    title = str(payload.get("title") or payload.get("name") or need or "upcoming")[:120]
    when = str(
        payload.get("starts_at")
        or payload.get("next_run_at")
        or payload.get("dtstart")
        or ""
    )[:40]
    desc = str(
        payload.get("description")
        or payload.get("task_goal")
        or payload.get("location")
        or ""
    )[:300]
    attendees = payload.get("attendees") or payload.get("with") or []
    if isinstance(attendees, str):
        attendees = [attendees]
    label = "Scheduled task" if claim_type == "prep_before_schedule" else "Meeting"
    goal = desc or f"Complete “{title}” without scrambling mid-run."
    open_threads = (
        f"Review notes/description: {desc[:120]}"
        if desc
        else "Pull last run result / prior notes for this title."
    )
    decisions = (
        "Confirm whether to run, skip, or reshape the goal before start."
        if claim_type == "prep_before_schedule"
        else "Confirm agenda owner and the one decision you need from attendees."
    )
    artifacts = (
        "Open the task_goal doc, last_result, and any linked dashboards."
        if claim_type == "prep_before_schedule"
        else "Open the invite, shared doc, and any linked tickets."
    )
    first5 = f"Spend 5 minutes stating the success check for “{title}” out loud."
    lines = [
        f"## {label} prep pack (filled)",
        f"- **Title:** {title}" + (f" @ {when}" if when else ""),
    ]
    if attendees:
        lines.append(
            "- **With:** " + ", ".join(str(a)[:40] for a in list(attendees)[:5])
        )
    lines.extend(
        [
            f"1. **Goal:** {goal}",
            f"2. **Open threads:** {open_threads}",
            f"3. **Decisions needed:** {decisions}",
            f"4. **Artifacts to open:** {artifacts}",
            f"5. **First 5 minutes:** {first5}",
        ]
    )
    return lines


def _filled_resume_checkpoint(payload: dict[str, Any], *, need: str) -> list[str]:
    goal = str(payload.get("goal") or payload.get("goal_id") or need)[:200]
    updated = str(payload.get("updated_at") or "")[:40]
    lines = [
        "## Resume checkpoint (filled)",
        f"- **Goal:** {goal}",
    ]
    if updated:
        lines.append(f"- **Last touch:** {updated}")
    lines.extend(
        [
            f"1. **Last known:** Goal still active; last update "
            f"{updated or 'unknown'} — treat prior plan as stale until re-checked.",
            f"2. **Smallest next observable (≤30 min):** Re-open the goal, "
            f"read the current checkpoint, and write one sentence on what’s left "
            f"for “{goal[:80]}”.",
            "3. **Risk if ignored another day:** Drift + restart cost; silence "
            "does not equal progress.",
            "4. **Ask operator:** resume / replan / park?",
        ]
    )
    return lines


def _filled_coach_checkin(payload: dict[str, Any], *, need: str) -> list[str]:
    title = str(payload.get("title") or need or "coach")[:120]
    instruction = str(payload.get("instruction") or "")[:400]
    continuity = payload.get("continuity") or {}
    if not isinstance(continuity, dict):
        continuity = {}
    yesterday = str(continuity.get("last_note") or continuity.get("summary") or "")[
        :200
    ]
    last_outcome = str(continuity.get("last_outcome") or "")[:40]
    conflicts = payload.get("conflicts") or []
    if isinstance(conflicts, str):
        conflicts = [conflicts]
    lines = [
        "## Standing coach check-in (filled)",
        f"- **Order:** {title}",
        f"- **Standing instruction:** {instruction or '(none — ask operator to clarify)'}",
    ]
    if yesterday or last_outcome:
        lines.append(
            f"- **Continuity:** Yesterday/last → {yesterday or '—'} "
            f"(outcome={last_outcome or 'unknown'})"
        )
    else:
        lines.append("- **Continuity:** First day of this order — establish baseline.")
    lines.extend(
        [
            "",
            "### Today’s protect plan",
            f"1. Restate the order in one line: {instruction[:120] or title}.",
            "2. Scan calendar/schedules in the protected window for conflicts.",
        ]
    )
    if conflicts:
        lines.append("3. Conflicts already seen:")
        for c in list(conflicts)[:5]:
            lines.append(f"   - {str(c)[:100]}")
        lines.append(
            "4. **Refuseable protect act (not executed):** propose holding or "
            "declining the conflicting invite — requires separate `act` approval."
        )
    else:
        lines.extend(
            [
                "3. If a conflict appears: propose a quiet-hours hold / decline "
                "(strength=`act`, never silent).",
                "4. If clear: confirm the window is protected and stop (silence is success).",
            ]
        )
    lines.extend(
        [
            "",
            "### Operator ask",
            "Keep / reshape / pause this standing order?",
        ]
    )
    return lines


def _filled_schedule_recover(payload: dict[str, Any]) -> list[str]:
    task = str(payload.get("task_name") or payload.get("name") or "schedule")[:80]
    last = str(
        payload.get("last_result")
        or payload.get("error")
        or payload.get("last_status")
        or ""
    )[:240]
    lines = [
        "## Schedule recovery (filled)",
        f"- **Task:** {task}",
    ]
    if last:
        lines.append(f"- **Quoted failure:** {last}")
    else:
        lines.append("- **Quoted failure:** (none in payload — read last_result)")
    lines.extend(
        [
            "1. Diagnose: config vs deps vs flaky external.",
            "2. Propose one fix (patch config, install dep, or skip once).",
            "3. Do **not** silent re-run without approval.",
        ]
    )
    return lines


def parse_ics_events(text: str) -> list[dict[str, Any]]:
    """Minimal VEVENT parser for local calendar.ics / hook payloads."""
    events: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current and (current.get("uid") or current.get("summary")):
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.split(";")[0].upper()
        if key == "UID":
            current["uid"] = val.strip()
        elif key == "SUMMARY":
            current["title"] = val.strip()
            current["summary"] = val.strip()
        elif key == "DTSTART":
            current["starts_at"] = val.strip()
            current["dtstart"] = val.strip()
        elif key == "DTEND":
            current["ends_at"] = val.strip()
        elif key == "DESCRIPTION":
            current["description"] = val.replace("\\n", "\n").strip()
        elif key == "LOCATION":
            current["location"] = val.strip()
        elif key == "ATTENDEE":
            attendees = list(current.get("attendees") or [])
            # CN=Name:mailto:x or mailto:x
            name = val
            if "mailto:" in val.lower():
                name = val.split("mailto:")[-1]
            attendees.append(name.strip())
            current["attendees"] = attendees
    return events


def person_allows_ambient(consent: dict[str, Any] | None) -> bool:
    """Soft ACL: ambient help allowed unless consent.ambient is explicitly false."""
    if not consent:
        return True
    if consent.get("ambient") is False:
        return False
    return True


async def style_help_markdown(
    markdown: str,
    *,
    personality_manager: Any | None = None,
) -> tuple[str, dict[str, Any]]:
    """Apply lived personality lint to help body.

    Prefers fenced ``` draft blocks; otherwise lints the full markdown.
    Fail-open if lint fails or manager missing.
    """
    meta: dict[str, Any] = {"styled": False, "violations": []}
    if personality_manager is None or not markdown:
        return markdown, meta

    fence = "```"
    start = markdown.find(fence)
    if start >= 0:
        start_body = markdown.find("\n", start)
        if start_body >= 0:
            start_body += 1
            end = markdown.find(fence, start_body)
            if end >= 0:
                draft = markdown[start_body:end]
                try:
                    rewritten, result = await personality_manager.lint_and_enforce(
                        draft
                    )
                except Exception as e:
                    meta["error"] = str(e)[:120]
                    return markdown, meta
                if not rewritten:
                    meta["violations"] = list(getattr(result, "violations", []) or [])
                    return markdown, meta
                meta["styled"] = True
                meta["passed"] = bool(getattr(result, "passed", True))
                styled = (
                    markdown[:start_body] + rewritten.rstrip() + "\n" + markdown[end:]
                )
                return styled, meta

    try:
        rewritten, result = await personality_manager.lint_and_enforce(markdown)
    except Exception as e:
        meta["error"] = str(e)[:120]
        return markdown, meta
    if not rewritten:
        meta["violations"] = list(getattr(result, "violations", []) or [])
        return markdown, meta
    meta["styled"] = True
    meta["passed"] = bool(getattr(result, "passed", True))
    return rewritten, meta
