"""Swarm boundary security — output validation, context filtering, env isolation, kill switch.

Since sub-agents are opaque external processes (Claude Code, Codex, etc.) running
in tmux, security is enforced at the edges:
- What we SEND: prompt enrichment filtered through PII guard, vault references stripped
- What we READ: PR diffs scanned for injection + suspicious code patterns
- Where they RUN: isolated workspace under /tmp/elophanto/swarm/<agent-id>/

See docs/27-SECURITY-HARDENING.md (Gap 7: Multi-Agent / Swarm Security).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.injection_guard import scan_for_injection
from core.pii_guard import redact_pii

if TYPE_CHECKING:
    from core.config import AgentProfileConfig, SwarmConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Context blocklist — lines matching these are stripped from enrichment context
# ---------------------------------------------------------------------------

_CONTEXT_BLOCKLIST: list[re.Pattern[str]] = [
    re.compile(
        r"vault[._]?(enc|salt|key|secret|password|token|credential)",
        re.IGNORECASE,
    ),
    re.compile(r"api[_\s]?key\s*[:=]", re.IGNORECASE),
    re.compile(
        r"(secret|token|password|credential)\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
    re.compile(r"config\.yaml|\.env\b|\.elophanto/", re.IGNORECASE),
    re.compile(r"data/elophanto\.db", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Diff suspicious-pattern scanner
# ---------------------------------------------------------------------------

_DIFF_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "credential_access",
        re.compile(
            r"os\.environ|getenv\s*\(|dotenv|load_dotenv|open\s*\(.*\.env",
            re.IGNORECASE,
        ),
    ),
    (
        "network_call",
        re.compile(
            r"requests\.|urllib\.|httpx\.|aiohttp\.|fetch\s*\(|\"curl\s|\"wget\s",
            re.IGNORECASE,
        ),
    ),
    (
        "file_traversal",
        re.compile(
            r"\.\./|/etc/|/root/|os\.path\.expanduser|Path\s*\(\s*[\"']~",
            re.IGNORECASE,
        ),
    ),
    (
        "system_command",
        re.compile(
            r"os\.system\s*\(|subprocess\.|eval\s*\(|exec\s*\(|__import__\s*\(",
        ),
    ),
]

# Pattern that must scan the full diff (including headers) rather than just added lines
_DIFF_FULL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "new_dependency",
        re.compile(
            r"\+\+\+ b/.*(?:requirements\.txt|pyproject\.toml|setup\.cfg|setup\.py)",
            re.IGNORECASE,
        ),
    ),
]

# Env vars matching these patterns are stripped from sub-agent environment
_SENSITIVE_ENV_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"VAULT", re.IGNORECASE),
    re.compile(r"SECRET", re.IGNORECASE),
    re.compile(r"TOKEN", re.IGNORECASE),
    re.compile(r"API[_]?KEY", re.IGNORECASE),
    re.compile(r"PASSWORD", re.IGNORECASE),
    re.compile(r"CREDENTIAL", re.IGNORECASE),
    re.compile(r"PRIVATE[_]?KEY", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Output report
# ---------------------------------------------------------------------------


@dataclass
class SwarmOutputReport:
    """Security validation report for a sub-agent's output."""

    agent_id: str
    branch: str
    diff_lines: int = 0
    suspicious: bool = False
    findings: list[str] = field(default_factory=list)
    injection_detected: bool = False
    injection_patterns: list[str] = field(default_factory=list)
    new_dependencies: list[str] = field(default_factory=list)
    verdict: str = "clean"  # "clean", "needs_review", "blocked"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sanitize_enrichment_context(context: str) -> str:
    """Filter knowledge vault chunks before sharing with sub-agents.

    1. Redact PII (SSNs, credit cards, API keys, etc.)
    2. Remove lines matching vault/credential/config blocklist patterns
    """
    if not context:
        return ""

    # PII redaction first
    context = redact_pii(context)

    # Strip lines matching blocklist
    clean_lines: list[str] = []
    for line in context.splitlines():
        if any(p.search(line) for p in _CONTEXT_BLOCKLIST):
            continue
        clean_lines.append(line)

    return "\n".join(clean_lines)


