"""``elophanto config`` — operator config management.

Subcommands:

  - ``migrate``  Detect config keys added in newer releases that the
                 operator's local ``config.yaml`` is missing and patch
                 them in with safe defaults. Idempotent — re-runs are
                 no-ops once everything is in place.

Migration design: the operator's existing ``config.yaml`` is preserved
byte-for-byte. We do not round-trip through PyYAML (that would lose
comments and reorder keys). Instead, each migration declares:

  - ``key_path``: dotted path whose presence is checked (e.g.
                  ``autonomous_mind.arbiter``)
  - ``inner_yaml``: the YAML snippet to insert under the parent block,
                    written at the proper indent
  - ``banner``: human comment shown above the inserted block

When the parent (``autonomous_mind:``) already exists in the file, the
new sub-block is **inserted into** it at the right indent. When the
parent doesn't exist, the whole thing is appended at top-level. Either
way the loader sees one coherent ``autonomous_mind:`` mapping — no
PyYAML duplicate-key clobbering.

See ``docs/75-AUTONOMOUS-MIND-V2.md`` for the arbiter example.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
import yaml
from rich.console import Console

console = Console()

_PROJECT_ROOT = Path(__file__).parent.parent.resolve()
_CONFIG_PATH = _PROJECT_ROOT / "config.yaml"


# ---------------------------------------------------------------------------
# Migration registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Migration:
    """One additive config migration.

    ``key_path`` — dotted path the migration adds (e.g.
    ``autonomous_mind.arbiter``). Migration runs when ``key_path`` is
    absent from the loaded config; once present, the migration is
    skipped on re-runs.

    ``inner_yaml`` — the YAML for the LEAF block only. It is the
    operator-facing content that goes UNDER the parent key. Do NOT
    include the parent key itself — the migrator handles that based
    on whether the parent already exists in the file.

    Example: for ``autonomous_mind.arbiter``, ``inner_yaml`` is the
    ``arbiter:`` block content. If ``autonomous_mind:`` already
    exists, the migrator inserts ``arbiter:`` under it at the correct
    indent; otherwise it adds the whole ``autonomous_mind:`` /
    ``arbiter:`` chain.
    """

    id: str
    key_path: str
    banner: str
    inner_yaml: str  # YAML for the leaf, no parent key


_MIGRATIONS: list[Migration] = [
    # Cost-protection gate added 2026-06-02. Operator burned $50 on
    # silent codex→openrouter fallback during a codex auth outage.
    # The gate refuses metered fallback in USER chat unless
    # explicitly opted in. Autonomous tasks bypass — they're bounded
    # by budget.daily_limit_usd. See core/router.py for the impl and
    # cli/dashboard/app.py for the chat banner.
    Migration(
        id="metered-fallback-gate-2026-06",
        key_path="llm.allow_metered_fallback_in_chat",
        banner=(
            "Cost-protection gate: refuse to fall over from codex to "
            "a metered provider (openrouter / openai / kimi / "
            "huggingface) during a USER chat unless explicitly "
            "allowed. Autonomous tasks bypass — bounded by "
            "budget.daily_limit_usd. Burned $50 on a silent codex→"
            "openrouter fallback before this shipped."
        ),
        inner_yaml="""metered_providers:
  - openrouter
  - openai
  - kimi
  - huggingface
# Set true if you ACCEPT the per-token bill when codex is down.
allow_metered_fallback_in_chat: false
""",
    ),
    # Phase 3 arbiter (docs/75-AUTONOMOUS-MIND-V2.md).
    # Originally added with enabled: false (operator opt-in). Flipped
    # to enabled: true on 2026-05-20 after the AlphaScala log review
    # showed the legacy free-form prompt produces analysis-paralysis
    # loops in production. Existing operators get the working default
    # on next ./update.sh; flip to false locally if you need the old
    # behavior as an escape hatch.
    Migration(
        id="arbiter-2026-05",
        key_path="autonomous_mind.arbiter",
        banner=(
            "Phase 3 scored-candidate arbiter for the autonomous mind. "
            "Default ON since 2026-05-20 (legacy prompt produced "
            "analysis-paralysis loops). Grep '[arbiter]' in "
            "logs/latest.log to audit the ranked menu the mind saw "
            "each wakeup."
        ),
        # No parent key — just the arbiter sub-block. The migrator
        # adds the right amount of indent for the actual insert point.
        inner_yaml="""arbiter:
  enabled: true
  top_k: 5
  # Linear combiner — see core/mind_arbiter.py:ArbiterWeights for
  # the meaning of each. Tune to shift WHICH KIND of work rises
  # to the top; absolute score numbers don't matter.
  weights:
    value: 1.0
    lens_bonus: 0.6
    staleness_bonus: 0.4
    affect_bias: 1.0
    cost: 0.3
    mission_weight: 0.5
