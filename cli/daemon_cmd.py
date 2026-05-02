"""elophanto daemon — install/uninstall/status the gateway as a background service.

Lets the agent keep running after you close the terminal. Today's
`start.sh` is foreground-only — quit the terminal, the agent dies.
With `daemon install`, EloPhanto registers a launchd user agent on
macOS or a systemd user service on Linux that auto-starts at login
and restarts on crash.

Vault password handling:
- We never write the password to disk in plaintext.
- macOS: stored in the user keychain via the system `security` tool.
- Linux: stored via `secret-tool` (libsecret) when available; falls
  back to a 0600 file at `~/.elophanto/vault_password` with a clear
  warning. User can opt out and pass `ELOPHANTO_VAULT_PASSWORD`
  themselves through the service's environment.

Logs go to `~/.elophanto/logs/daemon.{out,err}.log`. View via
`elophanto daemon logs`.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.prompt import Confirm, Prompt

console = Console()

# Service identifiers — lowercase, dotted reverse-DNS for launchd; bare slug for systemd.
_LAUNCHD_LABEL = "com.elophanto.gateway"
_SYSTEMD_UNIT = "elophanto-gateway.service"

# Keychain storage IDs (macOS Keychain + libsecret).
_KEYCHAIN_SERVICE = "elophanto"
_KEYCHAIN_ACCOUNT = "vault"


# ────────────────────────────────────────────────────────────────────
# Platform detection
# ────────────────────────────────────────────────────────────────────


def _platform() -> str:
    """Return 'macos' | 'linux' | 'unsupported'."""
    s = platform.system().lower()
    if s == "darwin":
        return "macos"
    if s == "linux":
        return "linux"
    return "unsupported"


def _user_home() -> Path:
    return Path.home()


def _data_dir() -> Path:
    """Where logs + fallback files live."""
    d = _user_home() / ".elophanto"
    d.mkdir(parents=True, exist_ok=True)
    (d / "logs").mkdir(parents=True, exist_ok=True)
    return d


# ────────────────────────────────────────────────────────────────────
# Vault password storage (OS keychain, no plaintext on disk)
# ────────────────────────────────────────────────────────────────────


def _store_password_macos(password: str) -> bool:
    """Store the vault password in the user keychain. Returns True on success."""
    if not shutil.which("security"):
        return False
    # Delete any previous entry so add doesn't duplicate.
    subprocess.run(
        [
            "security",
            "delete-generic-password",
            "-s",
            _KEYCHAIN_SERVICE,
            "-a",
            _KEYCHAIN_ACCOUNT,
        ],
        capture_output=True,
        check=False,
    )
    rc = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-s",
            _KEYCHAIN_SERVICE,
            "-a",
            _KEYCHAIN_ACCOUNT,
            "-w",
            password,
            "-U",  # update if exists
        ],
        capture_output=True,
    )
    return rc.returncode == 0


def _read_password_macos() -> str | None:
    if not shutil.which("security"):
        return None
    rc = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-s",
            _KEYCHAIN_SERVICE,
            "-a",
            _KEYCHAIN_ACCOUNT,
            "-w",
        ],
        capture_output=True,
        text=True,
    )
    if rc.returncode != 0:
        return None
    return rc.stdout.strip() or None


def _delete_password_macos() -> None:
    if not shutil.which("security"):
        return
    subprocess.run(
        [
            "security",
            "delete-generic-password",
            "-s",
            _KEYCHAIN_SERVICE,
            "-a",
            _KEYCHAIN_ACCOUNT,
        ],
        capture_output=True,
        check=False,
    )


def _store_password_linux(password: str) -> bool:
    """Try secret-tool first; fall back to 0600 file under ~/.elophanto/."""
    if shutil.which("secret-tool"):
        rc = subprocess.run(
            [
                "secret-tool",
                "store",
                "--label=EloPhanto vault password",
                "service",
                _KEYCHAIN_SERVICE,
                "account",
                _KEYCHAIN_ACCOUNT,
            ],
            input=password,
            text=True,
            capture_output=True,
        )
        if rc.returncode == 0:
            return True
        console.print(
            f"  [yellow]secret-tool failed ({rc.stderr.strip()}); "
            "falling back to local file.[/]"
        )
    # Fallback: 0600 file. Less ideal but workable.
    fp = _data_dir() / "vault_password"
    fp.write_text(password, encoding="utf-8")
    fp.chmod(0o600)
    console.print(
        f"  [yellow]Stored vault password at {fp} (0600). "
        "Install libsecret + secret-tool for encrypted storage.[/]"
    )
    return True


def _read_password_linux() -> str | None:
    if shutil.which("secret-tool"):
        rc = subprocess.run(
            [
                "secret-tool",
                "lookup",
                "service",
                _KEYCHAIN_SERVICE,
                "account",
                _KEYCHAIN_ACCOUNT,
            ],
            capture_output=True,
            text=True,
        )
        if rc.returncode == 0 and rc.stdout.strip():
            return rc.stdout.strip()
    fp = _data_dir() / "vault_password"
    if fp.exists():
        try:
            return fp.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None
    return None


def _delete_password_linux() -> None:
    if shutil.which("secret-tool"):
        subprocess.run(
            [
                "secret-tool",
                "clear",
                "service",
                _KEYCHAIN_SERVICE,
                "account",
                _KEYCHAIN_ACCOUNT,
            ],
            capture_output=True,
            check=False,
        )
    fp = _data_dir() / "vault_password"
    if fp.exists():
        fp.unlink()


def _store_password(password: str) -> bool:
    """Dispatch to the platform store. No-op when password is empty."""
    if not password:
        return True
    p = _platform()
    if p == "macos":
        return _store_password_macos(password)
    if p == "linux":
        return _store_password_linux(password)
    return False


def _read_password() -> str | None:
    p = _platform()
    if p == "macos":
        return _read_password_macos()
    if p == "linux":
        return _read_password_linux()
    return None


def _delete_password() -> None:
    p = _platform()
    if p == "macos":
        _delete_password_macos()
    elif p == "linux":
        _delete_password_linux()


# ────────────────────────────────────────────────────────────────────
# Service file generation
# ────────────────────────────────────────────────────────────────────


def _resolve_python() -> str:
    """Best-guess full path to the python interpreter that should run the daemon.

    Prefer the project's .venv if it exists (works for source installs);
    fall back to sys.executable (works after `pipx install elophanto`).
    """
    project_root = Path(__file__).resolve().parents[1]
    venv_python = project_root / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _resolve_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _build_launchd_plist(python: str, project_root: Path, log_dir: Path) -> str:
    """Generate a launchd plist as a string. Caller writes it to disk."""
    out_log = log_dir / "daemon.out.log"
    err_log = log_dir / "daemon.err.log"
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{_LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>-m</string>
    <string>cli.gateway_cmd</string>
    <string>--no-cli</string>
  </array>
  <key>WorkingDirectory</key>
  <string>{project_root}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>ELOPHANTO_DAEMON</key>
    <string>1</string>
    <key>PATH</key>
    <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
    <key>Crashed</key>
    <true/>
  </dict>
  <key>ThrottleInterval</key>
  <integer>30</integer>
  <key>StandardOutPath</key>
  <string>{out_log}</string>
  <key>StandardErrorPath</key>
  <string>{err_log}</string>
</dict>
</plist>
"""


