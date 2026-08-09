"""Hosted (EloPhanto Cloud) product laws.

When ``ELOPHANTO_CLOUD=1``, the runtime is a managed always-on instance —
not self-custody on the operator's laptop. These helpers enforce the
non-negotiable Hosted trust laws while leaving EloPhanto Open (local CLI)
unchanged.

Laws (summary):
  L0  Honesty — managed custody (label, never claim self-custody)
  L1  Nuclear absent — max mode is full_auto + CRITICAL always-ask
  L2  Money — exportable hot-wallet tooling stays ask/deny by profile
  L3  Shell — profile forces ask on shell_execute
  L4  Browser — dedicated fresh profile (applied in config load)
  L5  Email — ABE fail-closed remains company trust gate
  L6  Approvals — CRITICAL always asks (nuclear gone)
  L7  Ops — provisioner mints auth; gateway fail-closed without token
  L8  Kill — owner kill/freeze endpoints (gateway commands)
  L9  Planes — control writes cannot raise mode to nuclear
"""

from __future__ import annotations

import os
from typing import Final

HOSTED_ENV: Final[str] = "ELOPHANTO_CLOUD"

# Permission modes allowed on Hosted. nuclear is intentionally absent.
HOSTED_PERMISSION_MODES: Final[tuple[str, ...]] = (
    "ask_always",
    "smart_auto",
    "full_auto",
)

OPEN_PERMISSION_MODES: Final[tuple[str, ...]] = (
    *HOSTED_PERMISSION_MODES,
    "nuclear",
)

HOSTED_MAX_PERMISSION_MODE: Final[str] = "full_auto"

HOSTED_CUSTODY_LABEL: Final[str] = (
    "Managed custody. This instance runs on infrastructure we operate. "
    "We can access this box under break-glass. It is not self-custody."
)


def is_hosted() -> bool:
    """True when this process is a Hosted / cloud instance."""
    return os.environ.get(HOSTED_ENV) == "1"


def allowed_permission_modes() -> tuple[str, ...]:
    """Modes the UI / Telegram / config_update may offer."""
    if is_hosted():
        return HOSTED_PERMISSION_MODES
    return OPEN_PERMISSION_MODES


def clamp_permission_mode(mode: str) -> str:
    """Clamp a requested mode to what this deployment allows.

    Hosted: nuclear → full_auto; unknown → ask_always (never promote).
    Open: unknown → ask_always; nuclear kept.
    """
    mode = (mode or "").strip().lower()
    allowed = allowed_permission_modes()
    if mode in allowed:
        return mode
    if is_hosted() and mode == "nuclear":
        return HOSTED_MAX_PERMISSION_MODE
    return "ask_always"


def nuclear_forbidden_reason() -> str | None:
    """Human reason if nuclear cannot be enabled, else None."""
    if is_hosted():
        return (
            "nuclear is not available on EloPhanto Hosted. "
            "Max mode is full_auto (CRITICAL actions still require approval). "
            "Use EloPhanto Open for nuclear on your own machine."
        )
    return None


def custody_banner() -> str | None:
    """In-product custody honesty string for Hosted surfaces."""
    if is_hosted():
        return HOSTED_CUSTODY_LABEL
    return None


def require_gateway_auth() -> bool:
    """Hosted must never bind publicly without an auth token."""
    return is_hosted()
