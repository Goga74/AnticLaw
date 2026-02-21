"""Tests for anticlaw.llm.tagger."""

from unittest.mock import MagicMock, patch

from anticlaw.core.models import Chat, ChatMessage
from anticlaw.llm.ollama_client import OllamaClient, OllamaNotAvailable
from anticlaw.llm.tagger import _parse_tags, auto_categorize, auto_tag


def _make_chat(title: str = "Auth Discussion", messages: list | None = None) -> Chat:
    if messages is None:
        messages = [
            ChatMessage(role="human", content="How should we implement auth?"),
            ChatMessage(role="assistant", content="I recommend JWT tokens."),
        ]
    return Chat(title=title, messages=messages)


class TestParseTags:
    def test_simple_comma_separated(self):
        assert _parse_tags("auth, jwt, security") == ["auth", "jwt", "security"]

    def test_with_quotes(self):
        assert _parse_tags('"auth", "jwt"') == ["auth", "jwt"]

    def test_with_brackets(self):
        assert _parse_tags("[auth, jwt, api]") == ["auth", "jwt", "api"]

    def test_with_bullets(self):
        assert _parse_tags("- auth\n- jwt\n- security") == ["auth", "jwt", "security"]

    def test_deduplicates(self):
        assert _parse_tags("auth, jwt, auth") == ["auth", "jwt"]

    def test_filters_invalid(self):
        assert _parse_tags("auth, 123abc, , ") == ["auth", "123abc"]

    def test_hyphenated_tags(self):
        assert _parse_tags("error-handling, api-design") == ["error-handling", "api-design"]

    def test_caps_at_10(self):
        tags = ", ".join(f"tag{i}" for i in range(15))
        result = _parse_tags(tags)
        assert len(result) <= 10

    def test_empty_string(self):
        assert _parse_tags("") == []

    def test_rejects_long_tags(self):
        result = _parse_tags("a" * 31 + ", valid")
        assert result == ["valid"]


class TestAutoTag:
    def test_returns_tags_from_ollama(self):
        client = MagicMock(spec=OllamaClient)
        client.generate.return_value = "auth, jwt, security, api"

        chat = _make_chat()
        tags = auto_tag(chat, client=client)

        assert tags == ["auth", "jwt", "security", "api"]
        assert client.generate.called

    def test_empty_messages_returns_empty(self):
        client = MagicMock(spec=OllamaClient)
        chat = Chat(title="Empty", messages=[])

        tags = auto_tag(chat, client=client)
        assert tags == []
        assert not client.generate.called

    def test_graceful_fallback_when_ollama_unavailable(self):
        client = MagicMock(spec=OllamaClient)
        client.generate.side_effect = OllamaNotAvailable("not running")

        chat = _make_chat()
        tags = auto_tag(chat, client=client)
        assert tags == []

    def test_creates_client_from_config(self):
        with patch("anticlaw.llm.tagger.OllamaClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.generate.return_value = "auth, jwt"
            mock_cls.return_value = mock_client

            chat = _make_chat()
            tags = auto_tag(chat, config={"model": "test"})

            mock_cls.assert_called_once_with({"model": "test"})
            assert tags == ["auth", "jwt"]


class TestAutoCategorize:
    def test_returns_project_suggestion(self):
        client = MagicMock(spec=OllamaClient)
        client.generate.return_value = "api-development"

        chat = _make_chat()
        result = auto_categorize(chat, client=client)
        assert result == "api-development"

    def test_with_existing_projects(self):
        client = MagicMock(spec=OllamaClient)
        client.generate.return_value = "auth-system"

        chat = _make_chat()
        result = auto_categorize(
            chat, existing_projects=["api-dev", "auth-system"], client=client,
        )
        assert result == "auth-system"

        prompt = client.generate.call_args[0][0]
        assert "api-dev" in prompt
        assert "auth-system" in prompt

    def test_empty_messages_returns_empty(self):
        client = MagicMock(spec=OllamaClient)
        chat = Chat(title="Empty", messages=[])

        result = auto_categorize(chat, client=client)
        assert result == ""

    def test_graceful_fallback_when_ollama_unavailable(self):
        client = MagicMock(spec=OllamaClient)
        client.generate.side_effect = OllamaNotAvailable("not running")

        chat = _make_chat()
        result = auto_categorize(chat, client=client)
        assert result == ""

    def test_cleans_up_response(self):
        client = MagicMock(spec=OllamaClient)
        client.generate.return_value = '  "API-Development."  \nSome extra text'

        chat = _make_chat()
        result = auto_categorize(chat, client=client)
        assert result == "api-development"
