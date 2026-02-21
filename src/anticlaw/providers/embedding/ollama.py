"""Ollama embedding provider (nomic-embed-text via HTTP API)."""

from __future__ import annotations

import logging

from anticlaw.providers.embedding.base import EmbeddingInfo

log = logging.getLogger(__name__)


class OllamaEmbeddingProvider:
    """Generate embeddings via Ollama HTTP API.

    Uses the /api/embed endpoint (Ollama 0.4+) which supports
    both single and batch embedding.

    Default model: nomic-embed-text (768-dim, ~275 MB).
    """

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        self._model = config.get("model", "nomic-embed-text")
        self._base_url = config.get("base_url", "http://localhost:11434").rstrip("/")
        self._dimensions = config.get("dimensions", 768)

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def info(self) -> EmbeddingInfo:
        return EmbeddingInfo(
            display_name=f"Ollama ({self._model})",
            version="1.0.0",
            dimensions=self._dimensions,
            max_tokens=8192,
            is_local=True,
            requires_auth=False,
        )

    def embed(self, text: str) -> list[float]:
        """Embed a single text via Ollama /api/embed."""
        import httpx

        resp = httpx.post(
            f"{self._base_url}/api/embed",
            json={"model": self._model, "input": text},
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["embeddings"][0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in a single request."""
        import httpx

        if not texts:
            return []

        resp = httpx.post(
            f"{self._base_url}/api/embed",
            json={"model": self._model, "input": texts},
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["embeddings"]
