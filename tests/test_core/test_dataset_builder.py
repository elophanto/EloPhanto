"""Tests for core/dataset_builder.py — DataSanitizer, QualityFilter, DatasetBuilder."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import SelfLearningConfig, SelfLearningPrivacyConfig
from core.dataset_builder import (
    DataSanitizer,
    DatasetBuilder,
    QualityFilter,
    _extract_signals,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> SelfLearningConfig:
    return SelfLearningConfig(
        enabled=True,
        collect_endpoint="https://api.example.com/v1/collect",
        register_endpoint="https://api.example.com/v1/auth/register",
        batch_size=3,
        min_turns=2,
        success_only=False,
    )


@pytest.fixture
def config_strict() -> SelfLearningConfig:
    """Config with strict filtering (success_only, higher min_turns)."""
    return SelfLearningConfig(
        enabled=True,
        batch_size=3,
        min_turns=3,
        success_only=True,
    )


@pytest.fixture
def config_no_filter() -> SelfLearningConfig:
    return SelfLearningConfig(
        enabled=True,
        batch_size=3,
        min_turns=1,
        success_only=False,
    )


@pytest.fixture
def sanitizer(config: SelfLearningConfig) -> DataSanitizer:
    return DataSanitizer(config)


@pytest.fixture
def quality_filter(config: SelfLearningConfig) -> QualityFilter:
    return QualityFilter(config)


@pytest.fixture
def mock_db() -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock(return_value=[{"cnt": 0}])
    db.execute_insert = AsyncMock(return_value=1)
    return db


@pytest.fixture
def builder(
    mock_db: MagicMock, config: SelfLearningConfig, tmp_path: Path
) -> DatasetBuilder:
    return DatasetBuilder(db=mock_db, config=config, data_dir=tmp_path)


# ---------------------------------------------------------------------------
# DataSanitizer tests
# ---------------------------------------------------------------------------


class TestDataSanitizer:
    """Test secret, PII, and browser data stripping."""

    def test_strip_github_pat(self, sanitizer: DataSanitizer) -> None:
        msgs = [
            {"role": "user", "content": "use ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef1234"}
        ]
        result = sanitizer.sanitize_conversations(msgs)
        assert "ghp_" not in result[0]["content"]
        assert "[REDACTED]" in result[0]["content"]

    def test_strip_openai_key(self, sanitizer: DataSanitizer) -> None:
        msgs = [
            {"role": "user", "content": "key is sk-abcdefghijklmnopqrstuvwxyz123456"}
        ]
        result = sanitizer.sanitize_conversations(msgs)
        assert "sk-" not in result[0]["content"]

    def test_strip_aws_key(self, sanitizer: DataSanitizer) -> None:
        msgs = [{"role": "user", "content": "AKIAIOSFODNN7EXAMPLE"}]
        result = sanitizer.sanitize_conversations(msgs)
        assert "AKIA" not in result[0]["content"]

    def test_strip_hf_token(self, sanitizer: DataSanitizer) -> None:
        msgs = [{"role": "user", "content": "hf_" + "X" * 34}]
        result = sanitizer.sanitize_conversations(msgs)
        assert "hf_" not in result[0]["content"]

    def test_strip_elp_key(self, sanitizer: DataSanitizer) -> None:
        msgs = [
            {"role": "user", "content": "key: elp_abcdefghijklmnopqrstuvwxyz123456"}
        ]
        result = sanitizer.sanitize_conversations(msgs)
        assert "elp_" not in result[0]["content"]

    def test_strip_private_key(self, sanitizer: DataSanitizer) -> None:
        msgs = [{"role": "user", "content": "-----BEGIN RSA PRIVATE KEY-----\nMIIE..."}]
        result = sanitizer.sanitize_conversations(msgs)
        assert "PRIVATE KEY" not in result[0]["content"]

    def test_strip_vault_reference(self, sanitizer: DataSanitizer) -> None:
        msgs = [{"role": "user", "content": "use vault:my_secret_key"}]
        result = sanitizer.sanitize_conversations(msgs)
        assert "vault:" not in result[0]["content"]
        assert "[VAULT_REF]" in result[0]["content"]

    def test_strip_password(self, sanitizer: DataSanitizer) -> None:
        msgs = [{"role": "user", "content": 'password = "supersecretpassword123"'}]
        result = sanitizer.sanitize_conversations(msgs)
        assert "supersecret" not in result[0]["content"]

    def test_strip_bearer_jwt(self, sanitizer: DataSanitizer) -> None:
        jwt = "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkw"
        msgs = [{"role": "user", "content": jwt}]
        result = sanitizer.sanitize_conversations(msgs)
        assert "eyJ" not in result[0]["content"]

    def test_strip_slack_token(self, sanitizer: DataSanitizer) -> None:
        msgs = [{"role": "user", "content": "xoxb-1234-abcdef-ghijklmn"}]
        result = sanitizer.sanitize_conversations(msgs)
        assert "xoxb-" not in result[0]["content"]

    def test_strip_pii_path(self, sanitizer: DataSanitizer) -> None:
        msgs = [{"role": "user", "content": "file at /Users/johnsmith/docs/secret.txt"}]
        result = sanitizer.sanitize_conversations(msgs)
        assert "johnsmith" not in result[0]["content"]
        assert "/REDACTED_PATH" in result[0]["content"]

    def test_strip_pii_email(self, sanitizer: DataSanitizer) -> None:
        msgs = [{"role": "user", "content": "send to john.doe@company.com"}]
        result = sanitizer.sanitize_conversations(msgs)
        assert "john.doe@company.com" not in result[0]["content"]
        assert "[EMAIL]" in result[0]["content"]

    def test_truncate_large_content(self, sanitizer: DataSanitizer) -> None:
        large = "x" * 5000
        msgs = [{"role": "tool", "content": large, "tool_call_id": "tc1"}]
        result = sanitizer.sanitize_conversations(msgs)
        assert len(result[0]["content"]) < 5000
        assert "[...truncated]" in result[0]["content"]

    def test_strip_browser_tool_calls(self, sanitizer: DataSanitizer) -> None:
        msgs = [
            {"role": "user", "content": "search google"},
            {
                "role": "assistant",
                "content": "I'll browse for you",
                "tool_calls": [
                    {
                        "id": "tc_browser",
                        "function": {"name": "browser_navigate", "arguments": "{}"},
                    },
                    {
                        "id": "tc_shell",
                        "function": {"name": "shell_execute", "arguments": "{}"},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "tc_browser", "content": "page loaded"},
            {"role": "tool", "tool_call_id": "tc_shell", "content": "output"},
        ]
        result = sanitizer.sanitize_conversations(msgs)
        # Browser tool call should be removed from assistant message
        assistant = result[1]
        assert len(assistant["tool_calls"]) == 1
        assert assistant["tool_calls"][0]["function"]["name"] == "shell_execute"
        # Browser tool response should be dropped
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "tc_shell"

    def test_drop_assistant_if_only_browser_calls(
        self, sanitizer: DataSanitizer
    ) -> None:
        msgs = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "tc1",
                        "function": {"name": "browser_click", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "tc1", "content": "clicked"},
        ]
        result = sanitizer.sanitize_conversations(msgs)
        assert len(result) == 0

    def test_no_browser_filter_when_disabled(self, config: SelfLearningConfig) -> None:
        config.privacy.exclude_browser_data = False
        sanitizer = DataSanitizer(config)
        msgs = [
            {
                "role": "assistant",
                "content": "browsing",
                "tool_calls": [
                    {
                        "id": "tc1",
                        "function": {"name": "browser_navigate", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "tc1", "content": "page loaded"},
        ]
        result = sanitizer.sanitize_conversations(msgs)
        assert len(result) == 2  # both messages kept

    def test_sanitize_tool_call_arguments(self, sanitizer: DataSanitizer) -> None:
        msgs = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "tc1",
                        "function": {
                            "name": "shell_execute",
                            "arguments": '{"command": "export TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef1234"}',
                        },
                    }
                ],
            }
        ]
        result = sanitizer.sanitize_conversations(msgs)
        args = result[0]["tool_calls"][0]["function"]["arguments"]
        assert "ghp_" not in args

    def test_preserves_non_secret_content(self, sanitizer: DataSanitizer) -> None:
        msgs = [{"role": "user", "content": "list all files in the project"}]
        result = sanitizer.sanitize_conversations(msgs)
        assert result[0]["content"] == "list all files in the project"

    def test_no_strip_when_disabled(self) -> None:
        config = SelfLearningConfig(
            privacy=SelfLearningPrivacyConfig(
                strip_credentials=False,
                strip_pii=False,
                strip_file_contents=False,
                exclude_browser_data=False,
            )
        )
        sanitizer = DataSanitizer(config)
        secret = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef1234"
        msgs = [{"role": "user", "content": secret}]
        result = sanitizer.sanitize_conversations(msgs)
        assert secret in result[0]["content"]


# ---------------------------------------------------------------------------
# QualityFilter tests
# ---------------------------------------------------------------------------


class TestQualityFilter:
    """Test quality filtering criteria."""

    def test_accept_failed_task_by_default(self, quality_filter: QualityFilter) -> None:
        """Default config now collects failures for negative examples."""
        msgs = [
            {"role": "user", "content": "do something"},
            {"role": "assistant", "content": "I'll try"},
            {"role": "assistant", "content": "failed"},
        ]
        assert quality_filter.should_collect(msgs, ["shell_execute"], success=False)

    def test_reject_failed_when_success_only(
        self, config_strict: SelfLearningConfig
    ) -> None:
        qf = QualityFilter(config_strict)
        msgs = [
            {"role": "user", "content": "do something"},
            {"role": "assistant", "content": "I'll try"},
            {"role": "assistant", "content": "failed"},
        ]
        assert not qf.should_collect(msgs, ["shell_execute"], success=False)

    def test_reject_single_turn(self, quality_filter: QualityFilter) -> None:
        """Single message is below min_turns=2."""
        msgs = [{"role": "user", "content": "hi"}]
        assert not quality_filter.should_collect(msgs, ["shell_execute"], success=True)

    def test_accept_without_tool_calls(self, quality_filter: QualityFilter) -> None:
        """Pure text conversations are now collected for sentiment data."""
        msgs = [
            {"role": "user", "content": "what is 2+2?"},
            {"role": "assistant", "content": "4"},
        ]
        assert quality_filter.should_collect(msgs, [], success=True)

    def test_accept_valid_interaction(self, quality_filter: QualityFilter) -> None:
        msgs = [
            {"role": "user", "content": "list files"},
            {"role": "assistant", "content": "I'll use shell"},
            {"role": "tool", "content": "file1.py"},
            {"role": "assistant", "content": "Found file1.py"},
        ]
        assert quality_filter.should_collect(msgs, ["shell_execute"], success=True)

    def test_accept_two_turn_conversation(self, quality_filter: QualityFilter) -> None:
        """min_turns=2 means a single user+assistant exchange is enough."""
        msgs = [
            {"role": "user", "content": "thanks that worked perfectly"},
            {"role": "assistant", "content": "glad to help"},
        ]
        assert quality_filter.should_collect(msgs, [], success=True)


# ---------------------------------------------------------------------------
# Signal extraction tests
# ---------------------------------------------------------------------------


class TestExtractSignals:
    """Test the _extract_signals helper."""

    def test_positive_sentiment(self) -> None:
        msgs = [
            {"role": "user", "content": "list files"},
            {"role": "assistant", "content": "here they are"},
            {"role": "user", "content": "thanks, perfect!"},
        ]
        signals = _extract_signals(msgs)
        assert signals["user_sentiment"] == "positive"
        assert signals["turn_count"] == 3

    def test_negative_sentiment(self) -> None:
        msgs = [
            {"role": "user", "content": "fix the bug"},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "wrong, that doesn't work"},
        ]
        signals = _extract_signals(msgs)
        assert signals["user_sentiment"] == "negative"

    def test_neutral_sentiment(self) -> None:
        msgs = [
            {"role": "user", "content": "list files"},
            {"role": "assistant", "content": "file1.py"},
        ]
        signals = _extract_signals(msgs)
        assert signals["user_sentiment"] == "neutral"

    def test_detects_denials(self) -> None:
        msgs = [
            {"role": "assistant", "content": "running command"},
            {"role": "tool", "content": "permission denied: cannot access /root"},
        ]
        signals = _extract_signals(msgs)
        assert signals["has_denials"] is True

    def test_detects_errors(self) -> None:
        msgs = [
            {"role": "assistant", "content": "I encountered an error while running"},
            {"role": "tool", "content": "Traceback: file not found"},
        ]
        signals = _extract_signals(msgs)
        assert signals["has_errors"] is True

    def test_no_signals(self) -> None:
        msgs = [
            {"role": "user", "content": "list files"},
            {"role": "assistant", "content": "here they are"},
        ]
        signals = _extract_signals(msgs)
        assert signals["has_denials"] is False
        assert signals["has_errors"] is False
        assert signals["user_sentiment"] == "neutral"


# ---------------------------------------------------------------------------
# DatasetBuilder tests
# ---------------------------------------------------------------------------


class TestDatasetBuilder:
    """Test the full dataset builder pipeline."""

    @pytest.mark.asyncio
    async def test_record_task_stores_in_db(
        self, builder: DatasetBuilder, mock_db: MagicMock
    ) -> None:
        msgs = [
            {"role": "system", "content": "You are EloPhanto"},
            {"role": "user", "content": "list files"},
            {"role": "assistant", "content": "running shell"},
            {"role": "tool", "content": "file1.py", "tool_call_id": "tc1"},
            {"role": "assistant", "content": "Found file1.py"},
        ]
        await builder.record_task(
            messages=msgs,
            tool_calls_made=["shell_execute"],
            success=True,
            duration_seconds=2.5,
            model_used="test-model",
        )
        mock_db.execute_insert.assert_called()
        call_args = mock_db.execute_insert.call_args[0]
        assert "INSERT" in call_args[0]
        assert "collect_examples" in call_args[0]

    @pytest.mark.asyncio
    async def test_record_task_skips_when_filtered(
        self, builder: DatasetBuilder, mock_db: MagicMock
    ) -> None:
        """Single turn (below min_turns=2) should be skipped."""
        msgs = [
            {"role": "user", "content": "hi"},
        ]
        await builder.record_task(
            messages=msgs,
            tool_calls_made=[],
            success=True,
            duration_seconds=1.0,
            model_used="test-model",
        )
        mock_db.execute_insert.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_upload_triggers_at_threshold(
        self, builder: DatasetBuilder, mock_db: MagicMock
    ) -> None:
        # Simulate buffer count at threshold
        mock_db.execute.return_value = [{"cnt": 3}]

        # Write key file so upload doesn't need registration
        (builder._data_dir / ".collect_key").write_text("elp_testkey123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "accepted": 1,
            "rejected": 0,
            "reasons": [],
            "dataset_size": 100,
        }
        mock_response.raise_for_status = MagicMock()

        # Mock the upload HTTP call
        with patch("core.dataset_builder.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            # Provide rows for the upload query
            mock_db.execute.side_effect = [
                [{"cnt": 3}],  # count query
                [  # select pending examples
                    {
                        "id": "test-id",
                        "conversations_json": "[]",
                        "metadata_json": "{}",
                    }
                ],
            ]

            msgs = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "do task"},
                {"role": "assistant", "content": "running"},
                {"role": "tool", "content": "done", "tool_call_id": "tc1"},
                {"role": "assistant", "content": "complete"},
            ]
            await builder.record_task(
                messages=msgs,
                tool_calls_made=["shell_execute"],
                success=True,
                duration_seconds=3.0,
                model_used="test-model",
            )

            # Verify upload was attempted
            mock_client.post.assert_called()

    @pytest.mark.asyncio
    async def test_register_stores_key_file(
        self, builder: DatasetBuilder, tmp_path: Path
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "api_key": "elp_testkey123",
            "agent_id": "sha256:abc",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("core.dataset_builder.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            key = await builder._register()

        assert key == "elp_testkey123"
        key_file = tmp_path / ".collect_key"
        assert key_file.exists()
        assert key_file.read_text() == "elp_testkey123"

    @pytest.mark.asyncio
    async def test_401_clears_key(
        self, builder: DatasetBuilder, mock_db: MagicMock, tmp_path: Path
    ) -> None:
        key_file = tmp_path / ".collect_key"
        key_file.write_text("elp_old_key")
        builder._api_key = "elp_old_key"

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status = MagicMock(side_effect=Exception("401"))

        mock_db.execute.return_value = [
            {"id": "t1", "conversations_json": "[]", "metadata_json": "{}"}
        ]

        with patch("core.dataset_builder.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            await builder._upload_batch()

        assert builder._api_key is None
        assert not key_file.exists()

    @pytest.mark.asyncio
    async def test_record_task_never_raises(
        self, builder: DatasetBuilder, mock_db: MagicMock
    ) -> None:
        """record_task must be exception-safe for fire-and-forget usage."""
        mock_db.execute_insert.side_effect = RuntimeError("DB exploded")
        msgs = [
            {"role": "user", "content": "do task"},
            {"role": "assistant", "content": "running"},
            {"role": "tool", "content": "done", "tool_call_id": "tc1"},
            {"role": "assistant", "content": "complete"},
        ]
        # Should not raise
        await builder.record_task(
            messages=msgs,
            tool_calls_made=["shell_execute"],
            success=True,
            duration_seconds=1.0,
            model_used="test-model",
        )

    @pytest.mark.asyncio
    async def test_flush_calls_upload(
        self, builder: DatasetBuilder, tmp_path: Path, mock_db: MagicMock
    ) -> None:
        (tmp_path / ".collect_key").write_text("elp_testkey123")
        mock_db.execute.return_value = []  # no pending examples

        await builder.flush()
        # Should not error even with no pending examples

    @pytest.mark.asyncio
    async def test_recover_on_409(
        self, builder: DatasetBuilder, tmp_path: Path
    ) -> None:
        register_response = MagicMock()
        register_response.status_code = 409

        recover_response = MagicMock()
        recover_response.status_code = 200
        recover_response.json.return_value = {"api_key": "elp_recovered"}

        with patch("core.dataset_builder.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=[register_response, recover_response]
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            key = await builder._register()

        assert key == "elp_recovered"
        assert (tmp_path / ".collect_key").read_text() == "elp_recovered"

    @pytest.mark.asyncio
    async def test_sanitized_data_in_db(
        self, builder: DatasetBuilder, mock_db: MagicMock
    ) -> None:
        """Verify that secrets are stripped before storing in local DB."""
        msgs = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "use ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef1234"},
            {"role": "assistant", "content": "running shell"},
            {"role": "tool", "content": "output", "tool_call_id": "tc1"},
            {"role": "assistant", "content": "done"},
        ]
        await builder.record_task(
            messages=msgs,
            tool_calls_made=["shell_execute"],
            success=True,
            duration_seconds=2.0,
            model_used="test-model",
        )
        # Check what was inserted
        call_args = mock_db.execute_insert.call_args[0]
        conversations_json = call_args[1][1]  # second param is conversations_json
        assert "ghp_" not in conversations_json
        assert "[REDACTED]" in conversations_json

    @pytest.mark.asyncio
    async def test_rich_metadata_in_db(
        self, builder: DatasetBuilder, mock_db: MagicMock
    ) -> None:
        """Verify that enriched metadata is stored (sentiment, denials, errors)."""
        msgs = [
            {"role": "user", "content": "fix the bug"},
            {"role": "assistant", "content": "running command"},
            {"role": "tool", "content": "error: file not found", "tool_call_id": "tc1"},
            {"role": "assistant", "content": "I encountered an error"},
            {"role": "user", "content": "wrong, that doesn't work at all"},
        ]
        await builder.record_task(
            messages=msgs,
            tool_calls_made=["shell_execute"],
            success=False,
            duration_seconds=5.0,
            model_used="test-model",
        )
        call_args = mock_db.execute_insert.call_args[0]
        metadata_json = call_args[1][2]  # third param is metadata_json
        metadata = json.loads(metadata_json)
        assert metadata["has_errors"] is True
        assert metadata["user_sentiment"] == "negative"
        assert metadata["turn_count"] == 4
        assert metadata["has_tool_use"] is True

    @pytest.mark.asyncio
    async def test_collects_pure_text_conversation(
        self, builder: DatasetBuilder, mock_db: MagicMock
    ) -> None:
        """Pure text conversations without tool use should now be collected."""
        msgs = [
            {"role": "user", "content": "thanks that was perfect!"},
            {"role": "assistant", "content": "glad to help"},
        ]
        await builder.record_task(
            messages=msgs,
            tool_calls_made=[],
            success=True,
            duration_seconds=1.0,
            model_used="test-model",
        )
        mock_db.execute_insert.assert_called()
        call_args = mock_db.execute_insert.call_args[0]
        metadata_json = call_args[1][2]
        metadata = json.loads(metadata_json)
        assert metadata["has_tool_use"] is False
        assert metadata["user_sentiment"] == "positive"
