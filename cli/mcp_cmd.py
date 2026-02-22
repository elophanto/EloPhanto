"""elophanto mcp — Manage MCP tool server connections.

Usage:
    elophanto mcp list            — Show configured servers
    elophanto mcp add NAME        — Add a new MCP server
    elophanto mcp remove NAME     — Remove a server
    elophanto mcp test [NAME]     — Test connection and list tools
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

console = Console()

_PERMISSION_CHOICES = ["safe", "moderate", "destructive"]


def _load_config(config_path: Path) -> dict:
    if not config_path.exists():
        console.print(
            "[red]No config.yaml found.[/red] Run [bold]elophanto init[/bold] first."
        )
        raise SystemExit(1)
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def _save_config(config_path: Path, config: dict) -> None:
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


@click.group()
@click.option(
    "--config",
    "config_path",
    type=click.Path(),
    default="config.yaml",
    help="Path to config.yaml",
)
@click.pass_context
def mcp_cmd(ctx: click.Context, config_path: str) -> None:
    """Manage MCP tool server connections."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = Path(config_path)


@mcp_cmd.command("list")
@click.pass_context
def list_servers(ctx: click.Context) -> None:
    """Show all configured MCP servers."""
    config = _load_config(ctx.obj["config_path"])
    mcp = config.get("mcp", {})
    servers = mcp.get("servers", {})

    if not servers:
        console.print("[dim]No MCP servers configured.[/dim]")
        console.print("Add one with: [bold]elophanto mcp add <name>[/bold]")
        return

    enabled = mcp.get("enabled", False)
    console.print(
        f"MCP: [{'green' if enabled else 'red'}]"
        f"{'enabled' if enabled else 'disabled'}[/]"
    )
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="bold")
    table.add_column("Transport")
    table.add_column("Command / URL")
    table.add_column("Permission")
    table.add_column("Enabled")

    for name, srv in servers.items():
        transport = "http" if srv.get("url") else "stdio"
        target = (
            srv.get("url")
            or f"{srv.get('command', '?')} {' '.join(srv.get('args', []))}"
        )
        if len(target) > 60:
            target = target[:57] + "..."
        perm = srv.get("permission_level", "moderate")
        srv_enabled = srv.get("enabled", True)
        table.add_row(
            name,
            transport,
            target,
            perm,
            "[green]yes[/]" if srv_enabled else "[red]no[/]",
        )

    console.print(table)


@mcp_cmd.command("add")
@click.argument("name")
@click.pass_context
def add_server(ctx: click.Context, name: str) -> None:
    """Add a new MCP server configuration."""
    config_path = ctx.obj["config_path"]
    config = _load_config(config_path)
    mcp = config.setdefault("mcp", {"enabled": False, "servers": {}})
    servers = mcp.setdefault("servers", {})

    if name in servers:
        console.print(f"[yellow]Server '{name}' already exists.[/yellow]")
        if not Confirm.ask("Overwrite?", default=False):
            return

    transport = Prompt.ask(
        "Transport",
        choices=["stdio", "http"],
        default="stdio",
    )

    server_cfg: dict = {}
    if transport == "stdio":
        command = Prompt.ask("Command (e.g. npx, uvx, python)")
        args_raw = Prompt.ask("Args (space-separated)", default="")
        server_cfg["command"] = command
        if args_raw.strip():
            server_cfg["args"] = args_raw.strip().split()

        # Optional env vars
        if Confirm.ask("Add environment variables?", default=False):
            while True:
                key = Prompt.ask("  Env var name (blank to stop)", default="")
                if not key:
                    break
                value = Prompt.ask(f"  {key} value (or vault:name)")
                server_cfg.setdefault("env", {})[key] = value
    else:
        url = Prompt.ask("Server URL")
        server_cfg["url"] = url
        auth = Prompt.ask(
            "Authorization header (or vault:name, blank to skip)", default=""
        )
        if auth:
            server_cfg["headers"] = {"Authorization": auth}

    perm = Prompt.ask(
        "Permission level",
        choices=_PERMISSION_CHOICES,
        default="moderate",
    )
    if perm != "moderate":
        server_cfg["permission_level"] = perm

    servers[name] = server_cfg
    mcp["enabled"] = True
    _save_config(config_path, config)

    console.print(f"[green]Added MCP server '{name}' and enabled MCP.[/green]")
    console.print(f"[dim]Saved to {config_path}[/dim]")

    if Confirm.ask("Test connection now?", default=True):
        _run_test(config_path, name)