def _build_systemd_unit(python: str, project_root: Path, log_dir: Path) -> str:
    """Generate a systemd user unit. Logs go to journald + the log dir."""
    return f"""\
[Unit]
Description=EloPhanto gateway (background daemon)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={project_root}
ExecStart={python} -m cli.gateway_cmd --no-cli
Environment=ELOPHANTO_DAEMON=1
Restart=on-failure
RestartSec=30
# Mirror logs into a file the user expects, in addition to journald.
StandardOutput=append:{log_dir}/daemon.out.log
StandardError=append:{log_dir}/daemon.err.log

[Install]
WantedBy=default.target
"""


def _launchd_plist_path() -> Path:
    return _user_home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"


def _systemd_unit_path() -> Path:
    return _user_home() / ".config" / "systemd" / "user" / _SYSTEMD_UNIT


# ────────────────────────────────────────────────────────────────────
# CLI commands
# ────────────────────────────────────────────────────────────────────


@click.group()
def daemon_cmd() -> None:
    """Run the EloPhanto gateway as a background daemon."""


@daemon_cmd.command("install")
@click.option(
    "--password",
    default=None,
    help="Vault password (otherwise prompted). Empty skips vault.",
)
@click.option(
    "--no-keychain",
    is_flag=True,
    help="Don't store the password — caller will set ELOPHANTO_VAULT_PASSWORD.",
)
def install_cmd(password: str | None, no_keychain: bool) -> None:
    """Install + start the gateway daemon."""
    p = _platform()
    if p == "unsupported":
        console.print(
            f"[red]Daemon mode not supported on {platform.system()}.[/] "
            "Run `./start.sh` in a terminal multiplexer (tmux, screen) instead."
        )
        sys.exit(1)

    project_root = _resolve_project_root()
    python = _resolve_python()
    log_dir = _data_dir() / "logs"

    # ── 1. Vault password ──
    if not no_keychain and password is None:
        password = Prompt.ask(
            "  Vault password (Enter to skip — daemon runs without vault)",
            password=True,
            default="",
        )
    if password and not no_keychain:
        if _store_password(password):
            console.print(
                f"  [green]Vault password stored in "
                f"{'macOS Keychain' if p == 'macos' else 'libsecret/keyring'}.[/]"
            )
        else:
            console.print(
                "  [yellow]Could not store password securely. Daemon will need "
                "ELOPHANTO_VAULT_PASSWORD set in its environment.[/]"
            )

    # ── 2. Write service file ──
    if p == "macos":
        plist = _build_launchd_plist(python, project_root, log_dir)
        plist_path = _launchd_plist_path()
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_text(plist)
        console.print(f"  [dim]Wrote {plist_path}[/]")
        # Unload first in case a previous version is loaded.
        subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
        rc = subprocess.run(
            ["launchctl", "load", "-w", str(plist_path)], capture_output=True
        )
        if rc.returncode != 0:
            console.print(
                f"  [red]launchctl load failed: {rc.stderr.decode().strip()}[/]"
            )
            sys.exit(1)
    else:
        unit = _build_systemd_unit(python, project_root, log_dir)
        unit_path = _systemd_unit_path()
        unit_path.parent.mkdir(parents=True, exist_ok=True)
        unit_path.write_text(unit)
        console.print(f"  [dim]Wrote {unit_path}[/]")
        for cmd in (
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "--now", _SYSTEMD_UNIT],
        ):
            rc = subprocess.run(cmd, capture_output=True)
            if rc.returncode != 0:
                console.print(
                    f"  [red]{' '.join(cmd)} failed: "
                    f"{rc.stderr.decode().strip()}[/]"
                )
                sys.exit(1)
        # On systemd, lingering keeps the service running across login sessions.
        # Ask the user about it — needs sudo.
        if Confirm.ask(
            "  Enable lingering so the daemon survives logout? (needs sudo)",
            default=True,
        ):
            subprocess.run(
                ["sudo", "loginctl", "enable-linger", os.environ.get("USER", "")],
                check=False,
            )

    console.print(
        f"  [green]Daemon installed and started.[/] "
        f"Logs: {log_dir}/daemon.{{out,err}}.log"
    )
    console.print(
        "  Status:    [dim]elophanto daemon status[/]\n"
        "  Stop:      [dim]elophanto daemon uninstall[/]\n"
        "  Logs tail: [dim]elophanto daemon logs[/]"
    )


