"""Tests for anticlaw.cli.project_cmd (aw list, show, move, tag, create, reindex)."""

from pathlib import Path

from click.testing import CliRunner

from anticlaw.cli.main import cli
from anticlaw.core.meta_db import MetaDB
from anticlaw.core.models import Chat, ChatMessage
from anticlaw.core.storage import ChatStorage


def _setup_home(tmp_path: Path) -> Path:
    """Create a home dir with a project and some chats."""
    home = tmp_path / "home"
    storage = ChatStorage(home)
    storage.init_home()

    # Create a project
    project_dir = storage.create_project("My Project", "A test project")

    # Create a chat in the project
    chat = Chat(
        id="proj-chat-001",
        title="Project Discussion",
        provider="claude",
        model="claude-opus-4-6",
        tags=["design"],
        messages=[
            ChatMessage(role="human", content="What architecture should we use?"),
            ChatMessage(role="assistant", content="I recommend a layered approach."),
        ],
    )
    storage.write_chat(project_dir / "2025-02-18_project-discussion.md", chat)

    # Create an inbox chat
    inbox_chat = Chat(
        id="inbox-chat-001",
        title="Quick Question",
        provider="claude",
        messages=[
            ChatMessage(role="human", content="How does async work?"),
            ChatMessage(role="assistant", content="Async uses event loops."),
        ],
    )
    storage.write_chat(home / "_inbox" / "2025-02-19_quick-question.md", inbox_chat)

    # Build index
    db = MetaDB(home / ".acl" / "meta.db")
    db.reindex_all(home)
    db.close()

    return home


class TestListCmd:
    def test_list_projects(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["list", "--home", str(home)])
        assert result.exit_code == 0, result.output
        assert "My Project" in result.output
        assert "1 chats" in result.output

    def test_list_chats_in_project(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["list", "my-project", "--home", str(home)])
        assert result.exit_code == 0, result.output
        assert "Project Discussion" in result.output
        assert "proj-cha" in result.output  # short ID

    def test_list_no_index(self, tmp_path: Path):
        home = tmp_path / "empty"
        home.mkdir()
        runner = CliRunner()
        result = runner.invoke(cli, ["list", "--home", str(home)])
        assert result.exit_code == 0
        assert "reindex" in result.output.lower()

    def test_list_empty_project(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["list", "nonexistent", "--home", str(home)])
        assert result.exit_code == 0
        assert "No chats" in result.output


class TestShowCmd:
    def test_show_chat(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["show", "proj-chat-001", "--home", str(home)])
        assert result.exit_code == 0, result.output
        assert "Project Discussion" in result.output
        assert "architecture" in result.output
        assert "## Human" in result.output
        assert "## Assistant" in result.output

    def test_show_partial_id(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        # Use prefix of the chat ID
        result = runner.invoke(cli, ["show", "proj-chat", "--home", str(home)])
        assert result.exit_code == 0, result.output
        assert "Project Discussion" in result.output

    def test_show_not_found(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["show", "nonexistent", "--home", str(home)])
        assert result.exit_code == 0
        assert "not found" in result.output.lower()


class TestMoveCmd:
    def test_move_chat(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()

        # Move inbox chat to project
        result = runner.invoke(cli, [
            "move", "inbox-chat-001", "my-project", "--home", str(home),
        ])
        assert result.exit_code == 0, result.output
        assert "Moved to my-project" in result.output

        # Verify in meta.db
        db = MetaDB(home / ".acl" / "meta.db")
        chat = db.get_chat("inbox-chat-001")
        assert chat["project_id"] == "my-project"
        db.close()

        # Verify file was moved
        old_path = home / "_inbox" / "2025-02-19_quick-question.md"
        assert not old_path.exists()
        new_path = home / "my-project" / "2025-02-19_quick-question.md"
        assert new_path.exists()

    def test_move_not_found(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "move", "nonexistent", "my-project", "--home", str(home),
        ])
        assert result.exit_code == 0
        assert "not found" in result.output.lower()

    def test_move_bad_project(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "move", "inbox-chat-001", "nonexistent-project", "--home", str(home),
        ])
        assert result.exit_code == 0
        assert "does not exist" in result.output


class TestTagCmd:
    def test_tag_chat(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "tag", "proj-chat-001", "auth", "security", "--home", str(home),
        ])
        assert result.exit_code == 0, result.output
        assert "auth" in result.output
        assert "security" in result.output
        assert "design" in result.output  # original tag preserved

        # Verify in file
        storage = ChatStorage(home)
        project_dir = home / "my-project"
        chat = storage.read_chat(
            project_dir / "2025-02-18_project-discussion.md",
            load_messages=False,
        )
        assert "auth" in chat.tags
        assert "security" in chat.tags
        assert "design" in chat.tags

        # Verify in meta.db
        db = MetaDB(home / ".acl" / "meta.db")
        import json
        rec = db.get_chat("proj-chat-001")
        tags = json.loads(rec["tags"])
        assert "auth" in tags
        db.close()

    def test_tag_not_found(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "tag", "nonexistent", "foo", "--home", str(home),
        ])
        assert result.exit_code == 0
        assert "not found" in result.output.lower()


class TestCreateProjectCmd:
    def test_create_project(self, tmp_path: Path):
        home = tmp_path / "home"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "create", "project", "New Project", "--home", str(home),
        ])
        assert result.exit_code == 0, result.output
        assert "New Project" in result.output

        # Verify directory was created
        assert (home / "new-project" / "_project.yaml").exists()

        # Verify in meta.db
        db = MetaDB(home / ".acl" / "meta.db")
        proj = db.get_project("new-project")
        assert proj is not None
        assert proj["name"] == "New Project"
        db.close()

    def test_create_project_with_description(self, tmp_path: Path):
        home = tmp_path / "home"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "create", "project", "My App", "-d", "A cool app", "--home", str(home),
        ])
        assert result.exit_code == 0, result.output

        storage = ChatStorage(home)
        project = storage.read_project(home / "my-app" / "_project.yaml")
        assert project.description == "A cool app"


class TestReindexCmd:
    def test_reindex(self, tmp_path: Path):
        home = tmp_path / "home"
        storage = ChatStorage(home)
        storage.init_home()

        # Create some chats without indexing
        chat = Chat(
            id="unindexed-001",
            title="Unindexed Chat",
            provider="claude",
            messages=[ChatMessage(role="human", content="hello world")],
        )
        storage.write_chat(home / "_inbox" / "chat.md", chat)

        runner = CliRunner()
        result = runner.invoke(cli, ["reindex", "--home", str(home)])
        assert result.exit_code == 0, result.output
        assert "Indexed 1 chats" in result.output

        # Verify we can search now
        db = MetaDB(home / ".acl" / "meta.db")
        assert db.get_chat("unindexed-001") is not None
        db.close()

    def test_reindex_empty(self, tmp_path: Path):
        home = tmp_path / "home"
        runner = CliRunner()
        result = runner.invoke(cli, ["reindex", "--home", str(home)])
        assert result.exit_code == 0
        assert "Indexed 0 chats" in result.output
