"""Tests for anticlaw.cli.clear_cmd (aw clear)."""

from pathlib import Path

from click.testing import CliRunner

from anticlaw.cli.main import cli
from anticlaw.core.models import Chat, ChatMessage
from anticlaw.core.storage import ChatStorage


def _setup_home(tmp_path: Path) -> Path:
    """Create a home dir with _inbox and _archive files."""
    home = tmp_path / "home"
    storage = ChatStorage(home)
    storage.init_home()

    # Create inbox chats
    for i in range(3):
        chat = Chat(
            id=f"inbox-{i:03d}",
            title=f"Inbox Chat {i}",
            provider="claude",
            messages=[
                ChatMessage(role="human", content=f"Question {i}"),
                ChatMessage(role="assistant", content=f"Answer {i}"),
            ],
        )
        storage.write_chat(home / "_inbox" / f"2025-01-0{i+1}_inbox-chat-{i}.md", chat)

    # Create archive chats
    archive_dir = home / "_archive"
    archive_dir.mkdir(exist_ok=True)
    for i in range(2):
        chat = Chat(
            id=f"archive-{i:03d}",
            title=f"Archive Chat {i}",
            provider="claude",
            messages=[
                ChatMessage(role="human", content=f"Old question {i}"),
                ChatMessage(role="assistant", content=f"Old answer {i}"),
            ],
        )
        storage.write_chat(archive_dir / f"2024-06-0{i+1}_archive-chat-{i}.md", chat)

    return home


class TestClearCmd:
    def test_confirm_yes_clears_inbox(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        inbox = home / "_inbox"
        assert len(list(inbox.glob("*.md"))) == 3

        runner = CliRunner()
        result = runner.invoke(cli, ["clear", "--home", str(home)], input="y\n")

        assert result.exit_code == 0
        assert "Cleared 3 files from _inbox/" in result.output
        assert len(list(inbox.glob("*.md"))) == 0

    def test_confirm_no_aborts(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        inbox = home / "_inbox"
        assert len(list(inbox.glob("*.md"))) == 3

        runner = CliRunner()
        result = runner.invoke(cli, ["clear", "--home", str(home)], input="N\n")

        assert result.exit_code == 0
        assert "Aborted." in result.output
        assert len(list(inbox.glob("*.md"))) == 3

    def test_empty_input_aborts(self, tmp_path: Path):
        """Default answer (empty) should abort."""
        home = _setup_home(tmp_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["clear", "--home", str(home)], input="\n")

        assert result.exit_code == 0
        assert "Aborted." in result.output

    def test_all_flag_clears_inbox_and_archive(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        inbox = home / "_inbox"
        archive = home / "_archive"
        assert len(list(inbox.glob("*.md"))) == 3
        assert len(list(archive.glob("*.md"))) == 2

        runner = CliRunner()
        result = runner.invoke(cli, ["clear", "--all", "--home", str(home)], input="y\n")

        assert result.exit_code == 0
        assert "Cleared 3 files from _inbox/" in result.output
        assert "Cleared 2 files from _archive/" in result.output
        assert "Reindexed" in result.output
        assert len(list(inbox.glob("*.md"))) == 0
        assert len(list(archive.glob("*.md"))) == 0

    def test_all_flag_shows_correct_prompt(self, tmp_path: Path):
        home = _setup_home(tmp_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["clear", "--all", "--home", str(home)], input="N\n")

        assert "Delete _inbox/, _archive/ and rebuild index?" in result.output

    def test_inbox_only_shows_correct_prompt(self, tmp_path: Path):
        home = _setup_home(tmp_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["clear", "--home", str(home)], input="N\n")

        assert "Delete all files in _inbox/?" in result.output

    def test_empty_inbox_reports_zero(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        # Remove all inbox files first
        for f in (home / "_inbox").glob("*.md"):
            f.unlink()

        runner = CliRunner()
        result = runner.invoke(cli, ["clear", "--home", str(home)], input="y\n")

        assert result.exit_code == 0
        assert "Cleared 0 files from _inbox/" in result.output

    def test_no_archive_dir_reports_zero(self, tmp_path: Path):
        """--all with missing _archive/ should report 0 without error."""
        home = _setup_home(tmp_path)
        # Remove _archive entirely
        import shutil
        shutil.rmtree(home / "_archive")

        runner = CliRunner()
        result = runner.invoke(cli, ["clear", "--all", "--home", str(home)], input="y\n")

        assert result.exit_code == 0
        assert "Cleared 0 files from _archive/" in result.output

    def test_yes_also_accepted(self, tmp_path: Path):
        home = _setup_home(tmp_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["clear", "--home", str(home)], input="yes\n")

        assert result.exit_code == 0
        assert "Cleared 3 files from _inbox/" in result.output
