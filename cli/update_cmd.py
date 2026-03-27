"""elophanto update — Self-update EloPhanto to the latest version."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import click

# Project root: parent of cli/
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def _get_branch(git_cmd: list[str]) -> str:
    """Get the current git branch, fall back to 'main'."""
    try:
        result = subprocess.run(
            git_cmd + ["rev-parse", "--abbrev-ref", "HEAD"],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "main"


def _commits_behind(git_cmd: list[str], branch: str) -> int:
    """Count commits behind origin."""
    try:
        result = subprocess.run(
            git_cmd + ["rev-list", f"HEAD..origin/{branch}", "--count"],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return int(result.stdout.strip())
    except Exception:
        return -1


def _stash_if_needed(git_cmd: list[str]) -> bool:
    """Stash local changes if any. Returns True if stashed."""
    result = subprocess.run(
        git_cmd + ["status", "--porcelain"],
        cwd=_PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        click.echo("  Stashing local changes...")
        subprocess.run(
            git_cmd + ["stash", "push", "-m", "elophanto-update-autostash"],
            cwd=_PROJECT_ROOT,
            check=True,
        )
        return True
    return False


def _restore_stash(git_cmd: list[str]) -> None:
    """Restore stashed changes."""
    try:
        subprocess.run(
            git_cmd + ["stash", "pop"],
            cwd=_PROJECT_ROOT,
            check=True,
            capture_output=True,
        )
        click.echo("  Restored local changes from stash.")
    except subprocess.CalledProcessError:
        click.echo("  Warning: could not restore stash. Run 'git stash pop' manually.")


@click.command("update")
@click.option("--check", is_flag=True, help="Only check for updates, don't install")
def update_cmd(check: bool) -> None:
    """Update EloPhanto to the latest version.

    Pulls the latest code from GitHub, reinstalls Python dependencies,
    rebuilds the browser bridge, and syncs skills.
    """
    git_dir = _PROJECT_ROOT / ".git"
    if not git_dir.exists():
        click.echo("Not a git repository. Please reinstall:")
        click.echo(
            "  git clone https://github.com/elophanto/EloPhanto.git && "
            "cd EloPhanto && ./setup.sh"
        )
        sys.exit(1)

    git_cmd = ["git"]

    # Fetch
    click.echo("Fetching updates...")
    try:
        subprocess.run(
            git_cmd + ["fetch", "origin", "--quiet"],
            cwd=_PROJECT_ROOT,
            check=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        click.echo("Failed to fetch from origin. Check your network connection.")
        sys.exit(1)

    branch = _get_branch(git_cmd)
    behind = _commits_behind(git_cmd, branch)

    if behind == 0:
        click.echo("Already up to date!")
        return

    if behind < 0:
        click.echo("Could not determine update status.")
        sys.exit(1)

    click.echo(f"Found {behind} new commit(s) on {branch}")

    if check:
        click.echo(f"Run 'elophanto update' to install {behind} update(s).")
        return

    # Stash local changes
    stashed = _stash_if_needed(git_cmd)

    # Pull
    click.echo("Pulling updates...")
    try:
        subprocess.run(
            git_cmd + ["pull", "--ff-only", "origin", branch],
            cwd=_PROJECT_ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        click.echo("Pull failed (merge conflict?). Run 'git pull' manually to resolve.")
        if stashed:
            _restore_stash(git_cmd)
        sys.exit(1)

    # Restore stash
    if stashed:
        _restore_stash(git_cmd)

    # Reinstall Python dependencies
    click.echo("Updating Python dependencies...")
    uv_bin = shutil.which("uv")
    if uv_bin:
        try:
            subprocess.run(
                [uv_bin, "pip", "install", "-e", ".", "--quiet"],
                cwd=_PROJECT_ROOT,
                check=True,
            )
        except subprocess.CalledProcessError:
            click.echo("  Warning: uv pip install failed. Try running setup.sh.")
    else:
        pip_cmd = [sys.executable, "-m", "pip"]
        try:
            subprocess.run(
                pip_cmd + ["install", "-e", ".", "--quiet"],
                cwd=_PROJECT_ROOT,
                check=True,
            )
        except subprocess.CalledProcessError:
            click.echo("  Warning: pip install failed. Try running setup.sh.")

    # Rebuild browser bridge if npm is available
    bridge_dir = _PROJECT_ROOT / "bridge" / "browser"
    if (bridge_dir / "package.json").exists() and shutil.which("npm"):
        click.echo("Rebuilding browser bridge...")
        try:
            subprocess.run(
                ["npm", "install", "--silent"],
                cwd=bridge_dir,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["npm", "run", "build", "--silent"],
                cwd=bridge_dir,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            click.echo(
                "  Warning: bridge rebuild failed. Run 'npm run build' in bridge/browser/."
            )

    click.echo("")
    click.echo(f"Updated! ({behind} commits pulled)")
    click.echo("Restart EloPhanto to use the new version.")
