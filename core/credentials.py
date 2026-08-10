"""Credential broker — resolves third-party secrets without leaking them.

This is the credential layer for *services the agent acts against on the
operator's behalf* (a gym booking API, Notion, Trello, Google). It is
deliberately separate from LLM provider keys, which live in ``config.yaml``
and are read by ``core/router.py`` — those are the agent's own keys, not
credentials it wields against a third party.

Three properties the plain vault could not give us:

1. **The model never sees the value.** ``resolve()`` returns a
   :class:`SecretString` whose ``str``/``repr`` are redacted, and issues a
   process-local *sentinel* (``«cred:ab12cd34»``). Tools put the sentinel in
   headers/bodies; :meth:`CredentialBroker.materialize` swaps in the real
   value at the network boundary and nowhere else.
2. **Per-item policy + approval.** Each credential slug carries
   ``auto`` / ``approve`` / ``deny``. ``approve`` (the default) asks the
   operator through the normal approval callback, with an optional TTL
   standing grant so a multi-step workflow doesn't prompt on every call.
3. **An audit trail.** Every resolve attempt — granted, denied, or
   auto — is written to ``credential_audit`` with the caller's stated
   reason. Values are never logged.

Reference forms accepted by :func:`parse_ref`::

    env:GITHUB_TOKEN            # process environment
    ${GITHUB_TOKEN}             # shorthand for the above
    vault:github.com            # whole vault entry
    vault:github.com#token      # one field of a vault entry
    file:/run/secrets/api#key   # JSON file, optional dotted pointer
    oauth:google                # access token from the OAuth token store

See ``docs/86-CREDENTIAL-BROKER.md``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets as _secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CREATE_AUDIT_TABLE = """\
CREATE TABLE IF NOT EXISTS credential_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL,
    caller TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
)"""

# Sentinel format. Guillemets keep it visually distinct from anything a
# model would plausibly emit on its own, and the hex tail makes collisions
# with real content effectively impossible.
_SENTINEL_RE = re.compile(r"«cred:([0-9a-f]{8})»")

_REDACTED = "«redacted»"

# Values shorter than this are not worth scrubbing from text — a 3-char
# "secret" would redact half the English language out of tool results.
_MIN_SCRUB_LEN = 6


class CredentialError(Exception):
    """Raised when a credential cannot be resolved or is refused."""


class SecretString:
    """A string that refuses to reveal itself in logs, reprs, or tracebacks.

    ``str()`` and ``repr()`` both return the redaction marker. The real
    value is only available through :meth:`reveal`, which is called at
    exactly one place per flow: the network boundary.
    """

    __slots__ = ("_value", "slug")

    def __init__(self, value: str, slug: str = "") -> None:
        self._value = value
        self.slug = slug

    def reveal(self) -> str:
        """Return the plaintext. Call this only at the point of use."""
        return self._value

    def __len__(self) -> int:
        return len(self._value)

    def __bool__(self) -> bool:
        return bool(self._value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretString):
            return _secrets.compare_digest(self._value, other._value)
        return NotImplemented

    def __hash__(self) -> int:  # pragma: no cover — identity semantics
        return hash(("SecretString", self.slug))

    def __str__(self) -> str:
        return _REDACTED

    def __repr__(self) -> str:
        return f"SecretString(slug={self.slug!r}, value={_REDACTED})"


@dataclass(frozen=True)
class CredentialRef:
    """A parsed pointer to where a secret lives."""

    source: str  # env | vault | file | oauth
    id: str  # variable name, vault key, file path, or provider name
    field: str = ""  # optional sub-field / JSON pointer

    def describe(self) -> str:
        base = f"{self.source}:{self.id}"
        return f"{base}#{self.field}" if self.field else base


@dataclass
class CredentialPolicy:
    """Per-slug access policy.

    ``mode``:
        ``auto``    — resolve without prompting.
        ``approve`` — ask the operator (default).
        ``deny``    — never resolve.

    ``grant_ttl_seconds`` turns one approval into a standing grant for
    that window, so a booking flow that makes six calls prompts once.
    """

    mode: str = "approve"
    grant_ttl_seconds: int = 0


def parse_ref(raw: str | dict[str, Any]) -> CredentialRef:
    """Parse a credential reference from its string or dict form.

    Raises :class:`CredentialError` on an unknown source so a typo fails
    loudly rather than silently resolving to nothing.
    """
    if isinstance(raw, dict):
        source = str(raw.get("source", "")).strip().lower()
        ident = str(raw.get("id", "")).strip()
        sub = str(raw.get("field", "")).strip()
        if not source or not ident:
            raise CredentialError(
                "Credential ref dict needs both 'source' and 'id' " f"(got {raw!r})"
            )
        if source not in _SOURCES:
            raise CredentialError(f"Unknown credential source {source!r}")
        return CredentialRef(source=source, id=ident, field=sub)

    text = str(raw).strip()
    if not text:
        raise CredentialError("Empty credential reference")

    # ${VAR} shorthand for env.
    shorthand = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", text)
    if shorthand:
        return CredentialRef(source="env", id=shorthand.group(1))

    if ":" not in text:
        raise CredentialError(
            f"Malformed credential ref {text!r} — expected 'source:id' "
            f"(one of {', '.join(sorted(_SOURCES))}) or '${{ENV_VAR}}'"
        )

    source, _, rest = text.partition(":")
    source = source.strip().lower()
    if source not in _SOURCES:
        raise CredentialError(
            f"Unknown credential source {source!r} in {text!r} — "
            f"expected one of {', '.join(sorted(_SOURCES))}"
        )
    ident, _, sub = rest.partition("#")
    ident = ident.strip()
    if not ident:
        raise CredentialError(f"Credential ref {text!r} has no identifier")
    return CredentialRef(source=source, id=ident, field=sub.strip())


_SOURCES = frozenset({"env", "vault", "file", "oauth"})


class CredentialBroker:
    """Resolves credential refs under policy, and keeps values out of context.

    The broker holds no secrets at rest — it reads through to the vault,
    the environment, a file, or the OAuth token store on each resolve.
    What it *does* hold is the sentinel map for the current process, so
    :meth:`materialize` can swap sentinels back at the network boundary.
    """

    def __init__(
        self,
        *,
        vault: Any = None,
        db: Any = None,
        oauth_store: Any = None,
        policies: dict[str, CredentialPolicy] | None = None,
        default_mode: str = "approve",
        project_root: Path | None = None,
    ) -> None:
        self._vault = vault
        self._db = db
        self._oauth_store = oauth_store
        self._policies = policies or {}
        self._default_mode = default_mode
        self._project_root = project_root or Path.cwd()

        # sentinel token -> plaintext, for this process only.
        self._sentinels: dict[str, str] = {}
        # sentinel token -> slug, for audit/redaction messages.
        self._sentinel_slugs: dict[str, str] = {}
        # slug -> unix expiry of a standing grant.
        self._grants: dict[str, float] = {}

        self._approval_callback: Callable[..., Any] | None = None
        self._audit_ready = False

    # ── wiring ──────────────────────────────────────────────────────

    def set_approval_callback(self, callback: Callable[..., Any] | None) -> None:
        """Set the operator-approval callback (same shape the executor uses)."""
        self._approval_callback = callback

    def set_vault(self, vault: Any) -> None:
        self._vault = vault

    def set_oauth_store(self, store: Any) -> None:
        self._oauth_store = store

    def policy_for(self, slug: str) -> CredentialPolicy:
        """Policy for *slug*, falling back to the configured default mode."""
        found = self._policies.get(slug)
        if found is not None:
            return found
        # Allow a wildcard prefix policy: "google.*" covers "google.calendar".
        for pattern, policy in self._policies.items():
            if pattern.endswith("*") and slug.startswith(pattern[:-1]):
                return policy
        return CredentialPolicy(mode=self._default_mode)

    # ── resolution ──────────────────────────────────────────────────

    async def resolve(
        self,
        slug: str,
        ref: str | dict[str, Any] | CredentialRef,
        *,
        reason: str,
        caller: str = "",
        approval_callback: Callable[..., Any] | None = None,
    ) -> SecretString:
        """Resolve *ref* to a secret, subject to policy and approval.

        ``reason`` is mandatory and is written to the audit log — the
        operator approving a prompt needs to know what the credential is
        about to be used for.
        """
        if not reason or not reason.strip():
            raise CredentialError("A reason is required to resolve a credential")

        parsed = ref if isinstance(ref, CredentialRef) else parse_ref(ref)
        policy = self.policy_for(slug)

        if policy.mode == "deny":
            await self._audit(slug, parsed.source, reason, "denied-by-policy", caller)
            raise CredentialError(
                f"Credential {slug!r} is denied by policy (mode: deny)."
            )

        needs_ask = policy.mode != "auto" and not self._has_grant(slug)
        if needs_ask:
            approved = await self._ask(
                slug=slug, ref=parsed, reason=reason, callback=approval_callback
            )
            if not approved:
                await self._audit(slug, parsed.source, reason, "denied", caller)
                raise CredentialError(f"Operator denied access to credential {slug!r}.")
            if policy.grant_ttl_seconds > 0:
                self._grants[slug] = time.monotonic() + policy.grant_ttl_seconds

        value = self._read(parsed)
        if value is None or value == "":
            await self._audit(slug, parsed.source, reason, "not-found", caller)
            raise CredentialError(
                f"Credential {slug!r} not found at {parsed.describe()}."
            )

        outcome = "auto" if policy.mode == "auto" else "granted"
        await self._audit(slug, parsed.source, reason, outcome, caller)
        return SecretString(value, slug=slug)

    def _has_grant(self, slug: str) -> bool:
        expiry = self._grants.get(slug)
        if expiry is None:
            return False
        if time.monotonic() >= expiry:
            self._grants.pop(slug, None)
            return False
        return True

    async def _ask(
        self,
        *,
        slug: str,
        ref: CredentialRef,
        reason: str,
        callback: Callable[..., Any] | None,
    ) -> bool:
        import inspect

        cb = callback or self._approval_callback
        if cb is None:
            # Fail closed. No approval path means no credential — the
            # alternative (silently granting) would make the policy a lie.
            logger.warning(
                "Credential %r needs approval but no callback is wired", slug
            )
            return False
        description = (
            f"Use credential '{slug}' (from {ref.describe()})\nReason: {reason}"
        )
        result = cb("credential_access", description, {"slug": slug})
        if inspect.isawaitable(result):
            return bool(await result)
        return bool(result)

    def _read(self, ref: CredentialRef) -> str | None:
        """Read the raw value behind *ref*. Never logs the value."""
        if ref.source == "env":
            return os.environ.get(ref.id)

        if ref.source == "vault":
            if self._vault is None:
                raise CredentialError(
                    "Vault is locked or unavailable — cannot resolve "
                    f"{ref.describe()}. Unlock it with `elophanto vault unlock`."
                )
            entry = self._vault.get(ref.id)
            if entry is None:
                return None
            if isinstance(entry, dict):
                if ref.field:
                    got = entry.get(ref.field)
                    return None if got is None else str(got)
                # No field named: prefer the conventional single-secret keys.
                for candidate in ("token", "api_key", "password", "value", "secret"):
                    if candidate in entry:
                        return str(entry[candidate])
                raise CredentialError(
                    f"Vault entry {ref.id!r} is a record with fields "
                    f"{sorted(entry)!r} — name one, e.g. 'vault:{ref.id}#token'."
                )
            return str(entry)

        if ref.source == "file":
            path = Path(ref.id)
            if not path.is_absolute():
                path = self._project_root / path
            if not path.exists():
                return None
            text = path.read_text(encoding="utf-8")
            if not ref.field:
                return text.strip()
            try:
                data: Any = json.loads(text)
            except json.JSONDecodeError as exc:
                raise CredentialError(
                    f"{path} is not JSON, so field {ref.field!r} cannot be read"
                ) from exc
            for part in ref.field.split("."):
                if not isinstance(data, dict) or part not in data:
                    return None
                data = data[part]
            return None if data is None else str(data)

        if ref.source == "oauth":
            if self._oauth_store is None:
                raise CredentialError(
                    "OAuth token store unavailable — run "
                    f"`elophanto oauth login {ref.id}` first."
                )
            token = self._oauth_store.access_token(ref.id)
            return token

        raise CredentialError(f"Unknown credential source {ref.source!r}")

    # ── sentinels ───────────────────────────────────────────────────

    def issue_sentinel(self, secret: SecretString) -> str:
        """Register *secret* and return an opaque placeholder for it.

        The placeholder is what goes into tool params, transcripts, and
        logs. Only :meth:`materialize` can turn it back into the value.
        """
        token = _secrets.token_hex(4)
        self._sentinels[token] = secret.reveal()
        self._sentinel_slugs[token] = secret.slug
        return f"«cred:{token}»"

    def materialize(self, obj: Any) -> Any:
        """Deep-substitute sentinels with real values.

        Call this at the network boundary and nowhere else. Returns a new
        structure; the input is left untouched so the caller can keep
        holding the safe, sentinel-bearing version for logging.
        """
        if isinstance(obj, str):
            return _SENTINEL_RE.sub(
                lambda m: self._sentinels.get(m.group(1), m.group(0)), obj
            )
        if isinstance(obj, dict):
            return {k: self.materialize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.materialize(v) for v in obj]
        if isinstance(obj, tuple):
            return tuple(self.materialize(v) for v in obj)
        return obj

    def has_sentinels(self, obj: Any) -> bool:
        """Whether *obj* contains at least one sentinel placeholder."""
        if isinstance(obj, str):
            return bool(_SENTINEL_RE.search(obj))
        if isinstance(obj, dict):
            return any(self.has_sentinels(v) for v in obj.values())
        if isinstance(obj, list | tuple):
            return any(self.has_sentinels(v) for v in obj)
        return False

    def redact(self, obj: Any) -> Any:
        """Scrub any live secret value out of *obj* before it is returned.

        Defence in depth for the case where a service echoes the token
        back (auth debug endpoints do this), which would otherwise walk
        the secret straight into the transcript.
        """
        if isinstance(obj, str):
            out = obj
            for token, value in self._sentinels.items():
                if len(value) >= _MIN_SCRUB_LEN and value in out:
                    slug = self._sentinel_slugs.get(token, "")
                    marker = f"«redacted:{slug}»" if slug else _REDACTED
                    out = out.replace(value, marker)
            return out
        if isinstance(obj, dict):
            return {k: self.redact(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.redact(v) for v in obj]
        if isinstance(obj, tuple):
            return tuple(self.redact(v) for v in obj)
        return obj

    def forget_sentinels(self) -> None:
        """Drop the sentinel map. Called when a run ends."""
        self._sentinels.clear()
        self._sentinel_slugs.clear()

    # ── audit ───────────────────────────────────────────────────────

    async def _audit(
        self, slug: str, source: str, reason: str, outcome: str, caller: str
    ) -> None:
        """Append one audit row. Never raises — auditing must not break a run."""
        if self._db is None:
            logger.info(
                "[credential-audit] slug=%s source=%s outcome=%s caller=%s reason=%s",
                slug,
                source,
                outcome,
                caller or "-",
                reason,
            )
            return
        try:
            if not self._audit_ready:
                await self._db.execute_insert(_CREATE_AUDIT_TABLE, ())
                self._audit_ready = True
            await self._db.execute_insert(
                "INSERT INTO credential_audit "
                "(slug, source, reason, outcome, caller, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    slug,
                    source,
                    reason[:500],
                    outcome,
                    caller[:120],
                    datetime.now(UTC).isoformat(),
                ),
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("credential audit write failed: %s", exc)

    async def recent_audit(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent audit rows (no values, ever)."""
        if self._db is None:
            return []
        try:
            rows = await self._db.fetch_all(
                "SELECT slug, source, reason, outcome, caller, created_at "
                "FROM credential_audit ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        except Exception:
            return []
        return [dict(r) for r in rows]


@dataclass
class BrokerConfigView:
    """Normalized broker settings, parsed from the ``credentials:`` section."""

    default_mode: str = "approve"
    policies: dict[str, CredentialPolicy] = field(default_factory=dict)
    bindings: dict[str, str] = field(default_factory=dict)


def broker_from_config(config: Any) -> BrokerConfigView:
    """Read broker settings off a Config object, tolerating absence.

    ``bindings`` maps a friendly slug to a credential ref, so a skill can
    say ``credential: "trello"`` instead of restating the ref every call.
    """
    section = getattr(config, "credentials", None)
    if section is None:
        return BrokerConfigView()
    policies: dict[str, CredentialPolicy] = {}
    for slug, raw in (getattr(section, "policies", None) or {}).items():
        if isinstance(raw, str):
            policies[slug] = CredentialPolicy(mode=raw)
        elif isinstance(raw, dict):
            policies[slug] = CredentialPolicy(
                mode=str(raw.get("mode", "approve")),
                grant_ttl_seconds=int(raw.get("grant_ttl_seconds", 0) or 0),
            )
        elif isinstance(raw, CredentialPolicy):
            policies[slug] = raw
    return BrokerConfigView(
        default_mode=str(getattr(section, "default_mode", "approve") or "approve"),
        policies=policies,
        bindings=dict(getattr(section, "bindings", None) or {}),
    )
