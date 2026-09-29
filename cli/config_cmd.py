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

Rewrites (``_REWRITES``) are the exception: they replace a value that has
stopped working — a retired model id — line by line, keeping the rest of
the file as it is.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
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
  cardholder_id: ""
""",
    ),
    # Agent Society, added 2026-09-05. Ships on: the campus is the
    # ordinary way to watch the agent work. An operator who already
    # wrote `society.enabled: false` keeps that — _get_nested returns
    # False, not None, so this migration is not pending for them.
    Migration(
        id="agent-society-2026-09",
        key_path="society.enabled",
        banner=(
            "Agent Society: a live isometric campus of the agent and its "
            "collaborators, on by default. Read-only, loopback-only, and "
            "opened in its own browser profile so the automated Chrome is "
            "never disturbed. Set enabled: false to turn off the server, "
            "the telemetry and the window; open_browser: false keeps the "
            "server without opening a window. See docs/93-AGENT-SOCIETY.md."
        ),
        inner_yaml="""enabled: true
host: 127.0.0.1       # loopback only — any other host is refused
port: 18790
open_browser: true    # false = serve, but open no window
""",
    ),
    # Long-run autonomy settings, added 2026-09-29 (docs/94, docs/95). The
    # code defaults apply without them; these make them visible. Keys the
    # operator already set are skipped (``_drop_present_keys``).
    Migration(
        id="long-run-goals-2026-09",
        key_path="goals.round_robin",
        banner=(
            "Long-run autonomy: plan and critique before acting, daily "
            "envelopes that pause a goal and resume it the next day, "
            "round-robin between active goals, and a daily health digest. "
            "See docs/94-LONG-RUN-AUTONOMY-REVIEW.md."
        ),
        inner_yaml="""deliberate: true              # plan each checkpoint attempt before acting
plan_critique: true           # critique and correct a plan before it is used
deliberation_effort: ""       # override the deliberation route's effort; "" = route's
daily_cost_envelope_usd: 0    # >0: a goal pauses for the day at this spend, resumes tomorrow
daily_time_envelope_seconds: 0
round_robin: false            # true: active goals take turns at checkpoint boundaries
health_digest_hour_utc: 7     # daily autonomy-health digest to every channel; -1 = off
""",
    ),
    Migration(
        id="pre-action-review-2026-09",
        key_path="agent.pre_action_review",
        banner=(
            "Before a CRITICAL tool (money, credentials, self-modification) "
            "runs unattended, a short review states the expected outcome "
            "and whether it is warranted. Chat is never reviewed."
        ),
        inner_yaml="""context_window_tokens: 200000  # planning model's window; compression starts at 70%
pre_action_review: true
""",
    ),
    Migration(
        id="mind-deliberate-2026-09",
        key_path="autonomous_mind.deliberate",
        banner=(
            "The mind weighs the arbiter's top candidates in a separate "
            "thinking call and commits to one before acting."
        ),
        inner_yaml="""deliberate: true
""",
    ),
    Migration(
        id="judge-model-2026-09",
        key_path="llm.judge_model",
        banner=(
            "Optional independent judge: the checkpoint panel and the final "
            "goal check on a different model family from the one that did "
            "the work (e.g. zai/glm-5.3). Empty = the deliberation route."
        ),
        inner_yaml="""# Send earlier turns' reasoning back to providers that support it (Z.ai).
preserve_reasoning: false
judge_model: ""
""",
    ),
    Migration(
        id="bench-2026-09",
        key_path="bench.enabled",
        banner=(
            "Benchmark from the agent's own history: `elophanto bench "
            "capture` / `bench run` replay verified checkpoints with every "
            "tool answered from the recording. enabled: also nightly. Off by "
            "default — it spends model quota. See docs/95-LEARNING-LOOP.md."
        ),
        inner_yaml="""enabled: false
hour_utc: 3
max_cases: 20
time_budget_seconds: 600
cases_dir: data/bench/cases
""",
    ),
    # A route for the thinking steps (docs/95 Phase B). Without it they use
    # `planning`, which operators often run at low effort for latency.
    Migration(
        id="deliberation-route-2026-09",
        key_path="llm.routing.deliberation",
        banner=(
            "Thinking steps — checkpoint plans, the mind's decision, "
            "critiques, the final goal check, judges — on the strongest "
            "model at the highest effort. Few calls, expensive when wrong. "
            "See docs/95-LEARNING-LOOP.md."
        ),
        inner_yaml="""deliberation:
  preferred_provider: codex
  reasoning_effort: xhigh
  models:
    codex: "gpt-6-astra"
    openai: "gpt-6-astra"
    zai: "glm-5.3"
    kimi: "kimi-k2.5"
    openrouter: "nvidia/nemotron-3-ultra-550b-a55b:free"
    ollama: "llama3.1:8b"
