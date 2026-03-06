"""create_database — Create a Supabase project with optional initial SQL."""

from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_SUPABASE_API = "https://api.supabase.com/v1"


class CreateDatabaseTool(BaseTool):
    """Create a Supabase project (database + auth + storage)."""

    def __init__(self) -> None:
        self._vault: Any = None
        self._config: Any = None  # DeploymentConfig

    @property
    def name(self) -> str:
        return "create_database"

    @property
    def description(self) -> str:
        return (
            "Create a new Supabase project with a PostgreSQL database. "
            "Returns the project URL, anon key, service role key, and "
            "database connection string. Optionally runs initial SQL "
            "(CREATE TABLE, etc.) after the project is ready."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Project name (e.g. 'my-saas-app').",
                },
                "region": {
                    "type": "string",
                    "description": "Supabase region (default: 'us-east-1').",
                },
                "sql": {
                    "type": "string",
                    "description": (
                        "Optional initial SQL to execute after the project is ready "
                        "(e.g. CREATE TABLE statements)."
                    ),
                },
            },
            "required": ["name"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    async def _resolve_token(self) -> str:
        """Resolve Supabase access token from vault."""
        if not self._vault:
            return ""
        ref = (
            self._config.supabase_token_ref if self._config else "supabase_access_token"
        )
        try:
            return self._vault.get(ref) or ""
        except Exception:
            return ""

    async def _api(
        self,
        method: str,
        path: str,
        token: str,
        json_data: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """Make a Supabase Management API call."""
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                method,
                f"{_SUPABASE_API}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=json_data,
            )
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text[:500]}
            return resp.status_code, data

    async def _get_org_id(self, token: str) -> str:
        """Get the Supabase organization ID."""
        if self._config and self._config.supabase_org_id:
            return self._config.supabase_org_id

        status, data = await self._api("GET", "/organizations", token)
        if status != 200 or not isinstance(data, list) or len(data) == 0:
            return ""
        return data[0].get("id", "")

    async def _wait_for_active(
        self, project_id: str, token: str, timeout: int = 120
    ) -> bool:
        """Poll until the project is ACTIVE_HEALTHY."""
        for _ in range(timeout // 5):
            status, data = await self._api("GET", f"/projects/{project_id}", token)
            if status == 200 and data.get("status") == "ACTIVE_HEALTHY":
                return True
            await asyncio.sleep(5)
        return False

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._config:
            return ToolResult(success=False, error="Deployment system is not enabled.")

        name = params.get("name", "")
        if not name:
            return ToolResult(success=False, error="'name' is required.")

        region = params.get("region", "us-east-1")
        sql = params.get("sql", "")

        token = await self._resolve_token()
        if not token:
            ref = self._config.supabase_token_ref
            return ToolResult(
                success=False,
                error=(
                    f"No Supabase token found for '{ref}' in vault. "
                    f"Set it with: vault_set key={ref} value=YOUR_TOKEN"
                ),
            )

        org_id = await self._get_org_id(token)
        if not org_id:
            return ToolResult(
                success=False,
                error=(
                    "Could not determine Supabase organization ID. "
                    "Set deployment.supabase_org_id in config.yaml or "
                    "check your Supabase access token permissions."
                ),
            )

        db_pass = secrets.token_urlsafe(24)

        try:
            status, data = await self._api(
                "POST",
                "/projects",
                token,
                json_data={
                    "name": name,
                    "organization_id": org_id,
                    "db_pass": db_pass,
                    "region": region,
                    "plan": "free",
                },
            )

            if status not in (200, 201):
                return ToolResult(
                    success=False,
                    error=f"Supabase project creation failed ({status}): {data}",
                )

            project_id = data.get("id", "")
            project_ref = data.get("ref", project_id)

            # Wait for project to become active
            active = await self._wait_for_active(project_id, token)
            if not active:
                return ToolResult(
                    success=False,
                    error=(
                        f"Project '{name}' created but not yet active after 120s. "
                        f"Check Supabase dashboard. project_id={project_id}"
                    ),
                )

            # Get API keys
            keys_status, keys_data = await self._api(
                "GET", f"/projects/{project_ref}/api-keys", token
            )
            anon_key = ""
            service_role_key = ""
            if keys_status == 200 and isinstance(keys_data, list):
                for key_entry in keys_data:
                    key_name = key_entry.get("name", "")
                    if key_name == "anon":
                        anon_key = key_entry.get("api_key", "")
                    elif key_name == "service_role":
                        service_role_key = key_entry.get("api_key", "")

            # Run initial SQL if provided
            sql_result = ""
            if sql:
                sql_status, sql_data = await self._api(
                    "POST",
                    f"/projects/{project_ref}/sql",
                    token,
                    json_data={"query": sql},
                )
                if sql_status == 200:
                    sql_result = "SQL executed successfully."
                else:
                    sql_result = f"SQL execution failed ({sql_status}): {sql_data}"

            url = f"https://{project_ref}.supabase.co"
            db_url = (
                f"postgresql://postgres.{project_ref}:{db_pass}"
                f"@aws-0-{region}.pooler.supabase.com:6543/postgres"
            )

            result_data: dict[str, Any] = {
                "status": "created",
                "project_id": project_id,
                "url": url,
                "anon_key": anon_key,
                "service_role_key": service_role_key,
                "db_url": db_url,
                "db_pass": db_pass,
                "region": region,
            }
            if sql_result:
                result_data["sql_result"] = sql_result

            return ToolResult(success=True, data=result_data)

        except Exception as e:
            return ToolResult(success=False, error=str(e))
