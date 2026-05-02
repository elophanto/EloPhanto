"""Kid-environment registry filter — when ELOPHANTO_KID=true, the registry
must strip kid_*, payment_*, wallet_*, and polymarket_* tools so the kid
literally cannot see them."""

from __future__ import annotations

import os

from core.config import load_config
from core.registry import ToolRegistry


def _build_registry() -> ToolRegistry:
    cfg = load_config("config.yaml")
    r = ToolRegistry(cfg.llm)
    r.load_builtin_tools(cfg)
    return r


def test_normal_environment_has_kid_and_payment_tools() -> None:
    """Sanity: in the parent process, kid_* and payment_* tools are present."""
    if os.environ.get("ELOPHANTO_KID") == "true":
        # Ensure we're really not in kid mode for this test
        del os.environ["ELOPHANTO_KID"]
    r = _build_registry()
    names = {t.name for t in r.all_tools()}
    assert "kid_spawn" in names
    assert any(n.startswith("payment_") for n in names)


def test_kid_environment_strips_disallowed_tools() -> None:
    """In kid mode, the registry-level filter removes the disallowed tools."""
    os.environ["ELOPHANTO_KID"] = "true"
    try:
        r = _build_registry()
        names = {t.name for t in r.all_tools()}
        # No kid_* tools — depth=1
        assert not any(n.startswith("kid_") for n in names)
        # No payment / wallet / polymarket tools — kids never move money
        for prefix in ("payment_", "wallet_", "polymarket_"):
            assert not any(
                n.startswith(prefix) for n in names
            ), f"Kid mode leaked {prefix}* tools"
    finally:
        del os.environ["ELOPHANTO_KID"]


def test_kid_environment_keeps_normal_tools() -> None:
    """Kid mode strips the dangerous tools but keeps the rest."""
    os.environ["ELOPHANTO_KID"] = "true"
    try:
        r = _build_registry()
        names = {t.name for t in r.all_tools()}
        # Core tools the kid genuinely needs
        for needed in ("shell_execute", "file_read", "file_write", "knowledge_search"):
            assert needed in names, f"kid mode incorrectly removed {needed}"
    finally:
        del os.environ["ELOPHANTO_KID"]
