"""elophanto init — First-time setup wizard + section editor.

Creates config.yaml, prompts for API keys, detects providers,
and lets user choose which models to use for each task type.

Usage:
    elophanto init          — Run the full setup wizard
    elophanto init edit     — Pick a section to edit
    elophanto init edit browser  — Edit browser settings directly
"""

from __future__ import annotations

from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

console = Console()

# Section names → descriptions (used in both wizard numbering and edit menu)
_SECTIONS = {
    "providers": "API keys and LLM providers",
    "models": "Model selection per task type",
    "permissions": "Permission mode",
    "browser": "Web browsing settings",
    "scheduler": "Background scheduling",
}


@click.group(invoke_without_command=True)
@click.option(
    "--config-dir",
    type=click.Path(),
    default=".",
    help="Directory for config files (default: current directory)",
)
@click.pass_context
def init_cmd(ctx: click.Context, config_dir: str) -> None:
    """Initialize or edit EloPhanto configuration."""
    ctx.ensure_object(dict)
    ctx.obj["config_dir"] = config_dir
    if ctx.invoked_subcommand is None:
        _run_full_wizard(config_dir)


@init_cmd.command("edit")
@click.argument("section", required=False)
@click.pass_context
def edit_cmd(ctx: click.Context, section: str | None) -> None:
    """Edit a specific section of the configuration.

    SECTION can be: providers, models, permissions, browser, scheduler.
    If omitted, shows a menu.
    """
    config_dir: str = ctx.obj["config_dir"]
    config_path = Path(config_dir) / "config.yaml"

    if not config_path.exists():
        console.print(
            "[red]No config.yaml found.[/red] Run [bold]elophanto init[/bold] first."
        )
        raise SystemExit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    # Resolve section
    if section:
        if section not in _SECTIONS:
            console.print(
                f"[red]Unknown section:[/red] {section}\n"
                f"Available: {', '.join(_SECTIONS)}"
            )
            raise SystemExit(1)
    else:
        console.print()
        console.print("[bold]Which section to edit?[/bold]")
        for i, (key, desc) in enumerate(_SECTIONS.items(), 1):
            console.print(f"  [bold]{i}[/bold]. {key:12s} — {desc}")
        choice = Prompt.ask(
            "\n  Section",
            choices=[str(i) for i in range(1, len(_SECTIONS) + 1)],
        )
        section = list(_SECTIONS.keys())[int(choice) - 1]

    console.print()

    # Dispatch to the right editor
    editors = {
        "providers": _edit_providers,
        "models": _edit_models,
        "permissions": _edit_permissions,
        "browser": _edit_browser,
        "scheduler": _edit_scheduler,
    }
    editors[section](config)

    # Save
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    console.print()
    console.print(f"[green]Saved to {config_path}[/green]")


# ── Section Editors ──────────────────────────────────────────────────────────
# Each reads current config values as defaults, modifies config in-place.


