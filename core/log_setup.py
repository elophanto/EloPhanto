"""Centralized logging setup — file + optional console output.

Logs are written to ``logs/elophanto.log`` (rotated at 5 MB, 3 backups kept).
Console output is controlled by the *debug* flag.

Includes a RedactingFilter that strips API keys, passwords, and other
secrets from log messages before they reach disk.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_DIR = Path("logs")
_LOG_FILE = _LOG_DIR / "elophanto.log"
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_BACKUP_COUNT = 3
_FMT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

_configured = False

_REDACT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(api[_-]?key|token|secret|password|passwd|authorization)\s*[:=]\s*\S+", re.I
    ),
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
            for arg in (
                record.args if isinstance(record.args, tuple) else (record.args,)
            ):
                if isinstance(arg, str):
                    for pattern in _REDACT_PATTERNS:
                        arg = pattern.sub(_REDACTED, arg)
                new_args.append(arg)
            record.args = tuple(new_args) if len(new_args) > 1 else new_args[0]
        return True


def setup_logging(*, debug: bool = False) -> None:
    """Configure root logger with file handler (always) and console level.

    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _configured
    if _configured:
        return
    _configured = True

    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    redact_filter = RedactingFilter()

    fmt = logging.Formatter(_FMT, datefmt=_DATE_FMT)

    fh = RotatingFileHandler(
        _LOG_FILE, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    fh.addFilter(redact_filter)
    root.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if debug else logging.WARNING)
    ch.setFormatter(fmt)
    ch.addFilter(redact_filter)
    root.addHandler(ch)
