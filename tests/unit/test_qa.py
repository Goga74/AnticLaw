"""Tests for anticlaw.llm.qa."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from anticlaw.core.meta_db import MetaDB, SearchResult
from anticlaw.core.models import Chat, ChatMessage
from anticlaw.core.storage import ChatStorage
from anticlaw.llm.ollama_client import OllamaClient, OllamaNotAvailableError
from anticlaw.llm.qa import QAResult, ask


def _setup_kb(tmp_path: Path) -> Path:
    """Create a minimal knowledge base with indexed chats."""
    home = tmp_path / "home"
    home.mkdir()
    acl = home / ".acl"
    acl.mkdir()
    inbox = home / "_inbox"
    inbox.mkdir()

    storage = ChatStorage(home)

    chat = Chat(
        id="chat-001",
        title="Auth Discussion",
        summary="Chose JWT tokens for authentication.",
        messages=[
            ChatMessage(role="human", content="How should we do auth?"),
            ChatMessage(role="assistant", content="Use JWT with refresh tokens."),
        ],
    )
    file_path = inbox / "2025-02-18_auth-discussion.md"
    storage.write_chat(file_path, chat)

    db = MetaDB(acl / "meta.db")
    db.index_chat(chat, file_path, "_inbox")
    db.close()

    return home


class TestAsk:
    def test_returns_answer_with_sources(self, tmp_path: Path):
        home = _setup_kb(tmp_path)

        client = MagicMock(spec=OllamaClient)
        client.generate.return_value = "You should use JWT with refresh tokens."

        result = ask("auth", home, client=client)

        assert result.answer == "You should use JWT with refresh tokens."
        assert len(result.sources) > 0
        assert result.error == ""

    def test_no_meta_db(self, tmp_path: Path):
        home = tmp_path / "empty"
        home.mkdir()

        client = MagicMock(spec=OllamaClient)
        result = ask("test", home, client=client)

        assert result.error != ""
        assert "database" in result.error.lower()

    def test_no_search_results(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        acl = home / ".acl"
        acl.mkdir()

        # Create empty meta.db (access conn to trigger file creation)
        db = MetaDB(acl / "meta.db")
        _ = db.conn  # triggers _open(), creates file
        db.close()

        client = MagicMock(spec=OllamaClient)
        result = ask("xyznonexistent123", home, client=client)

        assert "No relevant chats" in result.answer
        assert result.sources == []
        assert not client.generate.called

    def test_ollama_unavailable_returns_error(self, tmp_path: Path):
        home = _setup_kb(tmp_path)

        client = MagicMock(spec=OllamaClient)
        client.generate.side_effect = OllamaNotAvailableError("not running")

        result = ask("auth", home, client=client)

        assert result.error != ""
        assert "Ollama" in result.error
        assert len(result.sources) > 0  # sources found before LLM call

    def test_creates_client_from_config(self, tmp_path: Path):
        home = _setup_kb(tmp_path)

        with patch("anticlaw.llm.qa.OllamaClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.generate.return_value = "An answer."
            mock_cls.return_value = mock_client

            result = ask("auth", home, config={"model": "test"})

            mock_cls.assert_called_once_with({"model": "test"})
            assert result.answer == "An answer."

    def test_context_respects_max_chars(self, tmp_path: Path):
        home = _setup_kb(tmp_path)

        client = MagicMock(spec=OllamaClient)
        client.generate.return_value = "Answer."

        result = ask("auth", home, client=client, max_context_chars=10)

        assert result.answer == "Answer."
        assert len(result.sources) >= 1


class TestQAResult:
    def test_default_values(self):
        r = QAResult(answer="test")
        assert r.answer == "test"
        assert r.sources == []
        assert r.error == ""
