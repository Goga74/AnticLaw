"""Tests for anticlaw.cli.search_cmd (aw search)."""

import json
import zipfile
from pathlib import Path

from click.testing import CliRunner

from anticlaw.cli.main import cli
from anticlaw.core.meta_db import MetaDB
from anticlaw.core.models import Chat, ChatMessage, Status
from anticlaw.core.storage import ChatStorage


def _setup_home(tmp_path: Path) -> Path:
    """Create a home dir with some indexed chats."""
    home = tmp_path / "home"
    storage = ChatStorage(home)
    storage.init_home()

    # Create inbox chats
    for i, (title, content) in enumerate([
        ("Auth Discussion", "How should we implement JWT authentication?"),
        ("Database Design", "Let's use PostgreSQL for the main database."),
        ("API Endpoints", "REST API with authentication middleware."),
    ]):
        chat = Chat(
            id=f"chat-{i:03d}",
            title=title,
            provider="claude",
            tags=["backend"] if i < 2 else ["api"],
            messages=[ChatMessage(role="human", content=content)],
        )
        storage.write_chat(home / "_inbox" / f"chat-{i}.md", chat)

    # Build index
    db = MetaDB(home / ".acl" / "meta.db")
    db.reindex_all(home)
    db.close()

    return home


class TestSearchCmd:
    def test_search_basic(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["search", "JWT", "--home", str(home)])
        assert result.exit_code == 0, result.output
        assert "Auth Discussion" in result.output
        assert "result(s)" in result.output

    def test_search_no_results(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["search", "kubernetes", "--home", str(home)])
        assert result.exit_code == 0
        assert "No results found" in result.output

    def test_search_exact(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "search", "JWT authentication", "--exact", "--home", str(home),
        ])
        assert result.exit_code == 0
        assert "Auth Discussion" in result.output

    def test_search_no_index(self, tmp_path: Path):
        home = tmp_path / "empty_home"
        home.mkdir()
        runner = CliRunner()
        result = runner.invoke(cli, ["search", "test", "--home", str(home)])
        assert result.exit_code == 0
        assert "reindex" in result.output.lower()

    def test_search_project_filter(self, tmp_path: Path):
        home = tmp_path / "home"
        storage = ChatStorage(home)
        storage.init_home()
        project_dir = storage.create_project("My Project")

        chat = Chat(
            id="proj-chat",
            title="Project Chat",
            provider="claude",
            messages=[ChatMessage(role="human", content="unique project keyword")],
        )
        storage.write_chat(project_dir / "proj.md", chat)

        inbox_chat = Chat(
            id="inbox-chat",
            title="Inbox Chat",
            provider="claude",
            messages=[ChatMessage(role="human", content="unique project keyword")],
        )
        storage.write_chat(home / "_inbox" / "inbox.md", inbox_chat)

        db = MetaDB(home / ".acl" / "meta.db")
        db.reindex_all(home)
        db.close()

        runner = CliRunner()
        result = runner.invoke(cli, [
            "search", "unique", "--project", "my-project", "--home", str(home),
        ])
        assert result.exit_code == 0, result.output
        assert "Project Chat" in result.output
        # Should NOT show inbox chat
        assert "Inbox Chat" not in result.output
