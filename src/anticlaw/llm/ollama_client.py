"""Ollama HTTP API client for local LLM operations."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class OllamaError(Exception):
    """Raised when Ollama API returns an error."""


class OllamaNotAvailableError(OllamaError):
    """Raised when Ollama server is not reachable."""


class OllamaClient:
    """Wrapper around Ollama HTTP API (localhost:11434).

    Provides generate() for text generation and available_models() for
    listing installed models. Graceful fallback when Ollama is not running.
    """

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        self._model = config.get("model", "llama3.1:8b")
        self._base_url = config.get("base_url", "http://localhost:11434").rstrip("/")
        self._timeout = config.get("timeout", 120.0)

    @property
    def model(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        return self._base_url

    def is_available(self) -> bool:
        """Check if Ollama server is reachable."""
        import httpx

        try:
            resp = httpx.get(f"{self._base_url}/api/tags", timeout=5.0)
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            return False

    def available_models(self) -> list[str]:
        """Return list of installed model names."""
        import httpx

        try:
            resp = httpx.get(f"{self._base_url}/api/tags", timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as e:
            raise OllamaNotAvailableError(
                f"Ollama not reachable at {self._base_url}: {e}"
            ) from e
        except httpx.HTTPStatusError as e:
            raise OllamaError(f"Ollama API error: {e}") from e

    def generate(self, prompt: str, model: str | None = None) -> str:
        """Generate text from a prompt via Ollama /api/generate.

        Args:
            prompt: The prompt to send to the model.
            model: Override the default model for this call.

        Returns:
            Generated text response.

        Raises:
            OllamaNotAvailableError: If Ollama server is not reachable.
            OllamaError: If the API returns an error.
        """
        import httpx

        use_model = model or self._model
        try:
            resp = httpx.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": use_model,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "").strip()
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as e:
            raise OllamaNotAvailableError(
                f"Ollama not reachable at {self._base_url}: {e}"
            ) from e
        except httpx.HTTPStatusError as e:
            raise OllamaError(f"Ollama API error: {e}") from e
