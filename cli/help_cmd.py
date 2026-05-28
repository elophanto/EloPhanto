"""Task-oriented help cheat-sheet.

``elophanto --help`` lists every command but doesn't tell you what to
DO with them. This command surfaces the common recipes grouped by
task, so a new operator (or future-you) can find the right command
without scanning 25 subcommand descriptions.

Topics are short and recipe-flavored — the goal is "I want to X, what
do I run?" The exhaustive flag listings still live under each
subcommand's ``--help``.
"""

from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


# Each topic value is (title, rows). Rows starting with "# " render as
# inline commentary instead of a command/description pair — useful for
# explaining gotchas (e.g. goals have no CLI surface).
_TOPICS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "config": (
        "Configuring EloPhanto",
        [
            (
                "elophanto init",
                "First-time setup wizard (LLM keys, browser, channels, ...)",
            ),
            ("elophanto init edit", "Menu of sections to re-edit"),
            (
                "elophanto init edit browser",
                "Switch local Chrome ↔ cloud browser; pick profile",
            ),
            (
                "elophanto init edit providers",
                "Update LLM API keys / enabled providers",
            ),
            ("elophanto init edit models", "Default LLM models per task type"),
            (
                "elophanto init edit permissions",
                "Tool permission tiers (auto / ask / deny)",
            ),
            ("elophanto init edit channels", "Telegram / Discord / Slack bot tokens"),
            ("elophanto init edit email", "AgentMail / SMTP configuration"),
            ("elophanto init edit payments", "Payment provider keys"),
            ("elophanto init edit replicate", "Replicate API for image / video models"),
            ("elophanto init edit gateway", "Gateway host, port, session limits"),
            ("elophanto init edit swarm", "Swarm coordinator settings"),
            ("elophanto init edit scheduler", "Scheduler concurrency limits"),
            ("elophanto init edit mcp", "MCP tool server registry"),
            (
                "elophanto init edit autonomous_mind",
                "Self-driving loop budget + cadence",
            ),
            (
                "elophanto themes list / show / init / validate",
                "Dashboard themes — fork the look, share with other operators",
            ),
            (
                "elophanto chat --theme <name>",
                "One-off override of dashboard.theme",
            ),
            ("elophanto config show", "Print effective merged config"),
            ("elophanto config migrate", "Patch config.yaml with new-version sections"),
            ("elophanto bootstrap", "Generate knowledge/system/ starter docs"),
        ],
    ),
    "run": (
        "Running the agent",
        [
            ("elophanto chat", "Interactive chat session (default entry point)"),
            ("elophanto gateway", "Start gateway + every enabled channel adapter"),
            (
                "elophanto daemon install",
                "Install + start the gateway as a system daemon",
            ),
            (
                "elophanto daemon status",
                "Show daemon state (running / stopped / not installed)",
            ),
            ("elophanto daemon logs", "Tail the daemon log"),
            (
                "elophanto daemon uninstall",
                "Stop + remove the daemon (keeps logs/config)",
            ),
            ("elophanto telegram", "Telegram bot only (if not using gateway)"),
            ("elophanto stop", "Cancel current run (this session only)"),
            ("elophanto stop --hard", "Halt mind + scheduler + all sessions"),
            ("elophanto resume", "Clear STOP sentinel — tick again on next wake"),
        ],
    ),
    "health": (
        "Health checks & diagnostics",
        [
            (
                "elophanto doctor",
                "Green/yellow/red preflight check (config, deps, vault)",
            ),
            ("elophanto vault list", "Names of secrets stored in the encrypted vault"),
            ("elophanto config show", "Effective config after profile + env merging"),
            ("elophanto affect status", "Current PAD affect state + recent events"),
            (
                "elophanto affect simulate",
                "Run a synthetic affect sequence (debug tool)",
            ),
            ("elophanto update", "Pull the latest agent code + rebuild bridge"),
        ],
    ),
    "vault": (
        "Secrets vault (encrypted credentials)",
        [
            ("elophanto vault init", "Create the encrypted vault (one-time)"),
            (
                "elophanto vault set <key> <value>",
                "Store a secret (Telegram token, etc.)",
            ),
            ("elophanto vault get <key>", "Print a stored secret"),
            ("elophanto vault list", "List secret names (values stay encrypted)"),
            ("elophanto vault delete <key>", "Remove a stored secret"),
            ("elophanto vault restore", "Restore vault from the most recent backup"),
        ],
    ),
    "goals": (
        "Goals & missions (durable drives)",
        [
            ("# Goals are CREATED by the agent (via the `goal_create` LLM tool).", ""),
            ("# In chat say: 'set a goal to ...'. From the CLI you can inspect", ""),
            ("# and prune the goal queue:", ""),
            ("elophanto goals list", "Recent goals (newest first, default 20)"),
            (
                "elophanto goals list --status active",
                "Filter by status (active/paused/completed/...)",
            ),
            (
                "elophanto goals show <id>",
                "Detail incl. checkpoints, cost, mission link",
            ),
            ("elophanto goals cancel <id>", "Mark cancelled — runner skips it"),
            ("elophanto goals pause/resume <id>", "Toggle active ↔ paused"),
            ("elophanto goals delete <id>", "Hard-delete a goal + its checkpoints"),
            ("elophanto goals delete-all", "Wipe the entire goal queue (asks confirm)"),
            ("# Missions are the parent drives a goal can belong to:", ""),
            ("elophanto mission list", "Active missions (--all for paused/retired)"),
            ("elophanto mission show <id>", "Mission detail incl. linked goals"),
            ("elophanto mission touch <id>", "Bump a mission's last-active timestamp"),
        ],
    ),
    "abe": (
        "ABE framework (companies / roles / voice / strategy / drafts)",
        [
            ("elophanto company list", "List all companies the agent manages"),
            ("elophanto company create <slug> [name]", "Create a new company"),
            ("elophanto company use <slug>", "Switch the active company"),
            ("elophanto company current", "Show the active company"),
            ("elophanto company pause/resume <slug>", "Pause / resume a company"),
            ("elophanto company archive <slug>", "Archive (soft-delete)"),
            ("elophanto company purge <slug>", "Hard-delete (destructive)"),
            ("elophanto company report [slug]", "Ledger + KPI report"),
            ("elophanto company trust", "Show / edit trust ladder"),
            (
                "elophanto role list / show / use <name>",
                "Role persona overlay (CEO / engineer / ...)",
            ),
            ("elophanto role clear / current", "Drop / inspect the active role"),
            (
                "elophanto voice show / proposed / approve / reject",
                "Voice contract review loop",
            ),
            (
                "elophanto voice exemplars / extract",
                "Manage voice exemplars + LLM extraction",
            ),
            (
                "elophanto strategy show / proposed / archive",
                "Strategy artifact lifecycle (Phase 11)",
            ),
            (
                "elophanto strategy capabilities / blockers",
                "Capability + blocker audit",
            ),
            ("elophanto drafts list", "Outreach drafts queue (Phase 9)"),
        ],
    ),
    "skills": (
        "Skills, MCP, and self-modification",
        [
            ("elophanto skills list", "List loaded skills"),
            ("elophanto skills hub", "Search PhantoHub registry"),
            (
                "elophanto skills install <name|url>",
                "Install a skill (hub / local / git URL)",
            ),
            ("elophanto skills read <name>", "Print a skill's SKILL.md"),
            ("elophanto skills remove <name>", "Remove an installed skill"),
            ("elophanto mcp list", "Show configured MCP tool servers"),
            ("elophanto mcp add / remove / test", "Manage MCP server connections"),
            ("elophanto rollback --list", "List revertible self-modification commits"),
            ("elophanto rollback --commit <sha>", "Revert a specific self-edit"),
        ],
    ),
    "ops": (
        "Schedules, kids, and trading",
        [
            ("elophanto schedule list", "Show all scheduled tasks"),
            ("elophanto schedule status", "Resource-typed concurrency picture"),
            ("elophanto schedule enable/disable <id>", "Toggle a schedule"),
            ("elophanto schedule delete <id>", "Remove a schedule"),
            ("elophanto schedule history <id>", "Past runs for a schedule"),
            ("elophanto kid list", "List child agents (kid-agent admin)"),
            ("elophanto kid build", "Build the kid container image"),
            ("elophanto kid destroy <id|name>", "Force-destroy a kid (escape hatch)"),
            ("elophanto polymarket performance", "Trading P&L / win rate"),
            ("elophanto polymarket mark", "Mark open positions to current best bid"),
        ],
    ),
}


