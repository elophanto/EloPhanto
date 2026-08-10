"""Node registry — companion devices as agent peripherals.

A *node* is a device that connects to the gateway to lend the agent senses
and hands it does not otherwise have: a phone's camera and location, a
laptop's screen, a speaker's microphone. It is not a chat channel. Nodes
do not carry conversations — they answer capability invocations.

The split matters architecturally: the model stays on the gateway, where
the tools, memory, and approval gates live. A node ships a small command
surface and nothing else, so adding a platform means implementing a
handful of handlers, not porting an agent.

Trust is deliberately conservative in two places:

* **Registration is not authorization.** A node advertises what it *can*
  do; whether the agent may actually invoke a given capability is decided
  here, against an operator allowlist. A device that claims a
  ``shell.run`` capability does not thereby get one.
* **Dangerous capabilities are opt-in per node.** Camera, screen capture,
  microphone, and SMS are gated behind explicit configuration, because a
  compromised or careless node otherwise turns the agent into a
  surveillance tool pointed at its own operator.

Invocation is request/response over the existing WebSocket, correlated by
``request_id`` with a timeout — a node that goes to sleep mid-request must
not wedge the agent loop.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Capabilities that can observe the operator or spend on their behalf.
# Never invokable unless the operator lists them for that node.
SENSITIVE_CAPABILITIES: frozenset[str] = frozenset(
    {
        "camera.snap",
        "camera.clip",
        "screen.snapshot",
        "screen.record",
        "mic.record",
        "sms.send",
        "contacts.search",
        "location.get",
        "shell.run",
        "computer.act",
    }
)

_DEFAULT_TIMEOUT = 60.0


@dataclass
class NodeCapability:
    """One thing a node can be asked to do."""

    name: str
    description: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def is_sensitive(self) -> bool:
        return self.name in SENSITIVE_CAPABILITIES


@dataclass
class Node:
    """A connected companion device."""

    node_id: str
    name: str
    platform: str
    capabilities: dict[str, NodeCapability] = field(default_factory=dict)
    connection: Any = None  # the ClientConnection that registered it
    registered_at: str = ""
    last_seen: str = ""

    def describe(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "platform": self.platform,
            "capabilities": sorted(self.capabilities),
            "registered_at": self.registered_at,
        }


class NodeError(Exception):
    """Raised when a node invocation cannot proceed."""


class NodeRegistry:
    """Tracks connected nodes and routes capability invocations to them."""

    def __init__(self, allowed: dict[str, list[str]] | None = None) -> None:
        # node_id (or "*") → capability names the operator has permitted.
        self._allowed = allowed or {}
        self._nodes: dict[str, Node] = {}
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}

    # ── registration ────────────────────────────────────────────────

    def register(
        self,
        node_id: str,
        name: str,
        platform: str,
        capabilities: list[dict[str, Any]],
        connection: Any = None,
    ) -> Node:
        """Record a node and the capabilities it advertises."""
        now = datetime.now(UTC).isoformat()
        caps = {
            str(c.get("name", "")): NodeCapability(
                name=str(c.get("name", "")),
                description=str(c.get("description", "")),
                params=dict(c.get("params") or {}),
            )
            for c in capabilities
            if c.get("name")
        }
        node = Node(
            node_id=node_id,
            name=name or node_id,
            platform=platform,
            capabilities=caps,
            connection=connection,
            registered_at=now,
            last_seen=now,
        )
        self._nodes[node_id] = node

        gated = [c for c in caps if c in SENSITIVE_CAPABILITIES]
        permitted = set(self.permitted_capabilities(node_id))
        blocked = [c for c in gated if c not in permitted]
        logger.info(
            "Node registered: %s (%s, %s) with %d capabilities%s",
            name,
            node_id[:8],
            platform,
            len(caps),
            f"; {len(blocked)} sensitive not permitted: {blocked}" if blocked else "",
        )
        return node

    def unregister(self, node_id: str) -> bool:
        return self._nodes.pop(node_id, None) is not None

    def unregister_connection(self, connection: Any) -> list[str]:
        """Drop every node behind a dropped connection. Returns their ids."""
        gone = [
            node_id
            for node_id, node in self._nodes.items()
            if node.connection is connection
        ]
        for node_id in gone:
            self._nodes.pop(node_id, None)
        if gone:
            logger.info("Nodes disconnected: %s", gone)
        return gone

    # ── queries ─────────────────────────────────────────────────────

    def get(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def list_nodes(self) -> list[dict[str, Any]]:
        return [n.describe() for n in self._nodes.values()]

    def permitted_capabilities(self, node_id: str) -> list[str]:
        """Capabilities the operator has allowed for this node.

        A capability must be permitted *and* advertised to be invokable.
        Non-sensitive capabilities are allowed by default; sensitive ones
        require an explicit listing under this node id or ``"*"``.
        """
        node = self._nodes.get(node_id)
        if node is None:
            return []
        explicit = set(self._allowed.get(node_id, [])) | set(self._allowed.get("*", []))
        out: list[str] = []
        for name, cap in node.capabilities.items():
            if cap.is_sensitive:
                if name in explicit or "*" in explicit:
                    out.append(name)
            else:
                out.append(name)
        return sorted(out)

    def find_node_for(self, capability: str) -> Node | None:
        """First connected node that both offers and may run *capability*."""
        for node in self._nodes.values():
            if capability in self.permitted_capabilities(node.node_id):
                return node
        return None

    # ── invocation ──────────────────────────────────────────────────

    async def invoke(
        self,
        capability: str,
        params: dict[str, Any] | None = None,
        node_id: str = "",
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        """Run *capability* on a node and await its result.

        Raises :class:`NodeError` when no eligible node is connected, when
        the capability is not permitted, or when the node does not answer
        in time.
        """
        node = self._nodes.get(node_id) if node_id else self.find_node_for(capability)
        if node is None:
            if node_id:
                raise NodeError(f"Node {node_id!r} is not connected.")
            connected = [n.name for n in self._nodes.values()]
            raise NodeError(
                f"No connected node offers {capability!r}. "
                + (
                    f"Connected nodes: {', '.join(connected)}."
                    if connected
                    else "No nodes are connected."
                )
            )

        if capability not in node.capabilities:
            raise NodeError(
                f"Node {node.name!r} does not offer {capability!r}. "
                f"It offers: {', '.join(sorted(node.capabilities)) or '(none)'}."
            )
        if capability not in self.permitted_capabilities(node.node_id):
            raise NodeError(
                f"{capability!r} is a sensitive capability and is not enabled "
                f"for node {node.name!r}. Add it under "
                f"`nodes.allowed_capabilities` in config.yaml to permit it."
            )
        if node.connection is None:
            raise NodeError(f"Node {node.name!r} has no live connection.")

        from core.protocol import node_invoke_message

        request_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future

        try:
            await node.connection.send(
                node_invoke_message(
                    node_id=node.node_id,
                    capability=capability,
                    params=params or {},
                    request_id=request_id,
                ).to_json()
            )
        except Exception as exc:
            self._pending.pop(request_id, None)
            raise NodeError(f"Could not reach node {node.name!r}: {exc}") from exc

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as exc:
            raise NodeError(
                f"Node {node.name!r} did not answer {capability!r} within "
                f"{timeout:.0f}s. It may be asleep or offline."
            ) from exc
        finally:
            self._pending.pop(request_id, None)
            node.last_seen = datetime.now(UTC).isoformat()

    def resolve_result(self, request_id: str, payload: dict[str, Any]) -> bool:
        """Deliver a NODE_RESULT to whoever is awaiting it."""
        future = self._pending.get(request_id)
        if future is None or future.done():
            return False
        future.set_result(payload)
        return True


def registry_from_config(config: Any) -> NodeRegistry:
    """Build a registry from the ``nodes:`` config section."""
    section = getattr(config, "nodes", None)
    allowed = dict(getattr(section, "allowed_capabilities", None) or {})
    return NodeRegistry(allowed=allowed)
