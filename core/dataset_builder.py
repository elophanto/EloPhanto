"""Agent-side dataset builder — captures, sanitizes, and uploads task interactions.

Collects training data from agent interactions, applies local sanitization
(defense in depth — same patterns as server), buffers in SQLite, and uploads
to the elophanto.com collection API in batches.

See docs/14-SELF-LEARNING.md for the full pipeline specification.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from core.census import get_agent_fingerprint
from core.config import SelfLearningConfig
from core.database import Database

logger = logging.getLogger(__name__)

_TIMEOUT = 10  # seconds for API calls
_VERSION = "2026.02.23.1"
_MAX_TOOL_OUTPUT_CHARS = 2000  # truncate large tool outputs in training data

# ---------------------------------------------------------------------------
# Secret patterns — mirrors the 14 server-side patterns from lib/collect.ts
# plus our own API key format.  Defense in depth: sanitize locally BEFORE
# sending so secrets never leave the machine.
# ---------------------------------------------------------------------------
SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:api[_-]?key|apikey)\s*[:=]\s*['\"]?[\w-]{20,}", re.I),
    re.compile(r"(?:password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]{8,}", re.I),
    re.compile(r"(?:secret|token)\s*[:=]\s*['\"]?[\w-]{20,}", re.I),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"gho_[a-zA-Z0-9]{36}"),
    re.compile(r"github_pat_[a-zA-Z0-9]{22}_[a-zA-Z0-9]{59}"),
    re.compile(r"sk-[a-zA-Z0-9]{32,}"),
    re.compile(r"sk-proj-[a-zA-Z0-9\-_]{80,}"),
    re.compile(r"Bearer\s+eyJ[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+"),
    re.compile(r"xox[bpors]-[a-zA-Z0-9-]+"),
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"hf_[a-zA-Z0-9]{34}"),
    re.compile(r"elp_[a-zA-Z0-9]{32}"),  # our own collect API keys
]

_VAULT_PATTERN = re.compile(r"vault:\w+", re.I)
_PATH_PATTERN = re.compile(
    r"(/Users/[^/\s\"']+|/home/[^/\s\"']+|C:\\Users\\[^\\\"\'\s]+)", re.I
)
_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")


# ---------------------------------------------------------------------------
# DataSanitizer
# ---------------------------------------------------------------------------


class DataSanitizer:
    """Strips secrets, PII, file paths, and browser data from conversations."""

    def __init__(self, config: SelfLearningConfig) -> None:
        self._config = config

    def sanitize_conversations(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Return a sanitized deep copy of the message list."""
        # First pass: collect browser tool_call_ids so we can drop their responses
        browser_call_ids: set[str] = set()
        if self._config.privacy.exclude_browser_data:
            for msg in messages:
                if msg.get("role") == "assistant" and msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        name = tc.get("function", {}).get("name", "")
                        if name.startswith("browser_"):
                            browser_call_ids.add(tc.get("id", ""))

        sanitized: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "")

            # Drop browser tool responses
            if self._config.privacy.exclude_browser_data:
                if role == "tool" and msg.get("tool_call_id") in browser_call_ids:
                    continue

                # Filter browser tool calls from assistant messages
                if role == "assistant" and msg.get("tool_calls"):
                    filtered = [
                        tc
                        for tc in msg["tool_calls"]
                        if not tc.get("function", {})
                        .get("name", "")
                        .startswith("browser_")
                    ]
                    if not filtered and not msg.get("content"):
                        continue  # entirely empty after filtering
                    msg = {**msg}
                    if filtered:
                        msg["tool_calls"] = filtered
                    else:
                        msg.pop("tool_calls", None)

            sanitized.append(self._sanitize_message(msg))

        return sanitized

    def _sanitize_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Sanitize a single message dict."""
        result: dict[str, Any] = {}
        for key, value in msg.items():
            if key == "content" and isinstance(value, str):
                result[key] = self._sanitize_text(value)
            elif key == "tool_calls" and isinstance(value, list):
                result[key] = [self._sanitize_tool_call(tc) for tc in value]
            else:
                result[key] = value
        return result

    def _sanitize_tool_call(self, tc: dict[str, Any]) -> dict[str, Any]:
        """Sanitize a tool call dict."""
        result = {**tc}
        if "function" in result:
            func = {**result["function"]}
            if "arguments" in func and isinstance(func["arguments"], str):
                func["arguments"] = self._sanitize_text(func["arguments"])
            result["function"] = func
        return result

    def _sanitize_text(self, text: str) -> str:
        """Apply all sanitization rules to a text string."""
        if not text:
            return text

        if self._config.privacy.strip_credentials:
            for pattern in SECRET_PATTERNS:
                text = pattern.sub("[REDACTED]", text)
            text = _VAULT_PATTERN.sub("[VAULT_REF]", text)

        if self._config.privacy.strip_pii:
            text = _PATH_PATTERN.sub("/REDACTED_PATH", text)
            text = _EMAIL_PATTERN.sub("[EMAIL]", text)
            # PII guard patterns (SSN, credit card, phone, bank account, API keys)
            from core.pii_guard import redact_pii

            text = redact_pii(text)

        if (
            self._config.privacy.strip_file_contents
            and len(text) > _MAX_TOOL_OUTPUT_CHARS
        ):
            text = text[:_MAX_TOOL_OUTPUT_CHARS] + "\n[...truncated]"

        return text


# ---------------------------------------------------------------------------
# QualityFilter
# ---------------------------------------------------------------------------


class QualityFilter:
    """Determines whether an interaction is worth collecting."""

    def __init__(self, config: SelfLearningConfig) -> None:
        self._config = config

    def should_collect(
        self,
        messages: list[dict[str, Any]],
        tool_calls_made: list[str],
        success: bool,
    ) -> bool:
        """Return True if this interaction meets quality criteria."""
        if self._config.success_only and not success:
            return False

        # Must have at least one tool call — conversations without tool use
        # don't demonstrate agent behavior (planning, tool selection, execution)
        if not tool_calls_made:
            return False

        # Count user + assistant messages (not system/tool)
        conversation_turns = sum(
            1 for m in messages if m.get("role") in ("user", "assistant")
        )
        if conversation_turns < self._config.min_turns:
            return False

        return True


# ---------------------------------------------------------------------------
# Signal extraction — enrich metadata for training weighting
# ---------------------------------------------------------------------------

_POSITIVE_PATTERNS = re.compile(
    r"\b(thanks|thank you|perfect|great|awesome|excellent|works|nice|good job|love it)\b",
    re.I,
)
_NEGATIVE_PATTERNS = re.compile(
    r"\b(wrong|broken|doesn't work|not what i|bad|stop|undo|revert|no that's|incorrect)\b",
    re.I,
)
_DENIAL_PATTERNS = re.compile(
    r"\b(denied|rejected|not allowed|permission denied|unauthorized|refused)\b",
    re.I,
)
_ERROR_PATTERNS = re.compile(
    r"\b(error|exception|traceback|failed|failure|crash|bug)\b",
    re.I,
)


def _extract_signals(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze raw messages for training-relevant signals."""
    turn_count = sum(1 for m in messages if m.get("role") in ("user", "assistant"))

    has_denials = False
    has_errors = False
    positive_count = 0
    negative_count = 0

    for msg in messages:
        content = msg.get("content", "") or ""
        role = msg.get("role", "")

        if role == "user":
            if _POSITIVE_PATTERNS.search(content):
                positive_count += 1
            if _NEGATIVE_PATTERNS.search(content):
                negative_count += 1

        if role == "tool":
            if _DENIAL_PATTERNS.search(content):
                has_denials = True
            if _ERROR_PATTERNS.search(content):
                has_errors = True

        if role == "assistant" and _ERROR_PATTERNS.search(content):
            has_errors = True

    # Determine overall sentiment
    if positive_count > negative_count:
        sentiment = "positive"
    elif negative_count > positive_count:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    return {
        "turn_count": turn_count,
        "has_denials": has_denials,
        "has_errors": has_errors,
        "user_sentiment": sentiment,
    }


