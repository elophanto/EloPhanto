"""Agent fingerprint — immutable identity anchor for self-verification.

On first boot, generates a unique fingerprint from the agent's config and
vault salt. Stored in the vault. On subsequent boots, verifies that the
stored fingerprint matches the current config — detects tampering or
config drift.

The fingerprint is:
- Included in <runtime_state> for the LLM's self-awareness
- Never exposed to external users or channels
- A code-level check, not a prompt-level one

See docs/27-SECURITY-HARDENING.md (Gap 3: Self-Identity Model).
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_VAULT_KEY = "_agent_fingerprint"


def generate_fingerprint(config_hash: str, vault_salt_hash: str) -> str:
    """Generate a deterministic SHA-256 fingerprint.

    Args:
        config_hash: Hash of stable config fields.
        vault_salt_hash: Hash of the vault salt file.

    Returns:
        Hex-encoded SHA-256 fingerprint (64 chars).
    """
    material = f"elophanto:fingerprint:{config_hash}:{vault_salt_hash}"
    return hashlib.sha256(material.encode()).hexdigest()


def compute_config_hash(config: Any) -> str:
    """Hash deterministic config fields.

    Only includes fields that define the agent's identity — not volatile
    runtime settings like budget amounts, wakeup intervals, etc.
    """
    stable_fields = {
        "agent_name": getattr(config, "agent_name", "EloPhanto"),
        "project_root": str(getattr(config, "project_root", "")),
        "permission_mode": getattr(config, "permission_mode", ""),
    }
    raw = json.dumps(stable_fields, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def compute_vault_salt_hash(project_root: Path) -> str:
    """Hash the vault salt file contents.

    Returns empty string if the salt file doesn't exist (no vault).
    """
    salt_path = project_root / "vault.salt"
    if not salt_path.exists():
        return ""
    try:
        salt_bytes = salt_path.read_bytes()
        return hashlib.sha256(salt_bytes).hexdigest()
    except Exception:
        return ""


def get_or_create_fingerprint(
    vault: Any,
    config_hash: str,
    vault_salt_hash: str,
) -> tuple[str, str]:
    """Get or create the agent fingerprint.

    Args:
        vault: Vault instance with get()/set() methods.
        config_hash: Current config hash.
        vault_salt_hash: Current vault salt hash.

    Returns:
        Tuple of (fingerprint_hex, status) where status is one of:
        - "verified": stored fingerprint matches current config
        - "created": first boot, fingerprint was generated and stored
        - "changed": config drift detected, fingerprint re-stamped
    """
    current = generate_fingerprint(config_hash, vault_salt_hash)

    stored_data = vault.get(_VAULT_KEY)
    if stored_data is None:
        # First boot — store fingerprint
        vault.set(
            _VAULT_KEY,
            {
                "fingerprint": current,
                "config_hash": config_hash,
                "vault_salt_hash": vault_salt_hash,
            },
        )
        logger.info("Agent fingerprint created: %s...%s", current[:8], current[-4:])
        return current, "created"

    stored_fp = (
        stored_data.get("fingerprint", "") if isinstance(stored_data, dict) else ""
    )

    if stored_fp == current:
        logger.debug("Agent fingerprint verified")
        return current, "verified"

    # Config drift — re-stamp
    vault.set(
        _VAULT_KEY,
        {
            "fingerprint": current,
            "config_hash": config_hash,
            "vault_salt_hash": vault_salt_hash,
            "previous_fingerprint": stored_fp,
        },
    )
    logger.warning(
        "Agent fingerprint changed (config drift): %s...%s → %s...%s",
        stored_fp[:8],
        stored_fp[-4:] if stored_fp else "",
        current[:8],
        current[-4:],
    )
    return current, "changed"
