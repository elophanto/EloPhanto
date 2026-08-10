"""Self-owned-scope guard — "is this my system to change?"

Every capable agent eventually gains the same three powers: authenticated
HTTP, stored credentials, and a browser logged in as you. Those powers do
not distinguish *your* account from someone else's — an API call that
cancels your gym booking and one that deletes a stranger's membership are
the same shape of request. The usual permission model can't tell them
apart either: it asks "is this caller authorized to drive the agent?", not
"is this target the operator's to modify?".

This module adds the missing axis. It classifies the *target* of an action:

    OWNED       — the operator declared this host/account as theirs.
    THIRD_PARTY — declared as someone else's, or matched a foreign-account
                  pattern (another user's id in the path, an admin route).
    UNKNOWN     — never seen; treated as not-yours for write purposes.

and crosses it with how reversible the action is:

    READ        — GET/HEAD/OPTIONS, list, search.
    WRITE       — create/update on a normal resource.
    DESTRUCTIVE — delete, purge, revoke, ban, transfer, deactivate.

The rule that matters, and the reason this file exists: **a destructive
action against a target that is not the operator's own is refused**, not
merely prompted, unless the operator has recorded an explicit written
authorization for that target. A prompt is the wrong control here —
approval fatigue makes "yes" the default answer, and the blast radius is
someone else's data.

Declaring scope (``data/owned_scope.yaml``)::

    owned:
      - api.mygym.example        # my account on this service
      - "*.mycompany.com"
    third_party:
      - api.competitor.example
    authorizations:
      - target: staging.client.example
        scope: "GET,POST,DELETE /api/test-fixtures/*"
        authorized_by: "Jane Doe, CTO — contract #4417"
        expires: "2026-12-31"

Authorizations are how legitimate authorized testing stays possible: the
operator records who authorized it and what the agreed scope is, and the
guard honours exactly that and nothing more.
"""

from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_SCOPE_FILE = "owned_scope.yaml"


class TargetScope(StrEnum):
    OWNED = "owned"
    THIRD_PARTY = "third_party"
    UNKNOWN = "unknown"


class ActionKind(StrEnum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


# HTTP methods that change state.
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH"})
_DESTRUCTIVE_METHODS = frozenset({"DELETE"})

# Path fragments that mark an action as destructive regardless of method —
# plenty of APIs delete via POST.
_DESTRUCTIVE_PATH_RE = re.compile(
    r"(?:^|[/_.-])(?:delete|destroy|remove|purge|wipe|erase|revoke|ban|"
    r"suspend|deactivate|terminate|cancel|refund|transfer|payout|"
    r"withdraw|disable)(?:$|[/_.-])",
    re.IGNORECASE,
)

# Routes that operate on *other people* — an agent acting on the operator's
# behalf has no business here unless the operator owns the system.
_FOREIGN_ACCOUNT_RE = re.compile(
    r"(?:^|/)(?:admin|users?|members?|accounts?|customers?|people|"
    r"subscribers?|employees?)/(?!me$|me/|self$|self/|current$|current/)"
    r"[^/]+",
    re.IGNORECASE,
)

# Self-referential path segments — these mean "my own record", which is
# owned-by-definition even on a service the operator doesn't run.
_SELF_PATH_RE = re.compile(
    r"(?:^|/)(?:me|self|current|my|mine|profile)(?:$|/)", re.IGNORECASE
)


@dataclass
class Authorization:
    """A recorded, operator-supplied authorization to touch a foreign system."""

    target: str
    scope: str = ""
    authorized_by: str = ""
    expires: str = ""
    note: str = ""

    def is_expired(self, today: date | None = None) -> bool:
        if not self.expires:
            return False
        try:
            deadline = datetime.fromisoformat(str(self.expires)).date()
        except ValueError:
            logger.warning(
                "Authorization for %s has unparseable expiry %r — treating "
                "as expired",
                self.target,
                self.expires,
            )
            return True
        return (today or datetime.now(UTC).date()) > deadline

    def covers(self, method: str, path: str) -> bool:
        """Whether this authorization's declared scope covers the request.

        Scope grammar is deliberately simple: ``METHOD[,METHOD] /glob``.
        An empty scope covers nothing — a blank authorization must not be
        a blank cheque.
        """
        if not self.scope.strip():
            return False
        methods_part, _, path_glob = self.scope.partition(" ")
        methods = {m.strip().upper() for m in methods_part.split(",") if m.strip()}
        if methods and "*" not in methods and method.upper() not in methods:
            return False
        path_glob = path_glob.strip() or "*"
        return fnmatch.fnmatch(path or "/", path_glob)


@dataclass
class ScopeVerdict:
    """The guard's decision about one action."""

    scope: TargetScope
    action: ActionKind
    allowed: bool
    requires_approval: bool
    reason: str
    target: str = ""
    authorization: Authorization | None = None

    @property
    def refused(self) -> bool:
        return not self.allowed

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": str(self.scope),
            "action": str(self.action),
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "reason": self.reason,
            "target": self.target,
        }


