"""Tests for anticlaw.cli.llm_cmd — aw summarize, aw autotag, aw ask."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from anticlaw.cli.llm_cmd import ask_cmd, autotag_cmd, summarize_cmd
from anticlaw.core.meta_db import MetaDB
from anticlaw.core.models import Chat, ChatMessage, Project
from anticlaw.core.storage import ChatStorage


def _setup_kb(tmp_path: Path) -> tuple[Path, str]:
    """Create a minimal KB and return (home, chat_id)."""
    home = tmp_path / "home"
    home.mkdir()
    acl = home / ".acl"
    acl.mkdir()

    # Create project
    project_dir = home / "test-project"
    project_dir.mkdir()
    storage = ChatStorage(home)
    storage.write_project(project_dir / "_project.yaml", Project(name="test-project"))

    # Create chat
    chat = Chat(
        id="chat-test-001",
        title="Auth Discussion",
        summary="Chose JWT.",
        tags=["auth"],
        messages=[
            ChatMessage(role="human", content="How should we do auth?"),
            ChatMessage(role="assistant", content="Use JWT with refresh tokens."),
        ],
    )
    file_path = project_dir / "2025-02-18_auth-discussion.md"
    storage.write_chat(file_path, chat)

    db = MetaDB(acl / "meta.db")
    db.index_chat(chat, file_path, "test-project")
    db.index_project(Project(name="test-project"), project_dir)
    db.close()

    return home, chat.id


class TestSummarizeCmd:
    @patch("anticlaw.cli.llm_cmd.OllamaClient")
    @patch("anticlaw.cli.llm_cmd.summarize_chat")
    def test_summarize_chat(self, mock_summarize, mock_cls, tmp_path: Path):
        home, chat_id = _setup_kb(tmp_path)

        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_cls.return_value = mock_client
        mock_summarize.return_value = "This chat discusses auth using JWT."

        runner = CliRunner()
        result = runner.invoke(summarize_cmd, [chat_id, "--home", str(home)])

        assert result.exit_code == 0
        assert "JWT" in result.output

    @patch("anticlaw.cli.llm_cmd.OllamaClient")
    @patch("anticlaw.cli.llm_cmd.summarize_project")
    def test_summarize_project(self, mock_summarize, mock_cls, tmp_path: Path):
        home, _ = _setup_kb(tmp_path)

        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_cls.return_value = mock_client
        mock_summarize.return_value = "Project focuses on authentication."

        runner = CliRunner()
        result = runner.invoke(summarize_cmd, ["test-project", "--home", str(home)])

        assert result.exit_code == 0
        assert "authentication" in result.output.lower()

    @patch("anticlaw.cli.llm_cmd.OllamaClient")
    def test_summarize_ollama_not_running(self, mock_cls, tmp_path: Path):
        home, chat_id = _setup_kb(tmp_path)

        mock_client = MagicMock()
        mock_client.is_available.return_value = False
        mock_cls.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(summarize_cmd, [chat_id, "--home", str(home)])

        assert result.exit_code == 0
        assert "not running" in result.output.lower()

    @patch("anticlaw.cli.llm_cmd.OllamaClient")
    def test_summarize_not_found(self, mock_cls, tmp_path: Path):
        home, _ = _setup_kb(tmp_path)

        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_cls.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(summarize_cmd, ["nonexistent", "--home", str(home)])

        assert result.exit_code == 0
        assert "not found" in result.output.lower()

    def test_summarize_help(self):
        runner = CliRunner()
        result = runner.invoke(summarize_cmd, ["--help"])
        assert result.exit_code == 0
        assert "summary" in result.output.lower()


class TestAutotagCmd:
    @patch("anticlaw.cli.llm_cmd.OllamaClient")
    @patch("anticlaw.cli.llm_cmd.auto_tag")
    def test_autotag_chat(self, mock_tag, mock_cls, tmp_path: Path):
        home, chat_id = _setup_kb(tmp_path)

        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_cls.return_value = mock_client
        mock_tag.return_value = ["jwt", "security", "api"]

        runner = CliRunner()
        result = runner.invoke(autotag_cmd, [chat_id, "--home", str(home)])

        assert result.exit_code == 0
        assert "jwt" in result.output

    @patch("anticlaw.cli.llm_cmd.OllamaClient")
    @patch("anticlaw.cli.llm_cmd.auto_tag")
    def test_autotag_project(self, mock_tag, mock_cls, tmp_path: Path):
        home, _ = _setup_kb(tmp_path)

        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_cls.return_value = mock_client
        mock_tag.return_value = ["jwt", "security"]

        runner = CliRunner()
        result = runner.invoke(autotag_cmd, ["test-project", "--home", str(home)])

        assert result.exit_code == 0
        assert "Tagged" in result.output

    @patch("anticlaw.cli.llm_cmd.OllamaClient")
    def test_autotag_ollama_not_running(self, mock_cls, tmp_path: Path):
        home, chat_id = _setup_kb(tmp_path)

        mock_client = MagicMock()
        mock_client.is_available.return_value = False
        mock_cls.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(autotag_cmd, [chat_id, "--home", str(home)])

        assert result.exit_code == 0
        assert "not running" in result.output.lower()

    def test_autotag_help(self):
        runner = CliRunner()
        result = runner.invoke(autotag_cmd, ["--help"])
        assert result.exit_code == 0
        assert "tag" in result.output.lower()


class TestAskCmd:
    @patch("anticlaw.cli.llm_cmd.qa_ask")
    @patch("anticlaw.cli.llm_cmd.OllamaClient")
    def test_ask_shows_answer(self, mock_cls, mock_ask, tmp_path: Path):
        home, _ = _setup_kb(tmp_path)

        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_cls.return_value = mock_client

        from anticlaw.core.meta_db import SearchResult
        from anticlaw.llm.qa import QAResult
        mock_ask.return_value = QAResult(
            answer="Use JWT tokens with refresh.",
            sources=[SearchResult(
                chat_id="chat-001", title="Auth Discussion",
                project_id="test", snippet="...", score=1.0, file_path="",
            )],
        )

        runner = CliRunner()
        result = runner.invoke(ask_cmd, ["what auth?", "--home", str(home)])

        assert result.exit_code == 0
        assert "JWT" in result.output
        assert "Sources" in result.output

    @patch("anticlaw.cli.llm_cmd.OllamaClient")
    def test_ask_ollama_not_running(self, mock_cls, tmp_path: Path):
        home, _ = _setup_kb(tmp_path)

        mock_client = MagicMock()
        mock_client.is_available.return_value = False
        mock_cls.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(ask_cmd, ["test question", "--home", str(home)])

        assert result.exit_code == 0
        assert "not running" in result.output.lower()

    @patch("anticlaw.cli.llm_cmd.qa_ask")
    @patch("anticlaw.cli.llm_cmd.OllamaClient")
    def test_ask_with_error(self, mock_cls, mock_ask, tmp_path: Path):
        home, _ = _setup_kb(tmp_path)

        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_cls.return_value = mock_client

        from anticlaw.llm.qa import QAResult
        mock_ask.return_value = QAResult(answer="", error="Database missing")

        runner = CliRunner()
        result = runner.invoke(ask_cmd, ["test", "--home", str(home)])

        assert result.exit_code == 0
        assert "Error" in result.output

    def test_ask_help(self):
        runner = CliRunner()
        result = runner.invoke(ask_cmd, ["--help"])
        assert result.exit_code == 0
        assert "question" in result.output.lower()