def scan_diff_for_suspicious_patterns(
    diff_text: str,
) -> tuple[bool, list[str]]:
    """Scan a git diff for dangerous patterns in added lines.

    Only scans lines starting with ``+`` (added code) to avoid
    false positives from removed code.

    Returns:
        (is_suspicious, list_of_finding_descriptions)
    """
    if not diff_text:
        return False, []

    # Extract added lines only (skip diff headers like +++ b/file)
    added_lines: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added_lines.append(line)

    added_text = "\n".join(added_lines)
    if not added_text:
        return False, []

    findings: list[str] = []
    for category, pattern in _DIFF_PATTERNS:
        matches = pattern.findall(added_text)
        if matches:
            # Include first match as context
            sample = matches[0] if isinstance(matches[0], str) else str(matches[0])
            findings.append(f"{category}: {sample[:80]}")

    # Patterns that need the full diff text (e.g. file headers)
    for category, pattern in _DIFF_FULL_PATTERNS:
        matches = pattern.findall(diff_text)
        if matches:
            sample = matches[0] if isinstance(matches[0], str) else str(matches[0])
            findings.append(f"{category}: {sample[:80]}")

    return bool(findings), findings


async def validate_agent_output(
    agent_id: str,
    branch: str,
    project_root: Path,
) -> SwarmOutputReport:
    """Validate a sub-agent's output by scanning its branch diff.

    Runs ``git diff main...{branch}`` and passes the result through:
    1. ``scan_diff_for_suspicious_patterns()`` — code-level threats
    2. ``scan_for_injection()`` — prompt injection patterns

    Returns a ``SwarmOutputReport`` with a verdict.
    """
    report = SwarmOutputReport(agent_id=agent_id, branch=branch)

    # Get diff
    cmd = f"git -C {project_root} diff main...{branch}"
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            report.findings.append(f"git diff failed: {stderr.decode()[:200]}")
            report.verdict = "needs_review"
            return report
        diff_text = stdout.decode(errors="replace")
    except Exception as e:
        report.findings.append(f"diff error: {e}")
        report.verdict = "needs_review"
        return report

    report.diff_lines = len(diff_text.splitlines())

    # Scan for suspicious code patterns
    suspicious, code_findings = scan_diff_for_suspicious_patterns(diff_text)
    report.suspicious = suspicious
    report.findings.extend(code_findings)

    # Extract new dependency info from findings
    report.new_dependencies = [
        f for f in code_findings if f.startswith("new_dependency:")
    ]

    # Scan for injection patterns
    injection_found, injection_patterns = scan_for_injection(diff_text)
    report.injection_detected = injection_found
    report.injection_patterns = injection_patterns

    # Determine verdict
    if injection_found:
        report.verdict = "blocked"
    elif len(code_findings) >= 3:
        report.verdict = "blocked"
    elif code_findings:
        report.verdict = "needs_review"
    else:
        report.verdict = "clean"

    return report


def build_isolated_env(
    agent_id: str,
    profile_env: dict[str, str],
) -> dict[str, str]:
    """Build a sanitized environment for a sub-agent tmux session.

    - Preserves non-sensitive profile env vars
    - Strips vars matching sensitive patterns (VAULT, SECRET, TOKEN, etc.)
    - Sets ELOPHANTO_SWARM_AGENT=1 and ELOPHANTO_WORKSPACE
    """
    safe_env: dict[str, str] = {}
    for key, value in profile_env.items():
        if any(p.search(key) for p in _SENSITIVE_ENV_PATTERNS):
            logger.debug(
                "Stripped sensitive env var %s from sub-agent %s", key, agent_id
            )
            continue
        safe_env[key] = value

    safe_env["ELOPHANTO_SWARM_AGENT"] = "1"
    safe_env["ELOPHANTO_WORKSPACE"] = f"/tmp/elophanto/swarm/{agent_id}/"

    return safe_env


def check_kill_conditions(
    agent: Any,
    profile: AgentProfileConfig,
    config: SwarmConfig,
    output_report: SwarmOutputReport | None = None,
) -> tuple[bool, str]:
    """Check if a sub-agent should be immediately terminated.

    Conditions:
    1. Time exceeded: elapsed > profile.max_time_seconds
    2. Diff too large: diff_lines > config.max_diff_lines
    3. Output blocked: output_report.verdict == "blocked"

    Returns:
        (should_kill, reason_string)
    """
    # Time check
    if agent.spawned_at:
        try:
            spawned = datetime.fromisoformat(agent.spawned_at)
            elapsed = (datetime.now(UTC) - spawned).total_seconds()
            if elapsed > profile.max_time_seconds:
                return (
                    True,
                    f"timeout: {int(elapsed)}s > {profile.max_time_seconds}s limit",
                )
        except (ValueError, TypeError):
            pass

    # Output report checks
    if output_report:
        if output_report.verdict == "blocked":
            return True, f"security:blocked - {'; '.join(output_report.findings[:3])}"
        if (
            config.max_diff_lines > 0
            and output_report.diff_lines > config.max_diff_lines
        ):
            return (
                True,
                f"diff_too_large: {output_report.diff_lines} lines > {config.max_diff_lines} limit",
            )

    return False, ""