@mcp_cmd.command("remove")
@click.argument("name")
@click.pass_context
def remove_server(ctx: click.Context, name: str) -> None:
    """Remove an MCP server from configuration."""
    config_path = ctx.obj["config_path"]
    config = _load_config(config_path)
    servers = config.get("mcp", {}).get("servers", {})

    if name not in servers:
        console.print(f"[red]Server '{name}' not found.[/red]")
        available = ", ".join(servers.keys()) if servers else "none"
        console.print(f"[dim]Available: {available}[/dim]")
        raise SystemExit(1)

    if not Confirm.ask(f"Remove MCP server '{name}'?", default=False):
        return

    del servers[name]
    _save_config(config_path, config)
    console.print(f"[green]Removed '{name}'.[/green]")


@mcp_cmd.command("test")
@click.argument("name", required=False)
@click.pass_context
def test_server(ctx: click.Context, name: str | None) -> None:
    """Test connection to MCP server(s) and list discovered tools."""
    _run_test(ctx.obj["config_path"], name)


def _run_test(config_path: Path, name: str | None) -> None:
    """Test MCP server connection(s)."""
    try:
        import mcp  # noqa: F401
    except ImportError:
        console.print(
            "[red]MCP SDK not installed.[/red]\n"
            "Run: [bold]uv pip install -e '.[mcp]'[/bold]"
        )
        raise SystemExit(1) from None

    config = _load_config(config_path)
    servers = config.get("mcp", {}).get("servers", {})

    if not servers:
        console.print("[dim]No MCP servers configured.[/dim]")
        return

    if name:
        if name not in servers:
            console.print(f"[red]Server '{name}' not found.[/red]")
            raise SystemExit(1)
        targets = {name: servers[name]}
    else:
        targets = servers

    asyncio.run(_test_servers(targets))


async def _test_servers(targets: dict) -> None:
    """Connect to servers, discover tools, and display results."""
    from core.config import MCPServerConfig
    from core.mcp_client import MCPServerConnection

    for name, srv_dict in targets.items():
        console.print(f"\n[bold]{name}[/bold]")

        # Build MCPServerConfig from dict
        transport = "http" if srv_dict.get("url") else "stdio"
        srv_config = MCPServerConfig(
            name=name,
            transport=transport,
            command=srv_dict.get("command", ""),
            args=srv_dict.get("args", []),
            env=srv_dict.get("env", {}),
            cwd=srv_dict.get("cwd", ""),
            url=srv_dict.get("url", ""),
            headers=srv_dict.get("headers", {}),
            permission_level=srv_dict.get("permission_level", "moderate"),
            timeout_seconds=srv_dict.get("timeout_seconds", 30),
            startup_timeout_seconds=srv_dict.get("startup_timeout_seconds", 30),
        )

        conn = MCPServerConnection(srv_config)
        try:
            with console.status(f"  Connecting to {name}..."):
                ok = await conn.connect()

            if not ok:
                console.print("  [red]Connection failed.[/red]")
                continue

            console.print("  [green]Connected.[/green]")

            with console.status("  Discovering tools..."):
                tools = await conn.discover_tools()

            if tools:
                console.print(f"  Found [bold]{len(tools)}[/bold] tools:")
                for t in tools:
                    desc = t.get("description", "")
                    if len(desc) > 60:
                        desc = desc[:57] + "..."
                    console.print(f"    [dim]•[/dim] {t['name']}  [dim]{desc}[/dim]")
            else:
                console.print("  [yellow]No tools discovered.[/yellow]")
        except Exception as e:
            console.print(f"  [red]Error: {e}[/red]")
        finally:
            await conn.disconnect()
