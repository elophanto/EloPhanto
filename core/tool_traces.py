"""Tool traces — what each checkpoint attempt called, and what came back.

The receipt gate has always seen a goal attempt's tool trail, but only for
as long as the attempt ran. Kept, the trail is two things: a replayable
recording (the benchmark in core/bench.py answers a model's tool calls from
it, so the model can be measured with no real tool running) and, for
attempts that passed every gate, training data (docs/95 Phases E and G).

Parameters are redacted before they are stored — any key that names a
secret, and every value passed to a ``vault_`` tool. Outputs are capped at
4 KB. Traces of failed attempts are pruned after two weeks; those of passed
attempts are kept, since they are the benchmark's cases.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

OUTPUT_CAP = 4096
PARAMS_CAP = 2048
RETAIN_FAILED_DAYS = 14

_SECRET_KEY = re.compile(
    r"pass(word|phrase)?|secret|token|api[_-]?key|private|credential|cookie|mnemonic|seed",
    re.I,
)
_REDACTED = "[redacted]"


def redact_params(tool: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """Params safe to store: secrets replaced, vault values never kept."""
    if not isinstance(params, dict):
        return {}
    if tool.startswith("vault_"):
        return {k: _REDACTED for k in params}
    out: dict[str, Any] = {}
    for k, v in params.items():
        if _SECRET_KEY.search(str(k)):
            out[k] = _REDACTED
        elif isinstance(v, dict):
            out[k] = redact_params("", v)
        else:
            out[k] = v
    return out


def output_json(result: Any) -> str:
    """A tool result as JSON text, capped. Replays parse it back."""
    try:
        payload = result.to_dict() if hasattr(result, "to_dict") else result
        return json.dumps(payload, default=str)[:OUTPUT_CAP]
    except Exception:
        return str(result)[:OUTPUT_CAP]


async def persist(
    db: Any,
    *,
    goal_id: str,
    checkpoint_order: int,
    attempt: int,
    trace: list[dict[str, Any]],
    started_at: str = "",
) -> None:
    """Store one attempt's trail. Best-effort: never fails the work.

    ``started_at`` — when the attempt began; stored as the rows' time so the
    benchmark can rebuild the ledger the attempt started from."""
    if not trace:
        return
    now = started_at or datetime.now(UTC).isoformat()
    rows = []
    for seq, row in enumerate(trace):
        params = row.get("call_params")
        try:
            params_text = json.dumps(
                params if isinstance(params, dict) else {}, default=str
            )
        except Exception:
            params_text = "{}"
        rows.append(
            (
                goal_id,
                int(checkpoint_order),
                int(attempt),
                seq,
                str(row.get("tool") or ""),
                params_text[:PARAMS_CAP],
                str(row.get("status") or ""),
                str(row.get("error") or "")[:500],
                str(row.get("output_json") or row.get("output") or "")[:OUTPUT_CAP],
                now,
            )
        )
    try:
        await db.execute_many(
            "INSERT INTO tool_traces (goal_id, checkpoint_order, attempt, seq, tool, "
            "params, status, error, output, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    except Exception as e:
        logger.debug("tool trace not stored: %s", e)


async def mark_passed(
    db: Any, *, goal_id: str, checkpoint_order: int, attempt: int
) -> None:
    try:
        await db.execute(
            "UPDATE tool_traces SET passed = 1 WHERE goal_id = ? AND checkpoint_order = ? "
            "AND attempt = ?",
            (goal_id, int(checkpoint_order), int(attempt)),
        )
    except Exception as e:
        logger.debug("tool trace not marked passed: %s", e)


async def prune(db: Any, *, days: int = RETAIN_FAILED_DAYS) -> None:
    """Drop failed attempts' traces older than ``days``."""
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    try:
        await db.execute(
            "DELETE FROM tool_traces WHERE passed = 0 AND created_at < ?", (cutoff,)
        )
    except Exception as e:
        logger.debug("tool trace prune failed: %s", e)


async def attempt_trace(
    db: Any, *, goal_id: str, checkpoint_order: int, attempt: int
) -> list[dict[str, Any]]:
    """One attempt's stored trail, in call order."""
    rows = await db.execute(
        "SELECT tool, params, status, error, output FROM tool_traces WHERE goal_id = ? "
        "AND checkpoint_order = ? AND attempt = ? ORDER BY seq",
        (goal_id, int(checkpoint_order), int(attempt)),
    )
    out = []
    for r in rows:
        try:
            params = json.loads(r["params"] or "{}")
        except ValueError:
            params = {}
        out.append(
            {
                "tool": r["tool"],
                "params": params if isinstance(params, dict) else {},
                "status": r["status"],
                "error": r["error"],
                "output": r["output"],
            }
        )
    return out
