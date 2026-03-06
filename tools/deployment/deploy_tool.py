"""deploy_website — Deploy a project to Vercel or Railway."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

# Patterns that indicate long-running operations (→ Railway)
_LONG_RUNNING_CODE_PATTERNS = (
    "openai",
    "anthropic",
    "ReadableStream",
    "WebSocket",
    "socket.io",
    "setTimeout",
)

_LONG_RUNNING_DEPS = ("ws", "socket.io", "bullmq", "pg-boss")


def _detect_provider(project_path: Path) -> str:
    """Auto-detect the best hosting provider for a project.

    Returns "railway" if the project has long-running operations,
    otherwise "vercel".
    """
    # Check API routes for long-running patterns
    api_dirs = [
        project_path / "src" / "app" / "api",
        project_path / "app" / "api",
        project_path / "pages" / "api",
        project_path / "src" / "pages" / "api",
    ]
    for api_dir in api_dirs:
        if not api_dir.exists():
            continue
        for f in api_dir.rglob("*.ts"):
            try:
                content = f.read_text(errors="ignore")
                if any(p in content for p in _LONG_RUNNING_CODE_PATTERNS):
                    return "railway"
            except OSError:
                continue
        for f in api_dir.rglob("*.js"):
            try:
                content = f.read_text(errors="ignore")
                if any(p in content for p in _LONG_RUNNING_CODE_PATTERNS):
                    return "railway"
            except OSError:
                continue

    # Check package.json for WebSocket / queue dependencies
    pkg_path = project_path / "package.json"
    if pkg_path.exists():
        try:
            pkg = json.loads(pkg_path.read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if any(d in deps for d in _LONG_RUNNING_DEPS):
                return "railway"
        except (json.JSONDecodeError, OSError):
            pass

    # Check for Procfile (typically means custom server)
    if (project_path / "Procfile").exists():
        return "railway"

    return "vercel"


class DeployWebsiteTool(BaseTool):
    """Deploy a web project to Vercel or Railway."""

    def __init__(self) -> None:
        self._vault: Any = None
        self._config: Any = None  # DeploymentConfig

    @property
    def name(self) -> str:
        return "deploy_website"

    @property
    def description(self) -> str:
        return (
            "Deploy a web project to a hosting provider. Supports Vercel "
            "(static sites, Next.js with fast APIs) and Railway (long-running "
            "operations, WebSockets, cron). Set provider to 'auto' to let "
            "the tool detect the best provider based on project contents."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Path to the project directory.",
                },
                "provider": {
                    "type": "string",
                    "enum": ["auto", "vercel", "railway"],
                    "description": (
                        "Hosting provider. 'auto' detects based on project "
                        "contents (default: 'auto')."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "Project name on the platform (optional).",
                },
                "env_vars": {
                    "type": "object",
                    "description": "Environment variables to set on the platform.",
                },
                "production": {
                    "type": "boolean",
                    "description": "Deploy to production (default: true).",
                },
            },
            "required": ["project_path"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    async def _resolve_token(self, ref: str) -> str:
        """Resolve a token from the vault."""
        if not self._vault:
            return ""
        try:
            return self._vault.get(ref) or ""
        except Exception:
            return ""

    async def _run_cmd(
        self, cmd: str, cwd: str, env: dict[str, str] | None = None
    ) -> tuple[int, str]:
        """Run a shell command and return (returncode, output)."""
        import os

        full_env = {**os.environ, **(env or {})}
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=full_env,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
        return proc.returncode or 0, (stdout or b"").decode(errors="replace")

    async def _deploy_vercel(
        self,
        project_path: Path,
        token: str,
        env_vars: dict[str, str],
        production: bool,
        name: str,
    ) -> dict[str, Any]:
        """Deploy to Vercel."""
        cwd = str(project_path)

        # Set env vars
        for key, value in env_vars.items():
            rc, out = await self._run_cmd(
                f'printf "%s" "{value}" | vercel env add {key} production --token {token} --yes 2>/dev/null || true',
                cwd=cwd,
            )
            logger.debug("vercel env add %s: rc=%d", key, rc)

        # Deploy
        cmd = f"vercel --yes --token {token}"
        if production:
            cmd += " --prod"
        if name:
            cmd += f" --name {name}"

        rc, output = await self._run_cmd(cmd, cwd=cwd)
        if rc != 0:
            return {"error": f"Vercel deploy failed (rc={rc}): {output[-500:]}"}

        # Extract URL from output (last line is typically the URL)
        url = ""
        for line in output.strip().splitlines():
            stripped = line.strip()
            if stripped.startswith("https://"):
                url = stripped
                break

        return {
            "url": url or "(check Vercel dashboard)",
            "provider": "vercel",
            "output": output[-500:],
        }

    async def _deploy_railway(
        self,
        project_path: Path,
        token: str,
        env_vars: dict[str, str],
        name: str,
    ) -> dict[str, Any]:
        """Deploy to Railway."""
        cwd = str(project_path)
        env = {"RAILWAY_TOKEN": token}

        # Set env vars
        if env_vars:
            pairs = " ".join(f"{k}={v}" for k, v in env_vars.items())
            rc, out = await self._run_cmd(
                f"railway variables set {pairs}",
                cwd=cwd,
                env=env,
            )
            logger.debug("railway variables set: rc=%d", rc)

        # Deploy
        rc, output = await self._run_cmd("railway up --detach", cwd=cwd, env=env)
        if rc != 0:
            return {"error": f"Railway deploy failed (rc={rc}): {output[-500:]}"}

        # Try to get the deployment URL
        rc2, domain_out = await self._run_cmd("railway domain", cwd=cwd, env=env)
        url = domain_out.strip() if rc2 == 0 else "(check Railway dashboard)"

        return {
            "url": url,
            "provider": "railway",
            "output": output[-500:],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._config:
            return ToolResult(success=False, error="Deployment system is not enabled.")

        project_path = Path(params.get("project_path", "")).expanduser()
        if not project_path.exists():
            return ToolResult(
                success=False, error=f"Project path does not exist: {project_path}"
            )
        if not (project_path / "package.json").exists():
            return ToolResult(
                success=False,
                error="No package.json found — is this a Node.js project?",
            )

        provider = params.get("provider", "auto")
        if provider == "auto":
            provider = self._config.default_provider
            if provider == "auto":
                provider = _detect_provider(project_path)
                logger.info("Auto-detected provider: %s", provider)

        name = params.get("name", "")
        env_vars: dict[str, str] = params.get("env_vars") or {}
        production = params.get("production", True)

        # Resolve token
        if provider == "vercel":
            token_ref = self._config.vercel_token_ref
        elif provider == "railway":
            token_ref = self._config.railway_token_ref
        else:
            return ToolResult(
                success=False,
                error=f"Unknown provider: {provider}. Use 'vercel' or 'railway'.",
            )

        token = await self._resolve_token(token_ref)
        if not token:
            return ToolResult(
                success=False,
                error=(
                    f"No token found for '{token_ref}' in vault. "
                    f"Set it with: vault_set key={token_ref} value=YOUR_TOKEN"
                ),
            )

        try:
            if provider == "vercel":
                result = await self._deploy_vercel(
                    project_path, token, env_vars, production, name
                )
            else:
                result = await self._deploy_railway(project_path, token, env_vars, name)

            if "error" in result:
                return ToolResult(success=False, error=result["error"])

            return ToolResult(
                success=True,
                data={
                    "status": "deployed",
                    "provider": result["provider"],
                    "url": result["url"],
                    "output_tail": result.get("output", "")[-200:],
                },
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                error=f"Deploy to {provider} timed out after 300s.",
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
