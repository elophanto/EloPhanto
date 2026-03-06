"""EloPhanto Cloud — Fly.io machine provisioning service.

Creates, manages, and destroys per-user Fly Machines. Each user gets an
isolated microVM running the EloPhanto Docker image with a persistent
volume for their vault, knowledge, and database.

Usage:
    # As a standalone API server (for webhook from Stripe/Supabase):
    python -m cloud.provision serve --port 8080

    # Direct CLI for testing:
    python -m cloud.provision create --user-id user_123 --region ams
    python -m cloud.provision destroy --user-id user_123
    python -m cloud.provision status --user-id user_123
    python -m cloud.provision list

Environment variables:
    FLY_API_TOKEN       — Fly.io API token (required)
    FLY_APP_NAME        — Fly app name (default: elophanto-cloud)
    FLY_IMAGE           — Docker image ref (default: registry.fly.io/elophanto-cloud:latest)
    SUPABASE_URL        — Supabase project URL (for user DB)
    SUPABASE_KEY        — Supabase service role key
    STRIPE_WEBHOOK_SECRET — For verifying Stripe webhooks
    PROVISION_API_KEY   — API key for authenticating provisioning requests
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

FLY_API = "https://api.machines.dev/v1"
FLY_APP = os.environ.get("FLY_APP_NAME", "elophanto-cloud")
FLY_TOKEN = os.environ.get("FLY_API_TOKEN", "")
FLY_IMAGE = os.environ.get("FLY_IMAGE", f"registry.fly.io/{FLY_APP}:latest")

DEFAULT_REGION = "ams"
DEFAULT_VM_SIZE = "shared-cpu-1x"
DEFAULT_MEMORY_MB = 512
DEFAULT_VOLUME_GB = 1
GATEWAY_PORT = 18789

# Machine auto-stop after inactivity (seconds). 0 = never.
AUTO_STOP_TIMEOUT = 1800  # 30 min


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class UserMachine:
    """Represents a user's provisioned Fly Machine."""

    user_id: str
    machine_id: str
    volume_id: str
    region: str
    status: str  # created, started, stopped, destroyed
    created_at: float = field(default_factory=time.time)
    hostname: str = ""


@dataclass
class ProvisionResult:
    success: bool
    machine: UserMachine | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Fly.io Machines API client
# ---------------------------------------------------------------------------