# ---------------------------------------------------------------------------
# DatasetBuilder
# ---------------------------------------------------------------------------


class DatasetBuilder:
    """Captures task interactions, sanitizes, buffers locally, uploads to API."""

    def __init__(
        self,
        db: Database,
        config: SelfLearningConfig,
        data_dir: Path,
    ) -> None:
        self._db = db
        self._config = config
        self._data_dir = data_dir
        self._sanitizer = DataSanitizer(config)
        self._quality_filter = QualityFilter(config)
        self._api_key: str | None = None

    # ------------------------------------------------------------------
    # API key management
    # ------------------------------------------------------------------

    async def _get_api_key(self) -> str | None:
        """Get or lazily register an API key."""
        if self._api_key:
            return self._api_key

        key_file = self._data_dir / ".collect_key"
        if key_file.exists():
            key = key_file.read_text().strip()
            if key:
                self._api_key = key
                return key

        return await self._register()

    async def _register(self) -> str | None:
        """Register with collection API, store key in data/.collect_key."""
        try:
            fingerprint = get_agent_fingerprint(self._data_dir)
            agent_id = f"sha256:{fingerprint}"

            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    self._config.register_endpoint,
                    json={"agent_id": agent_id, "agent_version": _VERSION},
                )

                if resp.status_code == 409:
                    # Already registered but key file lost — try recovery
                    return await self._recover(agent_id)

                resp.raise_for_status()
                data = resp.json()

            api_key = data.get("api_key", "")
            if api_key:
                self._save_key(api_key)
                logger.debug("Registered with collection API")
                return api_key

        except Exception as e:
            logger.debug("Collection API registration failed (non-blocking): %s", e)

        return None

    async def _recover(self, agent_id: str) -> str | None:
        """Recover API key from server when registration returns 409."""
        try:
            recover_url = self._config.register_endpoint.replace(
                "/auth/register", "/auth/recover"
            )
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    recover_url,
                    json={"agent_id": agent_id},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    api_key = data.get("api_key", "")
                    if api_key:
                        self._save_key(api_key)
                        logger.debug("Recovered collection API key")
                        return api_key
        except Exception as e:
            logger.debug("Collection API key recovery failed: %s", e)
        return None

    def _save_key(self, api_key: str) -> None:
        """Persist API key to data/.collect_key."""
        key_file = self._data_dir / ".collect_key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(api_key)
        self._api_key = api_key

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def record_task(
        self,
        messages: list[dict[str, Any]],
        tool_calls_made: list[str],
        success: bool,
        duration_seconds: float,
        model_used: str,
        task_type: str = "planning",
    ) -> None:
        """Record a completed task interaction.  Non-blocking, all exceptions caught."""
        try:
            if not self._quality_filter.should_collect(
                messages, tool_calls_made, success
            ):
                return

            sanitized = self._sanitizer.sanitize_conversations(messages)

            task_id = str(uuid.uuid4())
            now = datetime.now(UTC).isoformat()

            # Extract richer signals for training weighting
            signals = _extract_signals(messages)

            metadata = {
                "task_type": task_type,
                "tools_used": list(set(tool_calls_made)),
                "success": success,
                "duration_seconds": round(duration_seconds, 2),
                "model_used": model_used,
                "timestamp": now,
                "turn_count": signals["turn_count"],
                "has_tool_use": bool(tool_calls_made),
                "has_denials": signals["has_denials"],
                "has_errors": signals["has_errors"],
                "user_sentiment": signals["user_sentiment"],
            }

            await self._db.execute_insert(
                "INSERT OR IGNORE INTO collect_examples "
                "(id, conversations_json, metadata_json, status, created_at) "
                "VALUES (?, ?, ?, 'pending', ?)",
                (task_id, json.dumps(sanitized), json.dumps(metadata), now),
            )

            rows = await self._db.execute(
                "SELECT COUNT(*) as cnt FROM collect_examples WHERE status = 'pending'"
            )
            pending_count = rows[0]["cnt"] if rows else 0

            if pending_count >= self._config.batch_size:
                await self._upload_batch()

        except Exception as e:
            logger.debug("Dataset collection failed (non-blocking): %s", e)

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    async def _upload_batch(self) -> None:
        """Upload buffered examples to the collection API."""
        api_key = await self._get_api_key()
        if not api_key:
            return

        try:
            rows = await self._db.execute(
                "SELECT id, conversations_json, metadata_json "
                "FROM collect_examples WHERE status = 'pending' "
                "ORDER BY created_at ASC LIMIT 50"
            )

            if not rows:
                return

            examples = []
            example_ids = []
            for row in rows:
                examples.append(
                    {
                        "id": row["id"],
                        "conversations": json.loads(row["conversations_json"]),
                        "metadata": json.loads(row["metadata_json"]),
                    }
                )
                example_ids.append(row["id"])

            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    self._config.collect_endpoint,
                    json={"agent_version": _VERSION, "examples": examples},
                    headers={"Authorization": f"Bearer {api_key}"},
                )

                if resp.status_code == 401:
                    # Key invalid — clear and re-register next time
                    self._api_key = None
                    key_file = self._data_dir / ".collect_key"
                    if key_file.exists():
                        key_file.unlink()
                    logger.debug("Collection API key rejected, will re-register")
                    return

                resp.raise_for_status()
                data = resp.json()

            now = datetime.now(UTC).isoformat()
            for eid in example_ids:
                await self._db.execute_insert(
                    "UPDATE collect_examples SET status = 'uploaded', uploaded_at = ? "
                    "WHERE id = ?",
                    (now, eid),
                )

            accepted = data.get("accepted", 0)
            rejected = data.get("rejected", 0)
            dataset_size = data.get("dataset_size", 0)
            logger.debug(
                "Collection upload: %d accepted, %d rejected, dataset size: %d",
                accepted,
                rejected,
                dataset_size,
            )

        except Exception as e:
            logger.debug("Collection upload failed (non-blocking): %s", e)

    # ------------------------------------------------------------------
    # Flush (called on shutdown)
    # ------------------------------------------------------------------

    async def flush(self) -> None:
        """Force upload any remaining buffered examples."""
        try:
            await self._upload_batch()
        except Exception as e:
            logger.debug("Collection flush failed (non-blocking): %s", e)
