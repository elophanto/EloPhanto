"""``elophanto affect`` — inspect + simulate the affect layer.

Two subcommands so smoke-testing doesn't need three SQLite queries:

    elophanto affect status         # current PAD + label + recent events
    elophanto affect simulate       # synthetic event sequence + trajectory

Status reads the live DB. Simulate runs in-memory against a temp DB
so it's safe to run anytime — never touches the real affect_state.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def _project_root() -> Path:
    """Resolve project root (the dir holding config.yaml). Mirrors the
    convention used by other CLI commands so they can be invoked from
    any subdirectory."""
    cwd = Path.cwd()
    for p in [cwd, *cwd.parents]:
        if (p / "config.yaml").exists() or (p / "config.demo.yaml").exists():
            return p
    return cwd


def _bar(v: float, width: int = 21) -> str:
    """ASCII gauge for [-1, +1]. Center marker at 0."""
    slot = round((v + 1) * (width - 1) / 2)
    slot = max(0, min(width - 1, slot))
    cells = ["─"] * width
    cells[width // 2] = "│"
    if slot == width // 2:
        cells[width // 2] = "●"
    else:
        cells[slot] = "●"
    return "".join(cells)


def _label_color(label: str) -> str:
    """rich color tag based on affective valence."""
    positive = {"joy", "pride", "relief"}
    negative = {"frustration", "anxiety", "dejection", "anger"}
    if label in positive:
        return "green"
    if label in negative:
        return "red"
    if label == "restlessness":
        return "yellow"
    if label == "unease":
        return "yellow"
    return "cyan"  # equanimity


# ──────────────────────────────────────────────────────────────────
# affect status — live DB inspection
# ──────────────────────────────────────────────────────────────────


async def _status_async(db_path: Path) -> int:
    from core.affect import AffectManager
    from core.database import Database

    if not db_path.exists():
        console.print(f"[red]Database not found:[/red] {db_path}")
        console.print(
            "[dim]Run the agent at least once so the schema is created.[/dim]"
        )
        return 1

    db = Database(db_path)
    await db.initialize()
    try:
        mgr = AffectManager(db=db)
        await mgr.load_or_create()
        mood = await mgr.current_mood()
        state = await mgr.get_state()
        temp_mod = await mgr.temperature_modifier()

        label = mood["dominant_label"]
        color = _label_color(label)

        # Header panel
        console.print(
            Panel(
                f"[bold {color}]{label}[/bold {color}] — "
                f"{mood['description']}\n\n"
                f"pleasure   {_bar(state.pleasure)}  {state.pleasure:+.2f}\n"
                f"arousal    {_bar(state.arousal)}  {state.arousal:+.2f}\n"
                f"dominance  {_bar(state.dominance)}  {state.dominance:+.2f}\n\n"
                f"magnitude  {mood['magnitude']:.2f}    "
                f"temp_modifier  {temp_mod:+.3f}",
                title="Affect — current state",
                border_style=color,
            )
        )

        # Recent events
        if state.recent_events:
            table = Table(title="Recent affective events (newest first)")
            table.add_column("when", style="dim")
            table.add_column("source")
            table.add_column("label")
            table.add_column("ΔP", justify="right")
            table.add_column("ΔA", justify="right")
            table.add_column("ΔD", justify="right")
            for e in reversed(state.recent_events):
                # Trim ISO timestamp to HH:MM:SS UTC for compactness.
                ts = e.created_at[11:19] if len(e.created_at) >= 19 else e.created_at
                table.add_row(
                    ts,
                    e.source,
                    f"[{_label_color(e.label)}]{e.label}[/{_label_color(e.label)}]",
                    f"{e.pleasure_delta:+.2f}",
                    f"{e.arousal_delta:+.2f}",
                    f"{e.dominance_delta:+.2f}",
                )
            console.print(table)
        else:
            console.print("[dim]No recent events recorded yet.[/dim]")

        # Last decay timestamp — useful for "is this state stale?"
        if state.last_decay_at:
            console.print(f"\n[dim]last decay sweep: {state.last_decay_at}[/dim]")
        if state.updated_at:
            console.print(f"[dim]last updated:     {state.updated_at}[/dim]")

        return 0
    finally:
        await db.close()


# ──────────────────────────────────────────────────────────────────
# affect simulate — trajectory check against a temp DB
# ──────────────────────────────────────────────────────────────────


async def _simulate_async(scenario: str) -> int:
    """Run a synthetic event sequence and print the trajectory.

    Pure tooling — uses a tempfile DB, never touches the real one.
    Catches calibration drift if `_LABEL_VECTORS` ever gets retuned.
    """
    from core.affect import (
        AffectManager,
        emit_anger,
        emit_anxiety,
        emit_frustration,
        emit_joy,
        emit_pride,
        emit_relief,
    )
    from core.database import Database

    scenarios: dict[str, list[tuple[str, str]]] = {
        "frustration": [
            ("frustration", "ego"),
            ("frustration", "ego"),
            ("frustration", "ego"),
        ],
        "anger": [
            # Mirrors the ego severity-based dispatch: high-severity
            # corrections in a row escalate to anger (+D, pushing back).
            ("anger", "ego"),
            ("anger", "ego"),
            ("anger", "ego"),
        ],
        "escalation": [
            # The natural arc: frustration compounds, then a high-severity
            # "Nth time I told you" trips anger. Distinct from pure anger
            # because the trajectory shows the escalation path.
            ("frustration", "ego"),
            ("frustration", "ego"),
            ("anger", "ego"),
            ("anger", "ego"),
        ],
        "burst": [
            ("frustration", "ego"),
            ("frustration", "ego"),
            ("anxiety", "verification"),
            ("frustration", "ego"),
        ],
        "win": [
            ("pride", "goal"),
            ("relief", "verification"),
            ("joy", "user"),
        ],
        "fail-recover": [
            ("anxiety", "executor"),
            ("anxiety", "verification"),
            ("relief", "verification"),
        ],
        "mixed": [
            ("frustration", "ego"),
            ("frustration", "ego"),
            ("relief", "verification"),
            ("pride", "goal"),
        ],
    }

    if scenario not in scenarios:
        console.print(f"[red]Unknown scenario:[/red] {scenario}")
        console.print(f"[dim]Choose one of:[/dim] {', '.join(scenarios.keys())}")
        return 1

    sequence = scenarios[scenario]
    emitter_map = {
        "frustration": emit_frustration,
        "anger": emit_anger,
        "anxiety": emit_anxiety,
        "relief": emit_relief,
        "pride": emit_pride,
        "joy": emit_joy,
    }

    # Tempfile DB — clean up on exit.
    tmpfile = tempfile.NamedTemporaryFile(
        suffix=".db", prefix="affect-sim-", delete=False
    )
    tmpfile.close()
    db_path = Path(tmpfile.name)
    try:
        db = Database(db_path)
        await db.initialize()
        mgr = AffectManager(db=db)
        await mgr.load_or_create()

        table = Table(title=f"Affect trajectory — scenario: {scenario}")
        table.add_column("step", justify="right")
        table.add_column("event")
        table.add_column("source", style="dim")
        table.add_column("P", justify="right")
        table.add_column("A", justify="right")
        table.add_column("D", justify="right")
        table.add_column("label")
        table.add_column("temp_mod", justify="right")

        # Step 0 baseline.
        mood = await mgr.current_mood()
        delta = await mgr.temperature_modifier()
        table.add_row(
            "0",
            "—",
            "(baseline)",
            "0.00",
            "0.00",
            "0.00",
            f"[cyan]{mood['dominant_label']}[/cyan]",
            f"{delta:+.2f}",
        )

        for i, (label, source) in enumerate(sequence, start=1):
            await emitter_map[label](mgr, source=source)
            mood = await mgr.current_mood()
            delta = await mgr.temperature_modifier()
            color = _label_color(mood["dominant_label"])
            table.add_row(
                str(i),
                label,
                source,
                f"{mood['pleasure']:+.2f}",
                f"{mood['arousal']:+.2f}",
                f"{mood['dominance']:+.2f}",
                f"[{color}]{mood['dominant_label']}[/{color}]",
                f"{delta:+.2f}",
            )

        console.print(table)

        # System-prompt block preview at the end of the sequence.
        block = await mgr.build_affect_context()
        if block:
            console.print(
                Panel(
                    block,
                    title="<affect> system-prompt block (final state)",
                    border_style="dim",
                )
            )
        else:
            console.print(
                "[dim]Final state below inject threshold — no prompt block.[/dim]"
            )

        await db.close()
        return 0
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ──────────────────────────────────────────────────────────────────
# Click wiring
# ──────────────────────────────────────────────────────────────────


@click.group(name="affect")
def affect_cmd() -> None:
    """Inspect and simulate the agent's state-level affect.

    See docs/69-AFFECT.md for the design rationale. State-level affect
    decays toward zero on the order of minutes-to-hours and colors
    the agent's tone without changing capability.
    """
    pass


@affect_cmd.command(name="status")
@click.option(
    "--db",
    "db_path_override",
    default=None,
    help="Override the DB path (defaults to project's data/elophanto.db)",
)
def affect_status(db_path_override: str | None) -> None:
    """Show current PAD state, dominant label, and recent events."""
    if db_path_override:
        db_path = Path(db_path_override).expanduser()
    else:
        db_path = _project_root() / "data" / "elophanto.db"
    rc = asyncio.run(_status_async(db_path))
    raise SystemExit(rc)


@affect_cmd.command(name="simulate")
@click.argument(
    "scenario",
    default="frustration",
    type=click.Choice(
        [
            "frustration",
            "anger",
            "escalation",
            "burst",
            "win",
            "fail-recover",
            "mixed",
        ]
    ),
)
def affect_simulate(scenario: str) -> None:
    """Run a synthetic affect sequence in a tempfile DB and print the
    trajectory. Never touches the real database.

    SCENARIO is one of:
      frustration   — three corrections in a row (compounding)
      anger         — three "Nth time I told you" corrections (pushing back)
      escalation    — frustration that escalates to anger
      burst         — frustration + anxiety mix
      win           — pride + relief + joy
      fail-recover  — anxiety twice, then relief
      mixed         — frustration → relief → pride
    """
    rc = asyncio.run(_simulate_async(scenario))
    raise SystemExit(rc)
