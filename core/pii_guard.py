"""PII detection and redaction guard.

Scans text for common PII patterns (SSN, credit card, phone, etc.)
and replaces them with redaction markers. Designed to sit alongside
the injection guard and log redaction as a distinct defense layer:

| Layer          | Module                    | What it catches                    |
|----------------|---------------------------|------------------------------------|
| Injection guard| core/injection_guard.py   | Prompt injection in external content|
| **PII guard**  | **core/pii_guard.py**     | **Sensitive user data (SSN, CC)**  |
| Log redaction  | core/log_setup.py         | API keys and tokens in log output  |

Phase 2 implementation: detection patterns are complete and tested.
Wiring into the tool output pipeline (core/agent.py) happens in Phase 2
of the security hardening roadmap.

See docs/27-SECURITY-HARDENING.md (Gap 2: PII Detection and Redaction).
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from typing import Any


class PIIType(enum.Enum):
    """Types of personally identifiable information."""

    SSN = "SSN"
    CREDIT_CARD = "CREDIT_CARD"
    PHONE = "PHONE"
    EMAIL_PASSWORD = "EMAIL_PASSWORD"
    API_KEY = "API_KEY"
    BANK_ACCOUNT = "BANK_ACCOUNT"


@dataclass
class PIIMatch:
    """A detected PII occurrence in text."""

    pii_type: PIIType
    start: int
    end: int

    @property
    def redacted(self) -> str:
        return f"[PII:{self.pii_type.value} detected \u2014 redacted]"


# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

# US Social Security Number: XXX-XX-XXXX
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# Credit card: 13-19 digits (optionally separated by spaces or dashes)
_CC_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")

# US phone: (XXX) XXX-XXXX or XXX-XXX-XXXX or +1XXXXXXXXXX
_PHONE_RE = re.compile(r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")

# Email + password combo: "email: x@y.com password: abc123" or similar
_EMAIL_PASS_RE = re.compile(
    r"(?:email|e-mail|user(?:name)?)\s*[:=]\s*\S+@\S+\s+"
    r"(?:password|passwd|pass|pwd)\s*[:=]\s*\S+",
    re.IGNORECASE,
)

# API key patterns (extends log_setup patterns to content scanning)
_API_KEY_RE = re.compile(
    r"\b(?:sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{36,}|"
    r"xox[bpsar]-[a-zA-Z0-9\-]{10,})\b"
)

# Bank account / routing numbers: 8-17 digits preceded by "account" or "routing"
_BANK_RE = re.compile(
    r"(?:account|routing|acct|a/c)\s*(?:number|num|no|#)?\s*[:=]?\s*\d{8,17}",
    re.IGNORECASE,
)

_PATTERNS: list[tuple[PIIType, re.Pattern[str]]] = [
    (PIIType.SSN, _SSN_RE),
    (PIIType.CREDIT_CARD, _CC_RE),
    (PIIType.PHONE, _PHONE_RE),
    (PIIType.EMAIL_PASSWORD, _EMAIL_PASS_RE),
    (PIIType.API_KEY, _API_KEY_RE),
    (PIIType.BANK_ACCOUNT, _BANK_RE),
]


def _luhn_check(number: str) -> bool:
    """Validate a credit card number using the Luhn algorithm."""
    digits = [int(d) for d in number if d.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def scan_for_pii(text: str) -> list[PIIMatch]:
    """Scan text for PII patterns.

    Returns a list of PIIMatch objects, sorted by position.
    Credit card matches are validated with the Luhn algorithm to
    reduce false positives.
    """
    matches: list[PIIMatch] = []

    for pii_type, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            # Extra validation for credit cards — Luhn check
            if pii_type == PIIType.CREDIT_CARD:
                digits_only = re.sub(r"\D", "", m.group())
                if not _luhn_check(digits_only):
                    continue

            matches.append(PIIMatch(pii_type=pii_type, start=m.start(), end=m.end()))

    matches.sort(key=lambda m: m.start)
    return matches


def redact_pii(text: str, matches: list[PIIMatch] | None = None) -> str:
    """Replace PII in text with redaction markers.

    If ``matches`` is not provided, scans the text first.
    """
    if matches is None:
        matches = scan_for_pii(text)

    if not matches:
        return text

    # Build result by replacing matched spans in reverse order
    result = text
    for m in reversed(matches):
        result = result[: m.start] + m.redacted + result[m.end :]

    return result


def redact_pii_in_dict(obj: Any, max_depth: int = 4) -> Any:
    """Recursively redact PII in string values within dicts/lists.

    Preserves structure: dicts remain dicts, lists remain lists.
    Only string values of length > 10 are scanned (short strings
    are unlikely to contain PII and scanning them wastes cycles).

    Mirrors the recursion pattern of ``injection_guard._wrap_dict_strings()``.
    """
    if max_depth <= 0:
        return obj
    if isinstance(obj, str):
        if len(obj) > 10:
            return redact_pii(obj)
        return obj
    if isinstance(obj, dict):
        return {
            k: (v if k.startswith("_") else redact_pii_in_dict(v, max_depth - 1))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_pii_in_dict(item, max_depth - 1) for item in obj]
    return obj
