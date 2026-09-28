"""The run ledger — durable working state for long-running work.

A goal's checkpoints used to share one thing: ``goals.context_summary``, an
LLM digest of the first 500 characters of each checkpoint's final answer.
Everything else a run learned — the files it wrote, the URLs it found, the
approach that failed and why, the half-finished step it was on when it was
interrupted — was discarded at the checkpoint boundary. A retry started blind,
a preempted checkpoint started from zero, and the only way to resume was for
the operator to say "continue" and for the agent to rediscover its own work.

The ledger is an append-only record per goal (``thread_id``), written as the
work happens:

  artifact  — a file / URL / id the work produced (written by code, from the
              tool trail — never paraphrased by the model)
  fact      — something established, with the receipt that established it
  decision  — what was chosen, why, and what was rejected
  failure   — an attempt that did not pass, and why
  question  — an open question or blocker (status open|closed)
  handoff   — where an interrupted run got to and what comes next
  plan      — the plan an attempt committed to before acting

It is rendered into every checkpoint prompt, so the next attempt — after a
retry, a preemption or a restart — starts from what is known instead of
from a prose summary. See docs/94-LONG-RUN-AUTONOMY-REVIEW.md §5.1 and §9.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LEDGER_KINDS: tuple[str, ...] = (
    "artifact",
    "fact",
    "decision",
    "failure",
    "question",
    "handoff",
    "plan",
)

# Tool-parameter keys that name something the call produced.
_ARTIFACT_PARAM_KEYS: tuple[str, ...] = (
    "path",
    "file_path",
    "output_path",
    "url",
    "filename",
)
# Result keys that name something a tool produced or found.
_ARTIFACT_RESULT_KEYS: tuple[str, ...] = (
    "path",
    "file_path",
    "output_path",
    "url",
    "post_url",
    "deployment_url",
    "id",
)
# A tool is a producer if its name says it creates, sends or saves something.
# Reads (file_read, browser_navigate, web_search) are not artifacts.
_PRODUCER_MARKERS: tuple[str, ...] = (
    "write",
    "create",
    "save",
    "publish",
    "post",
    "send",
    "upload",
    "export",
    "generate",
    "deploy",
    "scorecard",
    "report",
    "deck",
    "patch",
    "move",
    "note",
    "draft",
)


@dataclass(frozen=True)
class LedgerEntry:
    id: int
    thread_id: str
    checkpoint_order: int | None
    attempt: int
    kind: str
    content: str
    ref: str
    source: str
    status: str
    created_at: str


def _is_producer(tool_name: str) -> bool:
    name = (tool_name or "").lower()
    return any(marker in name for marker in _PRODUCER_MARKERS)


def extract_artifacts(tool_trace: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """``(ref, description)`` pairs for what a checkpoint's tools produced.

    Code, not the model, decides what counts: a producer tool's path/url
    parameters, and any path/url/id a successful tool returned. Deduplicated
    by ref, in trail order.
    """
    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    def _add(ref: Any, desc: str) -> None:
        text = str(ref or "").strip()
        if not text or len(text) > 500 or text in seen:
            return
        seen.add(text)
        out.append((text, desc))

    for row in tool_trace or []:
        if (row.get("status") or "") != "ok" or row.get("error"):
            continue
        tool = str(row.get("tool") or "")
        params = row.get("params") or row.get("data") or {}
        if _is_producer(tool) and isinstance(params, dict):
            for key in _ARTIFACT_PARAM_KEYS:
                if params.get(key):
                    _add(params[key], f"{tool} {key}")
        result = row.get("result_data")
        if isinstance(result, dict):
            for key in _ARTIFACT_RESULT_KEYS:
                val = result.get(key)
                if isinstance(val, (str, int)) and str(val):
                    if key == "id" and not _is_producer(tool):
                        continue  # ids from reads are lookups, not products
                    _add(val, f"{tool} returned {key}")
    return out


class RunLedger:
    """Read/write access to the ``run_ledger`` table."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def add(
        self,
        thread_id: str,
        kind: str,
        content: str,
        *,
        checkpoint_order: int | None = None,
        attempt: int = 0,
        ref: str = "",
        source: str = "model",
        status: str = "",
    ) -> int:
        """Append one entry. Returns its id (0 on failure — never raises)."""
        if kind not in LEDGER_KINDS:
            raise ValueError(f"unknown ledger kind {kind!r}; one of {LEDGER_KINDS}")
        text = (content or "").strip()
        if not text:
            return 0
        if kind == "question" and not status:
            status = "open"
        try:
            return int(
                await self._db.execute_insert(
                    "INSERT INTO run_ledger (thread_id, checkpoint_order, attempt, kind, "
                    "content, ref, source, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        thread_id,
                        checkpoint_order,
                        int(attempt or 0),
                        kind,
                        text[:4000],
                        (ref or "")[:500],
                        source,
                        status,
                        datetime.now(UTC).isoformat(),
                    ),
                )
                or 0
            )
        except Exception as e:
            logger.warning("run_ledger add failed (%s/%s): %s", thread_id, kind, e)
            return 0

    async def record_artifacts(
        self,
        thread_id: str,
        tool_trace: list[dict[str, Any]],
        *,
        checkpoint_order: int | None,
        attempt: int,
    ) -> int:
        """Add an artifact row for each new thing the trail produced."""
        existing = {e.ref for e in await self.entries(thread_id, kinds=("artifact",))}
        added = 0
        for ref, desc in extract_artifacts(tool_trace):
            if ref in existing:
                continue
            if await self.add(
                thread_id,
                "artifact",
                desc,
                ref=ref,
                checkpoint_order=checkpoint_order,
                attempt=attempt,
                source="code",
            ):
                added += 1
                existing.add(ref)
        return added

    async def close_question(self, entry_id: int) -> bool:
        try:
            await self._db.execute(
                "UPDATE run_ledger SET status = 'closed' WHERE id = ? AND kind = 'question'",
                (entry_id,),
            )
            return True
        except Exception:
            return False

    async def entries(
        self,
        thread_id: str,
        *,
        kinds: tuple[str, ...] | None = None,
        limit: int = 500,
    ) -> list[LedgerEntry]:
        try:
            if kinds:
                marks = ",".join("?" for _ in kinds)
                rows = await self._db.execute(
                    f"SELECT * FROM run_ledger WHERE thread_id = ? AND kind IN ({marks}) "
                    "ORDER BY id ASC LIMIT ?",
                    (thread_id, *kinds, limit),
                )
            else:
                rows = await self._db.execute(
                    "SELECT * FROM run_ledger WHERE thread_id = ? ORDER BY id ASC LIMIT ?",
                    (thread_id, limit),
                )
        except Exception as e:
            logger.debug("run_ledger read failed for %s: %s", thread_id, e)
            return []
        return [
            LedgerEntry(
                id=r["id"],
                thread_id=r["thread_id"],
                checkpoint_order=r["checkpoint_order"],
                attempt=r["attempt"],
                kind=r["kind"],
                content=r["content"],
                ref=r["ref"],
                source=r["source"],
                status=r["status"],
                created_at=r["created_at"],
            )
            for r in rows or []
        ]

    async def latest_handoff(
        self, thread_id: str, checkpoint_order: int | None = None
    ) -> LedgerEntry | None:
        rows = await self.entries(thread_id, kinds=("handoff",))
        if checkpoint_order is not None:
            rows = [r for r in rows if r.checkpoint_order == checkpoint_order]
        return rows[-1] if rows else None

    async def delete_thread(self, thread_id: str) -> None:
        try:
            await self._db.execute(
                "DELETE FROM run_ledger WHERE thread_id = ?", (thread_id,)
            )
        except Exception as e:
            logger.debug("run_ledger delete failed for %s: %s", thread_id, e)

    async def render(
        self,
        thread_id: str,
        *,
        checkpoint_order: int | None = None,
        max_chars: int = 4000,
    ) -> str:
        """The ledger as a prompt block. Empty string when there is nothing.

        Sections are ordered by how much a resuming run needs them: the
        handoff and failures for the current checkpoint first, then what
        exists (artifacts), what is known (facts, decisions), what is open.
        """
        all_rows = await self.entries(thread_id)
        if not all_rows:
            return ""

        def _cp(e: LedgerEntry) -> str:
            return (
                f"#{e.checkpoint_order}" if e.checkpoint_order is not None else "goal"
            )

        sections: list[str] = []

        handoffs = [e for e in all_rows if e.kind == "handoff"]
        if checkpoint_order is not None:
            mine = [e for e in handoffs if e.checkpoint_order == checkpoint_order]
            if mine:
                sections.append(
                    "WHERE THE LAST RUN OF THIS CHECKPOINT STOPPED:\n"
                    + mine[-1].content[:1500]
                )

        failures = [e for e in all_rows if e.kind == "failure"]
        if checkpoint_order is not None:
            failures = [e for e in failures if e.checkpoint_order == checkpoint_order]
        if failures:
            lines = [f"- attempt {e.attempt}: {e.content[:300]}" for e in failures[-5:]]
            sections.append(
                "FAILED ATTEMPTS (do not repeat these):\n" + "\n".join(lines)
            )

        plans = [e for e in all_rows if e.kind == "plan"]
        if checkpoint_order is not None:
            plans = [e for e in plans if e.checkpoint_order == checkpoint_order]
        if plans:
            sections.append(
                "LAST PLAN FOR THIS CHECKPOINT:\n" + plans[-1].content[:1200]
            )

        artifacts = [e for e in all_rows if e.kind == "artifact"]
        if artifacts:
            lines = [
                f"- [{_cp(e)}] {e.ref} ({e.content[:80]})" for e in artifacts[-30:]
            ]
            more = len(artifacts) - 30
            head = "ARTIFACTS (exist — reuse, do not recreate):"
            if more > 0:
                head += f" ({more} older omitted)"
            sections.append(head + "\n" + "\n".join(lines))

        facts = [e for e in all_rows if e.kind == "fact"]
        if facts:
            lines = [
                f"- [{_cp(e)}] {e.content[:240]}"
                + (f" (source: {e.ref})" if e.ref else "")
                for e in facts[-20:]
            ]
            sections.append("ESTABLISHED FACTS:\n" + "\n".join(lines))

        decisions = [e for e in all_rows if e.kind == "decision"]
        if decisions:
            lines = [f"- [{_cp(e)}] {e.content[:300]}" for e in decisions[-12:]]
            sections.append("DECISIONS (and why):\n" + "\n".join(lines))

        questions = [
            e for e in all_rows if e.kind == "question" and e.status != "closed"
        ]
        if questions:
            lines = [f"- (id {e.id}) {e.content[:240]}" for e in questions[-10:]]
            sections.append("OPEN QUESTIONS / BLOCKERS:\n" + "\n".join(lines))

        text = "\n\n".join(sections)
        if len(text) > max_chars:
            text = text[: max_chars - 40].rstrip() + "\n[ledger truncated]"
        return text

    async def write_markdown(
        self, thread_id: str, path: Path, *, title: str = ""
    ) -> None:
        """Mirror the ledger to a readable file (best-effort)."""
        rows = await self.entries(thread_id)
        if not rows:
            return
        lines = [f"# Run ledger — {title or thread_id}", ""]
        for kind in LEDGER_KINDS:
            of_kind = [e for e in rows if e.kind == kind]
            if not of_kind:
                continue
            lines.append(f"## {kind}s")
            for e in of_kind:
                where = (
                    f"#{e.checkpoint_order}"
                    if e.checkpoint_order is not None
                    else "goal"
                )
                ref = f" — `{e.ref}`" if e.ref else ""
                status = f" [{e.status}]" if e.status else ""
                lines.append(
                    f"- {e.created_at[:16]} {where} a{e.attempt}{status}: "
                    f"{e.content.replace(chr(10), ' ')[:600]}{ref}"
                )
            lines.append("")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines), encoding="utf-8")
        except Exception as e:
            logger.debug("ledger markdown write failed for %s: %s", thread_id, e)
