"""The email read tools see the whole AgentMail account, not one inbox.

2026-08-16: an X login code went to lonelydegree799@agentmail.to; the tools
read only the vault's `agentmail_inbox_id` (elophanto@elophanto.com), so
email_search answered "success, 0 results" and the model went hunting for
console logins. Mail to any inbox on the account is the agent's mail.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest


class _Msg(SimpleNamespace):
    pass


class _FakeClient:
    """Mimics the AgentMail SDK surface the tools use."""

    def __init__(self) -> None:
        self._inboxes = ["elophanto@elophanto.com", "lonelydegree799@agentmail.to"]
        self._mail = {
            "elophanto@elophanto.com": [
                _Msg(message_id="m1", from_="Twitch <a@twitch.tv>", subject="Twitch code",
                     text="291112", received_at="2026-05-19T10:07:48Z"),
            ],
            "lonelydegree799@agentmail.to": [
                _Msg(message_id="m2", from_="X <info@x.com>", subject="Your X confirmation code is 264464",
                     text="264464", received_at="2026-08-16T12:46:49Z"),
            ],
        }
        client = self

        class _Messages:
            def list(self, inbox_id):
                return SimpleNamespace(messages=client._mail.get(inbox_id, []))

            def get(self, inbox_id, message_id):
                for m in client._mail.get(inbox_id, []):
                    if m.message_id == message_id:
                        return m
                raise RuntimeError("not found")

        class _Inboxes:
            messages = _Messages()

            def list(self):
                return SimpleNamespace(
                    inboxes=[SimpleNamespace(inbox_id=i) for i in client._inboxes]
                )

        self.inboxes = _Inboxes()


@pytest.fixture
def agentmail_stub(monkeypatch):
    mod = types.ModuleType("agentmail")
    holder = {}

    class AgentMail:  # noqa: N801 — SDK name
        def __init__(self, api_key):
            holder["client"] = _FakeClient()
            self.inboxes = holder["client"].inboxes

    mod.AgentMail = AgentMail
    monkeypatch.setitem(sys.modules, "agentmail", mod)
    return holder


def _tool(cls):
    t = cls()
    t._vault = {"agentmail_api_key": "k", "agentmail_inbox_id": "elophanto@elophanto.com"}
    t._config = SimpleNamespace(provider="agentmail", api_key_ref="agentmail_api_key")
    return t


@pytest.mark.asyncio
async def test_search_spans_every_inbox_on_the_account(agentmail_stub) -> None:
    from tools.email.search_tool import EmailSearchTool

    r = await _tool(EmailSearchTool).execute({"query": "X confirmation code"})
    assert r.success and r.data["inboxes_searched"] == [
        "elophanto@elophanto.com", "lonelydegree799@agentmail.to"
    ]
    top = r.data["results"][0]
    assert top["inbox"] == "lonelydegree799@agentmail.to" and "264464" in top["subject"]


@pytest.mark.asyncio
async def test_list_merges_inboxes_newest_first_and_can_pin_one(agentmail_stub) -> None:
    from tools.email.list_tool import EmailListTool

    r = await _tool(EmailListTool).execute({"limit": 10})
    assert r.success and [m["inbox"] for m in r.data["messages"]] == [
        "lonelydegree799@agentmail.to", "elophanto@elophanto.com"
    ]
    one = await _tool(EmailListTool).execute({"inbox": "lonelydegree799"})
    assert one.data["inboxes"] == ["lonelydegree799@agentmail.to"]
    assert [m["message_id"] for m in one.data["messages"]] == ["m2"]


@pytest.mark.asyncio
async def test_read_finds_the_message_in_whichever_inbox_holds_it(agentmail_stub) -> None:
    from tools.email.read_tool import EmailReadTool

    r = await _tool(EmailReadTool).execute({"message_id": "m2"})
    assert r.success and r.data["inbox"] == "lonelydegree799@agentmail.to"
    assert "264464" in (r.data.get("body") or r.data.get("text") or "")