class FlyClient:
    """Thin async wrapper around the Fly Machines REST API."""

    def __init__(self, app: str = FLY_APP, token: str = FLY_TOKEN) -> None:
        self._app = app
        self._token = token
        self._base = f"{FLY_API}/apps/{app}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def create_volume(
        self, name: str, region: str, size_gb: int = DEFAULT_VOLUME_GB
    ) -> dict[str, Any]:
        """Create a persistent volume for user data."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._base}/volumes",
                headers=self._headers(),
                json={
                    "name": name,
                    "region": region,
                    "size_gb": size_gb,
                    "encrypted": True,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def create_machine(
        self,
        name: str,
        region: str,
        volume_id: str,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create and start a Fly Machine with the EloPhanto image."""
        config: dict[str, Any] = {
            "image": FLY_IMAGE,
            "env": {
                "PYTHONUNBUFFERED": "1",
                "ELOPHANTO_CLOUD": "1",
                "ELOPHANTO_CONFIG": "/data/config.yaml",
                **(env or {}),
            },
            "services": [
                {
                    "ports": [
                        {
                            "port": 443,
                            "handlers": ["tls", "http"],
                        },
                        {
                            "port": 80,
                            "handlers": ["http"],
                        },
                    ],
                    "protocol": "tcp",
                    "internal_port": GATEWAY_PORT,
                    "autostop": "stop",
                    "autostart": True,
                    "min_machines_running": 0,
                    "concurrency": {
                        "type": "connections",
                        "hard_limit": 25,
                        "soft_limit": 20,
                    },
                }
            ],
            "guest": {
                "cpu_kind": "shared",
                "cpus": 1,
                "memory_mb": DEFAULT_MEMORY_MB,
            },
            "mounts": [
                {
                    "volume": volume_id,
                    "path": "/data",
                }
            ],
            "checks": {
                "health": {
                    "type": "http",
                    "port": GATEWAY_PORT,
                    "path": "/health",
                    "interval": "30s",
                    "timeout": "5s",
                    "grace_period": "15s",
                }
            },
            "restart": {"policy": "on-failure", "max_retries": 3},
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._base}/machines",
                headers=self._headers(),
                json={
                    "name": name,
                    "region": region,
                    "config": config,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def get_machine(self, machine_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self._base}/machines/{machine_id}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def start_machine(self, machine_id: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._base}/machines/{machine_id}/start",
                headers=self._headers(),
            )
            resp.raise_for_status()

    async def stop_machine(self, machine_id: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._base}/machines/{machine_id}/stop",
                headers=self._headers(),
            )
            resp.raise_for_status()

    async def destroy_machine(self, machine_id: str, force: bool = False) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(
                f"{self._base}/machines/{machine_id}",
                headers=self._headers(),
                params={"force": "true"} if force else {},
            )
            resp.raise_for_status()

    async def destroy_volume(self, volume_id: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(
                f"{self._base}/volumes/{volume_id}",
                headers=self._headers(),
            )
            resp.raise_for_status()

    async def list_machines(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self._base}/machines",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def wait_for_state(
        self, machine_id: str, state: str, timeout_s: int = 60
    ) -> bool:
        """Poll machine until it reaches the desired state."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            machine = await self.get_machine(machine_id)
            if machine.get("state") == state:
                return True
            await asyncio.sleep(2)
        return False


# ---------------------------------------------------------------------------
# Provisioner — orchestrates machine lifecycle
# ---------------------------------------------------------------------------


class Provisioner:
    """High-level provisioning operations for per-user EloPhanto instances."""

    def __init__(self, fly: FlyClient | None = None) -> None:
        self._fly = fly or FlyClient()

    async def create_user_instance(
        self,
        user_id: str,
        region: str = DEFAULT_REGION,
        vault_password: str | None = None,
    ) -> ProvisionResult:
        """Provision a new EloPhanto instance for a user.

        1. Create persistent volume
        2. Create machine with volume mounted
        3. Wait for machine to start
        4. Return connection info
        """
        safe_name = f"ep-{user_id[:20].replace('_', '-')}"
        vol_name = f"data_{user_id[:20].replace('-', '_')}"

        try:
            # 1. Create volume
            logger.info(f"Creating volume for {user_id} in {region}")
            vol = await self._fly.create_volume(vol_name, region)
            volume_id = vol["id"]

            # 2. Build env vars for the machine
            env: dict[str, str] = {
                "ELOPHANTO_USER_ID": user_id,
            }
            if vault_password:
                env["ELOPHANTO_VAULT_PASSWORD"] = vault_password

            # 3. Create machine
            logger.info(f"Creating machine {safe_name} in {region}")
            machine = await self._fly.create_machine(
                name=safe_name,
                region=region,
                volume_id=volume_id,
                env=env,
            )
            machine_id = machine["id"]

            # 4. Wait for it to start
            logger.info(f"Waiting for machine {machine_id} to start...")
            started = await self._fly.wait_for_state(
                machine_id, "started", timeout_s=90
            )
            if not started:
                logger.warning(
                    f"Machine {machine_id} did not reach started state in time"
                )

            hostname = f"{safe_name}.fly.dev"

            result = UserMachine(
                user_id=user_id,
                machine_id=machine_id,
                volume_id=volume_id,
                region=region,
                status="started" if started else "created",
                hostname=hostname,
            )

            logger.info(
                f"Provisioned {user_id}: machine={machine_id} "
                f"volume={volume_id} hostname={hostname}"
            )
            return ProvisionResult(success=True, machine=result)

        except httpx.HTTPStatusError as e:
            error = f"Fly API error: {e.response.status_code} {e.response.text}"
            logger.error(f"Failed to provision {user_id}: {error}")
            return ProvisionResult(success=False, error=error)
        except Exception as e:
            logger.error(f"Failed to provision {user_id}: {e}")
            return ProvisionResult(success=False, error=str(e))

    async def destroy_user_instance(
        self, user_id: str, machine_id: str, volume_id: str
    ) -> bool:
        """Destroy a user's machine and volume. Returns True on success."""
        try:
            logger.info(f"Destroying machine {machine_id} for {user_id}")
            await self._fly.stop_machine(machine_id)
            await asyncio.sleep(2)
            await self._fly.destroy_machine(machine_id, force=True)

            logger.info(f"Destroying volume {volume_id} for {user_id}")
            await self._fly.destroy_volume(volume_id)

            logger.info(f"Destroyed instance for {user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to destroy instance for {user_id}: {e}")
            return False

    async def get_user_status(self, machine_id: str) -> dict[str, Any]:
        """Get current status of a user's machine."""
        try:
            machine = await self._fly.get_machine(machine_id)
            return {
                "id": machine["id"],
                "name": machine.get("name", ""),
                "state": machine.get("state", "unknown"),
                "region": machine.get("region", ""),
                "created_at": machine.get("created_at", ""),
                "updated_at": machine.get("updated_at", ""),
            }
        except Exception as e:
            return {"error": str(e)}

    async def start_user_instance(self, machine_id: str) -> bool:
        """Wake a hibernated machine."""
        try:
            await self._fly.start_machine(machine_id)
            return await self._fly.wait_for_state(machine_id, "started", timeout_s=60)
        except Exception:
            return False

    async def stop_user_instance(self, machine_id: str) -> bool:
        """Hibernate a machine (preserves volume)."""
        try:
            await self._fly.stop_machine(machine_id)
            return True
        except Exception:
            return False

    async def list_all_instances(self) -> list[dict[str, Any]]:
        """List all machines in the Fly app."""
        try:
            machines = await self._fly.list_machines()
            return [
                {
                    "id": m["id"],
                    "name": m.get("name", ""),
                    "state": m.get("state", "unknown"),
                    "region": m.get("region", ""),
                }
                for m in machines
            ]
        except Exception as e:
            return [{"error": str(e)}]


