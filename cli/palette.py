"""Shared Rich REPL palette — Blade Runner 2049 cinematic amber.

Used by the scrolling Rich chat fallback (``cli/chat_cmd.py`` and
``channels/cli_adapter.py``). The Textual dashboard uses YAML themes
separately; this module keeps the narrow-TTY / non-dashboard path in
the same visual family as the ``blade`` dashboard theme.
"""

from __future__ import annotations

# Lead amber + soft off-white body
C_PRIMARY = "#f3efe6"
C_ACCENT = "#f0a020"
C_ACCENT_ALT = "#3aa8a0"
C_SUCCESS = "#3aa8a0"
C_WARN = "#f0b429"
C_ERROR = "#e07070"
C_DIM = "#6b7385"
C_USER = "bold #f3efe6"
C_AGENT = "bold #3aa8a0"
C_BORDER = "#1e2533"

# Amber → cream banner gradient (dark streetlight → bright mark)
BANNER_LINES: list[tuple[str, str]] = [
    (
        "#5c3d1a",
        "  ███████╗██╗      ██████╗ ██████╗ ██╗  ██╗ █████╗ ███╗   ██╗████████╗ ██████╗",
    ),
    (
        "#8a5a28",
        "  ██╔════╝██║     ██╔═══██╗██╔══██╗██║  ██║██╔══██╗████╗  ██║╚══██╔══╝██╔═══██╗",
    ),
    (
        "#b87a35",
        "  █████╗  ██║     ██║   ██║██████╔╝███████║███████║██╔██╗ ██║   ██║   ██║   ██║",
    ),
    (
        "#f0a020",
        "  ██╔══╝  ██║     ██║   ██║██╔═══╝ ██╔══██║██╔══██║██║╚██╗██║   ██║   ██║   ██║",
    ),
    (
        "#f0c078",
        "  ███████╗███████╗╚██████╔╝██║     ██║  ██║██║  ██║██║ ╚████║   ██║   ╚██████╔╝",
    ),
    (
        "#f3efe6",
        "  ╚══════╝╚══════╝ ╚═════╝ ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝    ╚═════╝",
    ),
]

LOGO_SMALL = f"[{C_ACCENT}]◆[/] [{C_PRIMARY}]EloPhanto[/]"

# prompt_toolkit style for the REPL caret
PROMPT_STYLE = "#f0a020 bold"
