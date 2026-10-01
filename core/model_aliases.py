"""Retired model ids and the model that replaces each one.

A config written before a model retired keeps working: the router swaps the
retired id for its replacement at call time, and ``elophanto config migrate``
rewrites the file. Matching is on the last path segment, so ``gpt-5.5``,
``codex/gpt-5.5`` and ``openai/gpt-5.5`` all resolve.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Codex retired the gpt-5.5 family on 2026-10-14; EloPhanto dropped it too.
RETIRED_MODELS: dict[str, str] = {
    "gpt-5.5": "gpt-6.1-sol",
    "gpt-5.5-mini": "gpt-6-luna",
}

_warned: set[str] = set()


def current_model(model: str) -> str:
    """Return ``model`` with a retired id replaced; other ids pass through."""
    if not model:
        return model
    prefix, _, name = model.rpartition("/")
    replacement = RETIRED_MODELS.get(name)
    if replacement is None:
        return model
    resolved = f"{prefix}/{replacement}" if prefix else replacement
    if model not in _warned:
        _warned.add(model)
        logger.warning(
            "Model %s is retired; using %s. Run `elophanto config migrate` "
            "to update config.yaml.",
            model,
            resolved,
        )
    return resolved
