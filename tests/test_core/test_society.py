"""Society contracts: real lifecycle, privacy, isolation and read-only transport."""

from __future__ import annotations

import asyncio
import http.client
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

import pytest

from core.config import Config, SocietyConfig, load_config
from core.executor import Executor
from core.society import (
    MAX_AGENTS,
    MAX_EVENTS,
    SocietyService,
    department_for_tool,
    observe_delegate,
    observe_run,
)
from tools.base import BaseTool, PermissionLevel, ToolResult


@pytest.fixture
def society(tmp_path: Path):
    service = SocietyService(SocietyConfig(enabled=True, open_browser=False, port=0), tmp_path)
    yield service
    service.stop()


def test_config_defaults_and_yaml_roundtrip(tmp_path: Path):
    assert Config().society.enabled is True   # ships on; `enabled: false` turns it off
    config = tmp_path / "config.yaml"
    config.write_text("society:\n  enabled: true\n  port: 19790\n  open_browser: false\n")
    parsed = load_config(config).society
    assert parsed == SocietyConfig(enabled=True, port=19790, open_browser=False)


@pytest.mark.parametrize(
    "values",
    [
        {"host": "0.0.0.0"},
        {"host": "example.com"},
        {"port": -1},
        {"port": 65536},
        {"port": True},
        {"enabled": "true"},
        {"open_browser": "false"},
    ],
)
def test_invalid_config_rejected(values):
    with pytest.raises(ValueError):
        SocietyConfig(**values)


def test_disabled_service_opens_nothing(tmp_path: Path):
    with patch("core.society.ThreadingHTTPServer") as server:
        # SocietyConfig() is enabled now — say what this test is about.
        assert SocietyService(SocietyConfig(enabled=False), tmp_path).start() is False
        server.assert_not_called()


def test_address_conflict_fails_open(society):
    assert society.start()
    duplicate = SocietyService(
        SocietyConfig(enabled=True, open_browser=False, port=urlsplit(society.url).port),
        society.project_root,
    )
    assert duplicate.start() is False
    assert duplicate._server is None


def test_state_is_bounded_and_does_not_leak_mutable_references(society):
    for index in range(300):
        society.update_agent(f"delegate:{index}", name="Test<script>\n" + "x" * 200, status="idle")
    state = society.snapshot()
    assert len(state["agents"]) <= MAX_AGENTS
    assert len(state["events"]) == MAX_EVENTS
    assert any(agent["id"] == "main" for agent in state["agents"])
    assert all(len(agent["name"]) <= 64 and "<" not in agent["name"] for agent in state["agents"])
    state["agents"][0]["status"] = "corrupted"
    assert society.snapshot()["agents"][0]["status"] != "corrupted"


@pytest.mark.parametrize(
    "tool,department",
    [
        ("browser_navigate", "research"),
        ("shell_execute", "engineering"),
        ("email_send", "communications"),
        ("knowledge_search", "knowledge"),
        ("swarm_spawn", "operations"),
        ("llm_call", "headquarters"),
    ],
)
def test_department_mapping(tool, department):
    assert department_for_tool(tool) == department


def _connection(service):
    parsed = urlsplit(service.url)
    return http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)


def test_http_read_only_routes_static_safety_and_origin(society, tmp_path):
    assets = tmp_path / "web" / "dist"
    (assets / "assets").mkdir(parents=True)
    (assets / "index.html").write_text("<title>Society</title>")
    (assets / "assets" / "main.js").write_text("export const ready = true")
    (tmp_path / "secret.txt").write_text("private")
    assert society.start()
    connection = _connection(society)
    for route in ["/society/", "/assets/main.js", "/api/society/state"]:
        connection.request("GET", route)
        response = connection.getresponse()
        data = response.read()
        assert response.status == 200, (route, data)
        assert response.getheader("Access-Control-Allow-Origin") is None
        if route.endswith("state"):
            assert json.loads(data)["agents"][0]["id"] == "main"
    for route in ["/society/%2e%2e/%2e%2e/secret.txt", "/api/execute"]:
        connection.request("GET", route)
        response = connection.getresponse()
        assert response.status == 404
        assert b"private" not in response.read()
    connection.request("GET", "/api/society/state", headers={"Host": "attacker.test"})
    response = connection.getresponse()
    assert response.status == 403
    response.read()
    connection.request("GET", "/api/society/state", headers={"Origin": "https://attacker.test"})
    response = connection.getresponse()
    assert response.status == 403
    response.read()
    connection.request("POST", "/api/society/state", body=b"{}")
    response = connection.getresponse()
    assert response.status == 501
    response.read()
    connection.close()


