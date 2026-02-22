"""Tests for anticlaw.llm.summarizer."""

from unittest.mock import MagicMock, patch

from anticlaw.core.models import Chat, ChatMessage
from anticlaw.llm.ollama_client import OllamaClient, OllamaNotAvailableError
from anticlaw.llm.summarizer import summarize_chat, summarize_project


def _make_chat(title: str = "Test Chat", messages: list | None = None) -> Chat:
    if messages is None:
        messages = [
            ChatMessage(role="human", content="How should we implement auth?"),
            ChatMessage(role="assistant", content="I recommend JWT tokens with refresh."),
        ]
    return Chat(title=title, messages=messages)


class TestSummarizeChat:
    def test_returns_summary_from_ollama(self):
        client = MagicMock(spec=OllamaClient)
        client.generate.return_value = "The chat discussed JWT authentication approach."

        chat = _make_chat()
        result = summarize_chat(chat, client=client)

        assert result == "The chat discussed JWT authentication approach."
        assert client.generate.called
        # Verify prompt contains title and messages
        prompt = client.generate.call_args[0][0]
        assert "Test Chat" in prompt
        assert "auth" in prompt

    def test_empty_messages_returns_empty(self):
        client = MagicMock(spec=OllamaClient)
        chat = Chat(title="Empty", messages=[])

        result = summarize_chat(chat, client=client)
        assert result == ""
        assert not client.generate.called

    def test_graceful_fallback_when_ollama_unavailable(self):
        client = MagicMock(spec=OllamaClient)
        client.generate.side_effect = OllamaNotAvailableError("not running")

        chat = _make_chat()
        result = summarize_chat(chat, client=client)
        assert result == ""

    def test_creates_client_from_config(self):
        with patch("anticlaw.llm.summarizer.OllamaClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.generate.return_value = "A summary."
            mock_cls.return_value = mock_client

            chat = _make_chat()
            result = summarize_chat(chat, config={"model": "test"})

            mock_cls.assert_called_once_with({"model": "test"})
            assert result == "A summary."

    def test_long_messages_truncated(self):
        client = MagicMock(spec=OllamaClient)
        client.generate.return_value = "Summary of long chat."

        # Create a chat with very long messages
        long_msg = ChatMessage(role="human", content="x" * 10000)
        chat = Chat(title="Long", messages=[long_msg])

        result = summarize_chat(chat, client=client)
        assert result == "Summary of long chat."
        # Verify the prompt was truncated
        prompt = client.generate.call_args[0][0]
        assert "[... truncated]" in prompt


class TestSummarizeProject:
    def test_returns_project_summary(self):
        client = MagicMock(spec=OllamaClient)
        client.generate.return_value = "Project focuses on API development."

        chats = [
            Chat(title="Auth discussion", summary="Chose JWT."),
            Chat(title="API design", summary="REST with versioning."),
        ]

        result = summarize_project("api-dev", "API project", chats, client=client)
        assert result == "Project focuses on API development."

        prompt = client.generate.call_args[0][0]
        assert "api-dev" in prompt
        assert "JWT" in prompt

    def test_empty_chats_returns_empty(self):
        client = MagicMock(spec=OllamaClient)
        result = summarize_project("empty", "", [], client=client)
        assert result == ""
        assert not client.generate.called

    def test_chats_without_summaries_use_titles(self):
        client = MagicMock(spec=OllamaClient)
        client.generate.return_value = "A project summary."

        chats = [Chat(title="Auth chat", summary="")]

        result = summarize_project("test", "", chats, client=client)
        assert result == "A project summary."
        prompt = client.generate.call_args[0][0]
        assert "Auth chat" in prompt

    def test_graceful_fallback_when_ollama_unavailable(self):
        client = MagicMock(spec=OllamaClient)
        client.generate.side_effect = OllamaNotAvailableError("not running")

        chats = [Chat(title="Test", summary="Summary.")]
        result = summarize_project("test", "", chats, client=client)
        assert result == ""
