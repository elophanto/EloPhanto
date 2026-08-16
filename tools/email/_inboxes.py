"""Which AgentMail inboxes the agent can read.

The vault holds ONE inbox id (``agentmail_inbox_id``) — the agent's own
address for sending. But an AgentMail account carries every inbox ever
created on it, and mail addressed to any of them is the agent's mail.
On 2026-08-16 an X login code went to lonelydegree799@agentmail.to while
the tools read only elophanto@elophanto.com; ``email_search`` answered
"success, 0 results" and the model went hunting for console logins. A
read tool must see the whole account.
"""

from __future__ import annotations

from typing import Any


def account_inbox_ids(client: Any, default: str | None = None) -> list[str]:
    """Every inbox id on the account, the vault default first. Falls back
    to ``[default]`` when the account listing is unavailable."""
    ids: list[str] = []
    try:
        response = client.inboxes.list()
        raw = getattr(response, "inboxes", None) or response
        for inbox in raw if isinstance(raw, list) else list(raw or []):
            inbox_id = getattr(inbox, "inbox_id", None) or getattr(inbox, "id", None)
            if inbox_id:
                ids.append(str(inbox_id))
    except Exception:
        ids = []
    if default:
        ids = [default] + [i for i in ids if i != default]
    return ids or ([default] if default else [])


def resolve_inbox(requested: str | None, client: Any, default: str | None) -> list[str]:
    """Inboxes to read for a call: the one asked for (by address or id,
    case-insensitive), else every inbox on the account."""
    ids = account_inbox_ids(client, default)
    if requested:
        want = requested.strip().lower()
        hit = [i for i in ids if i.lower() == want or i.lower().startswith(want + "@")]
        return hit or [requested.strip()]
    return ids


def list_messages(client: Any, inbox_id: str) -> list[Any]:
    """Messages of one inbox as a plain list (SDK returns page objects)."""
    try:
        response = client.inboxes.messages.list(inbox_id=inbox_id)
    except Exception:
        return []
    raw = getattr(response, "messages", None) or response
    if isinstance(raw, list):
        return raw
    try:
        return list(raw or [])
    except Exception:
        return []