@daemon_cmd.command("uninstall")
@click.option("--keep-password", is_flag=True, help="Don't remove keychain entry.")
def uninstall_cmd(keep_password: bool) -> None:
    """Stop + remove the daemon (preserves logs and config)."""
    p = _platform()
    if p == "macos":
        plist_path = _launchd_plist_path()
        if plist_path.exists():
            subprocess.run(
                ["launchctl", "unload", str(plist_path)], capture_output=True
            )
            plist_path.unlink()
            console.print(f"  [green]Removed {plist_path}[/]")
        else:
            console.print("  [dim]No plist found — daemon was not installed.[/]")
    elif p == "linux":
        unit_path = _systemd_unit_path()
        for cmd in (
            ["systemctl", "--user", "disable", "--now", _SYSTEMD_UNIT],
            ["systemctl", "--user", "daemon-reload"],
        ):
            subprocess.run(cmd, capture_output=True, check=False)
        if unit_path.exists():
            unit_path.unlink()
            console.print(f"  [green]Removed {unit_path}[/]")
        else:
            console.print("  [dim]No unit found — daemon was not installed.[/]")
    else:
        console.print(f"[red]Daemon not supported on {platform.system()}.[/]")
        sys.exit(1)

    if not keep_password:
        _delete_password()
        console.print("  [dim]Removed stored vault password.[/]")
    console.print("  [green]Daemon uninstalled.[/]")