""",
    ),
]


# ---------------------------------------------------------------------------
# Rewrites — values that must change, not keys that must be added
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rewrite:
    """One value-replacing config migration.

    Additive migrations never touch what the operator wrote. A rewrite
    does, so it is kept to values that stop working: a retired model id.
    ``pending`` inspects the parsed config; ``apply`` edits the text line
    by line so comments and key order survive.
    """

    id: str
    banner: str
    pending: Callable[[dict[str, Any]], bool]
    apply: Callable[[str], str]


_RETIRED_CODEX = "gpt-5.5"
_CURRENT_CODEX = "gpt-6-astra"
# ``gpt-5.5`` exactly — not ``gpt-5.5-mini`` or ``gpt-5.55``.
_RETIRED_RE = re.compile(r"gpt-5\.5(?![\w.-])")


def _codex_retired_pending(cfg: dict[str, Any]) -> bool:
    llm = cfg.get("llm") or {}
    codex = (llm.get("providers") or {}).get("codex") or {}
    if str(codex.get("default_model") or "") == _RETIRED_CODEX:
        return True
    for route in (llm.get("routing") or {}).values():
        models = (route or {}).get("models") if isinstance(route, dict) else None
        if isinstance(models, dict) and str(models.get("codex") or "") == _RETIRED_CODEX:
            return True
    for section, key in (("llm", "vision_model"), ("browser", "vision_model")):
        if str((cfg.get(section) or {}).get(key) or "") == f"codex/{_RETIRED_CODEX}":
            return True
    return False


def _codex_retired_apply(text: str) -> str:
    """Replace gpt-5.5 where it names a Codex model: ``codex/gpt-5.5``
    anywhere, a routing ``codex: gpt-5.5`` entry, and ``default_model``
    inside the ``providers.codex`` block. ``openai: gpt-5.5`` (the direct
    API) is left alone."""
    out: list[str] = []
    codex_indent: int | None = None
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if codex_indent is not None and stripped.strip() and indent <= codex_indent:
            codex_indent = None
        if re.match(r"codex:\s*(#.*)?$", stripped.rstrip("\n")):
            codex_indent = indent  # entering the providers.codex block
        elif re.match(r"codex:\s*[\"']?gpt-5\.5[\"']?\s*(#.*)?$", stripped.rstrip("\n")):
            line = _RETIRED_RE.sub(_CURRENT_CODEX, line, count=1)
        elif codex_indent is not None and stripped.startswith("default_model:"):
            line = _RETIRED_RE.sub(_CURRENT_CODEX, line, count=1)
        line = re.sub(
            rf"codex/{re.escape(_RETIRED_CODEX)}(?![\w.-])", f"codex/{_CURRENT_CODEX}", line
        )
        out.append(line)
    return "".join(out)


_REWRITES: list[Rewrite] = [
    Rewrite(
        id="codex-gpt-6-2026-09",
        banner=(
            "Codex retires gpt-5.5 on 2026-10-14. Codex model references "
            "(providers.codex.default_model, routing `codex:` entries, "
            "codex/gpt-5.5 vision) move to gpt-6-astra. Direct-API "
            "`openai:` entries are left as they are."
        ),
        pending=_codex_retired_pending,
        apply=_codex_retired_apply,
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
    inner = _drop_present_keys(migration.inner_yaml, text, parts[:-1])
    if not inner.strip():
        return text
    migration = Migration(migration.id, migration.key_path, migration.banner, inner)
    ts = datetime.now(UTC).strftime("%Y-%m-%d")
    banner = (
        f"# ── Added by `elophanto config migrate` on {ts} "
        f"(migration: {migration.id}) ──\n"
        f"# {migration.banner}\n"
    )

    lines = text.splitlines(keepends=True)
    if _find_top_level_block_end(lines, parent) is None:
        # Parent doesn't exist — append the full chain at EOF.
        full_chain = _wrap_in_parents(migration.inner_yaml, parts[:-1])
        suffix = text if text.endswith("\n") else text + "\n"
        return suffix + "\n" + banner + full_chain

    # Insert into the deepest ancestor that exists (``llm.routing`` for
    # ``llm.routing.deliberation``), wrapping the leaf in any missing
    # intermediate keys, at that block's own child indent.
    depth, end_idx, indent = _deepest_block(lines, parts[:-1])
    nested = _wrap_in_parents(migration.inner_yaml, parts[depth:-1])
    insertion = _indent_block(banner, indent) + _indent_block(nested, indent)
    if not insertion.endswith("\n"):
        insertion += "\n"

    # Ensure there's a newline boundary between existing content and
    # our insert.
    head = "".join(lines[:end_idx])
    tail = "".join(lines[end_idx:])
    if head and not head.endswith("\n"):
        head += "\n"
    return head + insertion + tail


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _deepest_block(lines: list[str], path: list[str]) -> tuple[int, int, int]:
    """Walk ``path`` through nested mappings in ``lines``. Returns (how
    many segments exist, the index after the deepest existing block, the
    indent of that block's children). The first segment must exist."""
    lo, hi, key_indent = 0, len(lines), 0
    depth, end, child_indent = 0, len(lines), 2
    for key in path:
        key_re = re.compile(rf"^{' ' * key_indent}{re.escape(key)}\s*:\s*(#.*)?$")
        start = next(
            (i for i in range(lo, hi) if key_re.match(lines[i].rstrip("\n"))), None
        )
        if start is None:
            break
        block_end = hi
        for j in range(start + 1, hi):
            if lines[j].strip() and _indent_of(lines[j]) <= key_indent:
                block_end = j
                break
        child = key_indent + 2
        for j in range(start + 1, block_end):
            stripped = lines[j].strip()
            if stripped and not stripped.startswith("#"):
                child = _indent_of(lines[j])
                break
        depth, end, child_indent = depth + 1, block_end, child
        lo, hi, key_indent = start + 1, block_end, child
    return depth, end, child_indent


def _drop_present_keys(inner: str, text: str, parents: list[str]) -> str:
    """Remove from ``inner`` the top-level keys the operator already set
    under ``parents``, with the comment lines directly above them. A
    migration that adds several keys is pending when one is missing; the
    others must not be written twice (PyYAML keeps the last duplicate
    silently)."""
    try:
        cfg = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return inner
    existing: Any = cfg
    for part in parents:
        existing = existing.get(part) if isinstance(existing, dict) else None
    if not isinstance(existing, dict) or not existing:
        return inner
    kept: list[str] = []
    pending_comments: list[str] = []
    skipping = False
    for line in inner.splitlines(keepends=True):
        if line.startswith("#"):
            pending_comments.append(line)
            continue
        if line and not line.startswith((" ", "\t")) and ":" in line:
            key = line.split(":", 1)[0].strip()
            skipping = key in existing
            if not skipping:
                kept.extend(pending_comments)
            pending_comments = []
        if not skipping:
            kept.append(line)
    return "".join(kept + pending_comments)


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
    rewrites = [r for r in _REWRITES if r.pending(cfg)]
    if not pending and not rewrites:
        console.print("[green]Up to date — no pending config migrations.[/green]")
        return

    total = len(pending) + len(rewrites)
    console.print(f"[yellow]Found {total} pending migration(s):[/yellow]")
    for m in pending:
        console.print(f"  • [bold]{m.id}[/bold]  — adds [cyan]{m.key_path}[/cyan]")
        console.print(f"    [dim]{m.banner}[/dim]")
    for r in rewrites:
        console.print(f"  • [bold]{r.id}[/bold]  — [cyan]rewrites values[/cyan]")
        console.print(f"    [dim]{r.banner}[/dim]")

    if check:
        console.print("[dim]Re-run without --check to apply.[/dim]")
        return

    if not yes:
        if not click.confirm(
            f"Patch {path} with these {total} change(s)?", default=True
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
    for r in rewrites:
        text = r.apply(text)
        console.print(f"  [green]✓[/green] applied {r.id}")

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

    still_missing = [m.id for m in pending if _get_nested(new_cfg, m.key_path) is None]
    still_missing += [r.id for r in rewrites if r.pending(new_cfg)]
    if still_missing:
        ids = ", ".join(still_missing)
        console.print(
            f"[red]Patched the file but these migrations did NOT take effect: "
            f"{ids}. Restore from {backup.name} and report this.[/red]"
        )
        sys.exit(2)

    console.print("\n[green]Done.[/green] Restart EloPhanto to pick up the new config.")
