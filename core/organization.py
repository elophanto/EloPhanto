"""Agent organization — spawn, manage, and teach persistent specialist child agents.

Each child is a full EloPhanto instance with its own identity, knowledge vault,
autonomous mind, and gateway. The OrganizationManager handles the lifecycle:
config derivation, knowledge seeding, process management, task delegation,
feedback collection, and teaching (corrections pushed to child's knowledge).

Communication is bidirectional through the gateway protocol — each child
connects to the master's gateway as a channel client.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from core.config import ChildSpecConfig, OrganizationConfig
from core.protocol import EventType, event_message

if TYPE_CHECKING:
    from core.config import Config
    from core.database import Database
    from core.gateway import Gateway

logger = logging.getLogger(__name__)

_DEFAULT_CHILDREN_DIR = Path.home() / ".elophanto-children"


@dataclass
class ChildAgent:
    """A persistent specialist child agent."""

    child_id: str
    role: str
    purpose: str
    status: str = "stopped"  # starting, running, stopped, failed
    port: int = 0
    work_dir: str = ""
    config_path: str = ""
    pid: int | None = None
    approved_count: int = 0
    rejected_count: int = 0
    tasks_completed: int = 0
    spawned_at: str = ""
    last_active: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def trust_score(self) -> int:
        """Net approval score (approved - rejected)."""
        return self.approved_count - self.rejected_count


class OrganizationManager:
    """Manages persistent specialist child agents."""

    def __init__(
        self,
        db: Database,
        config: OrganizationConfig,
        master_config: Config,
        gateway: Gateway | None = None,
    ) -> None:
        self._db = db
        self._config = config
        self._master_config = master_config
        self._gateway = gateway
        self._children: dict[str, ChildAgent] = {}
        self._monitor_task: asyncio.Task[None] | None = None
        self._children_dir = (
            Path(config.children_dir) if config.children_dir else _DEFAULT_CHILDREN_DIR
        )

    # ── Properties ──────────────────────────────────────────────────

    @property
    def is_monitoring(self) -> bool:
        return self._monitor_task is not None and not self._monitor_task.done()

    @property
    def running_children(self) -> list[ChildAgent]:
        return [c for c in self._children.values() if c.status == "running"]

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the organization manager and reload persisted children."""
        await self._reload_from_db()
        # Check which children are still alive
        for child in list(self._children.values()):
            if child.status == "running" and child.pid:
                if not self._is_process_alive(child.pid):
                    child.status = "stopped"
                    child.pid = None
                    await self._persist_child(child)
        if not self.is_monitoring:
            self._monitor_task = asyncio.create_task(
                self._monitor_loop(), name="organization-monitor"
            )
            logger.info(
                "Organization monitor started (%d children, %d running)",
                len(self._children),
                len(self.running_children),
            )

    async def stop(self) -> None:
        """Stop the monitor (does NOT stop child agents)."""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        self._monitor_task = None
        logger.info("Organization monitor stopped")

    async def shutdown(self) -> None:
        """Stop monitor and gracefully stop all running children."""
        await self.stop()
        for child in list(self.running_children):
            await self.stop_child(child.child_id, reason="master shutdown")

    # ── Spawning ────────────────────────────────────────────────────

    async def spawn_specialist(
        self,
        role: str,
        purpose: str = "",
        seed_knowledge: list[str] | None = None,
        budget_pct: float | None = None,
    ) -> ChildAgent:
        """Spawn a new specialist or return existing one for the role."""
        # Check for existing specialist with this role
        existing = self._find_by_role(role)
        if existing:
            if existing.status == "running":
                return existing
            # Restart stopped specialist
            return await self.restart_child(existing.child_id)

        # Check limits
        if len(self.running_children) >= self._config.max_children:
            raise RuntimeError(
                f"Max children reached ({self._config.max_children}). "
                "Stop an existing specialist first."
            )

        # Resolve spec from config or build from arguments
        spec = self._resolve_spec(role, purpose, seed_knowledge, budget_pct)

        child_id = uuid.uuid4().hex[:8]
        port = self._allocate_port()
        work_dir = self._children_dir / child_id
        config_path = work_dir / "config.yaml"

        # Create work directory
        work_dir.mkdir(parents=True, exist_ok=True)

        # Derive config
        await self._derive_config(spec, child_id, port, work_dir, config_path)

        # Seed knowledge
        await self._seed_knowledge(spec, work_dir)

        # Create child record
        child = ChildAgent(
            child_id=child_id,
            role=spec.role,
            purpose=spec.purpose,
            status="starting",
            port=port,
            work_dir=str(work_dir),
            config_path=str(config_path),
            spawned_at=datetime.now(UTC).isoformat(),
        )
        self._children[child_id] = child
        await self._persist_child(child)

        # Bootstrap the child process
        try:
            await self._bootstrap_child(child)
        except Exception as e:
            child.status = "failed"
            child.metadata["error"] = str(e)
            await self._persist_child(child)
            raise

        self._broadcast(
            EventType.AGENT_SPAWNED,
            {
                "child_id": child_id,
                "role": spec.role,
                "port": port,
                "type": "organization",
            },
        )

        return child

    async def get_or_spawn(self, role: str, **kwargs: Any) -> ChildAgent:
        """Get existing specialist for role or spawn a new one."""
        existing = self._find_by_role(role)
        if existing and existing.status == "running":
            return existing
        return await self.spawn_specialist(role, **kwargs)

    # ── Child Control ───────────────────────────────────────────────

    async def stop_child(self, child_id: str, reason: str = "") -> ChildAgent:
        """Stop a running child agent."""
        child = self._children.get(child_id)
        if not child:
            raise ValueError(f"Unknown child: {child_id}")

        if child.pid and self._is_process_alive(child.pid):
            try:
                os.kill(child.pid, signal.SIGTERM)
                # Wait up to 5s for graceful shutdown
                for _ in range(50):
                    await asyncio.sleep(0.1)
                    if not self._is_process_alive(child.pid):
                        break
                else:
                    os.kill(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        child.status = "stopped"
        child.pid = None
        child.metadata["stopped_reason"] = reason
        await self._persist_child(child)

        self._broadcast(
            EventType.AGENT_STOPPED,
            {
                "child_id": child_id,
                "role": child.role,
                "reason": reason,
                "type": "organization",
            },
        )
        logger.info("Stopped child %s (%s): %s", child_id, child.role, reason)
        return child

    async def restart_child(self, child_id: str) -> ChildAgent:
        """Restart a stopped child agent."""
        child = self._children.get(child_id)
        if not child:
            raise ValueError(f"Unknown child: {child_id}")

        if (
            child.status == "running"
            and child.pid
            and self._is_process_alive(child.pid)
        ):
            return child

        child.status = "starting"
        await self._persist_child(child)

        try:
            await self._bootstrap_child(child)
        except Exception as e:
            child.status = "failed"
            child.metadata["error"] = str(e)
            await self._persist_child(child)
            raise

        return child

    # ── Task Delegation ─────────────────────────────────────────────

    async def send_task(self, child_id: str, task: str) -> dict[str, Any]:
        """Send a task to a child agent via its gateway."""
        child = self._children.get(child_id)
        if not child:
            raise ValueError(f"Unknown child: {child_id}")
        if child.status != "running":
            raise RuntimeError(
                f"Child {child_id} is not running (status: {child.status})"
            )

        # Send via WebSocket to child's gateway
        import websockets

        uri = f"ws://127.0.0.1:{child.port}"
        try:
            async with websockets.connect(uri) as ws:  # type: ignore[attr-defined]
                from core.protocol import chat_message

                msg = chat_message(
                    channel=f"master:{self._master_config.agent_name}",
                    user_id="master",
                    content=task,
                    session_id="master",
                )
                await ws.send(msg.to_json())
                # Wait for acknowledgment (up to 10s)
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=10)
                    return (
                        json.loads(raw) if isinstance(raw, str) else {"status": "sent"}
                    )
                except TimeoutError:
                    return {"status": "sent", "note": "no ack within 10s"}
        except Exception as e:
            logger.warning("Failed to send task to child %s: %s", child_id, e)
            return {"status": "error", "error": str(e)}

    # ── Feedback & Teaching ─────────────────────────────────────────

    async def approve(
        self, child_id: str, task_ref: str = "", feedback: str = ""
    ) -> None:
        """Approve a child's work — positive reinforcement."""
        child = self._children.get(child_id)
        if not child:
            raise ValueError(f"Unknown child: {child_id}")

        child.approved_count += 1
        child.tasks_completed += 1
        child.last_active = datetime.now(UTC).isoformat()
        await self._persist_child(child)
        await self._store_feedback(child_id, task_ref, "approval", feedback)

        if feedback:
            await self._push_knowledge(
                child,
                f"# Positive Feedback: {task_ref or 'Task'}\n\n"
                f"**Feedback**: {feedback}\n\n"
                "This approach was approved. Continue using similar methods.",
                tags=["reinforcement", child.role],
            )

        logger.info("Approved child %s (%s): %s", child_id, child.role, task_ref)

    async def reject(self, child_id: str, task_ref: str = "", reason: str = "") -> None:
        """Reject a child's work — correction stored as knowledge."""
        child = self._children.get(child_id)
        if not child:
            raise ValueError(f"Unknown child: {child_id}")

        child.rejected_count += 1
        child.tasks_completed += 1
        child.last_active = datetime.now(UTC).isoformat()
        await self._persist_child(child)
        await self._store_feedback(child_id, task_ref, "rejection", reason)

        if reason:
            await self._push_knowledge(
                child,
                f"# Correction: {task_ref or 'Task'}\n\n"
                f"**Task**: {task_ref}\n"
                f"**Feedback**: Rejected — {reason}\n\n"
                "Avoid this approach in future tasks.",
                tags=["correction", child.role],
            )

        logger.info(
            "Rejected child %s (%s): %s — %s", child_id, child.role, task_ref, reason
        )

    async def teach(
        self, child_id: str, content: str, tags: list[str] | None = None
    ) -> None:
        """Push knowledge to a child agent."""
        child = self._children.get(child_id)
        if not child:
            raise ValueError(f"Unknown child: {child_id}")

        await self._push_knowledge(
            child,
            content,
            tags=tags or ["teaching", child.role],
        )
        await self._store_feedback(child_id, "", "teaching", content[:200])
        logger.info("Taught child %s (%s): %s", child_id, child.role, content[:80])

    # ── Status ──────────────────────────────────────────────────────

    def list_children(self) -> list[dict[str, Any]]:
        """List all children with status and performance."""
        result = []
        for child in self._children.values():
            alive = child.pid is not None and self._is_process_alive(child.pid)
            result.append(
                {
                    "child_id": child.child_id,
                    "role": child.role,
                    "purpose": child.purpose,
                    "status": "running" if alive else child.status,
                    "port": child.port,
                    "trust_score": child.trust_score,
                    "approved": child.approved_count,
                    "rejected": child.rejected_count,
                    "tasks_completed": child.tasks_completed,
                    "last_active": child.last_active,
                }
            )
        return result

    def get_organization_context(self) -> str:
        """Build organization context for the master's system prompt."""
        children = self.list_children()
        if not children:
            return ""

        lines = ["<organization>"]
        lines.append(
            "You lead a team of specialist agents. Each specialist is autonomous,"
        )
        lines.append("grows expertise over time, and reports back for your review.\n")
        lines.append("AVAILABLE SPECIALISTS:")
        for c in children:
            trust = c["trust_score"]
            trust_label = (
                "high trust"
                if trust >= 20
                else (
                    "trusted"
                    if trust >= 10
                    else "learning" if trust >= 0 else "needs oversight"
                )
            )
            lines.append(
                f"  - {c['role']} ({c['status']}) — {c.get('purpose', '')[:60]} "
                f"| trust: {trust} ({trust_label}) | tasks: {c['tasks_completed']}"
            )

        lines.append("")
        lines.append("DELEGATION FRAMEWORK:")
        lines.append("- Quick, simple tasks you can handle well → do it yourself")
        lines.append("- Tasks requiring deep domain expertise → delegate to specialist")
        lines.append("- Multiple independent tasks → delegate in parallel")
        lines.append(
            f"- A specialist with trust ≥{self._config.auto_approve_threshold} "
            "→ delegate with less oversight"
        )
        lines.append("- A new or low-trust specialist → review all output")
        lines.append("")
        lines.append("Use organization_spawn to create new specialists.")
        lines.append("Use organization_delegate to assign tasks.")
        lines.append("Use organization_review to approve/reject and teach.")
        lines.append("</organization>")
        return "\n".join(lines)

    # ── Internal: Config Derivation ─────────────────────────────────

    async def _derive_config(
        self,
        spec: ChildSpecConfig,
        child_id: str,
        port: int,
        work_dir: Path,
        config_path: Path,
    ) -> None:
        """Generate a derived config.yaml for the child."""
        # Start from master config, override specific sections
        master = self._master_config

        # Calculate budget allocation
        daily_budget = master.llm.budget.daily_limit_usd
        child_daily = daily_budget * (spec.budget_pct / 100.0)

        # Build provider config (inherit API keys)
        providers: dict[str, Any] = {}
        for name, prov in master.llm.providers.items():
            if prov.enabled:
                providers[name] = {
                    "api_key": prov.api_key,
                    "enabled": True,
                    "base_url": prov.base_url,
                    "default_model": prov.default_model,
                }

        child_config: dict[str, Any] = {
            "agent_name": f"{spec.role}-specialist-{child_id}",
            "permission_mode": "auto_approve",
            "gateway": {
                "enabled": True,
                "host": "127.0.0.1",
                "port": port,
                "max_sessions": 5,
            },
            "database": {
                "db_path": str(work_dir / "data" / "elophanto.db"),
            },
            "knowledge": {
                "knowledge_dir": str(work_dir / "knowledge"),
                "auto_index_on_startup": True,
            },
            "identity": {
                "enabled": True,
                "first_awakening": True,
                "auto_evolve": True,
                "nature_file": str(work_dir / "knowledge" / "self" / "nature.md"),
            },
            "autonomous_mind": {
                "enabled": spec.autonomous,
                "wakeup_seconds": spec.wakeup_seconds,
                "budget_pct": 100,  # Child controls its full allocated budget
            },
            "llm": {
                "providers": providers,
                "routing": {
                    "planning": master.llm.routing.get("planning", ""),
                    "simple": master.llm.routing.get("simple", ""),
                },
                "budget": {
                    "daily_limit_usd": round(child_daily, 2),
                    "per_task_limit_usd": round(child_daily / 2, 2),
                },
            },
            "browser": {
                "enabled": master.browser.enabled,
            },
            "storage": {
                "data_dir": str(work_dir / "data"),
            },
            "parent": {
                "enabled": True,
                "host": master.gateway.host,
                "port": master.gateway.port,
                "child_id": child_id,
            },
        }

        # Write config
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(yaml.dump(child_config, default_flow_style=False))
        logger.info("Derived config for child %s at %s", child_id, config_path)

    async def _seed_knowledge(self, spec: ChildSpecConfig, work_dir: Path) -> None:
        """Copy seed knowledge files from master to child's knowledge dir."""
        child_knowledge = work_dir / "knowledge"
        child_knowledge.mkdir(parents=True, exist_ok=True)
        (child_knowledge / "self").mkdir(exist_ok=True)
        (child_knowledge / "system").mkdir(exist_ok=True)
        (child_knowledge / "learned").mkdir(exist_ok=True)
        (child_knowledge / "learned" / "corrections").mkdir(parents=True, exist_ok=True)

        master_knowledge = Path(self._master_config.knowledge.knowledge_dir)

        # Write purpose file so the child knows its role
        purpose_file = child_knowledge / "system" / "purpose.md"
        purpose_file.write_text(
            f"---\nscope: system\ntags: identity, purpose\n---\n\n"
            f"# Specialist Role: {spec.role}\n\n"
            f"**Purpose**: {spec.purpose}\n\n"
            f"You are a specialist agent focused on {spec.role}. "
            f"Work autonomously within your domain. Report findings to your "
            f"master agent. Learn from feedback — corrections are stored in "
            f"knowledge/learned/corrections/.\n"
        )

        # Copy seed knowledge files
        for seed_path_str in spec.seed_knowledge:
            seed_path = Path(seed_path_str)
            if not seed_path.is_absolute():
                seed_path = master_knowledge / seed_path_str
            if seed_path.is_file():
                dest = child_knowledge / "system" / seed_path.name
                shutil.copy2(seed_path, dest)
                logger.debug("Seeded knowledge: %s → %s", seed_path, dest)
            elif seed_path.is_dir():
                dest_dir = child_knowledge / "system" / seed_path.name
                shutil.copytree(seed_path, dest_dir, dirs_exist_ok=True)
            else:
                logger.warning("Seed knowledge not found: %s", seed_path)

    # ── Internal: Process Management ────────────────────────────────

    async def _bootstrap_child(self, child: ChildAgent) -> None:
        """Start a child EloPhanto process."""
        import sys

        work_dir = Path(child.work_dir)

        # Ensure data directory exists
        (work_dir / "data").mkdir(parents=True, exist_ok=True)

        # Copy the EloPhanto source (symlink for local dev, copy for production)
        src_root = self._master_config.project_root
        child_src = work_dir / "src"
        if not child_src.exists():
            # Symlink core modules — lightweight, always current
            child_src.mkdir(parents=True, exist_ok=True)
            for module in ("core", "tools", "channels", "cli", "plugins", "skills"):
                src_mod = src_root / module
                dst_mod = child_src / module
                if src_mod.is_dir() and not dst_mod.exists():
                    dst_mod.symlink_to(src_mod)
            # Copy essential files
            for f in ("__main__.py", "pyproject.toml"):
                src_f = src_root / f
                if src_f.is_file():
                    dst_f = child_src / f
                    if not dst_f.exists():
                        shutil.copy2(src_f, dst_f)

        # Build environment — inherit Python path but strip sensitive vars.
        env = dict(os.environ)
        env["ELOPHANTO_CONFIG"] = str(child.config_path)
        env["PYTHONPATH"] = str(child_src)

        # Default-deny: strip any env var whose name suggests it carries
        # credentials. This is strictly stricter than the prior list (which
        # missed API_KEY / TOKEN / PASSWORD). Children boot with their OWN
        # disk vault (own work_dir/config) — they don't receive parent
        # vault contents via env.
        #
        # ChildSpec.vault_scope is reserved for future explicit inheritance
        # (analogous to KidConfig — write a scoped JSON via env). For v1,
        # keep parent ↔ child secrets isolated entirely.
        _CRED_NEEDLES = (
            "VAULT",
            "SECRET",
            "PRIVATE_KEY",
            "CREDENTIAL",
            "API_KEY",
            "APIKEY",
            "TOKEN",
            "PASSWORD",
            "PASSWD",
        )
        # Whitelist a small set of false positives — env vars that LOOK
        # secret but are operational and safe to inherit (e.g. SHELL session,
        # paths). Keep this list narrow.
        _CRED_WHITELIST = {"HOMEBREW_NO_ANALYTICS_MESSAGE_OUTPUT"}
        for key in list(env.keys()):
            if key in _CRED_WHITELIST:
                continue
            key_upper = key.upper()
            if any(needle in key_upper for needle in _CRED_NEEDLES):
                del env[key]

        # Start the child process
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "cli.gateway_cmd",
            "--config",
            str(child.config_path),
            cwd=str(child_src),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        child.pid = proc.pid
        child.status = "running"
        child.last_active = datetime.now(UTC).isoformat()
        await self._persist_child(child)

        # Wait for gateway to be ready (poll port)
        ready = await self._wait_for_gateway(child.port, timeout=30)
        if not ready:
            logger.warning(
                "Child %s gateway not ready after 30s (port %d)",
                child.child_id,
                child.port,
            )
            # Don't fail — process may still be initializing

        logger.info(
            "Bootstrapped child %s (%s) on port %d, pid=%d",
            child.child_id,
            child.role,
            child.port,
            proc.pid or 0,
        )

    async def _wait_for_gateway(self, port: int, timeout: int = 30) -> bool:
        """Wait for a child's gateway to accept connections."""
        import socket

        for _ in range(timeout * 2):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                result = sock.connect_ex(("127.0.0.1", port))
                sock.close()
                if result == 0:
                    return True
            except OSError:
                pass
            await asyncio.sleep(0.5)
        return False

    # ── Internal: Knowledge Push ────────────────────────────────────

    async def _push_knowledge(
        self,
        child: ChildAgent,
        content: str,
        tags: list[str] | None = None,
    ) -> None:
        """Write a knowledge file to the child's knowledge directory."""
        child_knowledge = Path(child.work_dir) / "knowledge" / "learned" / "corrections"
        child_knowledge.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        filename = f"{timestamp}-{uuid.uuid4().hex[:4]}.md"
        filepath = child_knowledge / filename

        tags_str = ", ".join(tags or ["learned"])
        frontmatter = (
            f"---\nscope: learned\ntags: {tags_str}\n"
            f"created: {datetime.now(UTC).strftime('%Y-%m-%d')}\n"
            f"source: master-feedback\n---\n\n"
        )
        filepath.write_text(frontmatter + content)
        logger.debug("Pushed knowledge to child %s: %s", child.child_id, filepath)

    # ── Internal: Monitoring ────────────────────────────────────────

    async def _monitor_loop(self) -> None:
        """Background loop to check child health."""
        while True:
            try:
                await asyncio.sleep(self._config.monitor_interval_seconds)
                await self._check_children()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Organization monitor error")
                await asyncio.sleep(10)

    async def _check_children(self) -> None:
        """Check health of all running children."""
        for child in list(self._children.values()):
            if child.status != "running" or not child.pid:
                continue

            if not self._is_process_alive(child.pid):
                logger.warning(
                    "Child %s (%s) process died (pid=%d)",
                    child.child_id,
                    child.role,
                    child.pid,
                )
                child.status = "stopped"
                child.pid = None
                child.metadata["stopped_reason"] = "process died unexpectedly"
                await self._persist_child(child)

                self._broadcast(
                    EventType.AGENT_FAILED,
                    {
                        "child_id": child.child_id,
                        "role": child.role,
                        "reason": "process died",
                        "type": "organization",
                    },
                )

    # ── Internal: DB Persistence ────────────────────────────────────

    async def _persist_child(self, child: ChildAgent) -> None:
        """Upsert child record to database."""
        await self._db.execute_insert(
            """INSERT INTO organization_children
               (child_id, role, purpose, status, port, work_dir, config_path,
                pid, approved_count, rejected_count, tasks_completed,
                spawned_at, last_active, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(child_id) DO UPDATE SET
                 status=excluded.status, pid=excluded.pid,
                 approved_count=excluded.approved_count,
                 rejected_count=excluded.rejected_count,
                 tasks_completed=excluded.tasks_completed,
                 last_active=excluded.last_active,
                 metadata_json=excluded.metadata_json""",
            (
                child.child_id,
                child.role,
                child.purpose,
                child.status,
                child.port,
                child.work_dir,
                child.config_path,
                child.pid,
                child.approved_count,
                child.rejected_count,
                child.tasks_completed,
                child.spawned_at,
                child.last_active,
                json.dumps(child.metadata),
            ),
        )

    async def _store_feedback(
        self, child_id: str, task_ref: str, feedback_type: str, content: str
    ) -> None:
        """Store feedback in the organization_feedback table."""
        await self._db.execute_insert(
            """INSERT INTO organization_feedback
               (child_id, task_ref, feedback_type, content, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (child_id, task_ref, feedback_type, content, datetime.now(UTC).isoformat()),
        )

    async def _reload_from_db(self) -> None:
        """Reload persisted children from database."""
        rows = await self._db.execute("SELECT * FROM organization_children", ())
        for row in rows:
            child = ChildAgent(
                child_id=row["child_id"],
                role=row["role"],
                purpose=row["purpose"],
                status=row["status"],
                port=row["port"],
                work_dir=row["work_dir"],
                config_path=row["config_path"],
                pid=row["pid"],
                approved_count=row["approved_count"],
                rejected_count=row["rejected_count"],
                tasks_completed=row["tasks_completed"],
                spawned_at=row["spawned_at"],
                last_active=row["last_active"],
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
            self._children[child.child_id] = child

    # ── Internal: Helpers ───────────────────────────────────────────

    def _find_by_role(self, role: str) -> ChildAgent | None:
        """Find a child by role."""
        for child in self._children.values():
            if child.role == role:
                return child
        return None

    def _allocate_port(self) -> int:
        """Allocate the next available port."""
        used_ports = {c.port for c in self._children.values()}
        port = self._config.port_range_start
        while port in used_ports:
            port += 1
        return port

    def _resolve_spec(
        self,
        role: str,
        purpose: str,
        seed_knowledge: list[str] | None,
        budget_pct: float | None,
    ) -> ChildSpecConfig:
        """Resolve a ChildSpecConfig from config or arguments."""
        # Check if there's a pre-configured spec
        if role in self._config.specs:
            spec = self._config.specs[role]
            # Override with explicit arguments if provided
            if purpose:
                spec.purpose = purpose
            if seed_knowledge is not None:
                spec.seed_knowledge = seed_knowledge
            if budget_pct is not None:
                spec.budget_pct = budget_pct
            return spec

        # Build from arguments
        return ChildSpecConfig(
            role=role,
            purpose=purpose or f"Specialist agent for {role}",
            seed_knowledge=seed_knowledge or [],
            budget_pct=budget_pct or 10.0,
        )

    @staticmethod
    def _is_process_alive(pid: int) -> bool:
        """Check if a process is still running."""
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def _broadcast(self, event_type: EventType, data: dict[str, Any]) -> None:
        """Broadcast event via gateway."""
        if self._gateway:
            try:
                msg = event_message("", str(event_type), data)
                asyncio.create_task(self._gateway.broadcast(msg))
            except Exception:
                logger.debug("Failed to broadcast %s", event_type)
