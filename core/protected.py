"""Protected files system — prevents the agent from modifying safety-critical code.

Defines which files are immutable and provides a check function used by
file write/delete tools and the shell executor.
"""

from __future__ import annotations

from pathlib import Path

PROTECTED_PATHS: set[str] = {
    "core/protected.py",
    "core/executor.py",
    "core/vault.py",
    "core/config.py",
    "core/registry.py",
    "core/log_setup.py",
    "permissions.yaml",
}

PROTECTED_PREFIXES: tuple[str, ...] = ("core/protected",)


def is_protected(path: str | Path, project_root: Path | None = None) -> bool:
    """Check whether a path points to a protected file.

    Resolves the path relative to the project root and checks against
    both exact matches and prefix patterns.
    """
    p = Path(path)

    if project_root is not None:
        try:
            p = p.resolve().relative_to(project_root.resolve())
        except ValueError:
            return False

    p_str = str(p)

    if p_str in PROTECTED_PATHS:
        return True

    for prefix in PROTECTED_PREFIXES:
        if p_str.startswith(prefix):
            return True

    return False


def check_command_for_protected(
    command: str, project_root: Path | None = None
) -> str | None:
    """Scan a shell command for references to protected files.

    Returns a rejection message if a protected path is found, otherwise None.
    Simple heuristic: tokenize the command and check each token.
    """
    tokens = command.split()
    for token in tokens:
        token_clean = token.strip("'\"`;|&>< ")
        if not token_clean:
            continue
        if is_protected(token_clean, project_root):
            return f"Command references protected file: {token_clean}"
    return None
