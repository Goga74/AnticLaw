"""Tests for anticlaw.sync.providers — LLM API adapters."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from anticlaw.sync.providers import (
    ClaudeAPI,
    GeminiAPI,
    OllamaLocal,
    OpenAIAPI,
    SyncAPIError,
    SyncAuthError,
    get_sync_provider,
    list_sync_providers,
)

# ---------------------------------------------------------------------------
# Provider info & registry
# ---------------------------------------------------------------------------


class TestSyncProviderRegistry:
    def test_list_providers(self):
        providers = list_sync_providers()
        assert "claude" in providers
        assert "chatgpt" in providers
        assert "gemini" in providers
        assert "ollama" in providers

    def test_get_claude(self):
        p = get_sync_provider("claude", {"api_key": "test"})
        assert p.name == "claude"
        assert isinstance(p, ClaudeAPI)

    def test_get_chatgpt(self):
        p = get_sync_provider("chatgpt", {"api_key": "test"})
        assert p.name == "chatgpt"
        assert isinstance(p, OpenAIAPI)

    def test_get_gemini(self):
        p = get_sync_provider("gemini", {"api_key": "test"})
        assert p.name == "gemini"
        assert isinstance(p, GeminiAPI)

    def test_get_ollama(self):
        p = get_sync_provider("ollama")
        assert p.name == "ollama"
        assert isinstance(p, OllamaLocal)

    def test_get_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown sync provider"):
            get_sync_provider("unknown")


# ---------------------------------------------------------------------------
# ClaudeAPI
# ---------------------------------------------------------------------------


class TestClaudeAPI:
    def test_info(self):
        p = ClaudeAPI({"api_key": "sk-test"})
        info = p.info
        assert info.name == "claude"
        assert info.requires_api_key is True
        assert "anthropic" in info.key_url

    def test_is_available_with_key(self):
        p = ClaudeAPI({"api_key": "sk-test"})
        assert p.is_available() is True

    def test_is_available_without_key(self):
        # No keyring configured, so no key
        with patch("anticlaw.sync.providers._get_api_key", return_value=None):
            p = ClaudeAPI({})
        assert p.is_available() is False

    def test_send_no_key_raises(self):
        with patch("anticlaw.sync.providers._get_api_key", return_value=None):
            p = ClaudeAPI({})
        with pytest.raises(SyncAuthError, match="No API key configured for Claude"):
            p.send([{"role": "human", "content": "hello"}])

    def test_send_success(self):
        p = ClaudeAPI({"api_key": "sk-test"})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "content": [{"type": "text", "text": "Hello from Claude!"}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = p.send([{"role": "human", "content": "hello"}])

        assert result == "Hello from Claude!"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "x-api-key" in call_kwargs.kwargs.get("headers", call_kwargs[1].get("headers", {}))

    def test_send_api_error(self):
        p = ClaudeAPI({"api_key": "sk-test"})

        import httpx

        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "rate limited", request=MagicMock(), response=mock_resp
        )

        with patch("httpx.post", return_value=mock_resp), \
                pytest.raises(SyncAPIError, match="Claude API error"):
            p.send([{"role": "human", "content": "hello"}])


# ---------------------------------------------------------------------------
# OpenAIAPI
# ---------------------------------------------------------------------------


class TestOpenAIAPI:
    def test_info(self):
        p = OpenAIAPI({"api_key": "sk-test"})
        assert p.info.name == "chatgpt"
        assert p.info.requires_api_key is True

    def test_send_no_key_raises(self):
        with patch("anticlaw.sync.providers._get_api_key", return_value=None):
            p = OpenAIAPI({})
        with pytest.raises(SyncAuthError, match="No API key configured for ChatGPT"):
            p.send([{"role": "human", "content": "hello"}])

    def test_send_success(self):
        p = OpenAIAPI({"api_key": "sk-test"})
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Hello from GPT!"}}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp):
            result = p.send([{"role": "human", "content": "hello"}])

        assert result == "Hello from GPT!"

    def test_send_empty_choices(self):
        p = OpenAIAPI({"api_key": "sk-test"})
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": []}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp):
            result = p.send([{"role": "human", "content": "hello"}])

        assert result == ""


# ---------------------------------------------------------------------------
# GeminiAPI
# ---------------------------------------------------------------------------


class TestGeminiAPI:
    def test_info(self):
        p = GeminiAPI({"api_key": "test"})
        assert p.info.name == "gemini"
        assert p.info.free_tier is True

    def test_send_no_key_raises(self):
        with patch("anticlaw.sync.providers._get_api_key", return_value=None):
            p = GeminiAPI({})
        with pytest.raises(SyncAuthError, match="No API key configured for Gemini"):
            p.send([{"role": "human", "content": "hello"}])

    def test_send_success(self):
        p = GeminiAPI({"api_key": "test-key"})
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Hello from Gemini!"}]}}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = p.send([{"role": "human", "content": "hello"}])

        assert result == "Hello from Gemini!"
        # Verify API key is in URL
        url = mock_post.call_args[0][0]
        assert "key=test-key" in url

    def test_send_role_mapping(self):
        p = GeminiAPI({"api_key": "test-key"})
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "response"}]}}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            p.send([
                {"role": "human", "content": "hello"},
                {"role": "assistant", "content": "hi"},
                {"role": "human", "content": "bye"},
            ])

        call_json = mock_post.call_args.kwargs["json"]
        roles = [c["role"] for c in call_json["contents"]]
        assert roles == ["user", "model", "user"]


# ---------------------------------------------------------------------------
# OllamaLocal
# ---------------------------------------------------------------------------


class TestOllamaLocal:
    def test_info(self):
        p = OllamaLocal()
        assert p.info.name == "ollama"
        assert p.info.requires_api_key is False
        assert p.info.free_tier is True

    def test_send_success(self):
        p = OllamaLocal()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "message": {"content": "Hello from Ollama!"},
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp):
            result = p.send([{"role": "human", "content": "hello"}])

        assert result == "Hello from Ollama!"

    def test_send_unreachable(self):
        p = OllamaLocal()

        import httpx

        with patch("httpx.post", side_effect=httpx.ConnectError("refused")), \
                pytest.raises(SyncAPIError, match="Ollama not reachable"):
            p.send([{"role": "human", "content": "hello"}])

    def test_is_available_true(self):
        p = OllamaLocal()
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.get", return_value=mock_resp):
            assert p.is_available() is True

    def test_is_available_false(self):
        p = OllamaLocal()

        import httpx

        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            assert p.is_available() is False
