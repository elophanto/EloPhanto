"""deployment_status — Check the status of a deployed project."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class DeploymentStatusTool(BaseTool):
    """Check the deployment status of a project."""

    @property
    def group(self) -> str:
        return "infra"

    def __init__(self) -> None:
        self._vault: Any = None
        self._config: Any = None  # DeploymentConfig

    @property
    def name(self) -> str:
        return "deployment_status"

    @property
    def description(self) -> str:
        return (
            "Check the deployment status of a project. Auto-detects the "
            "provider from project config files (.vercel/project.json or "
            "railway.json). Returns the deployment URL, status, and provider."
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
                        "Hosting provider. 'auto' detects from project config "
                        "(default: 'auto')."
                    ),
                },
            },
            "required": ["project_path"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    def _detect_provider(self, project_path: Path) -> str:
        """Detect provider from project config files."""
        if (project_path / ".vercel" / "project.json").exists():
            return "vercel"
        if (project_path / "railway.json").exists():
            return "railway"
        if (project_path / "railway.toml").exists():
            return "railway"
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
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        return proc.returncode or 0, (stdout or b"").decode(errors="replace")

    async def _resolve_token(self, ref: str) -> str:
        """Resolve a token from the vault."""
        if not self._vault:
            return ""
        try:
            return self._vault.get(ref) or ""
        except Exception:
            return ""

    async def _vercel_status(self, project_path: Path) -> dict[str, Any]:
        """Get Vercel deployment status."""
        token = await self._resolve_token(
            self._config.vercel_token_ref if self._config else "vercel_token"
        )
        if not token:
            return {"error": "No Vercel token in vault."}

        # Read project config for project ID
        config_file = project_path / ".vercel" / "project.json"
        project_id = ""
        if config_file.exists():
            try:
                cfg = json.loads(config_file.read_text())
                project_id = cfg.get("projectId", "")
            except (json.JSONDecodeError, OSError):
                pass

        rc, output = await self._run_cmd(
            f"vercel ls --token {token} --yes 2>/dev/null | head -5",
            cwd=str(project_path),
        )
        return {
            "provider": "vercel",
            "project_id": project_id,
            "recent_deployments": output.strip()[:500],
        }

    async def _railway_status(self, project_path: Path) -> dict[str, Any]:
        """Get Railway deployment status."""
        token = await self._resolve_token(
            self._config.railway_token_ref if self._config else "railway_token"
        )
        if not token:
            return {"error": "No Railway token in vault."}

        env = {"RAILWAY_TOKEN": token}
        rc, output = await self._run_cmd(
            "railway status", cwd=str(project_path), env=env
        )
        rc2, domain_out = await self._run_cmd(
            "railway domain", cwd=str(project_path), env=env
        )
        return {
            "provider": "railway",
            "status_output": output.strip()[:500],
            "url": domain_out.strip() if rc2 == 0 else "",
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._config:
            return ToolResult(success=False, error="Deployment system is not enabled.")

        project_path = Path(params.get("project_path", "")).expanduser()
        if not project_path.exists():
            return ToolResult(
                success=False, error=f"Project path does not exist: {project_path}"
            )

        provider = params.get("provider", "auto")
        if provider == "auto":
            provider = self._detect_provider(project_path)
            if not provider:
                return ToolResult(
                    success=False,
                    error=(
                        "Could not detect provider. No .vercel/project.json or "
                        "railway.json found. Specify provider explicitly."
                    ),
                )

        try:
            if provider == "vercel":
                result = await self._vercel_status(project_path)
            elif provider == "railway":
                result = await self._railway_status(project_path)
            else:
                return ToolResult(
                    success=False,
                    error=f"Unknown provider: {provider}.",
                )

            if "error" in result:
                return ToolResult(success=False, error=result["error"])

            return ToolResult(success=True, data=result)
        except Exception as e:
            return ToolResult(success=False, error=str(e))