""",
    ),
    # ABE fiat rail (Stripe) — added 2026-06-18.
    # tmp/abe-finance-rail-spec-2026-06-18.md. Safe by default: mode=test
    # uses Stripe TEST keys (no real money, no KYC). Going live requires the
    # company's entity_state=verified + an explicit operator go-live flip —
    # enforced by the tools + doctor, never by editing this file alone.
    Migration(
        id="payments-fiat-stripe-2026-06",
        key_path="payments.fiat",
        banner=(
            "Fiat payment rail (Stripe). mode=test by default — full API, "
            "zero real money, no KYC needed to develop. Set up with the "
            "wizard (paste a free sk_test_ key) or `elophanto init edit "
            "payments`. Live mode is a separate KYC-gated operator step."
        ),
        inner_yaml="""fiat:
  enabled: false
  provider: stripe
  mode: test            # test (no real money, no KYC) | live
  base_currency: USD
  account_id: ""
  # API keys live in the vault under these refs — never in this file:
  secret_key_ref: stripe_secret_key
  publishable_key_ref: stripe_publishable_key
  webhook_secret_ref: stripe_webhook_secret
  issuing_enabled: false
""",
    ),
]


# ---------------------------------------------------------------------------
# Config inspection
# ---------------------------------------------------------------------------


def _get_nested(d: Any, dotted: str) -> Any | None:
    """Walk ``d`` along ``dotted`` and return the leaf, or None if
    any segment is missing. Tolerates non-dict intermediates so the
    check stays defensive against half-written configs."""
    cur: Any = d
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _pending_migrations(cfg: dict[str, Any]) -> list[Migration]:
    return [m for m in _MIGRATIONS if _get_nested(cfg, m.key_path) is None]


# ---------------------------------------------------------------------------
# Text-level YAML surgery
# ---------------------------------------------------------------------------


def _indent_block(text: str, spaces: int) -> str:
    """Indent every non-empty line by ``spaces`` spaces. Empty lines
    stay empty so the result keeps its visual breathing room. Trailing
    newline is preserved — losing it caused banner + next block to
    collide on one line (2026-05-20 bug)."""
    pad = " " * spaces
    out = "\n".join(pad + ln if ln.strip() else ln for ln in text.splitlines())
    if text.endswith("\n") and not out.endswith("\n"):
        out += "\n"
    return out


def _find_top_level_block_end(lines: list[str], top_key: str) -> int | None:
    """Return the index AFTER the last line belonging to the
    ``top_key:`` block, or None if the block is absent.

    A top-level block starts at a line matching ``^top_key:`` (zero
    indent) and ends at the next zero-indent non-blank line that
    isn't a comment continuation. If the block runs to EOF, returns
    ``len(lines)``.
    """
    start_re = re.compile(rf"^{re.escape(top_key)}\s*:")
    start: int | None = None
    for i, ln in enumerate(lines):
        if start_re.match(ln):
            start = i
            break
    if start is None:
        return None
    # Scan forward for the next zero-indent non-blank, non-comment line.
    for j in range(start + 1, len(lines)):
        ln = lines[j]
        if not ln.strip():
            continue
        if ln.startswith("#"):
            # Top-level comment between blocks counts as boundary —
            # we want to insert BEFORE it so the new sub-block
            # belongs to the block above.
            return j
        if not ln.startswith((" ", "\t")):
            return j
    return len(lines)


def _apply_migration(text: str, migration: Migration) -> str:
    """Patch ``text`` with ``migration``. Returns the new file body.

    Strategy:
      - If the parent key (first segment of ``key_path``) is missing
        from ``text``, append the whole chain at top-level.
      - Otherwise, find the end of the parent block and insert the
        sub-block (indented by 2 spaces) just before the next
        top-level item.

    The banner comment is emitted above the inserted block in both
    branches so operators can grep for the migration ID.
    """
    parts = migration.key_path.split(".")
    parent = parts[0]
    ts = datetime.now(UTC).strftime("%Y-%m-%d")
    banner = (
        f"# ── Added by `elophanto config migrate` on {ts} "
        f"(migration: {migration.id}) ──\n"
        f"# {migration.banner}\n"
    )

    lines = text.splitlines(keepends=True)
    end_idx = _find_top_level_block_end(lines, parent)

    if end_idx is None:
        # Parent doesn't exist — append the full chain at EOF.
        full_chain = _wrap_in_parents(migration.inner_yaml, parts[:-1])
        suffix = text if text.endswith("\n") else text + "\n"
        return suffix + "\n" + banner + full_chain

    # Parent exists. The sub-key path between parent and leaf may be
    # multiple levels (rare today; arbiter is one level), so we wrap
    # in any intermediate keys. Indent by 2 because we're going one
    # level deep into ``parent``.
    nested = _wrap_in_parents(migration.inner_yaml, parts[1:-1])
    indented_content = _indent_block(nested, 2)
    indented_banner = _indent_block(banner, 2)
    insertion = indented_banner + indented_content
    if not insertion.endswith("\n"):
        insertion += "\n"

    # Ensure there's a newline boundary between existing content and
    # our insert.
    head = "".join(lines[:end_idx])
    tail = "".join(lines[end_idx:])
    if head and not head.endswith("\n"):
        head += "\n"
    return head + insertion + tail


def _wrap_in_parents(inner: str, parents: list[str]) -> str:
    """Wrap ``inner`` in nested parent keys, indenting each level by
    2 spaces. ``parents=[]`` returns ``inner`` untouched."""
    out = inner
    for parent in reversed(parents):
        out = f"{parent}:\n{_indent_block(out, 2)}\n"
    return out


# ---------------------------------------------------------------------------
# Click commands
# ---------------------------------------------------------------------------


@click.group("config")
def config_cmd() -> None:
    """Operator config management."""


@config_cmd.command("migrate")
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(),
    help="Path to config.yaml (default: ./config.yaml in project root)",
)
@click.option(
    "--check",
    is_flag=True,
    help="Report what would change without writing.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Apply all pending migrations without prompting.",
)
def migrate_cmd(config_path: str | None, check: bool, yes: bool) -> None:
    """Patch config.yaml with sections added in newer EloPhanto releases.

    Compares your config against the migration registry and inserts any
    sub-blocks whose keys are missing, at the correct indent under their
    parent. Idempotent: re-runs after a successful migration are no-ops.
    """
    path = Path(config_path) if config_path else _CONFIG_PATH
    if not path.exists():
        console.print(f"[red]config not found:[/red] {path}")
        console.print("Run [bold]elophanto init[/bold] to create a fresh config.")
        sys.exit(1)

    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        console.print(f"[red]config is not valid YAML:[/red] {e}")
        sys.exit(1)

    pending = _pending_migrations(cfg)
    if not pending:
        console.print("[green]Up to date — no pending config migrations.[/green]")
        return

    console.print(f"[yellow]Found {len(pending)} pending migration(s):[/yellow]")
    for m in pending:
        console.print(f"  • [bold]{m.id}[/bold]  — adds [cyan]{m.key_path}[/cyan]")
        console.print(f"    [dim]{m.banner}[/dim]")

    if check:
        console.print("[dim]Re-run without --check to apply.[/dim]")
        return

    if not yes:
        if not click.confirm(
            f"Patch {path} with these {len(pending)} block(s)?", default=True
        ):
            console.print("[dim]Aborted.[/dim]")
            return

    # Back up the file once before any edits so a partial failure
    # leaves the operator with a recoverable artifact.
    backup = path.with_suffix(path.suffix + ".bak")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    console.print(f"  [dim]backup → {backup.name}[/dim]")

    text = path.read_text(encoding="utf-8")
    for m in pending:
        text = _apply_migration(text, m)
        console.print(f"  [green]✓[/green] applied {m.id}")

    path.write_text(text, encoding="utf-8")

    # Verify the result parses AND that the migrated key path is now
    # present — if either fails the operator can revert from .bak.
    try:
        new_cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        console.print(
            f"[red]Result is not valid YAML:[/red] {e}\n"
            f"Restore from {backup.name} and report this."
        )
        sys.exit(2)

    still_missing = [m for m in pending if _get_nested(new_cfg, m.key_path) is None]
    if still_missing:
        ids = ", ".join(m.id for m in still_missing)
        console.print(
            f"[red]Patched the file but these migrations did NOT take effect: "
            f"{ids}. Restore from {backup.name} and report this.[/red]"
        )
        sys.exit(2)

    console.print("\n[green]Done.[/green] Restart EloPhanto to pick up the new config.")
