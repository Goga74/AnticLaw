"""Tests for anticlaw.llm.ollama_client."""

from unittest.mock import MagicMock, patch

import pytest

from anticlaw.llm.ollama_client import OllamaClient, OllamaError, OllamaNotAvailable


class TestOllamaClientInit:
    def test_default_config(self):
        client = OllamaClient()
        assert client.model == "llama3.1:8b"
        assert client.base_url == "http://localhost:11434"

    def test_custom_config(self):
        client = OllamaClient({
            "model": "qwen2.5:7b",
            "base_url": "http://myhost:9999/",
        })
        assert client.model == "qwen2.5:7b"
        assert client.base_url == "http://myhost:9999"  # trailing slash stripped


class TestIsAvailable:
    @patch("httpx.get")
    def test_available_when_server_responds(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        client = OllamaClient()
        assert client.is_available() is True
        mock_get.assert_called_once()

    @patch("httpx.get")
    def test_not_available_on_connect_error(self, mock_get):
        import httpx
        mock_get.side_effect = httpx.ConnectError("connection refused")

        client = OllamaClient()
        assert client.is_available() is False

    @patch("httpx.get")
    def test_not_available_on_timeout(self, mock_get):
        import httpx
        mock_get.side_effect = httpx.TimeoutException("timeout")

        client = OllamaClient()
        assert client.is_available() is False


class TestAvailableModels:
    @patch("httpx.get")
    def test_returns_model_names(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [
                {"name": "llama3.1:8b"},
                {"name": "nomic-embed-text"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = OllamaClient()
        models = client.available_models()
        assert models == ["llama3.1:8b", "nomic-embed-text"]

    @patch("httpx.get")
    def test_raises_on_connect_error(self, mock_get):
        import httpx
        mock_get.side_effect = httpx.ConnectError("refused")

        client = OllamaClient()
        with pytest.raises(OllamaNotAvailable, match="not reachable"):
            client.available_models()

    @patch("httpx.get")
    def test_empty_models(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = OllamaClient()
        assert client.available_models() == []


class TestGenerate:
    @patch("httpx.post")
    def test_generate_returns_response(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "  The answer is 42.  "}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = OllamaClient()
        result = client.generate("What is the answer?")
        assert result == "The answer is 42."

        # Verify the request
        call_args = mock_post.call_args
        assert "api/generate" in call_args[0][0]
        assert call_args[1]["json"]["prompt"] == "What is the answer?"
        assert call_args[1]["json"]["stream"] is False

    @patch("httpx.post")
    def test_generate_with_custom_model(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "result"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = OllamaClient()
        client.generate("test", model="qwen2.5:7b")

        call_args = mock_post.call_args
        assert call_args[1]["json"]["model"] == "qwen2.5:7b"

    @patch("httpx.post")
    def test_generate_raises_on_connect_error(self, mock_post):
        import httpx
        mock_post.side_effect = httpx.ConnectError("refused")

        client = OllamaClient()
        with pytest.raises(OllamaNotAvailable):
            client.generate("test")

    @patch("httpx.post")
    def test_generate_raises_on_http_error(self, mock_post):
        import httpx
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        mock_post.return_value = mock_resp

        client = OllamaClient()
        with pytest.raises(OllamaError):
            client.generate("test")

    @patch("httpx.post")
    def test_generate_empty_response(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": ""}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = OllamaClient()
        result = client.generate("test")
        assert result == ""

    @patch("httpx.post")
    def test_generate_uses_default_model(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "ok"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = OllamaClient({"model": "my-model:latest"})
        client.generate("hello")

        call_args = mock_post.call_args
        assert call_args[1]["json"]["model"] == "my-model:latest"
