"""Training data from verified runs (docs/95 Phase G).

Two files, from the recorded tool traces and the ledger:

  ``sft.jsonl``         checkpoint attempts that passed every gate, as chat
                        trajectories with tool calls — the prompt the
                        attempt started from, each call and what it returned,
                        and the checkpoint's result.
  ``preference.jsonl``  the same checkpoint failing and then passing:
                        the prompt, the passing trajectory (chosen) and the
                        failed one (rejected).

Parameters were redacted when the traces were stored; every text field is
also passed through the PII redactor here. Fine-tuning itself is not done
here — it needs GPU infrastructure and a trainable model — the export is the
part that did not exist.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.goal_runner import build_checkpoint_prompt
from core.pii_guard import redact_pii
from core.run_ledger import RunLedger
from core.tool_traces import attempt_trace


def _trajectory(recording: list[dict[str, Any]], final: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for i, call in enumerate(recording, 1):
        call_id = f"call_{i}"
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": call["tool"],
                            "arguments": redact_pii(
                                json.dumps(call.get("params") or {})
                            ),
                        },
                    }
                ],
            }
        )
        output = call.get("output") or (
            json.dumps({"success": False, "error": call.get("error") or ""})
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": redact_pii(str(output)),
            }
        )
    if final:
        messages.append({"role": "assistant", "content": redact_pii(final)})
    return messages


async def _prompt(
    db: Any, goal: dict[str, Any], cp: dict[str, Any], started: str
) -> str:
    ledger = await RunLedger(db).render(
        str(goal["goal_id"]),
        checkpoint_order=int(cp["checkpoint_order"]),
        before=started,
    )
    return redact_pii(
        build_checkpoint_prompt(
            goal=str(goal.get("goal") or ""),
            order=int(cp["checkpoint_order"]),
            total=int(goal.get("total_checkpoints") or cp["checkpoint_order"]),
            title=str(cp.get("title") or ""),
            stage=str(cp.get("stage") or ""),
            description=str(cp.get("description") or ""),
            criteria=str(cp.get("success_criteria") or ""),
            context="",
            ledger=ledger,
        )
    )


async def export(db: Any, out_dir: Path, *, limit: int = 1000) -> dict[str, Any]:
    """Write ``sft.jsonl`` and ``preference.jsonl`` under ``out_dir``."""
    attempts = await db.execute(
        "SELECT goal_id, checkpoint_order, attempt, MAX(passed) AS passed, "
        "MIN(created_at) AS started FROM tool_traces "
        "GROUP BY goal_id, checkpoint_order, attempt ORDER BY MIN(id) DESC LIMIT ?",
        (int(limit),),
    )
    by_checkpoint: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for a in attempts:
        by_checkpoint.setdefault(
            (str(a["goal_id"]), int(a["checkpoint_order"])), []
        ).append(dict(a))

    out_dir.mkdir(parents=True, exist_ok=True)
    sft_path, pref_path = out_dir / "sft.jsonl", out_dir / "preference.jsonl"
    n_sft = n_pref = 0
    with (
        sft_path.open("w", encoding="utf-8") as sft,
        pref_path.open("w", encoding="utf-8") as pref,
    ):
        for (goal_id, order), tries in by_checkpoint.items():
            passed = [t for t in tries if int(t["passed"])]
            if not passed:
                continue
            goals = await db.execute(
                "SELECT * FROM goals WHERE goal_id = ?", (goal_id,)
            )
            cps = await db.execute(
                "SELECT * FROM goal_checkpoints WHERE goal_id = ? AND checkpoint_order = ?",
                (goal_id, order),
            )
            if not goals or not cps:
                continue
            goal, cp = dict(goals[0]), dict(cps[0])
            final = (
                str(cp.get("result_summary") or "").split("\n[receipt]", 1)[0].strip()
            )
            win = passed[0]
            win_rec = await attempt_trace(
                db, goal_id=goal_id, checkpoint_order=order, attempt=int(win["attempt"])
            )
            if not win_rec:
                continue
            prompt = await _prompt(db, goal, cp, str(win["started"]))
            chosen = _trajectory(win_rec, final)
            meta = {
                "goal_id": goal_id,
                "checkpoint_order": order,
                "attempt": int(win["attempt"]),
            }
            sft.write(
                json.dumps(
                    {
                        "messages": [{"role": "user", "content": prompt}, *chosen],
                        "metadata": meta,
                    }
                )
                + "\n"
            )
            n_sft += 1
            # A failure before the pass, answered from the same starting point.
            for lost in sorted(
                (
                    t
                    for t in tries
                    if not int(t["passed"]) and int(t["attempt"]) < int(win["attempt"])
                ),
                key=lambda t: int(t["attempt"]),
            ):
                lost_rec = await attempt_trace(
                    db,
                    goal_id=goal_id,
                    checkpoint_order=order,
                    attempt=int(lost["attempt"]),
                )
                if not lost_rec:
                    continue
                lost_prompt = await _prompt(db, goal, cp, str(lost["started"]))
                pref.write(
                    json.dumps(
                        {
                            "prompt": [{"role": "user", "content": lost_prompt}],
                            "chosen": chosen,
                            "rejected": _trajectory(lost_rec, ""),
                            "metadata": {
                                **meta,
                                "rejected_attempt": int(lost["attempt"]),
                            },
                        }
                    )
                    + "\n"
                )
                n_pref += 1
    return {
        "sft": n_sft,
        "preference": n_pref,
        "sft_path": sft_path,
        "preference_path": pref_path,
    }