_INTRO = (
    "[bold]EloPhanto — quick reference[/bold]\n\n"
    "Run [bold cyan]elophanto help <topic>[/bold cyan] for a focused list, or "
    "[bold cyan]elophanto <cmd> --help[/bold cyan] for full flag docs."
)


def _print_topic(topic: str) -> None:
    title, rows = _TOPICS[topic]
    table = Table(
        title=title,
        title_style="bold",
        show_header=False,
        box=None,
        padding=(0, 2),
    )
    table.add_column(style="cyan", no_wrap=False)
    table.add_column(style="dim")
    for cmd, desc in rows:
        if cmd.startswith("# "):
            # Inline commentary row — render across both columns in dim.
            table.add_row(f"[dim italic]{cmd[2:]}[/dim italic]", "")
            continue
        table.add_row(cmd, desc)
    console.print()
    console.print(table)
    console.print()


def _print_all() -> None:
    console.print()
    console.print(Panel(_INTRO, expand=False, padding=(1, 2)))
    console.print()

    topics_line = "  ".join(f"[cyan]{t}[/cyan]" for t in _TOPICS)
    console.print(f"[bold]Topics:[/bold]  {topics_line}")
    for topic in _TOPICS:
        _print_topic(topic)

    console.print(
        "[dim]Tip: every command supports --help, e.g. "
        "`elophanto init edit --help`.[/dim]"
    )
    console.print()


@click.command("help")
@click.argument("topic", required=False)
def help_cmd(topic: str | None) -> None:
    """Show task-oriented recipes (config / run / health / vault / …).

    With no argument prints all topics. With a topic name prints just
    that section. Topic names: config, run, health, vault, goals, abe, skills, ops.
    """
    if topic is None:
        _print_all()
        return
    if topic not in _TOPICS:
        console.print(
            f"[red]Unknown topic:[/red] {topic}\n" f"Available: {', '.join(_TOPICS)}"
        )
        raise SystemExit(1)
    _print_topic(topic)
