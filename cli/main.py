"""CLI entry point for EloPhanto.

Registered as `elophanto` console script in pyproject.toml.
"""

from __future__ import annotations

import click

from cli.bootstrap_cmd import bootstrap_cmd
from cli.chat_cmd import chat_cmd
from cli.doctor_cmd import doctor_cmd
from cli.gateway_cmd import gateway_cmd
from cli.init_cmd import init_cmd
from cli.kid_cmd import kid_cmd
from cli.mcp_cmd import mcp_cmd
from cli.rollback_cmd import rollback_cmd
from cli.schedule_cmd import schedule_cmd
from cli.skills_cmd import skills_cmd
from cli.telegram_cmd import telegram_cmd
from cli.update_cmd import update_cmd
from cli.vault_cmd import vault_cmd


@click.group()
@click.version_option(package_name="elophanto", prog_name="EloPhanto")
def cli() -> None:
    """EloPhanto — A self-evolving AI agent."""


cli.add_command(init_cmd, "init")
cli.add_command(bootstrap_cmd, "bootstrap")
cli.add_command(doctor_cmd, "doctor")
cli.add_command(chat_cmd, "chat")
cli.add_command(gateway_cmd, "gateway")
cli.add_command(schedule_cmd, "schedule")
cli.add_command(vault_cmd, "vault")
cli.add_command(rollback_cmd, "rollback")
cli.add_command(telegram_cmd, "telegram")
cli.add_command(skills_cmd, "skills")
cli.add_command(mcp_cmd, "mcp")
cli.add_command(kid_cmd, "kid")
cli.add_command(update_cmd, "update")


if __name__ == "__main__":
    cli()
