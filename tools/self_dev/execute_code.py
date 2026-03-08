"""execute_code — Sandboxed Python execution with tool access via RPC."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

# Environment variables safe to pass to sandbox
_SAFE_ENV_KEYS = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER", "SHELL"}

# Max output size from sandbox (50KB)
_MAX_OUTPUT = 50 * 1024

# Default timeout (5 minutes)
_DEFAULT_TIMEOUT = 300


class ExecuteCodeTool(BaseTool):
    """Execute Python scripts in a sandboxed environment with tool access."""

    @property
    def group(self) -> str:
        return "selfdev"

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        self._registry: Any = None
        self._executor: Any = None

    @property
    def name(self) -> str:
        return "execute_code"

    @property
    def description(self) -> str:
        return (
            "Execute a Python script in a sandboxed environment with access to "
            "a curated set of tools via RPC (web_search, web_extract, file_read, "
            "file_write, file_list, knowledge_search, shell_execute). Use for "
            "complex multi-step tasks that would require many sequential tool "
            "calls. The script runs in an isolated process with no access to "
            "credentials or secrets."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": (
                        "Python script to execute. Import 'elophanto_tools' "
                        "for tool access. Available functions: web_search, "
                        "web_extract, file_read, file_write, file_list, "
                        "knowledge_search, shell_execute."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "What this script does (logged for audit).",
                },
                "timeout": {
                    "type": "integer",
                    "description": f"Timeout in seconds (default: {_DEFAULT_TIMEOUT}, max: 600).",
                },
            },
            "required": ["code", "description"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        code = params["code"]
        description = params["description"]
        timeout = min(params.get("timeout", _DEFAULT_TIMEOUT), 600)

        if not self._registry:
            return ToolResult(
                success=False,
                error="Tool registry not available for code execution sandbox.",
            )

        logger.info("[execute_code] Running: %s", description)

        # Start RPC server
        from tools.self_dev.rpc_server import RPCServer
        from tools.self_dev.stub_generator import generate_stubs

        rpc = RPCServer(self._registry, self._executor)

        try:
            socket_path = await rpc.start()

            # Generate tool stubs
            stubs_code = generate_stubs(socket_path)

            # Create temp working directory
            with tempfile.TemporaryDirectory(prefix="elophanto_sandbox_") as work_dir:
                # Write stubs module
                stubs_path = Path(work_dir) / "elophanto_tools.py"
                stubs_path.write_text(stubs_code, encoding="utf-8")

                # Write the user script
                script_path = Path(work_dir) / "script.py"
                script_path.write_text(code, encoding="utf-8")

                # Build sanitized environment
                env = {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}
                env["PYTHONPATH"] = work_dir
                env["PYTHONDONTWRITEBYTECODE"] = "1"

                # Run the script
                proc = await asyncio.create_subprocess_exec(
                    "python3",
                    str(script_path),
                    cwd=work_dir,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(), timeout=timeout
                    )
                except TimeoutError:
                    proc.kill()
                    await proc.communicate()
                    return ToolResult(
                        success=False,
                        error=f"Script timed out after {timeout}s",
                    )

                stdout_str = stdout.decode("utf-8", errors="replace")[:_MAX_OUTPUT]
                stderr_str = stderr.decode("utf-8", errors="replace")[:_MAX_OUTPUT]

                if proc.returncode != 0:
                    return ToolResult(
                        success=False,
                        error=f"Script failed (exit {proc.returncode}):\n{stderr_str}",
                        data={"stdout": stdout_str},
                    )

                return ToolResult(
                    success=True,
                    data={
                        "stdout": stdout_str,
                        "stderr": stderr_str if stderr_str else None,
                        "description": description,
                    },
                )

        except Exception as e:
            logger.error("[execute_code] Error: %s", e)
            return ToolResult(success=False, error=f"Sandbox error: {e}")
        finally:
            await rpc.stop()