def _edit_providers(config: dict) -> None:
    """Edit LLM provider API keys and settings."""
    active_providers: dict[str, bool] = {}

    # --- OpenRouter ---
    console.print(
        "[bold]OpenRouter[/bold] (cloud models: Claude, GPT, Gemini, Llama, etc.)"
    )
    current_or_key = (
        config.get("llm", {})
        .get("providers", {})
        .get("openrouter", {})
        .get("api_key", "")
    )
    or_key = Prompt.ask(
        (
            "  API key (press Enter to keep current)"
            if current_or_key
            else "  API key (press Enter to skip)"
        ),
        default=current_or_key,
        show_default=False,
    )
    if or_key:
        _ensure_provider(config, "openrouter")
        config["llm"]["providers"]["openrouter"]["api_key"] = or_key
        config["llm"]["providers"]["openrouter"]["enabled"] = True
        config["llm"]["providers"]["openrouter"].setdefault(
            "base_url", "https://openrouter.ai/api/v1"
        )
        active_providers["openrouter"] = True
        or_models = _fetch_openrouter_models(or_key)
        if or_models:
            console.print(
                f"  [green]Connected! {len(or_models)} models available.[/green]"
            )
        else:
            console.print("  [green]API key saved.[/green]")
    else:
        _ensure_provider(config, "openrouter")
        config["llm"]["providers"]["openrouter"]["enabled"] = False
        active_providers["openrouter"] = False
        console.print("  [dim]Disabled.[/dim]")

    console.print()

    # --- Z.ai ---
    console.print("[bold]Z.ai / GLM[/bold] (cost-effective coding models)")
    console.print("  [dim]Models: glm-5, glm-4.7, glm-4.7-flash, glm-4-plus[/dim]")
    current_zai_key = (
        config.get("llm", {}).get("providers", {}).get("zai", {}).get("api_key", "")
    )
    zai_key = Prompt.ask(
        (
            "  API key (press Enter to keep current)"
            if current_zai_key
            else "  API key (press Enter to skip)"
        ),
        default=current_zai_key,
        show_default=False,
    )
    if zai_key:
        _ensure_provider(config, "zai")
        config["llm"]["providers"]["zai"]["api_key"] = zai_key
        config["llm"]["providers"]["zai"]["enabled"] = True
        config["llm"]["providers"]["zai"].setdefault(
            "base_url_coding", "https://api.z.ai/api/coding/paas/v4"
        )
        config["llm"]["providers"]["zai"].setdefault(
            "base_url_paygo", "https://api.z.ai/api/paas/v4"
        )
        active_providers["zai"] = True

        current_coding = (
            config.get("llm", {})
            .get("providers", {})
            .get("zai", {})
            .get("coding_plan", False)
        )
        has_coding_plan = Confirm.ask(
            "  Do you have the Z.ai Coding Plan subscription?", default=current_coding
        )
        config["llm"]["providers"]["zai"]["coding_plan"] = has_coding_plan

        current_default = (
            config.get("llm", {})
            .get("providers", {})
            .get("zai", {})
            .get("default_model", "glm-4.7")
        )
        zai_default = Prompt.ask(
            "  Default Z.ai model",
            choices=["glm-5", "glm-4.7", "glm-4.7-flash", "glm-4-plus"],
            default=current_default,
        )
        config["llm"]["providers"]["zai"]["default_model"] = zai_default

        current_fast = (
            config.get("llm", {})
            .get("providers", {})
            .get("zai", {})
            .get("fast_model", "glm-4.7-flash")
        )
        zai_fast = Prompt.ask(
            "  Fast/cheap Z.ai model",
            choices=["glm-4.7-flash", "glm-4.7", "glm-5"],
            default=current_fast,
        )
        config["llm"]["providers"]["zai"]["fast_model"] = zai_fast
        console.print("  [green]Z.ai configured.[/green]")
    else:
        _ensure_provider(config, "zai")
        config["llm"]["providers"]["zai"]["enabled"] = False
        active_providers["zai"] = False
        console.print("  [dim]Disabled.[/dim]")

    console.print()

    # --- Ollama ---
    console.print("[bold]Ollama[/bold] (local models — free, private, offline)")
    ollama_available = _check_ollama()
    if ollama_available:
        ollama_models = _fetch_ollama_models()
        if ollama_models:
            console.print(
                f"  [green]Ollama running with {len(ollama_models)} model(s):[/green]"
            )
            for m in ollama_models:
                console.print(f"    - {m}")
        else:
            console.print("  [green]Ollama running[/green] but no models installed.")
            console.print("  [dim]Pull a model: ollama pull qwen2.5:7b[/dim]")
        _ensure_provider(config, "ollama")
        config["llm"]["providers"]["ollama"]["enabled"] = True
        config["llm"]["providers"]["ollama"].setdefault(
            "base_url", "http://localhost:11434"
        )
        active_providers["ollama"] = True
    else:
        console.print(
            "  [yellow]Ollama not detected.[/yellow] "
            "Install from https://ollama.ai for local models."
        )
        _ensure_provider(config, "ollama")
        config["llm"]["providers"]["ollama"]["enabled"] = False
        active_providers["ollama"] = False

    # --- Provider Priority ---
    console.print()
    enabled_names = [p for p, active in active_providers.items() if active]
    if len(enabled_names) > 1:
        current_priority = config.get("llm", {}).get("provider_priority", enabled_names)
        console.print(
            "[bold]Provider Priority[/bold]\n"
            "  [dim]Order in which providers are tried.[/dim]"
        )
        priority_input = Prompt.ask(
            "  Priority order (comma-separated)",
            default=", ".join(current_priority),
        )
        priority = [p.strip() for p in priority_input.split(",") if p.strip()]
    else:
        priority = enabled_names
        if priority:
            console.print(f"  Using: {priority[0]}")
    config.setdefault("llm", {})["provider_priority"] = priority


