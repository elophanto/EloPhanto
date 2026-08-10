"""Outbound network policy — SSRF classification and host allow/deny.

An agent that can make authenticated HTTP requests on your behalf can also
be talked into making them against your own infrastructure: the cloud
metadata endpoint, a loopback admin port, a printer on the LAN. Prompt
injection in a fetched page is enough to try it. This module is the check
that stands between a model-chosen URL and the socket.

Two independent gates:

* :func:`classify_host` — is this address in a range that a request from an
  agent has no business reaching? Loopback, private RFC1918, link-local
  (including the ``169.254.169.254`` metadata address), CGNAT, multicast,
  and the IPv6 equivalents, plus NAT64/6to4-embedded IPv4 so an attacker
  cannot smuggle ``127.0.0.1`` through ``::ffff:127.0.0.1``.
* :func:`check_url` — scheme, port, and operator allow/deny lists.

DNS resolution is part of the check on purpose: a hostname that resolves
into a blocked range is blocked, which closes the DNS-rebinding-shaped hole
where ``evil.example`` points at ``127.0.0.1``.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Hostnames that are never legitimate targets for an agent request.
BLOCKED_HOSTNAMES: frozenset[str] = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
        "instance-data.ec2.internal",
    }
)

# Schemes we will speak. Everything else (file:, gopher:, ftp:, data:) is
# either not HTTP or a known SSRF amplifier.
ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Ports commonly fronting internal services. Blocked unless the operator
# explicitly allows the host.
_SUSPICIOUS_PORTS: frozenset[int] = frozenset(
    {22, 23, 25, 445, 465, 587, 993, 995, 2375, 2376, 3306, 5432, 6379, 9200, 11211}
)


class NetPolicyError(Exception):
    """Raised when a request is refused by network policy."""


@dataclass
class NetPolicy:
    """Operator-controlled outbound policy."""

    # Exact hostnames (or fnmatch globs) that bypass the private-range
    # block. This is the break-glass for "my agent must reach my NAS".
    allow_hosts: list[str] = field(default_factory=list)
    # Hostnames that are always refused, checked before everything else.
    deny_hosts: list[str] = field(default_factory=list)
    # When true, only hosts in allow_hosts may be reached at all.
    allowlist_only: bool = False
    # Break-glass for private/loopback targets generally.
    allow_private_network: bool = False
    max_redirects: int = 5
    timeout_seconds: float = 30.0

    def matches_allow(self, host: str) -> bool:
        return _host_matches(host, self.allow_hosts)

    def matches_deny(self, host: str) -> bool:
        return _host_matches(host, self.deny_hosts)


def _host_matches(host: str, patterns: list[str]) -> bool:
    import fnmatch

    h = (host or "").lower()
    for pattern in patterns:
        p = (pattern or "").lower().strip()
        if not p:
            continue
        if fnmatch.fnmatch(h, p):
            return True
        if not p.startswith("*") and h.endswith("." + p):
            return True
    return False


def _unwrap_embedded_ipv4(addr: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """Extract an IPv4 address embedded in an IPv6 one, if present.

    Covers IPv4-mapped (``::ffff:a.b.c.d``), 6to4 (``2002:``) and the
    NAT64 well-known prefix (``64:ff9b::/96``). Without this, the private
    range checks below can be bypassed by re-encoding the address.
    """
    if addr.ipv4_mapped:
        return addr.ipv4_mapped
    if addr.sixtofour:
        return addr.sixtofour
    packed = addr.packed
    if packed[:4] == b"\x00\x64\xff\x9b":
        return ipaddress.IPv4Address(packed[12:16])
    return None


def is_blocked_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> tuple[bool, str]:
    """Whether *ip* is in a range an agent request must not reach."""
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = _unwrap_embedded_ipv4(ip)
        if embedded is not None:
            blocked, why = is_blocked_ip(embedded)
            if blocked:
                return True, f"IPv6-embedded IPv4 {embedded} ({why})"

    if ip.is_loopback:
        return True, "loopback address"
    # Link-local before private: Python counts link-local as private, and
    # 169.254.169.254 is the cloud metadata endpoint — the operator
    # reading this error deserves the specific name, not the generic one.
    if ip.is_link_local:
        return True, "link-local address (includes cloud metadata)"
    if ip.is_private:
        return True, "private (RFC1918 / ULA) address"
    if ip.is_multicast:
        return True, "multicast address"
    if ip.is_reserved:
        return True, "reserved address"
    if ip.is_unspecified:
        return True, "unspecified address"

    if isinstance(ip, ipaddress.IPv4Address):
        # Carrier-grade NAT — not covered by is_private.
        if ip in ipaddress.ip_network("100.64.0.0/10"):
            return True, "CGNAT address"
        # Documentation / benchmark ranges.
        for net in (
            "192.0.2.0/24",
            "198.51.100.0/24",
            "203.0.113.0/24",
            "198.18.0.0/15",
        ):
            if ip in ipaddress.ip_network(net):
                return True, f"reserved documentation range {net}"

    return False, ""


def classify_host(host: str) -> tuple[bool, str]:
    """Resolve *host* and report whether any of its addresses are blocked.

    Returns ``(blocked, reason)``. A host that fails to resolve is not
    blocked here — the connection will fail on its own, and treating DNS
    failure as a policy violation produces confusing errors.
    """
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return True, "empty hostname"
    if h in BLOCKED_HOSTNAMES:
        return True, f"blocked hostname {h!r}"

    # Literal IP in the URL — check directly, no DNS needed.
    literal = h.strip("[]")
    try:
        ip = ipaddress.ip_address(literal)
    except ValueError:
        pass
    else:
        return is_blocked_ip(ip)

    try:
        infos = socket.getaddrinfo(h, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False, ""
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("getaddrinfo(%s) failed: %s", h, exc)
        return False, ""

    for info in infos:
        sockaddr = info[4]
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        blocked, why = is_blocked_ip(ip)
        if blocked:
            return True, f"{h} resolves to {ip} ({why})"
    return False, ""


def check_url(url: str, policy: NetPolicy | None = None) -> str:
    """Validate *url* against policy. Returns the normalized URL.

    Raises :class:`NetPolicyError` with an operator-readable explanation
    when the request must not be made.
    """
    pol = policy or NetPolicy()
    parsed = urlparse((url or "").strip())

    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise NetPolicyError(
            f"Refused: scheme {scheme or '(none)'!r} is not allowed. "
            "Only http and https requests are permitted."
        )

    host = (parsed.hostname or "").lower()
    if not host:
        raise NetPolicyError(f"Refused: no hostname in URL {url!r}")

    if pol.matches_deny(host):
        raise NetPolicyError(f"Refused: {host} is on the deny list.")

    if pol.allowlist_only and not pol.matches_allow(host):
        raise NetPolicyError(
            f"Refused: {host} is not on the allow list and "
            "network policy is allowlist-only."
        )

    explicitly_allowed = pol.matches_allow(host)

    port = parsed.port
    if port is not None and port in _SUSPICIOUS_PORTS and not explicitly_allowed:
        raise NetPolicyError(
            f"Refused: port {port} on {host} commonly fronts an internal "
            "service. Add the host to credentials/network allow_hosts if this "
            "is intentional."
        )

    if not explicitly_allowed and not pol.allow_private_network:
        blocked, why = classify_host(host)
        if blocked:
            raise NetPolicyError(
                f"Refused: {why}. Agent requests to internal, loopback, or "
                "metadata addresses are blocked to prevent a fetched page or "
                "injected instruction from turning the agent against your own "
                "network. Add the host to allow_hosts if this is intentional."
            )

    return parsed.geturl()


def policy_from_config(config: Any) -> NetPolicy:
    """Build a :class:`NetPolicy` from the ``network:`` config section."""
    section = getattr(config, "network", None)
    if section is None:
        return NetPolicy()
    return NetPolicy(
        allow_hosts=list(getattr(section, "allow_hosts", None) or []),
        deny_hosts=list(getattr(section, "deny_hosts", None) or []),
        allowlist_only=bool(getattr(section, "allowlist_only", False)),
        allow_private_network=bool(getattr(section, "allow_private_network", False)),
        max_redirects=int(getattr(section, "max_redirects", 5) or 5),
        timeout_seconds=float(getattr(section, "timeout_seconds", 30.0) or 30.0),
    )
