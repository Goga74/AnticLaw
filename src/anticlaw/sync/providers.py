"""LLM API adapters for bidirectional sync.

Each adapter sends conversation messages to a cloud LLM API and returns
the assistant response. API keys are read from the system keyring.

WARNING: Cloud API access requires SEPARATE paid API keys.
- Claude: https://console.anthropic.com/settings/keys (pay-per-token)
- ChatGPT: https://platform.openai.com/api-keys (pay-per-token)
- Gemini: https://aistudio.google.com/apikey (FREE tier: 15 RPM, 1M tokens/day)
- Ollama: No key needed — runs locally at localhost:11434 (FREE)

Web subscriptions (Claude Pro, ChatGPT Plus) do NOT provide API access.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)


@dataclass
class SyncProviderInfo:
    """Metadata about a sync provider."""

    name: str
    display_name: str
    requires_api_key: bool
    key_url: str = ""
    free_tier: bool = False


@runtime_checkable
class SyncProvider(Protocol):
    """Contract for LLM API adapters used in bidirectional sync."""

    @property
    def name(self) -> str:
        """Provider ID: 'claude', 'chatgpt', 'gemini', 'ollama'."""
        ...

    @property
    def info(self) -> SyncProviderInfo:
        """Provider metadata."""
        ...

    def send(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
    ) -> str:
        """Send messages to the LLM API and return the assistant response.

        Args:
            messages: List of {"role": "human"|"assistant", "content": "..."}.
            model: Optional model override.

        Returns:
            The assistant's response text.

        Raises:
            SyncAuthError: Missing or invalid API key.
            SyncAPIError: API returned an error.
        """
        ...

    def is_available(self) -> bool:
        """Check if the provider is reachable and authenticated."""
        ...


class SyncError(Exception):
    """Base error for sync operations."""


class SyncAuthError(SyncError):
    """Missing or invalid API key."""


class SyncAPIError(SyncError):
    """API returned an error."""


def _get_api_key(service: str) -> str | None:
    """Retrieve an API key from the system keyring."""
    try:
        import keyring

        return keyring.get_password("anticlaw", service)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Claude API adapter (Anthropic Messages API)
# ---------------------------------------------------------------------------


class ClaudeAPI:
    """Send messages to Claude via the Anthropic Messages API."""

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        self._model = config.get("model", "claude-sonnet-4-20250514")
        self._api_key = config.get("api_key") or _get_api_key("claude_api_key")
        self._base_url = config.get(
            "base_url", "https://api.anthropic.com"
        ).rstrip("/")
        self._max_tokens = config.get("max_tokens", 4096)

    @property
    def name(self) -> str:
        return "claude"

    @property
    def info(self) -> SyncProviderInfo:
        return SyncProviderInfo(
            name="claude",
            display_name="Claude (Anthropic)",
            requires_api_key=True,
            key_url="https://console.anthropic.com/settings/keys",
        )

    def send(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
    ) -> str:
        if not self._api_key:
            raise SyncAuthError(
                "No API key configured for Claude.\n"
                "Claude API access requires an Anthropic API key "
                "(separate from Claude Pro subscription).\n"
                "Get your key at: https://console.anthropic.com/settings/keys\n"
                "Then store it: python -c "
                "\"import keyring; keyring.set_password('anticlaw', 'claude_api_key', 'YOUR_KEY')\""
            )

        import httpx

        api_messages = [
            {"role": "user" if m["role"] == "human" else "assistant", "content": m["content"]}
            for m in messages
        ]

        try:
            resp = httpx.post(
                f"{self._base_url}/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model or self._model,
                    "max_tokens": self._max_tokens,
                    "messages": api_messages,
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()
            # Anthropic response: {"content": [{"type": "text", "text": "..."}]}
            content_blocks = data.get("content", [])
            return "\n".join(
                b.get("text", "") for b in content_blocks if b.get("type") == "text"
            ).strip()
        except httpx.HTTPStatusError as e:
            raise SyncAPIError(f"Claude API error ({e.response.status_code}): {e}") from e
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as e:
            raise SyncAPIError(f"Claude API unreachable: {e}") from e

    def is_available(self) -> bool:
        return bool(self._api_key)


# ---------------------------------------------------------------------------
# OpenAI API adapter (Chat Completions)
# ---------------------------------------------------------------------------


class OpenAIAPI:
    """Send messages to ChatGPT via the OpenAI Chat Completions API."""

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        self._model = config.get("model", "gpt-4o-mini")
        self._api_key = config.get("api_key") or _get_api_key("openai_api_key")
        self._base_url = config.get(
            "base_url", "https://api.openai.com"
        ).rstrip("/")

    @property
    def name(self) -> str:
        return "chatgpt"

    @property
    def info(self) -> SyncProviderInfo:
        return SyncProviderInfo(
            name="chatgpt",
            display_name="ChatGPT (OpenAI)",
            requires_api_key=True,
            key_url="https://platform.openai.com/api-keys",
        )

    def send(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
    ) -> str:
        if not self._api_key:
            raise SyncAuthError(
                "No API key configured for ChatGPT.\n"
                "OpenAI API access requires a separate API key "
                "(NOT included with ChatGPT Plus subscription).\n"
                "Get your key at: https://platform.openai.com/api-keys\n"
                "Then store it: python -c "
                "\"import keyring; keyring.set_password('anticlaw', 'openai_api_key', 'YOUR_KEY')\""
            )

        import httpx

        api_messages = [
            {"role": "user" if m["role"] == "human" else "assistant", "content": m["content"]}
            for m in messages
        ]

        try:
            resp = httpx.post(
                f"{self._base_url}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model or self._model,
                    "messages": api_messages,
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "").strip()
            return ""
        except httpx.HTTPStatusError as e:
            raise SyncAPIError(f"OpenAI API error ({e.response.status_code}): {e}") from e
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as e:
            raise SyncAPIError(f"OpenAI API unreachable: {e}") from e

    def is_available(self) -> bool:
        return bool(self._api_key)


# ---------------------------------------------------------------------------
# Gemini API adapter (Google Generative AI)
# ---------------------------------------------------------------------------


class GeminiAPI:
    """Send messages to Gemini via the Google Generative AI REST API.

    FREE tier: 15 requests/minute, 1M tokens/day (Gemini Flash).
    """

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        self._model = config.get("model", "gemini-2.0-flash")
        self._api_key = config.get("api_key") or _get_api_key("gemini_api_key")
        self._base_url = config.get(
            "base_url", "https://generativelanguage.googleapis.com"
        ).rstrip("/")

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def info(self) -> SyncProviderInfo:
        return SyncProviderInfo(
            name="gemini",
            display_name="Gemini (Google)",
            requires_api_key=True,
            key_url="https://aistudio.google.com/apikey",
            free_tier=True,
        )

    def send(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
    ) -> str:
        if not self._api_key:
            raise SyncAuthError(
                "No API key configured for Gemini.\n"
                "Get a FREE API key at: https://aistudio.google.com/apikey\n"
                "Free tier: 15 requests/minute, 1M tokens/day.\n"
                "Then store it: python -c "
                "\"import keyring; keyring.set_password('anticlaw', 'gemini_api_key', 'YOUR_KEY')\""
            )

        import httpx

        # Convert to Gemini format: {"contents": [{"role": "user"|"model", "parts": [...]}]}
        contents = []
        for m in messages:
            role = "user" if m["role"] == "human" else "model"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})

        use_model = model or self._model
        url = (
            f"{self._base_url}/v1beta/models/{use_model}:generateContent"
            f"?key={self._api_key}"
        )

        try:
            resp = httpx.post(
                url,
                headers={"Content-Type": "application/json"},
                json={"contents": contents},
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()
            # Gemini response: {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                return "\n".join(p.get("text", "") for p in parts).strip()
            return ""
        except httpx.HTTPStatusError as e:
            raise SyncAPIError(f"Gemini API error ({e.response.status_code}): {e}") from e
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as e:
            raise SyncAPIError(f"Gemini API unreachable: {e}") from e

    def is_available(self) -> bool:
        return bool(self._api_key)


# ---------------------------------------------------------------------------
# Ollama local adapter
# ---------------------------------------------------------------------------


class OllamaLocal:
    """Send messages to a local Ollama instance. No API key needed."""

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        self._model = config.get("model", "llama3.1:8b")
        self._base_url = config.get("base_url", "http://localhost:11434").rstrip("/")
        self._timeout = config.get("timeout", 120.0)

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def info(self) -> SyncProviderInfo:
        return SyncProviderInfo(
            name="ollama",
            display_name="Ollama (local)",
            requires_api_key=False,
            free_tier=True,
        )

    def send(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
    ) -> str:
        import httpx

        # Convert to Ollama /api/chat format
        api_messages = [
            {"role": "user" if m["role"] == "human" else "assistant", "content": m["content"]}
            for m in messages
        ]

        try:
            resp = httpx.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": model or self._model,
                    "messages": api_messages,
                    "stream": False,
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "").strip()
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as e:
            raise SyncAPIError(
                f"Ollama not reachable at {self._base_url}. "
                f"Is Ollama running? Start with: ollama serve\n{e}"
            ) from e
        except httpx.HTTPStatusError as e:
            raise SyncAPIError(f"Ollama API error ({e.response.status_code}): {e}") from e

    def is_available(self) -> bool:
        try:
            import httpx

            resp = httpx.get(f"{self._base_url}/api/tags", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, type] = {
    "claude": ClaudeAPI,
    "chatgpt": OpenAIAPI,
    "gemini": GeminiAPI,
    "ollama": OllamaLocal,
}


def get_sync_provider(name: str, config: dict | None = None) -> SyncProvider:
    """Get a sync provider instance by name.

    Args:
        name: Provider name ('claude', 'chatgpt', 'gemini', 'ollama').
        config: Provider-specific configuration overrides.

    Returns:
        Configured SyncProvider instance.

    Raises:
        ValueError: Unknown provider name.
    """
    cls = _PROVIDERS.get(name)
    if cls is None:
        available = ", ".join(sorted(_PROVIDERS.keys()))
        raise ValueError(f"Unknown sync provider '{name}'. Available: {available}")
    return cls(config)


def list_sync_providers() -> list[str]:
    """Return all available sync provider names."""
    return sorted(_PROVIDERS.keys())