def _edit_models(config: dict) -> None:
    """Edit model selection per task type.

    Asks for a model per active provider per task, producing a ``models``
    map (provider → model) instead of a single preferred_model.
    """
    console.print("[bold]Model Selection[/bold]")
    console.print(
        "  [dim]Choose which model to use for each task type.\n"
        "  Enter the full model name (e.g. anthropic/claude-sonnet-4.6, "
        "glm-4.7, qwen2.5:7b).[/dim]"
    )

    # Detect active providers from config
    providers = config.get("llm", {}).get("providers", {})
    active: dict[str, bool] = {}
    for name, pcfg in providers.items():
        active[name] = bool(pcfg.get("enabled"))

    or_key = providers.get("openrouter", {}).get("api_key", "")
    or_models = _fetch_openrouter_models(or_key) if or_key else []
    ollama_models = _fetch_ollama_models() if active.get("ollama") else []

    _print_model_summary(active, or_models, ollama_models)
    console.print()

    routing = config.setdefault("llm", {}).setdefault("routing", {})
    priority = config.get("llm", {}).get("provider_priority", [])

    # Cloud providers that need interactive model selection
    cloud_providers = ["openrouter", "zai"]

    # Default models per (provider, task)
    defaults: dict[str, dict[str, str]] = {
        "openrouter": {
            "planning": "anthropic/claude-sonnet-4.6",
            "coding": "qwen/qwen3.5-plus-02-15",
            "analysis": "google/gemini-3.1-pro-preview",
            "simple": "minimax/minimax-m2.5",
        },
        "zai": {
            "planning": "glm-5",
            "coding": "glm-4.7",
            "analysis": "glm-4.7-flash",
            "simple": "glm-4.7-flash",
        },
    }

    task_types = [
        ("planning", "Planning", "reasoning, goal decomposition — strongest model"),
        ("coding", "Coding", "writing code, plugins — strong coding model"),
        ("analysis", "Analysis", "summarization, text processing — balanced"),
        ("simple", "Simple", "formatting, classification — cheapest/fastest"),
    ]

    for task_key, label, desc in task_types:
        console.print(f"  [bold]{label}[/bold] ({desc})")

        # Read existing models map (or legacy preferred_model)
        existing = routing.get(task_key, {})
        existing_models: dict[str, str] = existing.get("models", {})

        models_map: dict[str, str] = {}

        # Ask for each active cloud provider
        for prov in cloud_providers:
            if not active.get(prov):
                continue
            # Current value from models map or legacy field
            current = existing_models.get(prov, "")
            if not current and prov == existing.get("preferred_provider"):
                current = existing.get("preferred_model", "")
            if not current and prov == existing.get("fallback_provider"):
                current = existing.get("fallback_model", "")
            default = current or defaults.get(prov, {}).get(task_key, "")
            if not default:
                continue
            model = Prompt.ask(f"    {prov} model", default=default)
            models_map[prov] = model

        # Auto-detect best ollama model
        if active.get("ollama") and ollama_models:
            current_ollama = existing_models.get(
                "ollama", existing.get("local_fallback", "")
            )
            fallback = current_ollama or _best_ollama(ollama_models, task_key)
            if fallback:
                models_map["ollama"] = fallback
                console.print(f"    [dim]ollama fallback: {fallback}[/dim]")

        if not models_map:
            continue

        # Determine preferred provider: first in priority that has a model
        preferred = ""
        for prov in priority:
            if prov in models_map:
                preferred = prov
                break
        if not preferred:
            preferred = next(iter(models_map))

        routing[task_key] = {
            "preferred_provider": preferred,
            "models": models_map,
        }

        console.print(
            f"    [dim]→ preferred: {models_map[preferred]} via {preferred}[/dim]"
        )

    # Embedding — always local
    routing["embedding"] = {
        "preferred_provider": "ollama",
        "models": {"ollama": "nomic-embed-text"},
        "local_only": True,
    }


