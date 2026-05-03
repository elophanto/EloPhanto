"""``elophanto doctor`` — preflight check before chat / gateway start.

Why this exists:
    The #1 reason new installs fail is silent misconfiguration —
    a placeholder ``YOUR_OPENROUTER_KEY`` in config.yaml, a missing
    Chrome profile path, an uninitialised vault, an empty
    ``knowledge/system/`` directory. Each of those causes a cryptic
    error 30 seconds into the first chat instead of a clear "fix
    this before you start" message.

    Doctor walks the install end-to-end and prints a green/yellow/red
    report. Yellow = optional thing missing (broker won't auth, but
    chat works). Red = chat will not work; here's what to do.

    Designed to be runnable on any fresh install without unlocking
    the vault — it inspects files, env, and the *shape* of config,
    not actual provider auth.

Exit codes:
    0 — all green or only yellow warnings
    1 — at least one red error blocking chat
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


# ──────────────────────────────────────────────────────────────────
# Check primitives
# ──────────────────────────────────────────────────────────────────


class CheckResult:
    """One row in the doctor report."""

    def __init__(
        self,
        name: str,
        status: str,  # "ok" | "warn" | "fail"
        detail: str,
        fix: str = "",
    ) -> None:
        self.name = name
        self.status = status
        self.detail = detail
        self.fix = fix

    @property
    def icon(self) -> str:
        return {
            "ok": "[green]✓[/]",
            "warn": "[yellow]![/]",
            "fail": "[red]✗[/]",
            "skip": "[dim]·[/]",
        }[self.status]


def _check_python() -> CheckResult:
    v = sys.version_info
    label = f"Python {v.major}.{v.minor}.{v.micro}"
    if v.major < 3 or (v.major == 3 and v.minor < 12):
        return CheckResult(
            "Python version",
            "fail",
            f"{label} (3.12+ required)",
            "brew install python@3.13 && uv python pin 3.13",
        )
    if v.minor >= 14:
        return CheckResult(
            "Python version",
            "warn",
            f"{label} (very new — some wheels may not build)",
            "If install fails, drop to 3.13: uv python pin 3.13",
        )
    return CheckResult("Python version", "ok", label)


def _check_uv() -> CheckResult:
    if not shutil.which("uv"):
        return CheckResult(
            "uv (package manager)",
            "fail",
            "not on PATH",
            "curl -LsSf https://astral.sh/uv/install.sh | sh",
        )
    return CheckResult("uv (package manager)", "ok", "installed")


def _check_node() -> CheckResult:
    if not shutil.which("node"):
        return CheckResult(
            "Node.js (browser bridge)",
            "warn",
            "not installed — browser tools disabled",
            "Install Node 24+ LTS from https://nodejs.org/",
        )
    return CheckResult("Node.js (browser bridge)", "ok", "installed")


def _check_ffmpeg() -> CheckResult:
    if not shutil.which("ffmpeg"):
        return CheckResult(
            "ffmpeg (pump.fun livestream)",
            "warn",
            "not installed — pump_livestream tools disabled",
            "brew install ffmpeg",
        )
    return CheckResult("ffmpeg (pump.fun livestream)", "ok", "installed")


def _check_container_runtime() -> CheckResult:
    """Container runtime check for kid-agents. Warn-by-default — kids
    are optional, so missing runtime is not a startup blocker.

    Refuses spawn at the tool level if runtime is missing; the message
    here just helps users get unstuck before they try."""
    found: list[str] = []
    for name in ("docker", "podman", "colima"):
        if shutil.which(name):
            found.append(name)
    if not found:
        import platform as _plat

        sysname = _plat.system().lower()
        if sysname == "darwin":
            fix = (
                "macOS: brew install colima docker && colima start "
                "(CLI-only, no GUI license needed)"
            )
        elif sysname == "linux":
            fix = "Linux: curl -fsSL https://get.docker.com | sh"
        else:
            fix = (
                "Install Docker Desktop from docker.com, run it once, "
                "then re-run elophanto doctor."
            )
        return CheckResult(
            "container runtime (kid agents)",
            "warn",
            "no docker/podman/colima found — kid_spawn will refuse",
            fix,
        )
    return CheckResult(
        "container runtime (kid agents)",
        "ok",
        f"available: {', '.join(found)}",
    )


def _check_agent_identity() -> CheckResult:
    """Agent-to-agent cryptographic identity (Ed25519 keypair).

    Auto-generated on first agent boot. Doctor only WARNS if missing —
    the agent will create it on next start, no manual action required.
    Reports the agent_id (truncated public-key prefix) for visibility
    when present.
    """
    try:
        from core.agent_identity import load_or_create
    except Exception as e:
        return CheckResult(
            "agent identity (Ed25519)",
            "warn",
            f"agent_identity module unavailable: {e}",
        )
    from pathlib import Path as _Path

    default_path = _Path.home() / ".elophanto" / "agent_identity.pem"
    if default_path.exists():
        try:
            key = load_or_create(default_path, auto_create=False)
            return CheckResult(
                "agent identity (Ed25519)",
                "ok",
                f"loaded — {key.agent_id} (peer trust handshakes ready)",
            )
        except Exception as e:
            return CheckResult(
                "agent identity (Ed25519)",
                "warn",
                f"key file present but unreadable: {e}",
                "rm ~/.elophanto/agent_identity.pem (agent will regenerate on next start — peers will see a new agent_id)",
            )
    return CheckResult(
        "agent identity (Ed25519)",
        "warn",
        "no key yet — will be auto-generated on first agent start",
    )


def _check_gateway_security(project_root: Path) -> CheckResult:
    """Surface the gateway's network exposure + verified-peers mode.

    Three states matter:
      - bound to loopback (127.0.0.1) → safe by default
      - bound beyond loopback WITHOUT verified_peers + WITHOUT TLS →
        warn loudly: any client with the URL+token can chat in plaintext
      - bound beyond loopback WITH verified_peers AND/OR TLS → ok
    """
    try:
        from core.config import load_config
    except Exception as e:
        return CheckResult("gateway security", "warn", f"config load failed: {e}")
    cfg_path = _config_path(project_root)
    if not cfg_path.exists():
        return CheckResult(
            "gateway security",
            "warn",
            "config.yaml not found — run elophanto init",
        )
    try:
        cfg = load_config(str(cfg_path))
    except Exception as e:
        return CheckResult("gateway security", "warn", f"config parse failed: {e}")

    gw = cfg.gateway
    is_loopback = gw.host in ("127.0.0.1", "::1", "localhost")
    has_tls = bool(gw.tls_cert and gw.tls_key)
    has_verified = bool(gw.require_verified_peers)

    if is_loopback:
        return CheckResult(
            "gateway security",
            "ok",
            f"bound to loopback ({gw.host}) — local-only, safe by default",
        )
    if has_verified and has_tls:
        return CheckResult(
            "gateway security",
            "ok",
            f"bound to {gw.host} with TLS + verified-peers — peer-to-peer hardened",
        )
    if has_verified:
        return CheckResult(
            "gateway security",
            "warn",
            f"bound to {gw.host} with verified-peers but NO TLS — handshake bytes travel plaintext",
            "Set gateway.tls_cert + gateway.tls_key in config.yaml (or run inside Tailscale, which encrypts at WireGuard layer).",
        )
    if has_tls:
        return CheckResult(
            "gateway security",
            "warn",
            f"bound to {gw.host} with TLS but verified-peers OFF — anyone with URL+token can connect",
            "Set gateway.require_verified_peers: true in config.yaml.",
        )
    return CheckResult(
        "gateway security",
        "warn",
        f"bound to {gw.host} WITHOUT TLS or verified-peers — exposed and trust-by-token only",
        "Set gateway.tls_cert + gateway.tls_key AND gateway.require_verified_peers: true. For cross-machine, run agents inside Tailscale.",
    )


def _check_tailscale() -> CheckResult:
    """Tailscale CLI presence — required only if you want
    agent_discover. Warn-by-default."""
    if shutil.which("tailscale"):
        return CheckResult(
            "tailscale (peer discovery)",
            "ok",
            "available — `agent_discover` will find peers on your tailnet",
        )
    return CheckResult(
        "tailscale (peer discovery)",
        "warn",
        "not installed — agent_discover returns no peers without it",
        "Install Tailscale (https://tailscale.com/download), join your tailnet, and re-run.",
    )


def _check_p2p_sidecar(project_root: Path) -> CheckResult:
    """libp2p sidecar binary check.

    Three states:
      - ok     -> peers.enabled true AND binary present + executable
      - warn   -> peers.enabled true but binary missing (with build hint)
      - skip   -> peers.enabled false (decentralized peers opt-out)
    """
    from core.config import load_config
    from core.peer_p2p import find_sidecar_binary

    try:
        cfg = load_config(project_root / "config.yaml")
    except Exception:
        return CheckResult(
            "p2p sidecar (decentralized peers)",
            "skip",
            "config not parseable — check config.yaml",
        )
    if not cfg.peers.enabled:
        return CheckResult(
            "p2p sidecar (decentralized peers)",
            "skip",
            "peers.enabled=false — decentralized transport disabled",
        )

    # Honour an explicit override before falling back to autodiscover.
    binary: Path | None = None
    if cfg.peers.sidecar_binary:
        candidate = Path(cfg.peers.sidecar_binary)
        if candidate.exists():
            binary = candidate
    if binary is None:
        binary = find_sidecar_binary()

    if binary is None or not binary.exists():
        return CheckResult(
            "p2p sidecar (decentralized peers)",
            "warn",
            "peers.enabled=true but elophanto-p2pd binary not found",
            "Build it: `cd bridge/p2p && go build -o elophanto-p2pd .`. "
            "Requires Go 1.22+. See docs/68-DECENTRALIZED-PEERS-RFC.md.",
        )
    if not os.access(binary, os.X_OK):
        return CheckResult(
            "p2p sidecar (decentralized peers)",
            "warn",
            f"binary at {binary} is not executable",
            f"chmod +x {binary}",
        )
    return CheckResult(
        "p2p sidecar (decentralized peers)",
        "ok",
        f"binary present ({binary.name}) — sidecar will spawn on agent start",
    )


def _check_kid_image(project_root: Path) -> CheckResult:
    """Check whether the elophanto-kid image is present and roughly fresh.

    'Fresh' = image was built after the most recent change in core/.
    Warns if missing or older than the codebase. Skipped silently when
    no container runtime is present (the runtime check already covered it).
    """
    docker_bin = shutil.which("docker") or shutil.which("podman")
    if not docker_bin:
        return CheckResult(
            "kid image (elophanto-kid:latest)",
            "skip",
            "no container runtime — see container runtime check",
        )
    import subprocess as _sp

    try:
        out = _sp.run(
            [
                docker_bin,
                "image",
                "inspect",
                "elophanto-kid:latest",
                "--format",
                "{{.Created}}",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (_sp.TimeoutExpired, OSError):
        return CheckResult(
            "kid image (elophanto-kid:latest)",
            "warn",
            "could not inspect image (runtime not responding)",
        )
    if out.returncode != 0:
        return CheckResult(
            "kid image (elophanto-kid:latest)",
            "warn",
            "image not built — kid_spawn will refuse",
            "Run: elophanto kid build",
        )
    image_created = out.stdout.strip()
    # Compare to most recent mtime in core/ — if code is newer, image is stale.
    core_dir = project_root / "core"
    if core_dir.exists():
        try:
            from datetime import datetime as _dt

            newest_code_mtime = max(p.stat().st_mtime for p in core_dir.rglob("*.py"))
            # Parse Docker's RFC3339-like timestamp ("2026-05-01T12:00:00.123456789Z")
            ts = image_created.replace("Z", "+00:00")[:32]
            try:
                image_dt = _dt.fromisoformat(ts).timestamp()
            except ValueError:
                image_dt = 0.0
            if image_dt and newest_code_mtime > image_dt + 60:
                return CheckResult(
                    "kid image (elophanto-kid:latest)",
                    "warn",
                    "image is older than core/ — rebuild for latest code",
                    "Run: elophanto kid build",
                )
        except OSError:
            pass
    return CheckResult(
        "kid image (elophanto-kid:latest)",
        "ok",
        f"present (created {image_created[:19]})",
    )


def _config_path(project_root: Path) -> Path:
    """Same lookup the loader does: env var first, then project root."""
    env = os.environ.get("ELOPHANTO_CONFIG", "").strip()
    if env:
        return Path(env).expanduser()
    return project_root / "config.yaml"


def _check_config_exists(project_root: Path) -> CheckResult:
    cfg = _config_path(project_root)
    if not cfg.exists():
        return CheckResult(
            "config.yaml",
            "fail",
            "missing",
            "Run `elophanto init` to create it (interactive wizard).",
        )
    return CheckResult("config.yaml", "ok", str(cfg))


def _check_providers(project_root: Path) -> list[CheckResult]:
    """Scan config.yaml for enabled providers and check their api_keys.

    Returns multiple rows (one per enabled provider plus a roll-up).
    The placeholder detector at config-load time auto-disables bad
    providers, but doctor reads the *raw* yaml so it can also flag
    "enabled: true with placeholder" combinations the user hasn't
    seen yet.
    """
    import yaml

    from core.config import is_placeholder_key

    rows: list[CheckResult] = []
    cfg_path = _config_path(project_root)
    if not cfg_path.exists():
        return rows
    try:
        raw = yaml.safe_load(cfg_path.read_text("utf-8")) or {}
    except Exception as e:
        rows.append(
            CheckResult(
                "config.yaml parse", "fail", f"yaml error: {e}", "Fix the YAML syntax."
            )
        )
        return rows

    providers = (raw.get("llm") or {}).get("providers") or {}
    if not providers:
        rows.append(
            CheckResult(
                "LLM providers",
                "fail",
                "no providers configured",
                "Run `elophanto init` to set up at least one.",
            )
        )
        return rows

    real_count = 0
    for name, p in providers.items():
        if not isinstance(p, dict):
            continue
        enabled = bool(p.get("enabled", False))
        api_key = p.get("api_key", "")

        # Codex doesn't use api_key — auto-detected from ~/.codex/auth.json.
        if name == "codex":
            auth_path = Path.home() / ".codex" / "auth.json"
            if enabled and not auth_path.exists():
                rows.append(
                    CheckResult(
                        f"provider: {name}",
                        "warn",
                        "enabled but ~/.codex/auth.json missing",
                        "Run `npm i -g @openai/codex && codex login` once.",
                    )
                )
            elif enabled:
                rows.append(
                    CheckResult(f"provider: {name}", "ok", "ChatGPT subscription")
                )
                real_count += 1
            continue

        # Ollama doesn't use api_key — base_url to a running daemon.
        if name == "ollama":
            if enabled:
                base = p.get("base_url", "http://localhost:11434")
                rows.append(CheckResult(f"provider: {name}", "ok", f"local @ {base}"))
                real_count += 1
            continue

        if not enabled:
            continue
        if not api_key:
            rows.append(
                CheckResult(
                    f"provider: {name}",
                    "fail",
                    "enabled but no api_key set",
                    f"Set llm.providers.{name}.api_key in config.yaml.",
                )
            )
            continue
        if is_placeholder_key(api_key):
            rows.append(
                CheckResult(
                    f"provider: {name}",
                    "fail",
                    f"placeholder api_key ({api_key!r}) — provider auto-disabled at runtime",
                    f"Replace llm.providers.{name}.api_key with a real key, or run `elophanto init`.",
                )
            )
            continue
        # Looks real — surface a green row.
        masked = api_key[:6] + "…" + api_key[-4:] if len(api_key) > 12 else "***"
        rows.append(CheckResult(f"provider: {name}", "ok", f"key set ({masked})"))
        real_count += 1

    if real_count == 0:
        rows.append(
            CheckResult(
                "LLM providers (rollup)",
                "fail",
                "0 providers actually usable — chat will fail on the first call",
                "Set at least one real api_key (OpenRouter is easiest: https://openrouter.ai/keys).",
            )
        )
    return rows


def _check_browser(project_root: Path) -> CheckResult:
    import yaml

    cfg_path = _config_path(project_root)
    if not cfg_path.exists():
        return CheckResult("browser", "warn", "no config.yaml — skipping check")
    try:
        raw = yaml.safe_load(cfg_path.read_text("utf-8")) or {}
    except Exception:
        return CheckResult(
            "browser", "warn", "config.yaml unparseable — skipping check"
        )
    b = raw.get("browser") or {}
    if not b.get("enabled", False):
        return CheckResult("browser", "ok", "disabled in config")
    mode = b.get("mode", "fresh")
    if mode == "fresh":
        return CheckResult(
            "browser",
            "ok",
            "fresh mode (clean session, no logged-in sites)",
        )
    user_data_dir = b.get("user_data_dir", "")
    if not user_data_dir:
        return CheckResult(
            "browser",
            "warn",
            "profile mode but user_data_dir empty — falls back to fresh",
            "Run `elophanto init edit browser` to auto-detect Chrome.",
        )
    if not Path(user_data_dir).expanduser().is_dir():
        return CheckResult(
            "browser",
            "fail",
            f"user_data_dir does not exist: {user_data_dir}",
            "Find your Chrome profile via chrome://version → 'Profile Path'.",
        )
    profile = b.get("profile_directory", "Default")
    return CheckResult(
        "browser",
        "ok",
        f"profile mode → {user_data_dir}/{profile}",
    )


def _check_vault(project_root: Path) -> CheckResult:
    """Vault is optional but expected for any tool that needs secrets."""
    # Defer to Vault.exists() so we stay in sync with the canonical
    # filenames (currently ``vault.salt`` + ``vault.enc`` in project root).
    try:
        from core.vault import Vault

        if Vault.exists(project_root):
            return CheckResult("vault", "ok", "initialised")
    except Exception as e:
        return CheckResult(
            "vault",
            "warn",
            f"check failed: {e}",
            "Run `elophanto vault init` to create one.",
        )
    return CheckResult(
        "vault",
        "warn",
        "not initialised — secrets-using tools (email, payments, polymarket, "
        "alphascala, pump.fun, replicate) will be unavailable",
        "Run `elophanto chat` and follow the 'Set vault password' prompt.",
    )


def _check_workspace(project_root: Path) -> CheckResult:
    """Confirm agent.workspace path resolves and is writable."""
    import yaml

    cfg = _config_path(project_root)
    if not cfg.exists():
        return CheckResult("workspace", "warn", "no config.yaml — skipping")
    try:
        raw = yaml.safe_load(cfg.read_text("utf-8")) or {}
    except Exception:
        return CheckResult("workspace", "warn", "config.yaml unparseable — skipping")
    ws = (raw.get("agent") or {}).get("workspace", "")
    if not ws:
        return CheckResult(
            "workspace", "warn", "agent.workspace not set in config.yaml"
        )
    p = Path(ws).expanduser()
    if not p.exists():
        try:
            p.mkdir(parents=True, exist_ok=True)
            return CheckResult("workspace", "ok", f"created at {p}")
        except OSError as e:
            return CheckResult(
                "workspace",
                "fail",
                f"cannot create {p}: {e}",
                "Set agent.workspace in config.yaml to a writable path.",
            )
    if not os.access(p, os.W_OK):
        return CheckResult(
            "workspace",
            "fail",
            f"{p} exists but is not writable",
            "Fix permissions or pick a different path.",
        )
    return CheckResult("workspace", "ok", str(p))


def _check_bootstrap(project_root: Path) -> CheckResult:
    """``knowledge/system/{identity,capabilities,styleguide}.md`` should exist.

    Without these the planner improvises — the #1 cause of "agent
    hallucinates on day one." `elophanto bootstrap` writes them.
    """
    sys_dir = project_root / "knowledge" / "system"
    targets = ("identity.md", "capabilities.md", "styleguide.md")
    missing = [t for t in targets if not (sys_dir / t).is_file()]
    if not missing:
        return CheckResult("bootstrap (knowledge/system)", "ok", "all 3 docs present")
    return CheckResult(
        "bootstrap (knowledge/system)",
        "warn",
        f"missing: {', '.join(missing)} — planner will improvise",
        "Run `elophanto bootstrap` (one time, ~30 s).",
    )


# ──────────────────────────────────────────────────────────────────
# Command
# ──────────────────────────────────────────────────────────────────


def _run_all_checks(project_root: Path) -> list[CheckResult]:
    rows: list[CheckResult] = []
    rows.append(_check_python())
    rows.append(_check_uv())
    rows.append(_check_node())
    rows.append(_check_ffmpeg())
    rows.append(_check_config_exists(project_root))
    rows.extend(_check_providers(project_root))
    rows.append(_check_browser(project_root))
    rows.append(_check_vault(project_root))
    rows.append(_check_workspace(project_root))
    rows.append(_check_bootstrap(project_root))
    rows.append(_check_container_runtime())
    rows.append(_check_kid_image(project_root))
    rows.append(_check_agent_identity())
    rows.append(_check_gateway_security(project_root))
    rows.append(_check_tailscale())
    rows.append(_check_p2p_sidecar(project_root))
    return rows


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@click.command(name="doctor")
@click.option(
    "--strict",
    is_flag=True,
    help="Treat warnings as failures (exit 1 on any non-OK row).",
)
def doctor_cmd(strict: bool) -> None:
    """Run preflight checks and print a green/yellow/red report.

    Exits 1 if any blocker is detected (or if --strict is set and
    any warning surfaces). Safe to run before `chat` or `gateway`
    in start.sh.
    """
    project_root = _project_root()
    rows = _run_all_checks(project_root)

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("", width=1)
    table.add_column("Check", style="bold")
    table.add_column("Detail")
    for r in rows:
        table.add_row(r.icon, r.name, r.detail)
    console.print(table)

    fails = [r for r in rows if r.status == "fail"]
    warns = [r for r in rows if r.status == "warn"]
    if fails:
        console.print("\n[bold red]Blockers — chat will fail until these are fixed:[/]")
        for r in fails:
            console.print(f"  [red]✗[/] [bold]{r.name}[/]")
            if r.fix:
                console.print(f"    → {r.fix}")
    if warns:
        console.print(
            "\n[bold yellow]Warnings — agent works, optional features disabled:[/]"
        )
        for r in warns:
            console.print(f"  [yellow]![/] [bold]{r.name}[/]")
            if r.fix:
                console.print(f"    → {r.fix}")
    if not fails and not warns:
        console.print("\n[bold green]All checks passed.[/] Ready to chat.")
    elif not fails:
        console.print("\n[bold green]No blockers.[/] You can run `elophanto chat`.")

    if fails or (strict and warns):
        sys.exit(1)


if __name__ == "__main__":
    doctor_cmd()
