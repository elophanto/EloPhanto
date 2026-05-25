"""Active-role contextvar — the per-cycle role EloPhanto is playing.

EloPhanto IS the CEO by default (the contextvar default is ``None`` —
no overlay, full tool access). The autonomous mind sets a non-default
role per cycle when the arbiter picks a role-neglect candidate; the
CLI sets it from ``~/.elophanto/current_role`` so an operator can
manually scope a session to e.g. ``sales`` while debugging that role's
behavior.

Identical pattern to ``core.company`` — same contextvar API, same
sidecar-file persistence. See ``docs/76-ABE-FRAMEWORK.md`` §Phase 2.
"""

from __future__ import annotations

import contextvars
from pathlib import Path

_current_role: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "elophanto_current_role", default=None
)


def current_role() -> str | None:
    """Return the active role name, or ``None`` if no overlay is active.

    ``None`` means "EloPhanto playing the CEO by default" — full tool
    access, no prompt overlay. This is the safe default for any code
    path that hasn't been wired to set a role explicitly.
    """
    return _current_role.get()


def set_current_role(name: str | None) -> contextvars.Token[str | None]:
    """Switch the active role. Returns a token usable with reset()."""
    return _current_role.set(name)


def reset_current_role(token: contextvars.Token[str | None]) -> None:
    _current_role.reset(token)


_CURRENT_ROLE_FILE = Path.home() / ".elophanto" / "current_role"


def read_persisted_current_role() -> str | None:
    """Read the operator's selected role from the sidecar file.

    Returns ``None`` if the file is missing, empty, or unreadable.
    Never raises — a corrupt sidecar file falls back to the default.
    """
    try:
        if not _CURRENT_ROLE_FILE.exists():
            return None
        name = _CURRENT_ROLE_FILE.read_text(encoding="utf-8").strip()
        return name or None
    except OSError:
        return None


def write_persisted_current_role(name: str | None) -> None:
    """Persist the operator's selected role. ``None`` clears the file."""
    if name is None:
        try:
            _CURRENT_ROLE_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        return
    _CURRENT_ROLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CURRENT_ROLE_FILE.write_text(name, encoding="utf-8")