def _edit_permissions(config: dict) -> None:
    """Edit permission mode."""
    console.print("[bold]Permission Mode[/bold]")
    console.print("  [dim]ask_always[/dim]  — Every tool requires approval")
    console.print(
        "  [dim]smart_auto[/dim]  — Safe actions auto-approve, risky ones ask"
    )
    console.print("  [dim]full_auto[/dim]   — Everything runs with logging only")
    current = config.get("agent", {}).get("permission_mode", "ask_always")
    mode = Prompt.ask(
        "  Select mode",
        choices=["ask_always", "smart_auto", "full_auto"],
        default=current,
    )
    config.setdefault("agent", {})["permission_mode"] = mode


def _edit_browser(config: dict) -> None:
    """Edit browser automation settings."""
    console.print("[bold]Web Browsing[/bold]")
    console.print(
        "  [dim]Let the agent open websites, click buttons, fill forms,\n"
        "  take screenshots, and read page content using real Chrome.[/dim]"
    )

    browser_cfg = config.setdefault("browser", {})
    current_enabled = browser_cfg.get("enabled", False)
    browser_enabled = Confirm.ask(
        "  Allow the agent to browse the web?", default=current_enabled
    )
    browser_cfg["enabled"] = browser_enabled
    browser_cfg.setdefault("use_system_chrome", True)
    browser_cfg.setdefault("viewport_width", 1280)
    browser_cfg.setdefault("viewport_height", 720)
    browser_cfg.setdefault("headless", False)

    if browser_enabled:
        current_mode = browser_cfg.get("mode", "fresh")
        use_sessions = Confirm.ask(
            "  Use your existing Chrome sessions (logged-in sites, cookies)?",
            default=current_mode == "profile",
        )

        if use_sessions:
            from core.browser_manager import (
                get_chrome_profiles,
                get_default_chrome_user_data_dir,
            )

            profile_dir = get_default_chrome_user_data_dir() or ""
            if profile_dir:
                profiles = get_chrome_profiles()
                current_profile_dir = browser_cfg.get("profile_directory", "Default")

                if len(profiles) > 1:
                    console.print("  [dim]Found multiple Chrome profiles:[/dim]")
                    default_choice = "1"
                    for i, p in enumerate(profiles, 1):
                        label = p["name"]
                        if p.get("email"):
                            label += f" — {p['email']}"
                        marker = ""
                        if p["directory"] == current_profile_dir:
                            marker = " [green](current)[/green]"
                            default_choice = str(i)
                        console.print(
                            f"    [bold]{i}[/bold]. {label} "
                            f"[dim]({p['directory']})[/dim]{marker}"
                        )
                    choice = Prompt.ask(
                        "  Which profile?",
                        choices=[str(i) for i in range(1, len(profiles) + 1)],
                        default=default_choice,
                    )
                    selected = profiles[int(choice) - 1]
                elif profiles:
                    selected = profiles[0]
                else:
                    selected = {"directory": "Default", "name": "Default"}

                browser_cfg["mode"] = "profile"
                browser_cfg["user_data_dir"] = profile_dir
                browser_cfg["profile_directory"] = selected["directory"]
                console.print(
                    f"  [green]Enabled — using profile "
                    f"[bold]{selected['name']}[/bold].[/green]\n"
                    f"  [dim]{profile_dir}/{selected['directory']}[/dim]"
                )
            else:
                browser_cfg["mode"] = "fresh"
                browser_cfg["user_data_dir"] = ""
                browser_cfg["profile_directory"] = "Default"
                console.print(
                    "  [yellow]Chrome profile not found — using a clean browser "
                    "instead.[/yellow]\n"
                    "  [dim]You won't be logged into any sites. "
                    "Set user_data_dir in config.yaml to fix this.[/dim]"
                )
        else:
            browser_cfg["mode"] = "fresh"
            browser_cfg["user_data_dir"] = ""
            console.print(
                "  [green]Enabled — clean browser (no saved sessions).[/green]"
            )

        browser_cfg.setdefault("cdp_port", 9222)
        browser_cfg.setdefault("cdp_ws_endpoint", "")
    else:
        browser_cfg["mode"] = "fresh"
        browser_cfg["user_data_dir"] = ""
        browser_cfg.setdefault("cdp_port", 9222)
        browser_cfg.setdefault("cdp_ws_endpoint", "")
        console.print("  [dim]Disabled.[/dim]")


