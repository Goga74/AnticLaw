"""Tests for anticlaw.cli.listen_cmd — aw listen."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from anticlaw.cli.listen_cmd import listen_cmd
from anticlaw.core.meta_db import MetaDB
from anticlaw.core.models import Chat, ChatMessage, Project
from anticlaw.core.storage import ChatStorage


def _setup_kb(tmp_path: Path) -> Path:
    """Create a minimal KB and return home path."""
    home = tmp_path / "home"
    home.mkdir()
    acl = home / ".acl"
    acl.mkdir()

    project_dir = home / "test-project"
    project_dir.mkdir()
    storage = ChatStorage(home)
    storage.write_project(project_dir / "_project.yaml", Project(name="test-project"))

    chat = Chat(
        id="chat-voice-001",
        title="Voice Test Chat",
        summary="Testing voice input.",
        tags=["voice", "test"],
        messages=[
            ChatMessage(role="human", content="How does voice input work?"),
            ChatMessage(role="assistant", content="It uses Whisper for speech-to-text."),
        ],
    )
    file_path = project_dir / "2025-03-01_voice-test.md"
    storage.write_chat(file_path, chat)

    db = MetaDB(acl / "meta.db")
    db.index_chat(chat, file_path, "test-project")
    db.index_project(Project(name="test-project"), project_dir)
    db.close()

    return home


class TestListenCmdHelp:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(listen_cmd, ["--help"])
        assert result.exit_code == 0
        assert "voice" in result.output.lower()
        assert "--continuous" in result.output
        assert "--mode" in result.output
        assert "--model" in result.output
        assert "--language" in result.output
        assert "--push-to-talk" in result.output


class TestListenCmdDepsNotInstalled:
    @patch(
        "anticlaw.cli.listen_cmd._create_provider",
        side_effect=SystemExit(1),
    )
    def test_exits_when_deps_missing(self, mock_create, tmp_path: Path):
        home = _setup_kb(tmp_path)
        runner = CliRunner()
        result = runner.invoke(listen_cmd, ["--home", str(home)])
        assert result.exit_code == 1


class TestListenCmdNotAvailable:
    @patch("anticlaw.cli.listen_cmd._create_provider")
    def test_error_when_provider_not_available(self, mock_create, tmp_path: Path):
        home = _setup_kb(tmp_path)

        mock_provider = MagicMock()
        mock_provider.is_available.return_value = False
        mock_create.return_value = mock_provider

        runner = CliRunner()
        result = runner.invoke(listen_cmd, ["--home", str(home)])
        assert result.exit_code == 0
        assert "not available" in result.output.lower()


class TestListenCmdSingleSearch:
    @patch("anticlaw.cli.listen_cmd._create_provider")
    def test_single_search_mode(self, mock_create, tmp_path: Path):
        home = _setup_kb(tmp_path)

        mock_provider = MagicMock()
        mock_provider.is_available.return_value = True
        mock_provider._push_to_talk = False
        mock_provider.listen.return_value = "voice input"
        mock_create.return_value = mock_provider

        runner = CliRunner()
        result = runner.invoke(listen_cmd, ["--home", str(home)])
        assert result.exit_code == 0
        assert "Heard: voice input" in result.output

    @patch("anticlaw.cli.listen_cmd._create_provider")
    def test_no_speech_detected(self, mock_create, tmp_path: Path):
        home = _setup_kb(tmp_path)

        mock_provider = MagicMock()
        mock_provider.is_available.return_value = True
        mock_provider._push_to_talk = False
        mock_provider.listen.return_value = ""
        mock_create.return_value = mock_provider

        runner = CliRunner()
        result = runner.invoke(listen_cmd, ["--home", str(home)])
        assert result.exit_code == 0
        assert "no speech" in result.output.lower()


class TestListenCmdAskMode:
    @patch("anticlaw.cli.listen_cmd._do_ask")
    @patch("anticlaw.cli.listen_cmd._create_provider")
    def test_ask_mode(self, mock_create, mock_ask, tmp_path: Path):
        home = _setup_kb(tmp_path)

        mock_provider = MagicMock()
        mock_provider.is_available.return_value = True
        mock_provider._push_to_talk = False
        mock_provider.listen.return_value = "what is auth?"
        mock_create.return_value = mock_provider

        runner = CliRunner()
        result = runner.invoke(listen_cmd, ["--mode", "ask", "--home", str(home)])
        assert result.exit_code == 0
        assert "Heard: what is auth?" in result.output
        mock_ask.assert_called_once_with("what is auth?", home)


class TestListenCmdContinuousMode:
    @patch("anticlaw.cli.listen_cmd._create_provider")
    def test_continuous_mode_stops_on_ctrl_c(self, mock_create, tmp_path: Path):
        home = _setup_kb(tmp_path)

        mock_provider = MagicMock()
        mock_provider.is_available.return_value = True
        mock_provider._push_to_talk = False
        # First call returns a query, second raises KeyboardInterrupt
        mock_provider.listen.side_effect = ["hello", KeyboardInterrupt]
        mock_create.return_value = mock_provider

        runner = CliRunner()
        result = runner.invoke(listen_cmd, ["--continuous", "--home", str(home)])
        assert result.exit_code == 0
        assert "continuous mode" in result.output.lower()
        assert "Heard: hello" in result.output


class TestListenCmdConfigOverrides:
    @patch("anticlaw.cli.listen_cmd._create_provider")
    def test_model_override(self, mock_create, tmp_path: Path):
        home = _setup_kb(tmp_path)

        mock_provider = MagicMock()
        mock_provider.is_available.return_value = True
        mock_provider._push_to_talk = False
        mock_provider.listen.return_value = ""
        mock_create.return_value = mock_provider

        runner = CliRunner()
        result = runner.invoke(listen_cmd, ["--model", "small", "--home", str(home)])
        assert result.exit_code == 0

        # Verify the config was passed to _create_provider with model override
        call_args = mock_create.call_args[0][0]
        assert call_args["model"] == "small"

    @patch("anticlaw.cli.listen_cmd._create_provider")
    def test_language_override(self, mock_create, tmp_path: Path):
        home = _setup_kb(tmp_path)

        mock_provider = MagicMock()
        mock_provider.is_available.return_value = True
        mock_provider._push_to_talk = False
        mock_provider.listen.return_value = ""
        mock_create.return_value = mock_provider

        runner = CliRunner()
        result = runner.invoke(listen_cmd, ["--language", "ru", "--home", str(home)])
        assert result.exit_code == 0

        call_args = mock_create.call_args[0][0]
        assert call_args["language"] == "ru"

    @patch("anticlaw.cli.listen_cmd._create_provider")
    def test_push_to_talk_flag(self, mock_create, tmp_path: Path):
        home = _setup_kb(tmp_path)

        mock_provider = MagicMock()
        mock_provider.is_available.return_value = True
        mock_provider._push_to_talk = True
        mock_provider.listen.return_value = ""
        mock_create.return_value = mock_provider

        runner = CliRunner()
        result = runner.invoke(listen_cmd, ["--push-to-talk", "--home", str(home)])
        assert result.exit_code == 0

        call_args = mock_create.call_args[0][0]
        assert call_args["push_to_talk"] is True


class TestDoSearch:
    def test_search_no_db(self, tmp_path: Path):
        from anticlaw.cli.listen_cmd import _do_search

        home = tmp_path / "empty"
        home.mkdir()
        (home / ".acl").mkdir()
        _do_search("test query", home)

    def test_search_with_results(self, tmp_path: Path):
        home = _setup_kb(tmp_path)
        from anticlaw.cli.listen_cmd import _do_search

        # Should not raise, results depend on index content
        _do_search("voice", home)


class TestDoAsk:
    @patch("anticlaw.cli.listen_cmd.load_config")
    def test_ask_falls_back_to_search_when_ollama_down(self, mock_config, tmp_path: Path):
        home = _setup_kb(tmp_path)

        mock_config.return_value = {"llm": {"provider": "ollama"}}

        with (
            patch("anticlaw.cli.listen_cmd._do_search") as mock_search,
            patch("anticlaw.llm.ollama_client.OllamaClient") as mock_cls,
        ):
            mock_client = MagicMock()
            mock_client.is_available.return_value = False
            mock_cls.return_value = mock_client

            from anticlaw.cli.listen_cmd import _do_ask

            _do_ask("test question", home)
            mock_search.assert_called_once_with("test question", home)
