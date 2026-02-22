"""Embedding clients for generating vector embeddings.

Supports Ollama (local) and OpenRouter (cloud) providers.
Both return EmbeddingResult dataclasses with the same interface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingResult:
    """Result of an embedding operation."""

    vector: list[float]
    model: str
    dimensions: int


class OllamaEmbedder:
    """Generates embeddings via Ollama's local API."""

    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=30.0)

    async def embed(
        self, text: str, model: str = "nomic-embed-text"
    ) -> EmbeddingResult:
        """Embed a single text string."""
        response = await self._client.post(
            f"{self._base_url}/api/embeddings",
            json={"model": model, "prompt": text},
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Ollama embedding failed ({response.status_code}): {response.text[:200]}"
            )

        data: dict[str, Any] = response.json()
        vector = data["embedding"]
        return EmbeddingResult(
            vector=vector,
            model=model,
            dimensions=len(vector),
        )

    async def embed_batch(
        self, texts: list[str], model: str = "nomic-embed-text"
    ) -> list[EmbeddingResult]:
        """Embed multiple texts sequentially."""
        results: list[EmbeddingResult] = []
        for text in texts:
            result = await self.embed(text, model)
            results.append(result)
        return results

    async def detect_model(
        self, primary: str = "nomic-embed-text", fallback: str = "mxbai-embed-large"
    ) -> tuple[str, int]:
        """Detect which embedding model is available.

        Returns:
            Tuple of (model_name, dimensions).
        """
        for model in [primary, fallback]:
            try:
                result = await self.embed("test", model)
                logger.info(f"Embedding model detected: {model} ({result.dimensions}d)")
                return model, result.dimensions
            except Exception:
                continue

        raise RuntimeError(
            f"No embedding model available. Install one with: ollama pull {primary}"
        )


# Backward-compatible alias
EmbeddingClient = OllamaEmbedder


class OpenRouterEmbedder:
    """Generates embeddings via OpenRouter's API (OpenAI-compatible)."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        default_model: str = "qwen/qwen3-embedding-8b",
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._client = httpx.AsyncClient(timeout=30.0)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "HTTP-Referer": "https://github.com/elophanto",
            "X-Title": "EloPhanto",
            "Content-Type": "application/json",
        }

    async def embed(self, text: str, model: str | None = None) -> EmbeddingResult:
        """Embed a single text string via OpenRouter."""
        model = model or self._default_model
        response = await self._client.post(
            f"{self._base_url}/embeddings",
            headers=self._headers(),
            json={"model": model, "input": text},
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"OpenRouter embedding failed ({response.status_code}): "
                f"{response.text[:200]}"
            )

        data: dict[str, Any] = response.json()
        vector = data["data"][0]["embedding"]
        return EmbeddingResult(
            vector=vector,
            model=model,
            dimensions=len(vector),
        )

    async def embed_batch(
        self, texts: list[str], model: str | None = None
    ) -> list[EmbeddingResult]:
        """Embed multiple texts. Uses batch input when possible."""
        model = model or self._default_model
        response = await self._client.post(
            f"{self._base_url}/embeddings",
            headers=self._headers(),
            json={"model": model, "input": texts},
            timeout=60.0,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"OpenRouter embedding failed ({response.status_code}): "
                f"{response.text[:200]}"
            )

        data: dict[str, Any] = response.json()
        return [
            EmbeddingResult(
                vector=item["embedding"],
                model=model,
                dimensions=len(item["embedding"]),
            )
            for item in data["data"]
        ]

    async def detect_model(
        self, primary: str | None = None, fallback: str | None = None
    ) -> tuple[str, int]:
        """Verify the configured model works by doing a test embed.

        Returns:
            Tuple of (model_name, dimensions).
        """
        model = primary or self._default_model
        models_to_try = [model]
        if fallback:
            models_to_try.append(fallback)

        for m in models_to_try:
            try:
                result = await self.embed("test", m)
                logger.info(
                    f"OpenRouter embedding model verified: {m} ({result.dimensions}d)"
                )
                return m, result.dimensions
            except Exception:
                continue

        raise RuntimeError(
            f"No OpenRouter embedding model available. Tried: {models_to_try}"
        )


def _create_openrouter_embedder(config: Any) -> OpenRouterEmbedder | None:
    """Try to create an OpenRouter embedder. Returns None if not configured."""
    or_cfg = config.llm.providers.get("openrouter")
    if not or_cfg or not or_cfg.api_key or not or_cfg.enabled:
        return None
    base_url = or_cfg.base_url or "https://openrouter.ai/api/v1"
    return OpenRouterEmbedder(
        api_key=or_cfg.api_key,
        base_url=base_url,
        default_model=config.knowledge.embedding_openrouter_model,
    )


def _create_ollama_embedder(config: Any) -> OllamaEmbedder:
    """Create an Ollama embedder (always available as local fallback)."""
    ollama_cfg = config.llm.providers.get("ollama")
    ollama_url = ollama_cfg.base_url if ollama_cfg else "http://localhost:11434"
    return OllamaEmbedder(base_url=ollama_url)


def create_embedder(config: Any) -> OllamaEmbedder | OpenRouterEmbedder:
    """Factory: create the right embedder based on config.

    Default priority: OpenRouter (fast cloud) → Ollama (local fallback).
    The ``embedding_provider`` config can override to force a specific provider.

    Args:
        config: The full Config object.

    Returns:
        An embedder instance (OpenRouterEmbedder or OllamaEmbedder).
    """
    provider = config.knowledge.embedding_provider

    if provider == "openrouter":
        embedder = _create_openrouter_embedder(config)
        if embedder:
            return embedder
        logger.warning(
            "OpenRouter embedding requested but no API key configured, "
            "falling back to Ollama"
        )
        return _create_ollama_embedder(config)

    if provider == "ollama":
        return _create_ollama_embedder(config)

    # "auto" (default): prefer OpenRouter if configured, else Ollama
    embedder = _create_openrouter_embedder(config)
    if embedder:
        logger.info("Using OpenRouter for embeddings (fast cloud)")
        return embedder
    logger.info("Using Ollama for embeddings (local)")
    return _create_ollama_embedder(config)
