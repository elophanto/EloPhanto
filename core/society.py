"""Read-only, local visualization of actual agent work.

This side channel never receives prompts, tool arguments, output, credentials,
URLs or paths. It cannot execute tools. Browser automation has no reference to
its HTTP service or its separately launched browser profile. All producer hooks
are fail-open, and slow viewers only retain one bounded snapshot per connection.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import json
import logging
import mimetypes
import re
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from core.config import SocietyConfig

logger = logging.getLogger(__name__)
DEPARTMENTS = frozenset(
    {"headquarters", "research", "engineering", "communications", "knowledge", "operations"}
)
STATUSES = frozenset({"idle", "thinking", "working", "waiting", "error", "offline"})
_agent_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "society_agent", default="main"
)
MAX_AGENTS = 128
MAX_EVENTS = 100
MAX_CLIENTS = 12


def department_for_tool(tool: str) -> str:
    """Classify only a public tool identifier, never its arguments."""
    tool = tool.lower()
    if tool.startswith(("browser", "web", "search", "fetch", "scrape")):
        return "research"
    if tool.startswith(("knowledge", "memory", "skill", "identity", "ego", "affect", "lesson")):
        return "knowledge"
    if tool.startswith(
        ("email", "slack", "discord", "telegram", "message", "twitter", "notify", "p2p")
    ):
        return "communications"
    if tool.startswith(
        ("shell", "file", "code", "git", "self_dev", "python", "desktop", "document")
    ):
        return "engineering"
    if tool.startswith(
        (
            "swarm",
            "kid",
            "child",
            "org",
            "delegate",
            "schedule",
            "goal",
            "mission",
            "payment",
            "wallet",
            "deploy",
            "job",
            "storage",
        )
    ):
        return "operations"
    return "headquarters"


def _label(value: Any, fallback: str = "", limit: int = 64) -> str:
    if not isinstance(value, str):
        return fallback
    return re.sub(r"[^\w .:@/-]", "", value, flags=re.UNICODE)[:limit] or fallback


def emit(service: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    """Every producer passes through this guard: telemetry cannot break work."""
    if service is None:
        return None
    try:
        return getattr(service, method)(*args, **kwargs)
    except Exception:
        logger.debug("Society telemetry update failed", exc_info=True)
        return None


class SocietyService:
    def __init__(
        self, config: SocietyConfig, project_root: Path, agent_name: str = "EloPhanto"
    ) -> None:
        self.config = config
        self.project_root = Path(project_root)
        self.assets = (self.project_root / "web" / "dist").resolve()
        self._condition = threading.Condition(threading.RLock())
        self._agents: dict[str, dict[str, Any]] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
        self._active_tools: dict[str, dict[str, tuple[str, float]]] = {}
        self._runs: dict[str, int] = {}
        self._external: dict[str, str] = {}
        self._sequence = 0
        self._completed = 0
        self._errors = 0
        self._started_at = time.time()
        self._stopping = threading.Event()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._clients = threading.BoundedSemaphore(MAX_CLIENTS)
        self.update_agent(
            "main", name=agent_name, kind="main", status="idle", department="headquarters"
        )

    @property
    def url(self) -> str:
        port = self._server.server_port if self._server else self.config.port
        return f"http://127.0.0.1:{port}/society/"

    def start(self) -> bool:
        if not self.config.enabled:
            return False
        if self._server is not None:
            return True
        try:
            self._stopping.clear()
            self._server = ThreadingHTTPServer(("127.0.0.1", self.config.port), self._handler())
            self._server.daemon_threads = True
            self._server.block_on_close = False
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                kwargs={"poll_interval": 0.2},
                name="society-http",
                daemon=True,
            )
            self._thread.start()
            logger.info("Agents society: %s", self.url)
            if self.config.open_browser:
                threading.Thread(
                    target=self._open_window, name="society-window", daemon=True
                ).start()
            return True
        except Exception as exc:
            logger.warning("Agents society could not start (%s); agent work continues", exc)
            if self._server is not None:
                self._server.server_close()
                self._server = None
            return False

    def _open_window(self) -> None:
        try:
            from core.society_launcher import open_society_window

            open_society_window(self.url, self.project_root)
        except Exception:
            logger.warning("Open the agents society at %s", self.url, exc_info=True)

    def stop(self) -> None:
        self.update_agent("main", status="offline", department="headquarters", event="disconnected")
        self._stopping.set()
        with self._condition:
            self._condition.notify_all()
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None

    def update_agent(
        self,
        agent_id: str,
        *,
        name: str = "",
        kind: str = "",
        parent_id: str = "",
        department: str = "",
        status: str = "",
        tool: str = "",
        event: str = "state",
        duration_ms: int | None = None,
    ) -> None:
        with self._condition:
            agent_id = _label(agent_id, "main")
            if agent_id not in self._agents and len(self._agents) >= MAX_AGENTS:
                # Keep the main agent and active workers; retire old inactive figures.
                victim = next(
                    (
                        key
                        for key, item in self._agents.items()
                        if key != "main" and item["status"] in {"idle", "offline", "error"}
                    ),
                    None,
                )
                if victim is None:
                    return
                self._agents.pop(victim, None)
                self._external.pop(victim, None)
            previous = self._agents.get(agent_id, {})
            now = time.time()
            item = {
                "id": agent_id,
                "name": _label(name) or previous.get("name", "Worker"),
                "kind": kind
                if kind in {"main", "delegate", "swarm", "kid", "specialist"}
                else previous.get("kind", "delegate"),
                "parent_id": _label(parent_id)
                or previous.get("parent_id", "" if agent_id == "main" else "main"),
                "department": department
                if department in DEPARTMENTS
                else previous.get("department", "headquarters"),
                "status": status if status in STATUSES else previous.get("status", "idle"),
                "tool": _label(tool, limit=80),
                "updated_at": now,
            }
            self._agents[agent_id] = item
            self._sequence += 1
            entry = {
                "id": self._sequence,
                "agent_id": agent_id,
                "kind": _label(event),
                "department": item["department"],
                "status": item["status"],
                "tool": item["tool"],
                "timestamp": now,
            }
            if duration_ms is not None:
                entry["duration_ms"] = max(0, duration_ms)
            self._events.append(entry)
            self._condition.notify_all()

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            return {
                "version": 1,
                "sequence": self._sequence,
                "started_at": self._started_at,
                "updated_at": self._events[-1]["timestamp"] if self._events else self._started_at,
                "agents": [dict(item) for item in self._agents.values()],
                "events": [dict(item) for item in self._events],
                "stats": {
                    "active": sum(
                        a["status"] in {"thinking", "working", "waiting"}
                        for a in self._agents.values()
                    ),
                    "total": len(self._agents),
                    "completed": self._completed,
                    "errors": self._errors,
                },
            }

    def begin_run(self) -> str:
        agent_id = _agent_context.get()
        with self._condition:
            self._runs[agent_id] = self._runs.get(agent_id, 0) + 1
            self.update_agent(
                agent_id, status="thinking", department="headquarters", event="task_started"
            )
        return agent_id

    def end_run(self, agent_id: str, *, failed: bool = False, cancelled: bool = False) -> None:
        with self._condition:
            count = self._runs.get(agent_id, 1) - 1
            if count > 0:
                self._runs[agent_id] = count
            else:
                self._runs.pop(agent_id, None)
            self.update_agent(
                agent_id,
                status="error" if failed else ("thinking" if count > 0 else "idle"),
                department="headquarters",
                event="task_cancelled"
                if cancelled
                else ("task_failed" if failed else "task_completed"),
            )

    def begin_tool(self, tool: str) -> tuple[str, str]:
        agent_id = _agent_context.get()
        ticket = uuid.uuid4().hex
        with self._condition:
            self._active_tools.setdefault(agent_id, {})[ticket] = (_label(tool), time.monotonic())
            self.update_agent(
                agent_id,
                status="working",
                department=department_for_tool(tool),
                tool=tool,
                event="tool_started",
            )
        return agent_id, ticket

    def waiting(self, tool: str) -> None:
        self.update_agent(
            _agent_context.get(),
            status="waiting",
            department=department_for_tool(tool),
            tool=tool,
            event="approval_requested",
        )

    def working(self, tool: str) -> None:
        self.update_agent(
            _agent_context.get(),
            status="working",
            department=department_for_tool(tool),
            tool=tool,
            event="tool_executing",
        )

    def end_tool(
        self,
        token: tuple[str, str],
        *,
        failed: bool = False,
        denied: bool = False,
        cancelled: bool = False,
    ) -> None:
        agent_id, ticket = token
        with self._condition:
            active = self._active_tools.get(agent_id, {})
            tool, started = active.pop(ticket, ("", time.monotonic()))
            if not active:
                self._active_tools.pop(agent_id, None)
            if failed:
                self._errors += 1
            elif not denied and not cancelled:
                self._completed += 1
            self.update_agent(
                agent_id,
                status="error" if failed else "idle",
                department=department_for_tool(tool),
                tool=tool,
                event="tool_cancelled"
                if cancelled
                else ("tool_denied" if denied else ("tool_failed" if failed else "tool_completed")),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            if active:
                next_tool = next(reversed(active.values()))[0]
                self.update_agent(
                    agent_id,
                    status="working",
                    department=department_for_tool(next_tool),
                    tool=next_tool,
                    event="working",
                )
            elif not failed:
                self.update_agent(
                    agent_id,
                    status="thinking" if self._runs.get(agent_id) else "idle",
                    department="headquarters",
                    event="returned",
                )

    def sync_managers(self, owner: Any) -> None:
        """External subprocesses expose lifecycle, never their private tool streams."""
        for attr, collection, id_field, kind, department in (
            ("_swarm_manager", "_agents", "agent_id", "swarm", "engineering"),
            ("_kid_manager", "_kids", "kid_id", "kid", "operations"),
            ("_organization_manager", "_children", "child_id", "specialist", "operations"),
        ):
            manager = getattr(owner, attr, None)
            if manager is None:
                continue
            for worker in list(getattr(manager, collection, {}).values()):
                raw_id = getattr(worker, id_field, "")
                agent_id = f"{kind}:{_label(raw_id)}"
                raw_status = getattr(worker, "status", "stopped")
                if self._external.get(agent_id) == raw_status:
                    continue
                status = {
                    "running": "working" if kind == "swarm" else "idle",
                    "starting": "thinking",
                    "paused": "waiting",
                    "failed": "error",
                    "completed": "idle",
                }.get(raw_status, "offline")
                label = {"swarm": "Builder", "kid": "Kid", "specialist": "Specialist"}[kind]
                self.update_agent(
                    agent_id,
                    name=f"{label} {raw_id[:6]}",
                    kind=kind,
                    department=department if status == "working" else "headquarters",
                    status=status,
                    event="worker_" + _label(raw_status),
                )
                if agent_id in self._agents:
                    self._external[agent_id] = raw_status

    def worker_event(self, kind: str, agent_id: str, event: str) -> None:
        """Lifecycle hooks for assignments that do not change process status."""
        raw_id = _label(agent_id)
        agent_id = f"{kind}:{raw_id}"
        if event == "assigned":
            # Assignment can arrive before the first manager presence poll.
            # Preserve its activity instead of resetting the actor to idle.
            self._external.setdefault(agent_id, "running")
            self.update_agent(
                agent_id,
                name=f"{kind.title()} {raw_id[:6]}",
                kind=kind,
                department="operations",
                status="working",
                event="task_started",
            )
        elif event in {"completed", "failed", "cancelled"}:
            self.update_agent(
                agent_id,
                kind=kind,
                department="headquarters",
                status="error" if event == "failed" else "idle",
                event="task_" + event,
            )

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        service = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                pass

            def _respond(self, code: int, data: bytes, content_type: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(data)

            def do_HEAD(self) -> None:
                self.do_GET()

            def do_GET(self) -> None:
                # Block DNS rebinding and cross-origin scripted access. No CORS.
                authority = self.headers.get("Host", "")
                allowed = {
                    f"127.0.0.1:{self.server.server_port}",
                    f"localhost:{self.server.server_port}",
                }
                origin = self.headers.get("Origin")
                if authority not in allowed or (
                    origin and origin not in {f"http://{host}" for host in allowed}
                ):
                    self._respond(403, b"Local access only", "text/plain")
                    return
                path = urlsplit(self.path).path
                if path == "/api/society/state":
                    self._respond(200, json.dumps(service.snapshot()).encode(), "application/json")
                elif path == "/api/society/events":
                    if self.command == "HEAD":
                        self._respond(200, b"", "text/event-stream")
                    else:
                        self._stream()
                elif path in {"/", "/society"}:
                    self.send_response(302)
                    self.send_header("Location", "/society/")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif path.startswith(("/society/", "/assets/")):
                    relative = (
                        unquote(path[len("/society/") :])
                        if path.startswith("/society/")
                        else unquote(path.lstrip("/"))
                    )
                    relative = relative or "index.html"
                    target = (service.assets / relative).resolve()
                    if not target.is_relative_to(service.assets) or not target.is_file():
                        self._respond(
                            404,
                            b"Society assets missing. Run: cd web && npm run build",
                            "text/plain",
                        )
                        return
                    content_type = (
                        mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                    )
                    try:
                        self._respond(200, target.read_bytes(), content_type)
                    except OSError:
                        self._respond(404, b"Not found", "text/plain")
                else:
                    self._respond(404, b"Not found", "text/plain")

            def _stream(self) -> None:
                if not service._clients.acquire(blocking=False):
                    self._respond(503, b"Too many viewers", "text/plain")
                    return
                try:
                    self.connection.settimeout(5)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache, no-store")
                    self.send_header("Connection", "close")
                    self.send_header("X-Accel-Buffering", "no")
                    self.end_headers()
                    sequence = -1
                    while not service._stopping.is_set():
                        with service._condition:
                            if sequence == service._sequence:
                                service._condition.wait(timeout=10)
                            state = service.snapshot()
                        if state["sequence"] != sequence:
                            sequence = state["sequence"]
                            data = f"id: {sequence}\nevent: state\ndata: {json.dumps(state, separators=(',', ':'))}\n\n"
                        else:
                            data = ": heartbeat\n\n"
                        self.wfile.write(data.encode())
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
                    pass
                finally:
                    service._clients.release()
                    self.close_connection = True

        return Handler


def observe_run(function: Callable) -> Callable:
    @functools.wraps(function)
    async def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        service = getattr(self, "_society", None)
        agent_id = emit(service, "begin_run")
        failed = cancelled = False
        try:
            result = await function(self, *args, **kwargs)
            failed = getattr(result, "success", True) is False
            return result
        except asyncio.CancelledError:
            cancelled = True
            raise
        except BaseException:
            failed = True
            raise
        finally:
            if agent_id is not None:
                emit(service, "end_run", agent_id, failed=failed, cancelled=cancelled)

    return wrapped


def observe_delegate(function: Callable) -> Callable:
    @functools.wraps(function)
    async def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        service = getattr(self, "_society", None)
        if service is None:
            return await function(self, *args, **kwargs)
        parent_id = _agent_context.get()
        agent_id = "delegate:" + uuid.uuid4().hex[:8]
        emit(
            service,
            "update_agent",
            agent_id,
            name=f"Scout {agent_id[-4:]}",
            kind="delegate",
            parent_id=parent_id,
            department="operations",
            status="thinking",
            event="spawned",
        )
        token = _agent_context.set(agent_id)
        try:
            return await function(self, *args, **kwargs)
        finally:
            _agent_context.reset(token)

    return wrapped


def observe_tool(function: Callable) -> Callable:
    @functools.wraps(function)
    async def wrapped(self: Any, tool_call: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        service = getattr(self, "_society", None)
        tool = (tool_call.get("function") or {}).get("name", "")
        token = emit(service, "begin_tool", tool)
        failed = denied = cancelled = False
        try:
            result = await function(self, tool_call, *args, **kwargs)
            denied = bool(getattr(result, "denied", False))
            failed = (
                bool(getattr(result, "error", None))
                or getattr(getattr(result, "result", None), "success", True) is False
            )
            return result
        except asyncio.CancelledError:
            cancelled = True
            raise
        except BaseException:
            failed = True
            raise
        finally:
            if token is not None:
                emit(service, "end_tool", token, failed=failed, denied=denied, cancelled=cancelled)

    return wrapped
