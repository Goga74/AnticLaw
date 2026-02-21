"""EmbeddingProvider Protocol and types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class EmbeddingInfo:
    """Metadata about an embedding provider."""

    display_name: str
    version: str
    dimensions: int
    max_tokens: int
    is_local: bool
    requires_auth: bool


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Contract for embedding generation.

    Implementations: OllamaEmbeddingProvider, OpenAIEmbeddingProvider, etc.
    """

    @property
    def name(self) -> str:
        """Unique provider ID: 'ollama', 'openai', 'local-model'."""
        ...

    @property
    def info(self) -> EmbeddingInfo:
        """Provider metadata."""
        ...

    def embed(self, text: str) -> list[float]:
        """Embed a single text. Returns vector."""
        ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts. Returns list of vectors."""
        ...
