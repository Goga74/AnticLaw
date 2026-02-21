"""Tests for embedding provider Protocol and OllamaEmbeddingProvider."""

from unittest.mock import MagicMock, patch

from anticlaw.providers.embedding.base import EmbeddingInfo, EmbeddingProvider
from anticlaw.providers.embedding.ollama import OllamaEmbeddingProvider


class TestEmbeddingInfo:
    def test_fields(self):
        info = EmbeddingInfo(
            display_name="Test",
            version="1.0",
            dimensions=768,
            max_tokens=8192,
            is_local=True,
            requires_auth=False,
        )
        assert info.display_name == "Test"
        assert info.dimensions == 768
        assert info.max_tokens == 8192
        assert info.is_local is True
        assert info.requires_auth is False


class TestEmbeddingProtocol:
    def test_ollama_satisfies_protocol(self):
        provider = OllamaEmbeddingProvider()
        assert isinstance(provider, EmbeddingProvider)

    def test_protocol_attributes(self):
        provider = OllamaEmbeddingProvider()
        assert hasattr(provider, "name")
        assert hasattr(provider, "info")
        assert hasattr(provider, "embed")
        assert hasattr(provider, "embed_batch")


class TestOllamaEmbeddingProvider:
    def test_default_config(self):
        p = OllamaEmbeddingProvider()
        assert p.name == "ollama"
        assert p.info.dimensions == 768
        assert p.info.is_local is True
        assert p.info.requires_auth is False
        assert "nomic-embed-text" in p.info.display_name

    def test_custom_config(self):
        p = OllamaEmbeddingProvider({
            "model": "custom-model",
            "base_url": "http://custom:1234",
            "dimensions": 384,
        })
        assert p._model == "custom-model"
        assert p._base_url == "http://custom:1234"
        assert p.info.dimensions == 384

    def test_trailing_slash_stripped(self):
        p = OllamaEmbeddingProvider({"base_url": "http://host:11434/"})
        assert p._base_url == "http://host:11434"

    def test_embed_calls_api(self):
        p = OllamaEmbeddingProvider()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"embeddings": [[0.1, 0.2, 0.3]]}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = p.embed("hello world")

        assert result == [0.1, 0.2, 0.3]
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "/api/embed" in call_args[0][0]
        assert call_args[1]["json"]["model"] == "nomic-embed-text"
        assert call_args[1]["json"]["input"] == "hello world"

    def test_embed_batch_calls_api(self):
        p = OllamaEmbeddingProvider()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "embeddings": [[0.1, 0.2], [0.3, 0.4]]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = p.embed_batch(["hello", "world"])

        assert len(result) == 2
        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.3, 0.4]
        call_json = mock_post.call_args[1]["json"]
        assert call_json["input"] == ["hello", "world"]

    def test_embed_batch_empty(self):
        p = OllamaEmbeddingProvider()
        assert p.embed_batch([]) == []

    def test_embed_uses_custom_model(self):
        p = OllamaEmbeddingProvider({"model": "mxbai-embed-large"})
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"embeddings": [[1.0]]}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            p.embed("test")

        assert mock_post.call_args[1]["json"]["model"] == "mxbai-embed-large"