# ---------------------------------------------------------------------------
# HTTP API server (receives webhooks from Stripe/Supabase)
# ---------------------------------------------------------------------------


async def _handle_request(
    request_body: bytes, path: str, api_key: str
) -> tuple[int, dict]:
    """Route incoming HTTP requests."""
    provisioner = Provisioner()

    if path == "/provision":
        data = json.loads(request_body)
        user_id = data.get("user_id")
        region = data.get("region", DEFAULT_REGION)
        if not user_id:
            return 400, {"error": "user_id required"}

        result = await provisioner.create_user_instance(user_id, region)
        if result.success and result.machine:
            return 201, {
                "machine_id": result.machine.machine_id,
                "volume_id": result.machine.volume_id,
                "hostname": result.machine.hostname,
                "region": result.machine.region,
                "status": result.machine.status,
            }
        return 500, {"error": result.error}

    elif path == "/destroy":
        data = json.loads(request_body)
        user_id = data.get("user_id", "")
        machine_id = data.get("machine_id")
        volume_id = data.get("volume_id")
        if not machine_id or not volume_id:
            return 400, {"error": "machine_id and volume_id required"}

        ok = await provisioner.destroy_user_instance(user_id, machine_id, volume_id)
        return 200 if ok else 500, {"success": ok}

    elif path == "/status":
        data = json.loads(request_body)
        machine_id = data.get("machine_id")
        if not machine_id:
            return 400, {"error": "machine_id required"}
        status = await provisioner.get_user_status(machine_id)
        return 200, status

    elif path == "/start":
        data = json.loads(request_body)
        machine_id = data.get("machine_id")
        if not machine_id:
            return 400, {"error": "machine_id required"}
        ok = await provisioner.start_user_instance(machine_id)
        return 200 if ok else 500, {"started": ok}

    elif path == "/stop":
        data = json.loads(request_body)
        machine_id = data.get("machine_id")
        if not machine_id:
            return 400, {"error": "machine_id required"}
        ok = await provisioner.stop_user_instance(machine_id)
        return 200, {"stopped": ok}

    elif path == "/list":
        machines = await provisioner.list_all_instances()
        return 200, {"machines": machines}

    elif path == "/health":
        return 200, {"ok": True}

    return 404, {"error": "not found"}


