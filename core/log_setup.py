"""Centralized logging setup — file + optional console output.

Each launch creates a new timestamped log file in ``logs/`` (e.g.
``logs/elophanto_2026-02-19_15-30-00.log``). A ``latest.log`` symlink
always points to the current session's log. Old logs beyond
``_MAX_LOG_FILES`` are automatically cleaned up.

Includes a RedactingFilter that strips API keys, passwords, and other
secrets from log messages before they reach disk.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path

_LOG_DIR = Path("logs")
_MAX_LOG_FILES = 10
_FMT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

_configured = False

_REDACT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(api[_-]?key|token|secret|password|passwd|authorization)\s*[:=]\s*\S+", re.I),
    re.compile(r"(sk-[a-zA-Z0-9]{20,})"),
    re.compile(r"(ghp_[a-zA-Z0-9]{36,})"),
    re.compile(r"([a-f0-9]{32,}\.[a-zA-Z0-9]{16,})"),
    re.compile(r"(Bearer\s+[a-zA-Z0-9._\-]+)", re.I),
]

_REDACTED = "[REDACTED]"


class RedactingFilter(logging.Filter):
    """Strip sensitive patterns from log records before output."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern in _REDACT_PATTERNS:
                record.msg = pattern.sub(_REDACTED, record.msg)
        if record.args:
            new_args: list[object] = []
            for arg in record.args if isinstance(record.args, tuple) else (record.args,):
                if isinstance(arg, str):
                    for pattern in _REDACT_PATTERNS:
                        arg = pattern.sub(_REDACTED, arg)
                new_args.append(arg)
            record.args = tuple(new_args) if len(new_args) > 1 else new_args[0]  # type: ignore[assignment]
        return True


def _cleanup_old_logs() -> None:
    """Remove oldest log files when count exceeds _MAX_LOG_FILES."""
    log_files = sorted(
        (f for f in _LOG_DIR.iterdir() if f.name.startswith("elophanto_") and f.suffix == ".log"),
        key=lambda f: f.stat().st_mtime,
    )
    while len(log_files) > _MAX_LOG_FILES:
        oldest = log_files.pop(0)
        oldest.unlink(missing_ok=True)


def setup_logging(*, debug: bool = False) -> None:
    """Configure root logger with a timestamped file handler and console.

    Each call creates a new ``logs/elophanto_<timestamp>.log`` file and
    updates a ``logs/latest.log`` symlink. Old logs are pruned to keep
    at most ``_MAX_LOG_FILES``.

    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _configured
    if _configured:
        return
    _configured = True

    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Timestamped log file for this session
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = _LOG_DIR / f"elophanto_{timestamp}.log"

    # Update latest.log symlink
    latest_link = _LOG_DIR / "latest.log"
    try:
        if latest_link.is_symlink() or latest_link.exists():
            latest_link.unlink()
        os.symlink(log_file.name, latest_link)
    except OSError:
        pass  # Symlinks may not work on all platforms

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    redact_filter = RedactingFilter()

    fmt = logging.Formatter(_FMT, datefmt=_DATE_FMT)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    fh.addFilter(redact_filter)
    root.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if debug else logging.WARNING)
    ch.setFormatter(fmt)
    ch.addFilter(redact_filter)
    root.addHandler(ch)

    _cleanup_old_logs()
