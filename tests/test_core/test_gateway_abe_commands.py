"""Tests for the ABE / goals / affect read commands the web dashboard uses.

These exercise the gateway's `_send_*` / `_build_company_rows` helpers
with fake managers wired onto the agent, asserting the JSON payload
shape the web frontend consumes. We capture what the helper sends by
stubbing the client's websocket.send.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.gateway import Gateway
from core.session import SessionManager


def _gateway_with_agent(agent: object) -> Gateway:
    return Gateway(
        agent=agent,
        session_manager=SessionManager(MagicMock()),
        host="127.0.0.1",
        port=18799,
        max_sessions=10,
    )


def _capture_client() -> tuple[MagicMock, list[dict]]:
    """A fake client whose websocket.send records the decoded payloads."""
    sent: list[dict] = []
    ws = MagicMock()

    async def _send(raw: str) -> None:
        msg = json.loads(raw)
        # response_message wraps payload JSON in data.content
        content = msg.get("data", {}).get("content")
        if content:
            sent.append(json.loads(content))

    ws.send = AsyncMock(side_effect=_send)
    return MagicMock(websocket=ws), sent


# ── Companies ───────────────────────────────────────────────────────


class _FakeCompany:
    def __init__(self, cid: str, name: str, trust: str = "operating") -> None:
        self.id = cid
        self.name = name
        self.status = "active"
        self.product_yaml = "what_we_sell: x"
        self.trust_state = trust


class _FakeCompanyMgr:
    def __init__(self, companies: list[_FakeCompany]) -> None:
        self._c = companies

    async def list(self) -> list[_FakeCompany]:
        return list(self._c)

    async def get(self, cid: str) -> _FakeCompany | None:
        return next((c for c in self._c if c.id == cid), None)


@pytest.mark.asyncio
async def test_companies_payload_shape() -> None:
    agent = SimpleNamespace(
        _company_manager=_FakeCompanyMgr([_FakeCompany("co-a", "Acme")]),
        _voice_manager=None,
        _strategy_manager=None,
        _db=None,
        _config=None,
    )
    gw = _gateway_with_agent(agent)
    client, sent = _capture_client()
    await gw._send_companies(client, "sess")

    assert len(sent) == 1
    rows = sent[0]["companies"]
    assert rows[0]["slug"] == "co-a"
    assert rows[0]["name"] == "Acme"
    assert rows[0]["trust"] == "operating"
    assert rows[0]["has_product"] is True
    # No managers wired → voice/strategy default to "none"
    assert rows[0]["voice"] == "none"
    assert rows[0]["strategy"] == "none"


@pytest.mark.asyncio
async def test_company_detail_not_found() -> None:
    agent = SimpleNamespace(
        _company_manager=_FakeCompanyMgr([]),
        _voice_manager=None,
        _strategy_manager=None,
        _db=None,
        _config=None,
    )
    gw = _gateway_with_agent(agent)
    client, sent = _capture_client()
    await gw._send_company_detail(client, "sess", "missing")
    assert sent[0]["company_detail"] is None


# ── Roles ───────────────────────────────────────────────────────────


class _FakeRole:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"{name} role"
        self.allowed_tool_groups = ["social", "email"]
        self.kpi = {"pipeline_advance": 10}
        self.last_active_at = None


class _FakeRoleMgr:
    async def list_roles(self) -> list[_FakeRole]:
        return [_FakeRole("sales"), _FakeRole("support")]


@pytest.mark.asyncio
async def test_roles_payload_shape() -> None:
    agent = SimpleNamespace(_role_manager=_FakeRoleMgr())
    gw = _gateway_with_agent(agent)
    client, sent = _capture_client()
    await gw._send_roles(client, "sess")
    roles = sent[0]["roles"]
    assert {r["name"] for r in roles} == {"sales", "support"}
    assert roles[0]["allowed_tool_groups"] == ["social", "email"]
    assert roles[0]["kpi"] == {"pipeline_advance": 10}


@pytest.mark.asyncio
async def test_roles_no_manager_empty() -> None:
    agent = SimpleNamespace(_role_manager=None)
    gw = _gateway_with_agent(agent)
    client, sent = _capture_client()
    await gw._send_roles(client, "sess")
    assert sent[0]["roles"] == []


# ── Goals ───────────────────────────────────────────────────────────


class _FakeGoal:
    def __init__(self, gid: str, status: str = "active") -> None:
        self.goal_id = gid
        self.goal = f"do {gid}"
        self.status = status
        self.current_checkpoint = 1
        self.total_checkpoints = 3
        self.llm_calls_used = 5
        self.cost_usd = 0.1234
        self.mission_id = None
        self.assigned_to_role = "sales"
        self.context_summary = "summary"
        self.created_at = "2026-05-28T00:00:00+00:00"
        self.updated_at = "2026-05-28T00:01:00+00:00"


class _FakeCheckpoint:
    def __init__(self, order: int) -> None:
        self.order = order
        self.title = f"step {order}"
        self.status = "pending"
        self.success_criteria = "done"


class _FakeGoalMgr:
    async def list_goals(self, status=None, limit=30):
        goals = [_FakeGoal("g1"), _FakeGoal("g2", status="completed")]
        if status:
            goals = [g for g in goals if g.status == status]
        return goals[:limit]

    async def get_goal(self, gid: str):
        return _FakeGoal(gid) if gid == "g1" else None

    async def get_checkpoints(self, gid: str):
        return [_FakeCheckpoint(1), _FakeCheckpoint(2)]


@pytest.mark.asyncio
async def test_goals_payload_shape() -> None:
    agent = SimpleNamespace(_goal_manager=_FakeGoalMgr())
    gw = _gateway_with_agent(agent)
    client, sent = _capture_client()
    await gw._send_goals(client, "sess", status=None, limit=30)
    goals = sent[0]["goals"]
    assert len(goals) == 2
    assert goals[0]["goal_id"] == "g1"
    assert goals[0]["cost_usd"] == 0.1234
    assert goals[0]["role"] == "sales"


@pytest.mark.asyncio
async def test_goals_status_filter() -> None:
    agent = SimpleNamespace(_goal_manager=_FakeGoalMgr())
    gw = _gateway_with_agent(agent)
    client, sent = _capture_client()
    await gw._send_goals(client, "sess", status="completed", limit=30)
    goals = sent[0]["goals"]
    assert len(goals) == 1 and goals[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_goal_detail_with_checkpoints() -> None:
    agent = SimpleNamespace(_goal_manager=_FakeGoalMgr())
    gw = _gateway_with_agent(agent)
    client, sent = _capture_client()
    await gw._send_goal_detail(client, "sess", "g1")
    d = sent[0]["goal_detail"]
    assert d["goal_id"] == "g1"
    assert len(d["checkpoints"]) == 2
    assert d["checkpoints"][0]["title"] == "step 1"


@pytest.mark.asyncio
async def test_goal_detail_missing() -> None:
    agent = SimpleNamespace(_goal_manager=_FakeGoalMgr())
    gw = _gateway_with_agent(agent)
    client, sent = _capture_client()
    await gw._send_goal_detail(client, "sess", "nope")
    assert sent[0]["goal_detail"] is None


# ── Affect ──────────────────────────────────────────────────────────


class _FakeAffectState:
    pleasure = 0.42
    arousal = -0.1
    dominance = 0.3
    updated_at = "2026-05-28T00:00:00+00:00"
    recent_events = [{"label": "pride", "source": "goal", "at": "t"}]


class _FakeAffectMgr:
    async def get_state(self):
        return _FakeAffectState()

    async def current_mood(self):
        return {
            "dominant_label": "pride",
            "description": "feeling good",
            "magnitude": 0.5,
        }


@pytest.mark.asyncio
async def test_affect_payload_shape() -> None:
    agent = SimpleNamespace(_affect_manager=_FakeAffectMgr())
    gw = _gateway_with_agent(agent)
    client, sent = _capture_client()
    await gw._send_affect(client, "sess")
    a = sent[0]["affect"]
    assert a["label"] == "pride"
    assert a["pleasure"] == 0.42
    assert a["recent_events"][0]["label"] == "pride"


@pytest.mark.asyncio
async def test_affect_no_manager_null() -> None:
    agent = SimpleNamespace(_affect_manager=None)
    gw = _gateway_with_agent(agent)
    client, sent = _capture_client()
    await gw._send_affect(client, "sess")
    assert sent[0]["affect"] is None


# ── Schedule mutations (delete / enable / disable) ──────────────────


class _FakeSchedEntry:
    def __init__(self, sid: str, enabled: bool = True) -> None:
        self.id = sid
        self.name = f"sched {sid}"
        self.description = ""
        self.cron_expression = "*/30 * * * *"
        self.task_goal = "do work"
        self.enabled = enabled
        self.last_run_at = None
        self.next_run_at = None
        self.last_status = "never_run"
        self.created_at = "2026-05-28T00:00:00+00:00"


class _FakeScheduler:
    def __init__(self) -> None:
        self.entries = {"s1": _FakeSchedEntry("s1"), "s2": _FakeSchedEntry("s2")}
        self.calls: list[tuple[str, str]] = []

    async def list_schedules(self) -> list[_FakeSchedEntry]:
        return list(self.entries.values())

    async def delete_schedule(self, sid: str) -> bool:
        self.calls.append(("delete", sid))
        return self.entries.pop(sid, None) is not None

    async def enable_schedule(self, sid: str) -> None:
        self.calls.append(("enable", sid))
        if sid in self.entries:
            self.entries[sid].enabled = True

    async def disable_schedule(self, sid: str) -> None:
        self.calls.append(("disable", sid))
        if sid in self.entries:
            self.entries[sid].enabled = False


@pytest.mark.asyncio
async def test_schedule_delete_removes_and_returns_list() -> None:
    sched = _FakeScheduler()
    gw = _gateway_with_agent(SimpleNamespace(_scheduler=sched))
    client, sent = _capture_client()
    await gw._mutate_schedule(client, "sess", "delete", "s1")
    assert ("delete", "s1") in sched.calls
    ids = [s["id"] for s in sent[0]["schedules"]]
    assert ids == ["s2"]  # s1 gone, list refreshed


@pytest.mark.asyncio
async def test_schedule_disable_then_enable() -> None:
    sched = _FakeScheduler()
    gw = _gateway_with_agent(SimpleNamespace(_scheduler=sched))
    client, sent = _capture_client()
    await gw._mutate_schedule(client, "sess", "disable", "s1")
    assert sched.entries["s1"].enabled is False
    row = next(s for s in sent[0]["schedules"] if s["id"] == "s1")
    assert row["enabled"] is False

    await gw._mutate_schedule(client, "sess", "enable", "s1")
    assert sched.entries["s1"].enabled is True


@pytest.mark.asyncio
async def test_schedule_mutate_no_scheduler_safe() -> None:
    gw = _gateway_with_agent(SimpleNamespace(_scheduler=None))
    client, sent = _capture_client()
    await gw._mutate_schedule(client, "sess", "delete", "s1")
    assert sent[0]["schedules"] == []


@pytest.mark.asyncio
async def test_build_schedules_shape() -> None:
    sched = _FakeScheduler()
    gw = _gateway_with_agent(SimpleNamespace(_scheduler=sched))
    rows = await gw._build_schedules()
    assert {r["id"] for r in rows} == {"s1", "s2"}
    assert rows[0]["cron_expression"] == "*/30 * * * *"


def test_schedule_mutations_are_owner_only() -> None:
    assert "schedule_delete" in Gateway._OWNER_ONLY_COMMANDS
    assert "schedule_toggle" in Gateway._OWNER_ONLY_COMMANDS