def _read_event(response):
    lines = []
    while True:
        line = response.readline().decode().strip()
        if not line:
            break
        lines.append(line)
    assert "event: state" in lines
    return json.loads(next(line[6:] for line in lines if line.startswith("data: ")))


def test_live_sse_delivers_initial_then_changed_state(society):
    assert society.start()
    connection = _connection(society)
    connection.request("GET", "/api/society/events")
    response = connection.getresponse()
    assert response.status == 200
    initial = _read_event(response)
    ticket = society.begin_tool("browser_navigate")
    updated = _read_event(response)
    assert updated["sequence"] > initial["sequence"]
    assert updated["agents"][0]["department"] == "research"
    assert updated["agents"][0]["status"] == "working"
    society.end_tool(ticket)
    final = _read_event(response)
    assert final["stats"]["completed"] == 1
    assert final["agents"][0]["status"] == "idle"
    response.close()
    connection.close()


class ObservedTool(BaseTool):
    name = "browser_test"
    description = "Test tool"
    input_schema = {"type": "object", "properties": {"secret": {"type": "string"}}}
    permission_level = PermissionLevel.SAFE

    def __init__(self, success=True):
        self.success = success
        self.started = asyncio.Event()
        self.finish = asyncio.Event()

    async def execute(self, params):
        self.started.set()
        await self.finish.wait()
        return ToolResult(success=self.success, data={"secret": params.get("secret")})


def _executor(society, tool, test_config):
    executor = Executor(test_config, SimpleNamespace(get=lambda name: tool))
    executor._society = society
    return executor


@pytest.mark.asyncio
async def test_real_executor_departure_return_and_payload_privacy(society, test_config):
    tool = ObservedTool()
    executor = _executor(society, tool, test_config)
    pending = asyncio.create_task(
        executor.execute(
            {
                "id": "sensitive-call-id",
                "function": {"name": tool.name, "arguments": '{"secret":"NEVER-EXPOSE-THIS"}'},
            }
        )
    )
    await asyncio.wait_for(tool.started.wait(), timeout=1)
    assert society.snapshot()["agents"][0]["department"] == "research"
    tool.finish.set()
    result = await pending
    assert result.result.data["secret"] == "NEVER-EXPOSE-THIS"
    state = society.snapshot()
    assert state["agents"][0]["status"] == "idle"
    assert "NEVER-EXPOSE-THIS" not in json.dumps(state)
    assert "sensitive-call-id" not in json.dumps(state)
    assert state["stats"]["completed"] == 1


@pytest.mark.asyncio
async def test_tool_failure_and_cancellation_release_activity(society, test_config):
    tool = ObservedTool(success=False)
    tool.finish.set()
    executor = _executor(society, tool, test_config)
    await executor.execute({"function": {"name": tool.name}})
    assert society.snapshot()["agents"][0]["status"] == "error"
    assert society.snapshot()["stats"]["errors"] == 1
    tool.finish.clear()
    task = asyncio.create_task(executor.execute({"function": {"name": tool.name}}))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert society.snapshot()["agents"][0]["status"] == "idle"
    assert society._active_tools == {}


@pytest.mark.asyncio
async def test_approval_wait_is_visible_and_denial_does_not_run_tool(society, test_config):
    tool = ObservedTool()
    test_config.permission_mode = "ask_always"
    tool.permission_level = PermissionLevel.MODERATE
    executor = _executor(society, tool, test_config)

    async def reject(*args):
        assert society.snapshot()["agents"][0]["status"] == "waiting"
        return False

    result = await executor.execute({"function": {"name": tool.name}}, approval_callback=reject)
    assert result.denied
    assert not tool.started.is_set()
    assert society.snapshot()["stats"]["completed"] == 0


@pytest.mark.asyncio
async def test_broken_telemetry_does_not_change_execution(test_config):
    tool = ObservedTool()
    tool.finish.set()
    executor = _executor(
        Mock(
            begin_tool=Mock(side_effect=RuntimeError("viewer broken")),
            working=Mock(side_effect=RuntimeError("viewer broken")),
        ),
        tool,
        test_config,
    )
    result = await executor.execute({"function": {"name": tool.name}})
    assert result.result.success


@pytest.mark.asyncio
async def test_parallel_delegates_have_distinct_actor_context_and_return(society):
    class Worker:
        _society = society

        @observe_delegate
        @observe_run
        async def work(self, tool, gate):
            token = society.begin_tool(tool)
            await gate.wait()
            society.end_tool(token)

    gate = asyncio.Event()
    worker = Worker()
    tasks = [
        asyncio.create_task(worker.work(tool, gate))
        for tool in ["browser_navigate", "shell_execute"]
    ]
    await asyncio.sleep(0)
    state = society.snapshot()
    delegates = [a for a in state["agents"] if a["kind"] == "delegate"]
    assert len(delegates) == 2
    assert {a["department"] for a in delegates} == {"research", "engineering"}
    assert all(a["parent_id"] == "main" for a in delegates)
    assert state["agents"][0]["status"] == "idle"
    gate.set()
    await asyncio.gather(*tasks)
    assert all(a["status"] == "idle" for a in society.snapshot()["agents"])
    assert society._runs == {}


def test_external_worker_lifecycle_omits_task_and_profile_secrets(society):
    swarm = SimpleNamespace(
        agent_id="worker1", status="running", task="secret-task", profile="private-profile"
    )
    kid = SimpleNamespace(kid_id="kid1", status="running", purpose="secret-purpose")
    owner = SimpleNamespace(
        _swarm_manager=SimpleNamespace(_agents={"worker1": swarm}),
        _kid_manager=SimpleNamespace(_kids={"kid1": kid}),
    )
    society.sync_managers(owner)
    state = society.snapshot()
    assert next(a for a in state["agents"] if a["id"] == "swarm:worker1")["status"] == "working"
    assert "secret-task" not in json.dumps(state)
    assert "secret-purpose" not in json.dumps(state)
    assert "private-profile" not in json.dumps(state)
    sequence = state["sequence"]
    society.sync_managers(owner)
    assert society.snapshot()["sequence"] == sequence
    swarm.status = "completed"
    society.sync_managers(owner)
    assert (
        next(a for a in society.snapshot()["agents"] if a["id"] == "swarm:worker1")["status"]
        == "idle"
    )
    society.worker_event("kid", "kid1", "assigned")
    society.sync_managers(owner)
    assert (
        next(a for a in society.snapshot()["agents"] if a["id"] == "kid:kid1")["status"]
        == "working"
    )
    society.worker_event("kid", "kid1", "completed")
    assert (
        next(a for a in society.snapshot()["agents"] if a["id"] == "kid:kid1")["status"] == "idle"
    )


@pytest.mark.asyncio
async def test_agent_owns_service_start_and_shutdown_without_provider_calls(test_config):
    from core.agent import Agent

    test_config.society = SocietyConfig(enabled=True, open_browser=False, port=0)
    agent = Agent(test_config)
    # Stop before tool/provider initialization: exercise the real early startup
    # and shutdown paths without making external calls or starting a browser.
    with patch.object(
        agent._registry, "load_builtin_tools", side_effect=RuntimeError("test checkpoint")
    ):
        with pytest.raises(RuntimeError, match="test checkpoint"):
            await agent.initialize()
    service = agent._society
    assert service is not None
    assert agent._executor._society is service
    connection = _connection(service)
    connection.request("GET", "/api/society/state")
    response = connection.getresponse()
    assert response.status == 200
    response.read()
    connection.close()
    await agent.shutdown()
    assert service._server is None
    assert service._thread is None
    assert agent._society is None
    assert agent._society_sync_task is None
    assert agent._executor._society is None


def test_overlapping_tools_keep_actor_at_remaining_job(society):
    research = society.begin_tool("browser_navigate")
    engineering = society.begin_tool("shell_execute")
    society.end_tool(engineering)
    assert society.snapshot()["agents"][0]["department"] == "research"
    assert society.snapshot()["agents"][0]["status"] == "working"
    society.end_tool(research)
    assert society.snapshot()["agents"][0]["status"] == "idle"


def test_kid_assignment_before_presence_poll_stays_working(society):
    kid = SimpleNamespace(kid_id="newkid", status="running")
    owner = SimpleNamespace(_kid_manager=SimpleNamespace(_kids={"newkid": kid}))
    society.worker_event("kid", "newkid", "assigned")
    society.sync_managers(owner)
    actor = next(a for a in society.snapshot()["agents"] if a["id"] == "kid:newkid")
    assert actor["status"] == "working"
    assert actor["name"] == "Kid newkid"