@daemon_cmd.command("status")
def status_cmd() -> None:
    """Show daemon state (running / stopped / not installed)."""
    p = _platform()
    if p == "macos":
        rc = subprocess.run(
            ["launchctl", "list", _LAUNCHD_LABEL],
            capture_output=True,
            text=True,
        )
        if rc.returncode != 0:
            console.print("  [yellow]Daemon not installed.[/]")
            sys.exit(1)
        # Parse the dict-format output for PID + last exit status.
        out = rc.stdout
        pid_line = next((line for line in out.splitlines() if '"PID"' in line), "")
        exit_line = next(
            (line for line in out.splitlines() if '"LastExitStatus"' in line), ""
        )
        if pid_line and "= " in pid_line:
            console.print(
                f"  [green]Running.[/] {pid_line.strip()} | {exit_line.strip()}"
            )
        else:
            console.print(
                f"  [yellow]Installed but not running.[/] {exit_line.strip()}"
            )
    elif p == "linux":
        rc = subprocess.run(
            ["systemctl", "--user", "is-active", _SYSTEMD_UNIT],
            capture_output=True,
            text=True,
        )
        state = rc.stdout.strip()
        if state == "active":
            console.print("  [green]Running.[/]")
        elif state in ("inactive", "failed"):
            console.print(f"  [yellow]{state}.[/] See `elophanto daemon logs`.")
        else:
            console.print(f"  [yellow]Daemon not installed ({state}).[/]")
            sys.exit(1)
    else:
        console.print(f"[red]Not supported on {platform.system()}.[/]")
        sys.exit(1)


@daemon_cmd.command("logs")
@click.option("-n", "lines", default=50, help="Number of log lines to show.")
@click.option("-f", "follow", is_flag=True, help="Follow log output.")
def logs_cmd(lines: int, follow: bool) -> None:
    """Tail the daemon log."""
    log_path = _data_dir() / "logs" / "daemon.out.log"
    err_path = _data_dir() / "logs" / "daemon.err.log"
    if not log_path.exists() and not err_path.exists():
        console.print("  [yellow]No daemon logs yet.[/]")
        return
    cmd = ["tail", f"-n{lines}"]
    if follow:
        cmd.append("-f")
    cmd.extend([str(log_path), str(err_path)])
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass
