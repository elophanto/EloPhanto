"""Shared helpers for parsing browser_eval results.

The Node.js bridge's ``browser_eval`` returns a dict shaped like
``{"success": bool, "expression": str, "resultJson": str, "error": str | None}``
where ``resultJson`` is a JSON-stringified value (e.g. ``'"found"'`` for
the string ``found``, ``"42"`` for the number, ``"null"`` if absent).

For a long time, several Python callers read ``result["result"]`` — a
key that does not exist — and silently treated every eval as returning
an empty string. That made multi-step browser flows fail in non-obvious
ways (e.g. ``twitter_post`` reporting "Could not find tweet text box"
even when the text box was clearly present).

This module centralizes the right way to read those results.
"""

from __future__ import annotations

import json
from typing import Any


def eval_value(result: Any) -> Any:
    """Decode a ``browser_eval`` tool result into the underlying Python value.

    Reads the bridge's ``resultJson`` field and JSON-decodes it, falling
    back gracefully when the input is shaped differently (e.g. a legacy
    ``{"result": ...}`` envelope, a bare string, or a missing field).

    Returns ``None`` when no recognizable value field is present.
    """
    if not isinstance(result, dict):
        return result

    raw = result.get("resultJson")
    if raw is None:
        # Tolerate legacy / direct-return envelopes
        legacy = result.get("result")
        if legacy is not None:
            return legacy
        return None

    if not isinstance(raw, str):
        return raw

    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw
