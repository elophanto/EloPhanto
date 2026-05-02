"""KidManager — registry + lifecycle for sandboxed child EloPhanto agents.

Mirrors the structure of SwarmManager (registry, persist, restart-from-DB,
broadcast events) but for *containerized* kids rather than tmux subprocesses.

A kid is a fresh EloPhanto instance running inside a hardened container.
It connects back to the parent's gateway as a WebSocket client (channel
`kid-agent`) and is identified by its `kid_id`.

See KID_AGENTS_PLAN.md for the full architecture; the rules in there are
enforced here and in core/kid_runtime.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.config import KidConfig
from core.kid_runtime import ContainerRuntime, ContainerRuntimeError, detect_runtime
from core.protocol import EventType

if TYPE_CHECKING:
    from core.database import Database
    from core.gateway import Gateway
    from core.vault import Vault

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class KidAgent:
    """A sandboxed child EloPhanto running in a container."""

    kid_id: str
    name: str
    container_id: str | None
    runtime: str
    image: str
    status: str  # starting | running | paused | stopped | failed
    vault_scope: list[str]
    volume_name: str
    parent_gateway_url: str
    purpose: str
    spawned_at: str
    parent_agent_id: str = "self"
    role: str | None = None
    last_active: str | None = None
    completed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class KidManager:
    """Owns the kid registry and orchestrates container lifecycle."""

    def __init__(
        self,
        db: Database,
        config: KidConfig,
        gateway: Gateway | None = None,
        vault: Vault | None = None,
        parent_gateway_url: str = "ws://host.docker.internal:18789",
    ) -> None:
        self._db = db
        self._config = config
        self._gateway = gateway
        self._vault = vault
        self._parent_gateway_url = parent_gateway_url
        self._kids: dict[str, KidAgent] = {}
        self._runtime: ContainerRuntime | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._last_spawn_at: float = 0.0
        # Per-kid inbound queues — populated by Gateway.handle_kid_message
        # via the hook installed in Agent.initialize(). exec() drains the
        # queue with a deadline so the parent gets the kid's response
        # without polluting the parent's chat history.
        self._kid_inbox: dict[str, asyncio.Queue[str]] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Detect a runtime, reload persisted kids, start the monitor.

        Failure to detect a runtime is NOT fatal here — kids just become
        unspawnable. The doctor surfaces this; tools refuse with a clear
        error when the user actually invokes kid_spawn.
        """
        if not self._config.enabled:
            logger.info("Kid agents disabled in config")
            return

        self._runtime = await detect_runtime(self._config.runtime_preference)
        if self._runtime is None:
            logger.warning(
                "No container runtime found (looked for: %s). Kid agents "
                "will be unspawnable until docker/podman/colima is installed.",
                self._config.runtime_preference,
            )

        await self._reload_from_db()

        if self._runtime is not None:
            self._monitor_task = asyncio.create_task(
                self._monitor_loop(), name="kid-monitor"
            )

    async def stop(self) -> None:
        """Stop the monitor; do NOT destroy running kids — they survive
        parent restarts and are re-attached on next start()."""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    @property
    def runtime_available(self) -> bool:
        return self._runtime is not None

    @property
    def runtime_name(self) -> str:
        return self._runtime.name if self._runtime else ""

    @property
    def running_kids(self) -> list[KidAgent]:
        return [k for k in self._kids.values() if k.status == "running"]

    # ------------------------------------------------------------------
    # Spawn
    # ------------------------------------------------------------------

    async def spawn(
        self,
        *,
        purpose: str,
        name: str | None = None,
        vault_scope: list[str] | None = None,
        image: str | None = None,
        memory_mb: int | None = None,
        cpus: float | None = None,
        network: str | None = None,
        role: str | None = None,
    ) -> KidAgent:
        """Spawn a new kid container.

        Defaults follow KidConfig. The vault subset defaults to empty
        (no secrets) — caller must explicitly grant keys.
        """
        if not self._config.enabled:
            raise RuntimeError("Kid agents are disabled in config")
        if self._runtime is None:
            raise RuntimeError(
                "No container runtime available. Install docker, podman, "
                "or colima — see `elophanto doctor` for platform-specific "
                "instructions."
            )

        # Concurrency cap
        if len(self.running_kids) >= self._config.max_concurrent_kids:
            raise RuntimeError(
                f"Max concurrent kids ({self._config.max_concurrent_kids}) "
                "reached. Destroy a running kid first or raise "
                "kids.max_concurrent_kids in config."
            )

        # Cooldown — prevents rapid spawn loops chewing the daemon
        import time as _t

        cooldown = self._config.spawn_cooldown_seconds
        if cooldown > 0:
            elapsed = _t.monotonic() - self._last_spawn_at
            if elapsed < cooldown:
                remaining = int(cooldown - elapsed)
                raise RuntimeError(f"Spawn cooldown active: {remaining}s remaining.")

        kid_id = uuid.uuid4().hex[:8]

        # Name derivation + dedup
        if name:
            slug_name = self._slugify(name)[:50] or "kid"
        else:
            slug_name = self._slugify(purpose)[:50] or "kid"
        if await self._name_in_use(slug_name):
            slug_name = f"{slug_name[:46]}-{kid_id[:4]}"

        scope = (
            vault_scope
            if vault_scope is not None
            else list(self._config.default_vault_scope)
        )
        image = image or self._config.default_image
        memory_mb = memory_mb or self._config.default_memory_mb
        cpus = cpus or self._config.default_cpus
        network = network or self._config.default_network
        volume_name = f"{self._config.volume_prefix}{kid_id}"

        # Build env: identity + scoped vault. Note KID_VAULT_JSON
        # contains plaintext secrets; the kid is responsible for
        # consuming + clearing it. The container is isolated, so
        # /proc/<pid>/environ exposure is bounded to this container.
        env = {
            "ELOPHANTO_KID": "true",
            "ELOPHANTO_KID_ID": kid_id,
            "ELOPHANTO_KID_NAME": slug_name,
            "ELOPHANTO_PARENT_GATEWAY": self._parent_gateway_url,
            "KID_PURPOSE": purpose[:500],
        }
        if scope and self._vault is not None:
            env["KID_VAULT_JSON"] = json.dumps(self._vault.subset(scope))

        spawned_at = datetime.now(UTC).isoformat()

        # Create the named volume (idempotent) — kid output lives here.
        await self._runtime.create_volume(volume_name)

        try:
            container_id = await self._runtime.start(
                image=image,
                name=f"elophanto-kid-{kid_id}",
                env=env,
                volume_name=volume_name,
                memory_mb=memory_mb,
                cpus=cpus,
                pids_limit=self._config.default_pids_limit,
                network_mode=network,
                drop_capabilities=self._config.drop_capabilities,
                read_only_rootfs=self._config.read_only_rootfs,
                no_new_privileges=self._config.no_new_privileges,
                run_as_uid=self._config.run_as_uid,
            )
        except ContainerRuntimeError:
            # Roll back the volume so we don't leak
            try:
                await self._runtime.remove_volume(volume_name)
            except ContainerRuntimeError:
                pass
            raise

        kid = KidAgent(
            kid_id=kid_id,
            name=slug_name,
            container_id=container_id,
            runtime=self._runtime.name,
            image=image,
            status="running",  # caller can downgrade to 'starting' if waiting for handshake
            vault_scope=scope,
            volume_name=volume_name,
            parent_gateway_url=self._parent_gateway_url,
            purpose=purpose,
            spawned_at=spawned_at,
            role=role,
            last_active=spawned_at,
        )
        self._kids[kid_id] = kid
        self._last_spawn_at = _t.monotonic()
        await self._persist_kid(kid)
        await self._broadcast(
            EventType.AGENT_SPAWNED,
            {
                "kid_id": kid_id,
                "name": slug_name,
                "image": image,
                "type": "kid",
            },
        )
        logger.info(
            "Spawned kid %s (name=%s, container=%s, scope=%d keys)",
            kid_id,
            slug_name,
            container_id[:12],
            len(scope),
        )
        return kid

    # ------------------------------------------------------------------
    # Exec / list / status / destroy
    # ------------------------------------------------------------------

    async def exec(
        self,
        kid_id_or_name: str,
        task: str,
        timeout: float = 600.0,
    ) -> str:
        """Send a task to a running kid and wait for the response.

        Returns the kid's final output (chat content tagged "[kid X done]").
        Raises TimeoutError if the kid doesn't respond within `timeout`
        seconds (default 10 minutes — generous because kids run real
        agent loops with browser/code/etc).

        Intermediate "starting" / "running" chat messages from the kid
        are drained but NOT returned; only the "done" message ends the
        wait. If the kid emits an "ERROR" message, it ends the wait too.
        """
        kid = await self.get_kid(kid_id_or_name)
        if not kid:
            raise RuntimeError(f"No kid named {kid_id_or_name!r}")
        if kid.status != "running":
            raise RuntimeError(
                f"Kid {kid.name} is in status {kid.status!r}; only running kids accept tasks"
            )

        # Ensure we have an inbox for this kid (idempotent).
        inbox = self._kid_inbox.setdefault(kid.kid_id, asyncio.Queue(maxsize=64))
        # Drain any stale messages from a prior exec — we only care
        # about responses that follow THIS task's broadcast.
        while not inbox.empty():
            try:
                inbox.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Broadcast the task assignment. Kid adapter listens for
        # CHILD_TASK_ASSIGNED with its kid_id and runs agent.run().
        if self._gateway:
            await self._broadcast(
                EventType.CHILD_TASK_ASSIGNED,
                {"kid_id": kid.kid_id, "task": task, "type": "kid"},
            )
        kid.last_active = datetime.now(UTC).isoformat()
        await self._persist_kid(kid)

        # Drain the inbox with a deadline. The kid sends N intermediate
        # chat lines and ends with "[kid <name> done in M steps]" or
        # "[kid <name> ERROR ...]"; we collect everything but only stop
        # waiting when we see a terminal marker.
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        collected: list[str] = []
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"Kid {kid.name} did not respond within {timeout}s. "
                    f"Collected {len(collected)} partial messages."
                )
            try:
                content = await asyncio.wait_for(inbox.get(), timeout=remaining)
            except TimeoutError as e:
                raise TimeoutError(
                    f"Kid {kid.name} did not respond within {timeout}s."
                ) from e
            collected.append(content)
            # Terminal markers — kid_agent_adapter._run_task emits these.
            if "done in" in content or "ERROR" in content:
                return content
            # Defensive cap — if the kid floods us with chatter, bail
            # rather than buffer forever.
            if len(collected) > 64:
                return (
                    "[kid output exceeded 64 messages without terminal "
                    "marker — returning partial collected stream]\n\n"
                    + "\n---\n".join(collected[-8:])
                )

    async def handle_kid_message(self, msg: Any) -> None:
        """Gateway hook: forward an inbound message from a kid into the
        per-kid inbox queue. Called by Gateway._handle_chat when it sees
        a chat with channel='kid-agent'."""
        kid_id = getattr(msg, "user_id", "") or ""
        if not kid_id:
            return
        inbox = self._kid_inbox.setdefault(kid_id, asyncio.Queue(maxsize=64))
        # Pull the chat content out of the message data dict.
        data = getattr(msg, "data", {}) or {}
        content = data.get("content", "") if isinstance(data, dict) else ""
        try:
            inbox.put_nowait(str(content))
        except asyncio.QueueFull:
            # Drop oldest to keep recent. Bounded memory > strict ordering.
            try:
                inbox.get_nowait()
                inbox.put_nowait(str(content))
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass
        # Touch last_active for monitoring.
        kid = self._kids.get(kid_id)
        if kid:
            kid.last_active = datetime.now(UTC).isoformat()

    async def list_kids(self, include_stopped: bool = False) -> list[KidAgent]:
        if include_stopped:
            return list(self._kids.values())
        return [k for k in self._kids.values() if k.status not in ("stopped", "failed")]

    async def get_kid(self, kid_id_or_name: str) -> KidAgent | None:
        if kid_id_or_name in self._kids:
            return self._kids[kid_id_or_name]
        # Fall back to name lookup
        for k in self._kids.values():
            if k.name == kid_id_or_name:
                return k
        return None

    async def destroy(self, kid_id_or_name: str, reason: str = "") -> bool:
        """Stop + remove the container, drop the volume, mark stopped.

        Volume removal is the point of no return for kid output — the
        parent should have already pulled out anything it wanted via
        `read_kid_file()` before calling destroy.
        """
        kid = await self.get_kid(kid_id_or_name)
        if not kid:
            return False
        if self._runtime is None:
            # Runtime gone but DB has the row — mark stopped and let the
            # next manager run reconcile.
            kid.status = "stopped"
            kid.completed_at = datetime.now(UTC).isoformat()
            kid.metadata["destroy_reason"] = reason or "runtime unavailable"
            await self._persist_kid(kid)
            return True
        try:
            if kid.container_id:
                await self._runtime.stop(kid.container_id, timeout=10)
                await self._runtime.remove(kid.container_id)
        except ContainerRuntimeError as e:
            logger.warning("destroy: stop/remove for %s failed: %s", kid.kid_id, e)
        try:
            await self._runtime.remove_volume(kid.volume_name)
        except ContainerRuntimeError as e:
            logger.warning("destroy: volume remove for %s failed: %s", kid.kid_id, e)

        kid.status = "stopped"
        kid.completed_at = datetime.now(UTC).isoformat()
        if reason:
            kid.metadata["destroy_reason"] = reason
        await self._persist_kid(kid)
        await self._broadcast(
            EventType.AGENT_STOPPED,
            {"kid_id": kid.kid_id, "type": "kid", "reason": reason},
        )
        return True

    # ------------------------------------------------------------------
    # File exchange — only safe surface to move data in/out of the kid
    # ------------------------------------------------------------------

    async def write_kid_file(
        self, kid_id_or_name: str, dest_path: str, data: bytes
    ) -> None:
        kid = await self.get_kid(kid_id_or_name)
        if not kid or not kid.container_id:
            raise RuntimeError(f"No live kid named {kid_id_or_name!r}")
        if self._runtime is None:
            raise RuntimeError("No container runtime available")
        await self._runtime.cp_to_container(kid.container_id, dest_path, data)

    async def read_kid_file(self, kid_id_or_name: str, src_path: str) -> bytes:
        kid = await self.get_kid(kid_id_or_name)
        if not kid or not kid.container_id:
            raise RuntimeError(f"No live kid named {kid_id_or_name!r}")
        if self._runtime is None:
            raise RuntimeError("No container runtime available")
        return await self._runtime.cp_from_container(
            kid.container_id, src_path, self._config.max_file_read_bytes
        )

    # ------------------------------------------------------------------
    # Monitor — reconcile DB state against actual container state
    # ------------------------------------------------------------------

    async def _monitor_loop(self) -> None:
        """Periodically reconcile kid status with container state.

        If a container has died unexpectedly, mark the kid `failed` so
        the parent sees the truth.
        """
        interval = max(5, self._config.monitor_interval_seconds)
        while True:
            try:
                await asyncio.sleep(interval)
                if self._runtime is None:
                    continue
                for kid in list(self._kids.values()):
                    if kid.status not in ("running", "starting"):
                        continue
                    if not kid.container_id:
                        continue
                    try:
                        info = await self._runtime.inspect(kid.container_id)
                        state = info.get("State", {})
                        is_running = bool(state.get("Running"))
                        if not is_running and kid.status == "running":
                            kid.status = "failed"
                            kid.completed_at = datetime.now(UTC).isoformat()
                            kid.metadata["died"] = (
                                state.get("Error") or "container exited"
                            )
                            await self._persist_kid(kid)
                            await self._broadcast(
                                EventType.AGENT_STOPPED,
                                {
                                    "kid_id": kid.kid_id,
                                    "type": "kid",
                                    "reason": "container died",
                                },
                            )
                    except ContainerRuntimeError:
                        # Likely the container is gone. Mark failed.
                        kid.status = "failed"
                        kid.completed_at = datetime.now(UTC).isoformat()
                        kid.metadata["died"] = "container missing"
                        await self._persist_kid(kid)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("kid monitor loop error: %s", e)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_kid(self, kid: KidAgent) -> None:
        await self._db.execute_insert(
            """INSERT INTO kid_agents
               (kid_id, name, parent_agent_id, container_id, runtime, image,
                status, role, vault_scope_json, volume_name, parent_gateway_url,
                purpose, spawned_at, last_active, completed_at, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(kid_id) DO UPDATE SET
                 container_id = excluded.container_id,
                 status = excluded.status,
                 role = excluded.role,
                 vault_scope_json = excluded.vault_scope_json,
                 volume_name = excluded.volume_name,
                 parent_gateway_url = excluded.parent_gateway_url,
                 purpose = excluded.purpose,
                 last_active = excluded.last_active,
                 completed_at = excluded.completed_at,
                 metadata_json = excluded.metadata_json""",
            (
                kid.kid_id,
                kid.name,
                kid.parent_agent_id,
                kid.container_id,
                kid.runtime,
                kid.image,
                kid.status,
                kid.role,
                json.dumps(kid.vault_scope),
                kid.volume_name,
                kid.parent_gateway_url,
                kid.purpose,
                kid.spawned_at,
                kid.last_active,
                kid.completed_at,
                json.dumps(kid.metadata),
            ),
        )

    async def _reload_from_db(self) -> None:
        rows = await self._db.execute(
            "SELECT * FROM kid_agents WHERE status IN ('running', 'starting')"
        )
        for row in rows:
            self._kids[row["kid_id"]] = self._row_to_kid(row)
        if rows:
            logger.info("Reloaded %d active kids from DB", len(rows))

    async def _name_in_use(self, name: str) -> bool:
        rows = await self._db.execute(
            "SELECT kid_id FROM kid_agents WHERE name = ? AND "
            "status NOT IN ('stopped', 'failed')",
            (name,),
        )
        return bool(rows)

    async def _broadcast(self, event_type: Any, data: dict[str, Any]) -> None:
        if not self._gateway:
            return
        try:
            from core.protocol import event_message

            await self._gateway.broadcast(event_message("", str(event_type), data))
        except Exception as e:
            logger.debug("kid broadcast failed: %s", e)

    @staticmethod
    def _row_to_kid(row: Any) -> KidAgent:
        try:
            scope = json.loads(row["vault_scope_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            scope = []
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        return KidAgent(
            kid_id=row["kid_id"],
            name=row["name"],
            container_id=row["container_id"],
            runtime=row["runtime"],
            image=row["image"],
            status=row["status"],
            vault_scope=scope,
            volume_name=row["volume_name"],
            parent_gateway_url=row["parent_gateway_url"],
            purpose=row["purpose"] or "",
            parent_agent_id=row["parent_agent_id"] or "self",
            role=row["role"],
            spawned_at=row["spawned_at"] or "",
            last_active=row["last_active"],
            completed_at=row["completed_at"],
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _slugify(text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[-\s]+", "-", text)
        return text.strip("-")
