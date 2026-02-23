"""Tests for anticlaw.cli.sync_cmd — aw send, aw chat CLI commands."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from anticlaw.cli.main import cli
from anticlaw.core.meta_db import MetaDB
from anticlaw.core.models import Chat, ChatMessage, Status
from anticlaw.core.storage import ChatStorage


def _setup_home(tmp_path: Path) -> Path:
    """Create a home with indexed chat data for CLI tests."""
    home = tmp_path / "home"
    acl = home / ".acl"
    acl.mkdir(parents=True)
    (home / "_inbox").mkdir()

    # Write config with sync
    import yaml

    config = {"sync": {"default_push_target": "ollama"}}
    (acl / "config.yaml").write_text(yaml.dump(config), encoding="utf-8")

    # Create project
    project_dir = home / "proj-a"
    project_dir.mkdir()

    # Write a chat
    storage = ChatStorage(home)
    chat = Chat(
        id="chat-001",
        title="Test Chat",
        provider="claude",
        tags=["test"],
        importance="medium",
        status=Status.ACTIVE,
        created=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
        updated=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
        messages=[ChatMessage(role="human", content="Hello, how are you?")],
    )
    chat_path = project_dir / "2025-06-01_test-chat.md"
    storage.write_chat(chat_path, chat)

    # Index in MetaDB
    db = MetaDB(acl / "meta.db")
    db.index_chat(chat, chat_path, "proj-a")
    db.close()

    return home


class TestSendCmd:
    def test_send_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["send", "--help"])
        assert result.exit_code == 0
        assert "Send a chat to an LLM API" in result.output

    def test_send_no_home(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(cli, ["send", "chat-001", "--home", str(tmp_path / "no")])
        assert "No knowledge base found" in result.output

    def test_send_chat_not_found(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["send", "nonexistent", "--home", str(home)])
        assert "not found" in result.output

    def test_send_success(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()

        mock_provider = MagicMock()
        mock_provider.name = "ollama"
        mock_provider.send.return_value = "I am fine, thanks!"

        with patch("anticlaw.sync.engine.get_sync_provider", return_value=mock_provider):
            result = runner.invoke(cli, [
                "send", "chat-001", "--provider", "ollama", "--home", str(home),
            ])

        assert result.exit_code == 0
        assert "Response received" in result.output

    def test_send_auth_error(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()

        from anticlaw.sync.providers import SyncAuthError

        mock_provider = MagicMock()
        mock_provider.name = "claude"
        mock_provider.send.side_effect = SyncAuthError("No API key")

        with patch("anticlaw.sync.engine.get_sync_provider", return_value=mock_provider):
            result = runner.invoke(cli, [
                "send", "chat-001", "--provider", "claude", "--home", str(home),
            ])

        assert "Authentication error" in result.output

    def test_send_api_error(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()

        from anticlaw.sync.providers import SyncAPIError

        mock_provider = MagicMock()
        mock_provider.name = "ollama"
        mock_provider.send.side_effect = SyncAPIError("Connection refused")

        with patch("anticlaw.sync.engine.get_sync_provider", return_value=mock_provider):
            result = runner.invoke(cli, [
                "send", "chat-001", "--provider", "ollama", "--home", str(home),
            ])

        assert "API error" in result.output


class TestChatCmd:
    def test_chat_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["chat", "--help"])
        assert result.exit_code == 0
        assert "interactive file-based chat" in result.output

    def test_chat_project_not_found(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["chat", "nonexistent", "--home", str(home)])
        assert "not found" in result.output

    def test_chat_no_provider(self, tmp_path: Path):
        """Without sync config, should error about no provider."""
        home = _setup_home(tmp_path)
        # Remove sync config
        import yaml

        config_path = home / ".acl" / "config.yaml"
        config_path.write_text(yaml.dump({}), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["chat", "proj-a", "--home", str(home)])
        assert "No provider" in result.output

    def test_chat_quit(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["chat", "proj-a", "--provider", "ollama", "--home", str(home)],
            input="quit\n",
        )
        assert "Chat ended" in result.output

    def test_chat_interactive_round_trip(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()

        mock_provider = MagicMock()
        mock_provider.name = "ollama"
        mock_provider.send.return_value = "Hello! I'm doing well."

        with patch("anticlaw.sync.engine.get_sync_provider", return_value=mock_provider):
            result = runner.invoke(
                cli,
                ["chat", "proj-a", "--provider", "ollama", "--home", str(home)],
                input="Hello!\nquit\n",
            )

        assert result.exit_code == 0
        assert "Hello! I'm doing well." in result.output
        assert "Chat saved" in result.output
