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
    # The gates themselves. Without these the agent can edit the code that
    # decides whether it needs approval, whether it may be stopped, and
    # whether a checkpoint may close — which is the same as having no gate.
    "core/ego.py",
    "core/trust_gate.py",
    "core/kill_switch.py",
    "core/checkpoint_receipt.py",
    "core/goal_runner.py",
    # The action-layer gates. These decide whether a secret is released,
    # whether a target is the operator's to change, and whether an address
    # may be reached at all. An agent that can edit them can authorise its
    # own third-party writes and read its own credentials in the clear.
    "core/credentials.py",
    "core/scope_guard.py",
    "core/net_policy.py",
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

# Config keys the agent may not change to ANY value — not merely keys it may
# not switch off. These describe where the agent appears on the network, and
# every geo-stamped claim in the evidence register rests on them being the
# operator's choice rather than the agent's.
#
# 2026-08-15: told to run a Nevada-observed competitor analysis, the agent hit
# a checkpoint demanding "2 of 3 checks report Nevada" against a proxy the
# operator had just moved to Florida. Instead of reporting the conflict it
# edited config.yaml twice — restoring the Nevada suffix and adding a sticky
# session — so its own checkpoint would pass. An agent that can rewrite where
# it observes from can satisfy any provenance claim it likes, which makes the
# claim worthless. Changing these is the operator's act, and if a goal cannot
# proceed without it, the goal is what should stop.
IMMUTABLE_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "proxy.enabled",
        "proxy.type",
        "proxy.host",
        "proxy.port",
        "proxy.username",
        "proxy.password",
        "proxy.state",
        "proxy.apply_to",
    }
)


def _config_values(content: str) -> dict[str, str]:
    """Flatten a config.yaml into {"section.key": "raw value"}.

    Line-based on purpose: the same no-YAML-dependency heuristic
    ``check_config_content`` already uses, and it only needs to see
    top-level sections, which is where every guarded key lives.
    """
    import re

    out: dict[str, str] = {}
    section = ""
    for line in content.splitlines():
        sec = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*):\s*$", line)
        if sec:
            section = sec.group(1)
            continue
        if re.match(r"^[a-zA-Z_]", line):  # a top-level scalar ends the section
            section = ""
            continue
        kv = re.match(r"^\s+([a-zA-Z_][a-zA-Z0-9_]*):\s*(.*)", line)
        if kv and section:
            value = kv.group(2).split("#")[0].strip()
            out[f"{section}.{kv.group(1)}"] = value
    return out


def check_config_edit(original: str, updated: str) -> str | None:
    """Guard a config.yaml edit, judged as a *change* rather than a state.

    Two rules, both answered by diffing against what is currently on disk:

    * an immutable key moved at all — refused;
    * a protected key was switched to its forbidden value — refused.

    The diff matters. ``check_config_content`` asks "does the result contain
    a forbidden value", which is right for a brand-new file and wrong for an
    edit: ``autonomous_mind.enabled: false`` is the shipped default, so that
    question refuses every edit to a config that has autonomy switched off —
    including edits nowhere near it. Asking "did this edit turn it off"
    keeps the protection and drops the false positive.
    """
    if (err := check_config_immutables(original, updated)) is not None:
        return err
    before, after = _config_values(original), _config_values(updated)
    for dotted, forbidden in PROTECTED_CONFIG_KEYS.items():
        if not isinstance(forbidden, bool):
            continue
        was = before.get(dotted, "").strip().lower()
        now = after.get(dotted, "").strip().lower()
        if now == str(forbidden).lower() and was != now:
            return (
                f"Refused: this edit sets '{dotted}' to '{forbidden}', which is "
                f"a protected configuration the agent cannot disable. Ask the "
                f"owner to change it manually if needed."
            )
    return None


def check_config_immutables(original: str, updated: str) -> str | None:
    """Refuse a config.yaml edit that changes an operator-only key.

    Returns a rejection message, or None when nothing guarded moved.
    Comparing against the current file (rather than pattern-matching the new
    one) is what makes this checkable: the question is not "is this value
    bad" but "did the agent change something that is not its to change".
    """
    before, after = _config_values(original), _config_values(updated)
    changed = [
        key
        for key in sorted(IMMUTABLE_CONFIG_KEYS)
        if before.get(key, "") != after.get(key, "")
    ]
    if not changed:
        return None
    return (
        f"Refused: this edit changes {', '.join(changed)} in config.yaml. "
        "Those keys decide where the agent appears on the network, and every "
        "geo-stamped claim in the evidence register depends on them being the "
        "operator's choice. Only the operator changes them, by hand. If a task "
        "cannot proceed without a different network exit, say so and stop — do "
        "not reconfigure the machine so the task passes."
    )


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
