"""Embedding client tests with mocked APIs."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.embeddings import (
    EmbeddingClient,
    OllamaEmbedder,
    OpenRouterEmbedder,
    create_embedder,
)


def _ollama_response(vector: list[float], status: int = 200):
    """Create a mock Ollama httpx response."""
    mock = MagicMock()
    mock.status_code = status
    mock.json.return_value = {"embedding": vector}
    mock.text = json.dumps({"embedding": vector})
    return mock


def _openrouter_response(vectors: list[list[float]], status: int = 200):
    """Create a mock OpenRouter httpx response (OpenAI format)."""
    mock = MagicMock()
    mock.status_code = status
    data = {"data": [{"embedding": v} for v in vectors]}
    mock.json.return_value = data
    mock.text = json.dumps(data)
    return mock


def _mock_client(mock_response):
    """Create a mock httpx client with a .post() that returns mock_response."""
    mock_instance = AsyncMock()
    mock_instance.post.return_value = mock_response
    return mock_instance


class TestOllamaEmbedder:
    @pytest.mark.asyncio
    async def test_embed_returns_vector(self) -> None:
        """embed() returns correct vector and dimensions."""
        client = OllamaEmbedder()
        fake_vec = [0.1] * 768
        client._client = _mock_client(_ollama_response(fake_vec))

        result = await client.embed("test text")

        assert result.dimensions == 768
        assert len(result.vector) == 768
        assert result.model == "nomic-embed-text"

    @pytest.mark.asyncio
    async def test_embed_batch(self) -> None:
        """embed_batch() returns results for each text."""
        client = OllamaEmbedder()
        fake_vec = [0.2] * 768
        client._client = _mock_client(_ollama_response(fake_vec))

        results = await client.embed_batch(["text1", "text2"])

        assert len(results) == 2
        assert all(r.dimensions == 768 for r in results)

    @pytest.mark.asyncio
    async def test_embed_error_raises(self) -> None:
        """embed() raises on non-200 status."""
        client = OllamaEmbedder()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "model not found"
        client._client = _mock_client(mock_resp)

        with pytest.raises(RuntimeError, match="Ollama embedding failed"):
            await client.embed("test")

    @pytest.mark.asyncio
    async def test_detect_model_primary(self) -> None:
        """detect_model() returns primary model when available."""
        client = OllamaEmbedder()
        fake_vec = [0.1] * 768
        client._client = _mock_client(_ollama_response(fake_vec))

        model, dims = await client.detect_model()

        assert model == "nomic-embed-text"
        assert dims == 768

    @pytest.mark.asyncio
    async def test_detect_model_fallback(self) -> None:
        """detect_model() falls back to secondary model."""
        client = OllamaEmbedder()
        fake_vec = [0.1] * 1024
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Model not found")
            return _ollama_response(fake_vec)

        mock_instance = AsyncMock()
        mock_instance.post.side_effect = side_effect
        client._client = mock_instance

        model, dims = await client.detect_model()

        assert model == "mxbai-embed-large"
        assert dims == 1024

    def test_backward_compatible_alias(self) -> None:
        """EmbeddingClient is an alias for OllamaEmbedder."""
        assert EmbeddingClient is OllamaEmbedder


class TestOpenRouterEmbedder:
    @pytest.mark.asyncio
    async def test_embed_returns_vector(self) -> None:
        """embed() returns correct vector and dimensions."""
        client = OpenRouterEmbedder(api_key="test-key")
        fake_vec = [0.1] * 3072
        client._client = _mock_client(_openrouter_response([fake_vec]))

        result = await client.embed("test text")

        assert result.dimensions == 3072
        assert len(result.vector) == 3072
        assert result.model == "google/gemini-embedding-001"

    @pytest.mark.asyncio
    async def test_embed_batch(self) -> None:
        """embed_batch() returns results for all texts in one call."""
        client = OpenRouterEmbedder(api_key="test-key")
        fake_vecs = [[0.1] * 3072, [0.2] * 3072]
        client._client = _mock_client(_openrouter_response(fake_vecs))

        results = await client.embed_batch(["text1", "text2"])

        assert len(results) == 2
        assert all(r.dimensions == 3072 for r in results)

    @pytest.mark.asyncio
    async def test_embed_error_raises(self) -> None:
        """embed() raises on non-200 status."""
        client = OpenRouterEmbedder(api_key="test-key")
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "invalid api key"
        client._client = _mock_client(mock_resp)

        with pytest.raises(RuntimeError, match="OpenRouter embedding failed"):
            await client.embed("test")

    @pytest.mark.asyncio
    async def test_detect_model(self) -> None:
        """detect_model() verifies the configured model works."""
        client = OpenRouterEmbedder(api_key="test-key")
        fake_vec = [0.1] * 3072
        client._client = _mock_client(_openrouter_response([fake_vec]))

        model, dims = await client.detect_model()

        assert model == "google/gemini-embedding-001"
        assert dims == 3072

    @pytest.mark.asyncio
    async def test_sends_auth_headers(self) -> None:
        """embed() sends Authorization and app headers."""
        client = OpenRouterEmbedder(api_key="sk-test-123")
        fake_vec = [0.1] * 768
        client._client = _mock_client(_openrouter_response([fake_vec]))

        await client.embed("test")

        call_kwargs = client._client.post.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert headers["Authorization"] == "Bearer sk-test-123"
        assert "X-Title" in headers


class TestBatchResilience:
    @pytest.mark.asyncio
    async def test_batch_retries_on_missing_data_key(self) -> None:
        """embed_batch retries when OpenRouter returns 200 with no 'data' key.

        Mirrors the production failure mode observed 14× in the
        2026-05-22 log: Gemini-embedding returns 200 with an error
        envelope instead of the embeddings payload.
        """
        client = OpenRouterEmbedder(api_key="test-key")
        client._BATCH_RETRY_BASE_DELAY_SEC = 0.0  # speed up the test
        fake_vecs = [[0.1] * 3072, [0.2] * 3072]

        bad = MagicMock()
        bad.status_code = 200
        bad.json.return_value = {"error": {"message": "upstream timeout"}}
        bad.text = "{}"
        good = _openrouter_response(fake_vecs)

        mock_instance = AsyncMock()
        mock_instance.post.side_effect = [bad, good]
        client._client = mock_instance

        results = await client.embed_batch(["t1", "t2"])

        assert len(results) == 2
        assert mock_instance.post.call_count == 2

    @pytest.mark.asyncio
    async def test_batch_resilient_falls_back_per_text(self) -> None:
        """embed_batch_resilient falls back to per-text on persistent batch failure."""
        client = OpenRouterEmbedder(api_key="test-key")
        client._BATCH_RETRY_BASE_DELAY_SEC = 0.0
        fake_vec = [0.5] * 3072

        bad = MagicMock()
        bad.status_code = 200
        bad.json.return_value = {"error": "boom"}
        bad.text = "{}"
        good_single = _openrouter_response([fake_vec])

        mock_instance = AsyncMock()
        # 3 batch attempts fail, then 2 per-text calls succeed
        mock_instance.post.side_effect = [bad, bad, bad, good_single, good_single]
        client._client = mock_instance

        results = await client.embed_batch_resilient(["t1", "t2"])

        assert len(results) == 2
        assert all(r is not None for r in results)
        assert mock_instance.post.call_count == 5

    @pytest.mark.asyncio
    async def test_batch_resilient_returns_none_for_failed_chunk(self) -> None:
        """embed_batch_resilient returns None where a per-text fallback also fails."""
        client = OpenRouterEmbedder(api_key="test-key")
        client._BATCH_RETRY_BASE_DELAY_SEC = 0.0
        fake_vec = [0.5] * 3072

        bad_batch = MagicMock()
        bad_batch.status_code = 200
        bad_batch.json.return_value = {"error": "boom"}
        bad_batch.text = "{}"
        good_single = _openrouter_response([fake_vec])
        bad_single = MagicMock()
        bad_single.status_code = 500
        bad_single.text = "upstream 500"

        mock_instance = AsyncMock()
        mock_instance.post.side_effect = [
            bad_batch,
            bad_batch,
            bad_batch,  # batch retry exhausted
            good_single,  # text 1 succeeds
            bad_single,  # text 2 fails
        ]
        client._client = mock_instance

        results = await client.embed_batch_resilient(["t1", "t2"])

        assert results[0] is not None
        assert results[1] is None


class TestCreateEmbedder:
    def test_creates_ollama_by_default(self, test_config) -> None:
        """Factory creates OllamaEmbedder when provider is 'ollama'."""
        test_config.knowledge.embedding_provider = "ollama"
        embedder = create_embedder(test_config)
        assert isinstance(embedder, OllamaEmbedder)

    def test_creates_openrouter(self, test_config) -> None:
        """Factory creates OpenRouterEmbedder when provider is 'openrouter'."""
        from core.config import ProviderConfig

        test_config.knowledge.embedding_provider = "openrouter"
        test_config.llm.providers["openrouter"] = ProviderConfig(
            api_key="sk-test", enabled=True, base_url="https://openrouter.ai/api/v1"
        )
        embedder = create_embedder(test_config)
        assert isinstance(embedder, OpenRouterEmbedder)

    def test_openrouter_falls_back_to_ollama(self, test_config) -> None:
        """Factory falls back to Ollama when OpenRouter has no API key."""
        test_config.knowledge.embedding_provider = "openrouter"
        test_config.llm.providers.pop("openrouter", None)
        embedder = create_embedder(test_config)
        assert isinstance(embedder, OllamaEmbedder)

    def test_auto_prefers_openrouter(self, test_config) -> None:
        """Auto mode prefers OpenRouter when configured."""
        from core.config import ProviderConfig

        test_config.knowledge.embedding_provider = "auto"
        test_config.llm.providers["openrouter"] = ProviderConfig(
            api_key="sk-test", enabled=True, base_url="https://openrouter.ai/api/v1"
        )
        embedder = create_embedder(test_config)
        assert isinstance(embedder, OpenRouterEmbedder)

    def test_auto_falls_back_to_ollama(self, test_config) -> None:
        """Auto mode falls back to Ollama when OpenRouter not configured."""
        test_config.knowledge.embedding_provider = "auto"
        test_config.llm.providers.pop("openrouter", None)
        embedder = create_embedder(test_config)
        assert isinstance(embedder, OllamaEmbedder)
