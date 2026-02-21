"""Recovery Mode — remote agent recovery without LLM.

When all LLM providers fail, the agent becomes unresponsive but the
gateway stays alive. Recovery commands are pure Python logic in the
gateway command dispatcher — zero LLM involvement.

Commands:
    /health              Show provider health report
    /health recheck      Re-run health checks
    /health full         Extended diagnostics
    /config get <key>    Read a config value (dot-notation)
    /config set <k> <v>  Update config in memory
    /config reload       Re-read config.yaml from disk
    /provider enable <n> Enable a provider
    /provider disable <n> Disable a provider
    /provider priority   Reorder provider fallback
    /restart             Graceful agent restart
    /recovery on         Enter recovery mode manually
    /recovery off        Exit recovery mode
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Config keys that can be modified via recovery commands.
# Security-critical keys (permissions, allowed_users, etc.) are blocked.
SAFE_CONFIG_KEYS = {
    "llm.providers.*",
    "llm.provider_priority",
    "llm.routing.*",
    "llm.budget.*",
    "browser.enabled",
    "gateway.session_timeout_hours",
}

# Keys that can NEVER be changed remotely.
BLOCKED_CONFIG_PREFIXES = (
    "permission",
    "shell.blacklist",
    "telegram.allowed_users",
    "discord.allowed_guilds",
    "slack.allowed_channels",
)


def _is_safe_key(key: str) -> bool:
    """Check if a config key is in the safe subset."""
    for blocked in BLOCKED_CONFIG_PREFIXES:
        if key.startswith(blocked):
            return False
    for pattern in SAFE_CONFIG_KEYS:
        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            if key.startswith(prefix):
                return True
        elif key == pattern:
            return True
    return False


def _get_nested_attr(obj: Any, key: str) -> Any:
    """Get a nested attribute using dot-notation (e.g. 'llm.provider_priority')."""
    parts = key.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Key not found: {part}")
            current = current[part]
        elif hasattr(current, part):
            current = getattr(current, part)
        else:
            raise KeyError(f"Key not found: {part}")
    return current


def _set_nested_attr(obj: Any, key: str, value: Any) -> None:
    """Set a nested attribute using dot-notation."""
    parts = key.split(".")
    current = obj
    for part in parts[:-1]:
        if isinstance(current, dict):
            current = current[part]
        else:
            current = getattr(current, part)
    final = parts[-1]
    if isinstance(current, dict):
        current[final] = value
    else:
        setattr(current, final, value)


class RecoveryHandler:
    """Handles recovery commands — pure Python, no LLM."""

    def __init__(
        self,
        config: Any,  # core.config.Config
        router: Any,  # core.router.LLMRouter
        agent: Any | None = None,  # core.agent.Agent
    ) -> None:
        self._config = config
        self._router = router
        self._agent = agent
        self._recovery_mode = False
        self._recovery_entered_at: float | None = None
        self._recovery_log: list[dict[str, Any]] = []

    @property
    def recovery_mode(self) -> bool:
        return self._recovery_mode

    def enter_recovery(self, reason: str = "manual") -> str:
        """Enter recovery mode."""
        if self._recovery_mode:
            return "Already in recovery mode."
        self._recovery_mode = True
        self._recovery_entered_at = time.time()
        self._log("recovery on", reason)
        logger.warning("Entered recovery mode: %s", reason)
        return "Recovery mode ACTIVE. Use /health to check providers."

    def exit_recovery(self) -> str:
        """Exit recovery mode."""
        if not self._recovery_mode:
            return "Not in recovery mode."
        self._recovery_mode = False
        duration = ""
        if self._recovery_entered_at:
            mins = (time.time() - self._recovery_entered_at) / 60
            duration = f" (was active for {mins:.1f}m)"
        self._recovery_entered_at = None
        self._log("recovery off", "")
        logger.info("Exited recovery mode%s", duration)
        return f"Recovery mode OFF.{duration}"

    def _log(self, command: str, detail: str) -> None:
        """Record a recovery action to the in-memory log."""
        self._recovery_log.append(
            {
                "ts": datetime.now(UTC).isoformat(),
                "command": command,
                "detail": detail,
            }
        )
        # Keep last 100 entries
        if len(self._recovery_log) > 100:
            self._recovery_log = self._recovery_log[-100:]

    async def handle(self, command_text: str, user_id: str = "") -> str | None:
        """Parse and dispatch a recovery command.

        Returns response text, or None if the command is not a recovery command.
        """
        parts = command_text.strip().split()
        if not parts:
            return None

        cmd = parts[0].lower()
        args = parts[1:]

        handlers = {
            "health": self._handle_health,
            "config": self._handle_config,
            "provider": self._handle_provider,
            "restart": self._handle_restart,
            "recovery": self._handle_recovery,
        }

        handler = handlers.get(cmd)
        if handler is None:
            return None

        self._log(command_text, f"user={user_id}")
        try:
            return await handler(args)
        except Exception as e:
            logger.error("Recovery command error: %s", e)
            return f"Error: {e}"

    # ------------------------------------------------------------------
    # /health
    # ------------------------------------------------------------------

    async def _handle_health(self, args: list[str]) -> str:
        subcmd = args[0] if args else ""

        if subcmd == "recheck":
            return await self._health_recheck()
        if subcmd == "full":
            return await self._health_full()
        return self._health_report()

    def _health_report(self) -> str:
        """Show provider health status."""
        lines: list[str] = []
        failed_at = self._router._provider_failed_at
        priority = self._config.llm.provider_priority

        for name in priority:
            provider_cfg = self._config.llm.providers.get(name)
            if not provider_cfg:
                continue

            if not provider_cfg.enabled:
                lines.append(f"  {name}: DISABLED")
                continue

            is_healthy = self._router._is_healthy(name)
            if is_healthy:
                lines.append(f"  {name}: healthy")
            else:
                fail_time = failed_at.get(name, 0)
                if fail_time:
                    ago = time.time() - fail_time
                    lines.append(f"  {name}: UNHEALTHY (down {ago:.0f}s)")
                else:
                    lines.append(f"  {name}: UNHEALTHY")

        # Budget info
        tracker = self._router.cost_tracker
        budget = self._config.llm.budget
        lines.append("")
        lines.append(
            f"Budget: ${tracker.daily_total:.2f} / ${budget.daily_limit_usd:.2f} daily"
        )

        # Recovery mode
        lines.append(f"Recovery mode: {'ACTIVE' if self._recovery_mode else 'off'}")

        header = "Provider Health"
        priority_str = " -> ".join(priority) if priority else "(none)"
        return f"{header}\n\n" + "\n".join(lines) + f"\n\nPriority: {priority_str}"

    async def _health_recheck(self) -> str:
        """Re-run provider health checks and report."""
        results = await self._router.health_check()

        lines: list[str] = []
        for name, healthy in results.items():
            status = "healthy" if healthy else "UNHEALTHY"
            lines.append(f"  {name}: {status}")

        all_down = all(not v for v in results.values()) if results else True
        if all_down and not self._recovery_mode:
            self.enter_recovery("all providers unhealthy after recheck")
            lines.append("\nAll providers down — auto-entered recovery mode.")

        return "Health Recheck\n\n" + "\n".join(lines)

    async def _health_full(self) -> str:
        """Extended diagnostics: providers + browser + scheduler + DB."""
        lines: list[str] = [self._health_report(), ""]

        # Browser bridge
        if self._agent and self._agent._browser_manager:
            alive = getattr(self._agent._browser_manager, "is_alive", False)
            lines.append(f"Browser bridge: {'alive' if alive else 'not running'}")
        else:
            lines.append("Browser bridge: disabled")

        # Scheduler
        if self._agent and self._agent._scheduler:
            lines.append("Scheduler: running")
        else:
            lines.append("Scheduler: disabled")

        # Database
        if self._agent and self._agent._db:
            try:
                await self._agent._db.execute_query("SELECT 1")
                lines.append("Database: ok")
            except Exception as e:
                lines.append(f"Database: ERROR ({e})")
        else:
            lines.append("Database: not initialized")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # /config
    # ------------------------------------------------------------------

    async def _handle_config(self, args: list[str]) -> str:
        subcmd = args[0] if args else ""

        if subcmd == "get" and len(args) >= 2:
            return self._config_get(args[1])
        if subcmd == "set" and len(args) >= 3:
            key = args[1]
            value_str = " ".join(args[2:])
            return self._config_set(key, value_str)
        if subcmd == "reload":
            return await self._config_reload()

        return (
            "Usage:\n"
            "  /config get <key>        — Read config value\n"
            "  /config set <key> <val>  — Update in memory\n"
            "  /config reload           — Re-read config.yaml"
        )

    def _config_get(self, key: str) -> str:
        """Read a config value by dot-notation key."""
        try:
            value = _get_nested_attr(self._config, key)
            # Format nicely
            if hasattr(value, "__dataclass_fields__"):
                # Dataclass — show as dict
                from dataclasses import asdict

                formatted = json.dumps(asdict(value), indent=2, default=str)
            elif isinstance(value, (dict, list)):
                formatted = json.dumps(value, indent=2, default=str)
            else:
                formatted = str(value)
            return f"{key} = {formatted}"
        except (KeyError, AttributeError) as e:
            return f"Key not found: {key} ({e})"

    def _config_set(self, key: str, value_str: str) -> str:
        """Update a config value in memory (not persisted to disk)."""
        if not _is_safe_key(key):
            return f"Blocked: '{key}' cannot be changed remotely (security-critical)."

        # Parse value: try JSON first, fall back to string
        try:
            value = json.loads(value_str)
        except (json.JSONDecodeError, ValueError):
            value = value_str

        try:
            _set_nested_attr(self._config, key, value)
            return f"Updated: {key} = {value}\n(in-memory only, lost on restart)"
        except (KeyError, AttributeError) as e:
            return f"Failed to set {key}: {e}"

    async def _config_reload(self) -> str:
        """Re-read config.yaml from disk."""
        from core.config import load_config

        config_path = self._config.project_root / "config.yaml"
        if not config_path.exists():
            return f"Config file not found: {config_path}"

        try:
            new_config = load_config(config_path)
            # Apply safe fields from new config
            self._config.llm = new_config.llm
            self._config.browser = new_config.browser
            # Don't overwrite security-critical fields
            return "Config reloaded from disk (LLM, browser sections updated)."
        except Exception as e:
            return f"Reload failed: {e}"

    # ------------------------------------------------------------------
    # /provider
    # ------------------------------------------------------------------

    async def _handle_provider(self, args: list[str]) -> str:
        subcmd = args[0] if args else ""

        if subcmd == "enable" and len(args) >= 2:
            return self._provider_toggle(args[1], enabled=True)
        if subcmd == "disable" and len(args) >= 2:
            return self._provider_toggle(args[1], enabled=False)
        if subcmd == "priority" and len(args) >= 2:
            return self._provider_priority(args[1:])

        return (
            "Usage:\n"
            "  /provider enable <name>       — Enable a provider\n"
            "  /provider disable <name>      — Disable a provider\n"
            "  /provider priority <a,b,c>    — Reorder fallback chain"
        )

    def _provider_toggle(self, name: str, *, enabled: bool) -> str:
        """Enable or disable a provider."""
        provider_cfg = self._config.llm.providers.get(name)
        if not provider_cfg:
            available = ", ".join(self._config.llm.providers.keys())
            return f"Unknown provider: {name}. Available: {available}"

        provider_cfg.enabled = enabled
        action = "enabled" if enabled else "disabled"

        # If enabling, also reset health status so router tries it
        if enabled:
            self._router._provider_health.pop(name, None)
            self._router._provider_failed_at.pop(name, None)

        return f"Provider '{name}' {action}."

    def _provider_priority(self, args: list[str]) -> str:
        """Reorder provider priority list."""
        # Accept "a,b,c" or "a b c"
        if len(args) == 1 and "," in args[0]:
            new_order = [p.strip() for p in args[0].split(",")]
        else:
            new_order = args

        # Validate all names exist
        for name in new_order:
            if name not in self._config.llm.providers:
                return f"Unknown provider: {name}"

        self._config.llm.provider_priority = new_order
        return f"Provider priority updated: {' -> '.join(new_order)}"

    # ------------------------------------------------------------------
    # /restart
    # ------------------------------------------------------------------

    async def _handle_restart(self, args: list[str]) -> str:
        if not self._agent:
            return "Agent reference not available — cannot restart."

        try:
            await self._agent.initialize()
            if self._recovery_mode:
                self.exit_recovery()
            return "Agent re-initialized successfully."
        except Exception as e:
            return f"Restart failed: {e}"

    # ------------------------------------------------------------------
    # /recovery
    # ------------------------------------------------------------------

    async def _handle_recovery(self, args: list[str]) -> str:
        subcmd = args[0] if args else ""

        if subcmd == "on":
            return self.enter_recovery("manual")
        if subcmd == "off":
            return self.exit_recovery()
        if subcmd == "log":
            return self._show_log()

        return (
            f"Recovery mode: {'ACTIVE' if self._recovery_mode else 'off'}\n\n"
            "Usage:\n"
            "  /recovery on   — Enter recovery mode\n"
            "  /recovery off  — Exit recovery mode\n"
            "  /recovery log  — Show recent recovery actions"
        )

    def _show_log(self) -> str:
        """Show recent recovery actions."""
        if not self._recovery_log:
            return "No recovery actions logged."
        lines = []
        for entry in self._recovery_log[-20:]:
            lines.append(f"  {entry['ts']} | {entry['command']} | {entry['detail']}")
        return "Recovery Log (last 20)\n\n" + "\n".join(lines)

    def check_auto_recovery(self) -> str | None:
        """Check if all providers are down and auto-enter recovery.

        Returns a notification message if auto-entering, None otherwise.
        Called periodically by the gateway health monitor.
        """
        if self._recovery_mode:
            return None

        # Check if all enabled providers are unhealthy
        all_unhealthy = True
        has_enabled = False
        for name in self._config.llm.provider_priority:
            provider_cfg = self._config.llm.providers.get(name)
            if provider_cfg and provider_cfg.enabled:
                has_enabled = True
                if self._router._is_healthy(name):
                    all_unhealthy = False
                    break

        if has_enabled and all_unhealthy:
            self.enter_recovery("all providers unhealthy")
            return (
                "All LLM providers are down. Entering recovery mode.\n"
                "Use /health to check status. Use /provider or /config to fix."
            )
        return None
