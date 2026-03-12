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

# Config keys that must never be disabled by the agent.
# These are checked when the agent tries to write config.yaml.
# Format: "section.key" -> value that is forbidden.
PROTECTED_CONFIG_KEYS: dict[str, object] = {
    "autonomous_mind.enabled": False,
    "heartbeat.enabled": False,
    "gateway.enabled": False,
    "scheduler.enabled": False,
}


def check_config_content(content: str) -> str | None:
    """Scan a config.yaml write for protected key violations.

    Returns a rejection message if a protected key is being set to a
    forbidden value, otherwise None. Uses simple line-based heuristics
    (no YAML parse dependency) to catch the common case of the agent
    setting a flag to false.
    """
    import re

    lines = content.splitlines()
    # Track current top-level section
    current_section: str = ""
    for line in lines:
        # Detect top-level section (no leading spaces, ends with colon)
        section_match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*):\s*$", line)
        if section_match:
            current_section = section_match.group(1)
            continue
        # Detect indented key: value
        kv_match = re.match(r"^\s+([a-zA-Z_][a-zA-Z0-9_]*):\s*(.+)", line)
        if kv_match and current_section:
            key = kv_match.group(1)
            val_str = kv_match.group(2).strip().split("#")[0].strip().lower()
            dotted = f"{current_section}.{key}"
            if dotted in PROTECTED_CONFIG_KEYS:
                forbidden = PROTECTED_CONFIG_KEYS[dotted]
                if isinstance(forbidden, bool):
                    if val_str == str(forbidden).lower():
                        return (
                            f"Refused: config.yaml write sets '{dotted}' to "
                            f"'{forbidden}' which is a protected configuration. "
                            f"This key cannot be disabled by the agent. "
                            f"Ask the owner to change it manually if needed."
                        )
    return None


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