def serve(port: int = 8080) -> None:
    """Start the provisioning API server."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    api_key = os.environ.get("PROVISION_API_KEY", "")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            # Auth check
            if api_key:
                auth = self.headers.get("Authorization", "")
                if auth != f"Bearer {api_key}":
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b'{"error":"unauthorized"}')
                    return

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else b"{}"

            status, data = asyncio.run(_handle_request(body, self.path, api_key))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def do_GET(self) -> None:
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt: str, *args: Any) -> None:
            logger.info(fmt % args)

    logger.info(f"Provisioning API listening on :{port}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    if len(sys.argv) < 2:
        print("Usage: python -m cloud.provision <command> [args]")
        print("Commands: serve, create, destroy, status, start, stop, list")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "serve":
        port = 8080
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
        serve(port)

    elif cmd == "create":
        user_id = ""
        region = DEFAULT_REGION
        for i, arg in enumerate(sys.argv):
            if arg == "--user-id" and i + 1 < len(sys.argv):
                user_id = sys.argv[i + 1]
            if arg == "--region" and i + 1 < len(sys.argv):
                region = sys.argv[i + 1]
        if not user_id:
            print("--user-id required")
            sys.exit(1)
        result = asyncio.run(Provisioner().create_user_instance(user_id, region))
        print(
            json.dumps(
                {
                    "success": result.success,
                    "machine_id": result.machine.machine_id if result.machine else None,
                    "volume_id": result.machine.volume_id if result.machine else None,
                    "hostname": result.machine.hostname if result.machine else None,
                    "error": result.error,
                },
                indent=2,
            )
        )

    elif cmd == "destroy":
        user_id = machine_id = volume_id = ""
        for i, arg in enumerate(sys.argv):
            if arg == "--user-id" and i + 1 < len(sys.argv):
                user_id = sys.argv[i + 1]
            if arg == "--machine-id" and i + 1 < len(sys.argv):
                machine_id = sys.argv[i + 1]
            if arg == "--volume-id" and i + 1 < len(sys.argv):
                volume_id = sys.argv[i + 1]
        if not machine_id or not volume_id:
            print("--machine-id and --volume-id required")
            sys.exit(1)
        ok = asyncio.run(
            Provisioner().destroy_user_instance(user_id, machine_id, volume_id)
        )
        print(json.dumps({"success": ok}))

    elif cmd == "status":
        machine_id = ""
        for i, arg in enumerate(sys.argv):
            if arg == "--machine-id" and i + 1 < len(sys.argv):
                machine_id = sys.argv[i + 1]
        if not machine_id:
            print("--machine-id required")
            sys.exit(1)
        status = asyncio.run(Provisioner().get_user_status(machine_id))
        print(json.dumps(status, indent=2))

    elif cmd == "start":
        machine_id = ""
        for i, arg in enumerate(sys.argv):
            if arg == "--machine-id" and i + 1 < len(sys.argv):
                machine_id = sys.argv[i + 1]
        if not machine_id:
            print("--machine-id required")
            sys.exit(1)
        ok = asyncio.run(Provisioner().start_user_instance(machine_id))
        print(json.dumps({"started": ok}))

    elif cmd == "stop":
        machine_id = ""
        for i, arg in enumerate(sys.argv):
            if arg == "--machine-id" and i + 1 < len(sys.argv):
                machine_id = sys.argv[i + 1]
        if not machine_id:
            print("--machine-id required")
            sys.exit(1)
        ok = asyncio.run(Provisioner().stop_user_instance(machine_id))
        print(json.dumps({"stopped": ok}))

    elif cmd == "list":
        machines = asyncio.run(Provisioner().list_all_instances())
        print(json.dumps({"machines": machines}, indent=2))

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
