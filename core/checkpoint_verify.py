"""Checkpoint verification — checks run by code, or by independent judges.

The receipt gate (core/checkpoint_receipt.py) is a smell test: it refuses a
completion that no tool output supports. It cannot tell whether the file was
written, the page is live, or the analysis is any good. A checkpoint may
therefore carry a ``verification`` — one check or a list, all of which must
pass — declared when the plan is made:

  {"type": "tool_output", "tool": "watch_list", "contains": "14"}
  {"type": "file_exists", "path": "reports/q3.md", "contains": "Summary", "min_bytes": 200}
  {"type": "url_ok", "url": "https://example.com/launch", "contains": "Pricing"}
  {"type": "artifact", "contains": "q3.md"}
  {"type": "judgment", "pack": "analysis", "focus": "are the rankings supported?"}

Code checks cost nothing and cannot be argued with. ``judgment`` convenes
an independent panel (core/panel.py) — never the model that did the work —
for checkpoints whose quality is the point. Unknown check types are ignored
rather than failed: a malformed plan must not wedge a goal. See
docs/94-LONG-RUN-AUTONOMY-REVIEW.md §11.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

CHECK_TYPES = ("tool_output", "file_exists", "url_ok", "artifact", "judgment")
_MAX_READ_BYTES = 1_000_000


@dataclass
class VerificationResult:
    ok: bool
    reason: str = ""
    findings: list[str] = field(default_factory=list)
    checked: int = 0


def parse_checks(raw: Any) -> list[dict[str, Any]]:
    """Normalise a stored ``verification`` value into a list of checks."""
    if raw is None or raw == "":
        return []
    value = raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    return [c for c in value if isinstance(c, dict) and c.get("type") in CHECK_TYPES]


def _resolve_path(path: str, workspace: str) -> Path:
    p = Path(path).expanduser()
    if p.is_absolute() or not workspace:
        return p
    return Path(workspace) / p


def _check_tool_output(check: dict[str, Any], tool_trace: list[dict[str, Any]]) -> str:
    tool = str(check.get("tool") or "").strip()
    needle = str(check.get("contains") or "").strip().lower()
    for row in tool_trace:
        if (row.get("status") or "") != "ok" or row.get("error"):
            continue
        if tool and row.get("tool") != tool:
            continue
        if not needle or needle in str(row.get("output") or "").lower():
            return ""
    what = f"'{tool}'" if tool else "any tool"
    return (
        f"no successful {what} call this attempt returned {needle!r}"
        if needle
        else (f"no successful {what} call this attempt")
    )


def _check_file(check: dict[str, Any], workspace: str) -> str:
    raw = str(check.get("path") or "").strip()
    if not raw:
        return ""
    p = _resolve_path(raw, workspace)
    if not p.is_file():
        return f"file {raw} does not exist"
    size = p.stat().st_size
    min_bytes = int(check.get("min_bytes") or 0)
    if min_bytes and size < min_bytes:
        return f"file {raw} is {size} bytes, expected at least {min_bytes}"
    needle = str(check.get("contains") or "")
    if needle:
        try:
            with p.open("rb") as fh:
                text = fh.read(_MAX_READ_BYTES).decode("utf-8", errors="replace")
        except OSError as e:
            return f"file {raw} could not be read: {e}"
        if needle.lower() not in text.lower():
            return f"file {raw} does not contain {needle!r}"
    return ""


async def _check_url(check: dict[str, Any]) -> str:
    url = str(check.get("url") or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return f"url {url} is not an http(s) URL"
    from core.net_policy import classify_host

    blocked, why = classify_host(parts.hostname)
    if blocked:
        return f"url {url} is not a public address ({why})"
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
    except Exception as e:
        return f"url {url} did not answer: {str(e)[:120]}"
    if resp.status_code >= 400:
        return f"url {url} returned HTTP {resp.status_code}"
    needle = str(check.get("contains") or "")
    if needle and needle.lower() not in resp.text[:200_000].lower():
        return f"url {url} does not contain {needle!r}"
    return ""


def _check_artifact(check: dict[str, Any], artifact_refs: list[str]) -> str:
    needle = str(check.get("contains") or "").strip().lower()
    if not needle:
        return ""
    if any(needle in ref.lower() for ref in artifact_refs):
        return ""
    return f"no recorded artifact matches {needle!r}"


async def _check_judgment(
    check: dict[str, Any],
    *,
    router: Any,
    criteria: str,
    result_text: str,
    evidence: str,
) -> tuple[str, list[str]]:
    """Convene an independent panel. Returns (failure reason, findings)."""
    if router is None:
        return "", []
    from core.panel import LENS_PACKS, QualityBar, assess, run_panel

    pack = str(check.get("pack") or "analysis")
    lenses = list(LENS_PACKS.get(pack) or LENS_PACKS.get("analysis") or [])
    if not lenses:
        return "", []
    focus = str(check.get("focus") or "").strip()
    goal = f"Success criteria: {criteria}" + (
        f"\nJudge especially: {focus}" if focus else ""
    )
    artifact = f"{result_text[:6000]}\n\nEVIDENCE FROM THE WORK:\n{evidence[:6000]}"

    from core.deliberation import judge_complete

    async def judge(prompt: str, _lens: Any) -> str:
        resp = await judge_complete(
            router,
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=900,
        )
        return resp.content or ""

    verdicts = await run_panel(artifact, lenses, judge, goal=goal)
    ok, why, _mean = assess(verdicts, QualityBar(min_score=3.5, max_rounds=1))
    if ok:
        return "", []
    findings = [f"[{v.lens}] {f}" for v in verdicts for f in v.actionable_findings]
    return f"panel review: {why}", findings[:12]


async def verify_checkpoint(
    raw_checks: Any,
    *,
    tool_trace: list[dict[str, Any]],
    artifact_refs: list[str],
    workspace: str,
    router: Any,
    criteria: str,
    result_text: str,
) -> VerificationResult:
    """Run every declared check. All must pass."""
    checks = parse_checks(raw_checks)
    if not checks:
        return VerificationResult(ok=True, reason="no verification declared")
    evidence = "\n".join(
        f"- {row.get('tool')}: {str(row.get('output') or '')[:400]}"
        for row in tool_trace[-12:]
        if (row.get("status") or "") == "ok"
    )
    evidence += "\nArtifacts: " + ", ".join(artifact_refs[-20:])
    failures: list[str] = []
    findings: list[str] = []
    for check in checks:
        kind = check.get("type")
        try:
            if kind == "tool_output":
                problem = _check_tool_output(check, tool_trace)
            elif kind == "file_exists":
                problem = _check_file(check, workspace)
            elif kind == "url_ok":
                problem = await _check_url(check)
            elif kind == "artifact":
                problem = _check_artifact(check, artifact_refs)
            else:
                problem, found = await _check_judgment(
                    check,
                    router=router,
                    criteria=criteria,
                    result_text=result_text,
                    evidence=evidence,
                )
                findings.extend(found)
        except Exception as e:  # a broken check is not the work's fault
            logger.warning("verification check %s errored: %s", kind, e)
            problem = ""
        if problem:
            failures.append(problem)
    if failures:
        return VerificationResult(
            ok=False, reason="; ".join(failures), findings=findings, checked=len(checks)
        )
    return VerificationResult(
        ok=True, reason=f"{len(checks)} check(s) passed", checked=len(checks)
    )