def _edit_scheduler(config: dict) -> None:
    """Edit background scheduling settings."""
    console.print("[bold]Background Scheduling[/bold]")
    console.print(
        "  [dim]Run tasks on a schedule (e.g. 'every morning at 9am').\n"
        "  Requires the agent to be running in the background.[/dim]"
    )
    scheduler_cfg = config.setdefault("scheduler", {})
    current_enabled = scheduler_cfg.get("enabled", False)
    scheduler_enabled = Confirm.ask(
        "  Enable task scheduling?", default=current_enabled
    )
    scheduler_cfg["enabled"] = scheduler_enabled
    scheduler_cfg.setdefault("max_concurrent_tasks", 1)
    scheduler_cfg.setdefault("default_max_retries", 3)
    scheduler_cfg.setdefault("task_timeout_seconds", 600)
    if scheduler_enabled:
        console.print("  [green]Scheduling enabled.[/green]")
    else:
        console.print("  [dim]Disabled.[/dim]")


# ── Full Wizard ──────────────────────────────────────────────────────────────


def _run_full_wizard(config_dir: str) -> None:
    """Run the complete first-time setup wizard."""
    config_path = Path(config_dir) / "config.yaml"

    console.print()
    console.print(
        Panel(
            "[bold blue]EloPhanto Setup Wizard[/bold blue]\n\n"
            "This will configure your LLM providers, model selection, and permissions.",
            border_style="blue",
        )
    )

    # Load existing or default config
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
        console.print(f"\n[dim]Found existing config at {config_path}[/dim]")
        if not Confirm.ask("  Overwrite existing configuration?", default=False):
            console.print("[dim]Keeping existing configuration.[/dim]")
            return
    else:
        default_config = Path(__file__).parent.parent / "config.yaml"
        if default_config.exists():
            with open(default_config) as f:
                config = yaml.safe_load(f) or {}
        else:
            config = _default_config()

    console.print()

    # Run each section with step numbers
    console.print("[bold]1-3. LLM Providers[/bold]")
    _edit_providers(config)

    console.print()
    console.print("[bold]4. Model Selection[/bold]")
    # Only run model selection if any provider is active
    providers = config.get("llm", {}).get("providers", {})
    any_active = any(p.get("enabled") for p in providers.values())
    if any_active:
        _edit_models(config)
    else:
        console.print("  [dim]No providers active — skipping model selection.[/dim]")

    console.print()
    console.print("[bold]5. Permission Mode[/bold]")
    _edit_permissions(config)

    console.print()
    console.print("[bold]6. Web Browsing[/bold]")
    _edit_browser(config)

    console.print()
    console.print("[bold]7. Background Scheduling[/bold]")
    _edit_scheduler(config)

    console.print()

    # Ensure defaults for sections not prompted
    config.setdefault("plugins", {"plugins_dir": "plugins", "auto_load": True})
    config.setdefault(
        "self_dev",
        {
            "max_llm_calls": 50,
            "max_time_seconds": 1800,
            "max_retries": 3,
            "test_timeout": 60,
        },
    )
    config.setdefault("shell", _default_shell_config())
    config.setdefault("llm", {}).setdefault(
        "budget",
        {"daily_limit_usd": 10.0, "per_task_limit_usd": 2.0},
    )

    # Write config
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    console.print()

    # Summary
    routing = config.get("llm", {}).get("routing", {})
    routing_summary = ""
    for task_type in ["planning", "coding", "analysis", "simple"]:
        r = routing.get(task_type, {})
        if r:
            routing_summary += (
                f"  {task_type}: {r.get('preferred_model', '?')} "
                f"via {r.get('preferred_provider', '?')}\n"
            )

    features_status = []
    if config.get("browser", {}).get("enabled"):
        features_status.append("Browser: [green]enabled[/green]")
    else:
        features_status.append("Browser: [dim]disabled[/dim]")
    if config.get("scheduler", {}).get("enabled"):
        features_status.append("Scheduler: [green]enabled[/green]")
    else:
        features_status.append("Scheduler: [dim]disabled[/dim]")
    features_str = " | ".join(features_status)

    mode = config.get("agent", {}).get("permission_mode", "ask_always")
    provider_list = config.get("llm", {}).get("provider_priority", [])

    console.print(
        Panel(
            f"[bold green]Configuration saved to {config_path}[/bold green]\n\n"
            f"Active providers: {', '.join(provider_list) or 'none'}\n"
            f"Permission mode: {mode}\n"
            f"Features: {features_str}\n\n"
            f"[bold]Model routing:[/bold]\n{routing_summary}\n"
            "Run [bold]elophanto chat[/bold] to start talking to your agent.",
            title="[bold]Setup Complete[/bold]",
            border_style="green",
        )
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _ensure_provider(config: dict, name: str) -> None:
    """Ensure the provider dict exists in config."""
    config.setdefault("llm", {}).setdefault("providers", {}).setdefault(name, {})


def _check_ollama() -> bool:
    """Check if Ollama is running."""
    try:
        import httpx

        resp = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


def _fetch_ollama_models() -> list[str]:
    """Get list of installed Ollama models."""
    try:
        import httpx

        resp = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        pass
    return []


def _fetch_openrouter_models(api_key: str) -> list[str]:
    """Fetch available model IDs from OpenRouter."""
    try:
        import httpx

        resp = httpx.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("data", [])
            return [m["id"] for m in models]
    except Exception:
        pass
    return []


def _print_model_summary(
    active: dict[str, bool],
    or_models: list[str],
    ollama_models: list[str],
) -> None:
    """Print a quick reference of popular models per provider."""
    console.print()
    if active.get("openrouter") and or_models:
        popular = [
            m
            for m in or_models
            if any(
                kw in m
                for kw in [
                    "claude",
                    "gpt-4o",
                    "gemini-2",
                    "llama",
                    "deepseek",
                    "qwen",
                ]
            )
        ][:20]
        if popular:
            console.print("  [bold]Popular OpenRouter models:[/bold]")
            for m in sorted(popular):
                console.print(f"    [dim]{m}[/dim]")
            console.print(
                f"    [dim]... and {len(or_models) - len(popular)} more[/dim]"
            )

    if active.get("zai"):
        console.print(
            "  [bold]Z.ai models:[/bold] glm-5, glm-4.7, glm-4.7-flash, glm-4-plus"
        )

    if active.get("ollama") and ollama_models:
        console.print(f"  [bold]Ollama models:[/bold] {', '.join(ollama_models)}")


def _ask_model(
    task_type: str,
    active: dict[str, bool],
    or_models: list[str],
    ollama_models: list[str],
    default_or: str,
    default_zai: str,
    default_ollama: str,
) -> dict[str, str] | None:
    """Ask user which model to use for a task type. Returns {provider, model}."""
    if active.get("openrouter"):
        default_model = default_or
    elif active.get("zai"):
        default_model = default_zai
    elif active.get("ollama") and default_ollama:
        default_model = default_ollama
    else:
        return None

    model = Prompt.ask(
        f"    Model for {task_type}",
        default=default_model,
    )

    provider = _infer_provider(model, active, or_models, ollama_models)

    local_fallback = ""
    if provider in ("openrouter", "zai") and active.get("ollama") and ollama_models:
        local_fallback = default_ollama or ""

    result: dict[str, str] = {"provider": provider, "model": model}
    if local_fallback:
        result["local_fallback"] = local_fallback

    console.print(f"    [dim]→ {model} via {provider}[/dim]")
    return result


def _infer_provider(
    model: str,
    active: dict[str, bool],
    or_models: list[str],
    ollama_models: list[str],
) -> str:
    """Infer which provider a model belongs to."""
    if model in ollama_models:
        return "ollama"
    if model.startswith("glm-"):
        return "zai"
    if "/" in model:
        return "openrouter"
    if ":" in model:
        return "ollama"
    if active.get("openrouter"):
        return "openrouter"
    if active.get("zai"):
        return "zai"
    return "ollama"


def _best_ollama(models: list[str], task_type: str) -> str:
    """Pick the best available Ollama model for a task type."""
    if not models:
        return ""

    if task_type == "planning":
        for pattern in ["qwen2.5:32b", "qwen2.5:14b", "llama3.1:70b", "llama3.1:8b"]:
            for m in models:
                if pattern in m:
                    return m
    elif task_type == "coding":
        for pattern in ["qwen2.5-coder", "deepseek-coder", "codellama"]:
            for m in models:
                if pattern in m:
                    return m
    elif task_type in ("analysis", "simple"):
        for pattern in ["qwen2.5:7b", "qwen2.5:3b", "llama3.2:3b", "phi"]:
            for m in models:
                if pattern in m:
                    return m

    return models[0]


def _default_shell_config() -> dict:
    """Default shell safety config."""
    return {
        "timeout": 30,
        "blacklist_patterns": [
            "rm -rf /",
            "rm -rf /*",
            "mkfs",
            "dd if=",
            "> /dev/sda",
            "chmod -R 777 /",
            ":(){ :|:& };:",
            "DROP DATABASE",
            "TRUNCATE",
        ],
        "safe_commands": [
            "ls",
            "cat",
            "pwd",
            "which",
            "echo",
            "grep",
            "find",
            "wc",
            "head",
            "tail",
            "df",
            "du",
            "ps",
            "uname",
        ],
    }


def _default_config() -> dict:
    """Return a minimal default configuration."""
    return {
        "agent": {
            "name": "EloPhanto",
            "permission_mode": "ask_always",
            "max_time_seconds": 1800,
        },
        "llm": {
            "providers": {
                "openrouter": {
                    "api_key": "",
                    "enabled": False,
                    "base_url": "https://openrouter.ai/api/v1",
                },
                "zai": {
                    "api_key": "",
                    "enabled": False,
                    "coding_plan": False,
                    "base_url_coding": "https://api.z.ai/api/coding/paas/v4",
                    "base_url_paygo": "https://api.z.ai/api/paas/v4",
                    "default_model": "glm-4.7",
                    "fast_model": "glm-4.7-flash",
                },
                "ollama": {
                    "base_url": "http://localhost:11434",
                    "enabled": True,
                },
            },
            "provider_priority": ["ollama", "zai", "openrouter"],
            "routing": {},
            "budget": {
                "daily_limit_usd": 10.0,
                "per_task_limit_usd": 2.0,
            },
        },
        "shell": _default_shell_config(),
        "plugins": {
            "plugins_dir": "plugins",
            "auto_load": True,
        },
        "self_dev": {
            "max_llm_calls": 50,
            "max_time_seconds": 1800,
            "max_retries": 3,
            "test_timeout": 60,
        },
        "browser": {
            "enabled": False,
            "mode": "fresh",
            "headless": False,
            "cdp_port": 9222,
            "cdp_ws_endpoint": "",
            "user_data_dir": "",
            "use_system_chrome": True,
            "viewport_width": 1280,
            "viewport_height": 720,
        },
        "scheduler": {
            "enabled": False,
            "max_concurrent_tasks": 1,
            "default_max_retries": 3,
            "task_timeout_seconds": 600,
        },
    }