@dataclass
class ScopePolicy:
    """How to treat each (scope, action) combination.

    Defaults are deliberately asymmetric: reads are free, writes to
    unknown targets ask, and destructive actions on anything that is not
    the operator's own are refused outright.
    """

    # Writes against a target that isn't declared owned.
    foreign_write: str = "ask"  # allow | ask | deny
    # Destructive actions against a target that isn't declared owned.
    foreign_destructive: str = "deny"  # allow | ask | deny
    # Destructive actions against the operator's own systems.
    owned_destructive: str = "ask"
    # Treat an undeclared host as third-party (strict) or merely unknown.
    strict_unknown: bool = False


class ScopeGuard:
    """Classifies action targets and rules on whether an action may proceed."""

    def __init__(
        self,
        *,
        owned: list[str] | None = None,
        third_party: list[str] | None = None,
        authorizations: list[Authorization] | None = None,
        policy: ScopePolicy | None = None,
    ) -> None:
        self._owned = [p.lower().lstrip(".") for p in (owned or [])]
        self._third_party = [p.lower().lstrip(".") for p in (third_party or [])]
        self._authorizations = authorizations or []
        self._policy = policy or ScopePolicy()

    # ── construction ────────────────────────────────────────────────

    @classmethod
    def load(
        cls, data_dir: str | Path, policy: ScopePolicy | None = None
    ) -> ScopeGuard:
        """Load declared scope from ``<data_dir>/owned_scope.yaml``.

        A missing file is normal on a fresh install and yields an empty
        guard — which still enforces the default-deny on foreign
        destructive actions, because nothing is declared owned yet.
        """
        path = Path(data_dir) / _SCOPE_FILE
        if not path.exists():
            return cls(policy=policy)
        try:
            import yaml

            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.error(
                "Failed to parse %s (%s) — falling back to an empty scope, "
                "which denies foreign destructive actions",
                path,
                exc,
            )
            return cls(policy=policy)

        auths = [
            Authorization(
                target=str(a.get("target", "")),
                scope=str(a.get("scope", "")),
                authorized_by=str(a.get("authorized_by", "")),
                expires=str(a.get("expires", "")),
                note=str(a.get("note", "")),
            )
            for a in (raw.get("authorizations") or [])
            if isinstance(a, dict) and a.get("target")
        ]
        return cls(
            owned=[str(x) for x in (raw.get("owned") or [])],
            third_party=[str(x) for x in (raw.get("third_party") or [])],
            authorizations=auths,
            policy=policy,
        )

    # ── classification ──────────────────────────────────────────────

    @staticmethod
    def _host_of(target: str) -> str:
        """Extract a bare hostname from a URL or host string."""
        text = (target or "").strip()
        if not text:
            return ""
        if "://" in text:
            return (urlparse(text).hostname or "").lower()
        # Bare host, possibly with port or path.
        return text.split("/")[0].split(":")[0].lower()

    @staticmethod
    def _matches(host: str, patterns: list[str]) -> bool:
        for pattern in patterns:
            if not pattern:
                continue
            if fnmatch.fnmatch(host, pattern):
                return True
            # A bare domain also covers its subdomains.
            if not pattern.startswith("*") and host.endswith("." + pattern):
                return True
        return False

    def classify(self, target: str) -> TargetScope:
        """Classify a URL or hostname as owned / third-party / unknown."""
        host = self._host_of(target)
        if not host:
            return TargetScope.UNKNOWN
        if self._matches(host, self._owned):
            return TargetScope.OWNED
        if self._matches(host, self._third_party):
            return TargetScope.THIRD_PARTY
        return (
            TargetScope.THIRD_PARTY
            if self._policy.strict_unknown
            else TargetScope.UNKNOWN
        )

    def classify_action(self, method: str, path: str = "") -> ActionKind:
        """Classify how reversible an HTTP action is."""
        m = (method or "GET").upper()
        p = path or ""
        if m in _DESTRUCTIVE_METHODS or _DESTRUCTIVE_PATH_RE.search(p):
            return ActionKind.DESTRUCTIVE
        if m in _WRITE_METHODS:
            return ActionKind.WRITE
        return ActionKind.READ

    def targets_foreign_account(self, path: str) -> bool:
        """Whether the path appears to address another person's record.

        ``/users/me/bookings`` is the operator's own; ``/users/8813/bookings``
        is somebody else's. This is a heuristic and it is meant to be one —
        it raises the bar, it does not replace the ownership declaration.
        """
        if not path:
            return False
        if _SELF_PATH_RE.search(path):
            return False
        return bool(_FOREIGN_ACCOUNT_RE.search(path))

    def find_authorization(
        self, target: str, method: str, path: str
    ) -> Authorization | None:
        """Return a live authorization covering this request, if any."""
        host = self._host_of(target)
        for auth in self._authorizations:
            if not self._matches(host, [auth.target.lower().lstrip(".")]):
                continue
            if auth.is_expired():
                logger.info(
                    "Authorization for %s expired on %s — not applying",
                    auth.target,
                    auth.expires,
                )
                continue
            if auth.covers(method, path):
                return auth
        return None

    # ── the decision ────────────────────────────────────────────────

    def assess(
        self,
        target: str,
        method: str = "GET",
        path: str = "",
    ) -> ScopeVerdict:
        """Rule on one action against one target."""
        scope = self.classify(target)
        action = self.classify_action(method, path)
        host = self._host_of(target) or target

        # Reads never trip the guard. Reading a public API is not an
        # ownership question, and the SSRF guard handles the network side.
        if action == ActionKind.READ:
            return ScopeVerdict(
                scope=scope,
                action=action,
                allowed=True,
                requires_approval=False,
                reason="Read-only action.",
                target=host,
            )

        foreign_account = self.targets_foreign_account(path)

        # An explicit, unexpired, in-scope authorization is the one way a
        # foreign write or destructive action proceeds.
        auth = self.find_authorization(target, method, path)
        if auth is not None and scope != TargetScope.OWNED:
            return ScopeVerdict(
                scope=scope,
                action=action,
                allowed=True,
                requires_approval=True,
                reason=(
                    f"Covered by recorded authorization for {auth.target} "
                    f"(authorized by: {auth.authorized_by or 'unspecified'}; "
                    f"scope: {auth.scope}). Still asking before proceeding."
                ),
                target=host,
                authorization=auth,
            )

        if scope == TargetScope.OWNED and not foreign_account:
            if action == ActionKind.DESTRUCTIVE:
                mode = self._policy.owned_destructive
                return ScopeVerdict(
                    scope=scope,
                    action=action,
                    allowed=mode != "deny",
                    requires_approval=mode == "ask",
                    reason=(
                        f"Destructive action on your own system ({host}). "
                        "Irreversible — confirming first."
                    ),
                    target=host,
                )
            return ScopeVerdict(
                scope=scope,
                action=action,
                allowed=True,
                requires_approval=False,
                reason=f"Write to your own declared system ({host}).",
                target=host,
            )

        # From here down the target is not the operator's own.
        if action == ActionKind.DESTRUCTIVE:
            mode = self._policy.foreign_destructive
            if foreign_account:
                # The hard stop this module exists for. No prompt: an
                # approval dialog is not an authorization to destroy a
                # third party's data.
                return ScopeVerdict(
                    scope=scope,
                    action=action,
                    allowed=False,
                    requires_approval=False,
                    reason=(
                        f"Refused: destructive action on what looks like "
                        f"another person's record at {host} ({path}). This "
                        "agent only performs destructive actions on systems "
                        "and accounts you have declared as yours. If you are "
                        "authorized to test this system, record it under "
                        "'authorizations' in data/owned_scope.yaml with the "
                        "authorizing party and agreed scope."
                    ),
                    target=host,
                )
            return ScopeVerdict(
                scope=scope,
                action=action,
                allowed=mode != "deny",
                requires_approval=mode == "ask",
                reason=(
                    (
                        f"Refused: destructive action on {host}, which is not a "
                        "system you have declared as yours. Add it to 'owned' in "
                        "data/owned_scope.yaml if it is, or record an "
                        "authorization if you are authorized to test it."
                    )
                    if mode == "deny"
                    else f"Destructive action on undeclared system {host}."
                ),
                target=host,
            )

        # Foreign write.
        mode = self._policy.foreign_write
        if foreign_account and mode != "allow":
            return ScopeVerdict(
                scope=scope,
                action=action,
                allowed=mode != "deny",
                requires_approval=True,
                reason=(
                    f"Write targeting another person's record at {host} "
                    f"({path}). Confirm this is yours to change."
                ),
                target=host,
            )
        return ScopeVerdict(
            scope=scope,
            action=action,
            allowed=mode != "deny",
            requires_approval=mode == "ask",
            reason=(
                f"Write to {host}, which you have not declared as yours."
                if mode != "allow"
                else f"Write to {host}."
            ),
            target=host,
        )

    # ── declaration helpers ─────────────────────────────────────────

    def declare_owned(self, host: str) -> None:
        """Add *host* to the owned list in memory (persist via :func:`save`)."""
        h = host.lower().lstrip(".")
        if h and h not in self._owned:
            self._owned.append(h)

    @property
    def owned(self) -> list[str]:
        return list(self._owned)

    @property
    def third_party(self) -> list[str]:
        return list(self._third_party)

    @property
    def authorizations(self) -> list[Authorization]:
        return list(self._authorizations)

    def save(self, data_dir: str | Path) -> Path:
        """Persist the current declaration back to ``owned_scope.yaml``."""
        import yaml

        path = Path(data_dir) / _SCOPE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "owned": self._owned,
            "third_party": self._third_party,
            "authorizations": [
                {
                    "target": a.target,
                    "scope": a.scope,
                    "authorized_by": a.authorized_by,
                    "expires": a.expires,
                    "note": a.note,
                }
                for a in self._authorizations
            ],
        }
        path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return path


@dataclass
class ScopeGuardConfigView:
    """Normalized ``scope:`` config section."""

    enabled: bool = True
    policy: ScopePolicy = field(default_factory=ScopePolicy)


def policy_from_config(config: Any) -> ScopeGuardConfigView:
    """Read scope-guard settings off a Config object, tolerating absence."""
    section = getattr(config, "scope", None)
    if section is None:
        return ScopeGuardConfigView()
    return ScopeGuardConfigView(
        enabled=bool(getattr(section, "enabled", True)),
        policy=ScopePolicy(
            foreign_write=str(getattr(section, "foreign_write", "ask") or "ask"),
            foreign_destructive=str(
                getattr(section, "foreign_destructive", "deny") or "deny"
            ),
            owned_destructive=str(
                getattr(section, "owned_destructive", "ask") or "ask"
            ),
            strict_unknown=bool(getattr(section, "strict_unknown", False)),
        ),
    )
