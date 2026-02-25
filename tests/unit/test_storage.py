"""Tests for anticlaw.core.storage."""

from datetime import datetime, timezone
from pathlib import Path

from anticlaw.core.models import Chat, ChatMessage, Importance, Project, Status
from anticlaw.core.storage import ChatStorage


def _make_chat(**kwargs) -> Chat:
    defaults = {
        "id": "test-001",
        "title": "Auth Discussion",
        "created": datetime(2025, 2, 18, 14, 30, tzinfo=timezone.utc),
        "updated": datetime(2025, 2, 20, 9, 15, tzinfo=timezone.utc),
        "provider": "claude",
        "remote_id": "28d595a3-5db0-492d-a49a-af74f13de505",
        "tags": ["auth", "jwt"],
        "summary": "Chose JWT + refresh tokens.",
        "importance": Importance.HIGH,
        "messages": [
            ChatMessage(
                role="human",
                content="How should we implement auth?",
                timestamp=datetime(2025, 2, 18, 14, 30, tzinfo=timezone.utc),
            ),
            ChatMessage(
                role="assistant",
                content="There are three main approaches...",
                timestamp=datetime(2025, 2, 18, 14, 31, tzinfo=timezone.utc),
            ),
        ],
    }
    defaults.update(kwargs)
    return Chat(**defaults)


def _make_project(**kwargs) -> Project:
    defaults = {
        "name": "Project Alpha",
        "description": "Main product API",
        "created": datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc),
        "updated": datetime(2025, 2, 20, 9, 15, tzinfo=timezone.utc),
        "tags": ["api", "backend"],
        "status": Status.ACTIVE,
        "providers": {"claude": {"project_id": "proj_abc123"}},
        "settings": {"auto_summarize": True, "retention_days": 90},
    }
    defaults.update(kwargs)
    return Project(**defaults)


class TestInitHome:
    def test_creates_structure(self, tmp_path: Path):
        home = tmp_path / "anticlaw"
        storage = ChatStorage(home)
        storage.init_home()

        assert (home / ".acl").is_dir()
        assert (home / "_inbox").is_dir()
        assert (home / "_archive").is_dir()


class TestChatRoundTrip:
    def test_write_then_read(self, tmp_path: Path):
        storage = ChatStorage(tmp_path)
        chat = _make_chat()
        path = tmp_path / "test-chat.md"

        storage.write_chat(path, chat)
        assert path.exists()

        loaded = storage.read_chat(path)
        assert loaded.id == chat.id
        assert loaded.title == chat.title
        assert loaded.provider == chat.provider
        assert loaded.remote_id == chat.remote_id
        assert loaded.tags == chat.tags
        assert loaded.summary == chat.summary
        assert loaded.importance == "high"
        assert loaded.status == "active"

    def test_messages_round_trip(self, tmp_path: Path):
        storage = ChatStorage(tmp_path)
        chat = _make_chat()
        path = tmp_path / "test-chat.md"

        storage.write_chat(path, chat)
        loaded = storage.read_chat(path)

        assert len(loaded.messages) == 2
        assert loaded.messages[0].role == "human"
        assert loaded.messages[0].content == "How should we implement auth?"
        assert loaded.messages[1].role == "assistant"
        assert loaded.messages[1].content == "There are three main approaches..."

    def test_empty_messages(self, tmp_path: Path):
        storage = ChatStorage(tmp_path)
        chat = _make_chat(messages=[])
        path = tmp_path / "empty.md"

        storage.write_chat(path, chat)
        loaded = storage.read_chat(path)
        assert loaded.messages == []

    def test_multiline_content(self, tmp_path: Path):
        storage = ChatStorage(tmp_path)
        content = "Line 1\nLine 2\n\nLine 4 with code:\n```python\nprint('hi')\n```"
        chat = _make_chat(
            messages=[ChatMessage(role="human", content=content)]
        )
        path = tmp_path / "multiline.md"

        storage.write_chat(path, chat)
        loaded = storage.read_chat(path)
        assert loaded.messages[0].content == content

    def test_load_without_messages(self, tmp_path: Path):
        storage = ChatStorage(tmp_path)
        chat = _make_chat()
        path = tmp_path / "test.md"
        storage.write_chat(path, chat)

        loaded = storage.read_chat(path, load_messages=False)
        assert loaded.title == chat.title
        assert loaded.messages == []


class TestEnumSerialization:
    def test_importance_writes_as_value(self, tmp_path: Path):
        """Importance enum should serialize as 'medium', not 'Importance.MEDIUM'."""
        storage = ChatStorage(tmp_path)
        chat = _make_chat(importance=Importance.MEDIUM)
        path = tmp_path / "enum-test.md"
        storage.write_chat(path, chat)

        raw = path.read_text(encoding="utf-8")
        assert "Importance.MEDIUM" not in raw
        assert "importance: medium" in raw

    def test_status_writes_as_value(self, tmp_path: Path):
        """Status enum should serialize as 'active', not 'Status.ACTIVE'."""
        storage = ChatStorage(tmp_path)
        chat = _make_chat(status=Status.ACTIVE)
        path = tmp_path / "status-test.md"
        storage.write_chat(path, chat)

        raw = path.read_text(encoding="utf-8")
        assert "Status.ACTIVE" not in raw
        assert "status: active" in raw

    def test_string_importance_still_works(self, tmp_path: Path):
        """If importance is already a plain string, it should serialize fine."""
        storage = ChatStorage(tmp_path)
        chat = _make_chat(importance="high")
        path = tmp_path / "str-imp.md"
        storage.write_chat(path, chat)

        loaded = storage.read_chat(path)
        assert loaded.importance == "high"

    def test_remote_project_id_empty_becomes_null(self, tmp_path: Path):
        """Empty remote_project_id should serialize as null, not ''."""
        storage = ChatStorage(tmp_path)
        chat = _make_chat(remote_project_id="")
        path = tmp_path / "null-rpid.md"
        storage.write_chat(path, chat)

        raw = path.read_text(encoding="utf-8")
        assert "remote_project_id: ''" not in raw
        assert "remote_project_id: null" in raw or "remote_project_id:" in raw

    def test_remote_project_id_with_value(self, tmp_path: Path):
        """Non-empty remote_project_id should be preserved."""
        storage = ChatStorage(tmp_path)
        chat = _make_chat(remote_project_id="proj-uuid-123")
        path = tmp_path / "rpid.md"
        storage.write_chat(path, chat)

        loaded = storage.read_chat(path)
        assert loaded.remote_project_id == "proj-uuid-123"


class TestProjectRoundTrip:
    def test_write_then_read(self, tmp_path: Path):
        storage = ChatStorage(tmp_path)
        project = _make_project()
        path = tmp_path / "_project.yaml"

        storage.write_project(path, project)
        assert path.exists()

        loaded = storage.read_project(path)
        assert loaded.name == project.name
        assert loaded.description == project.description
        assert loaded.tags == project.tags
        assert loaded.status == "active"
        assert loaded.providers == project.providers
        assert loaded.settings == project.settings

    def test_create_project(self, tmp_path: Path):
        storage = ChatStorage(tmp_path)
        project_dir = storage.create_project("My New Project", "Description here")

        assert project_dir.is_dir()
        assert (project_dir / "_project.yaml").exists()

        loaded = storage.read_project(project_dir / "_project.yaml")
        assert loaded.name == "My New Project"
        assert loaded.description == "Description here"


class TestListProjects:
    def test_empty_home(self, tmp_path: Path):
        storage = ChatStorage(tmp_path)
        assert storage.list_projects() == []

    def test_finds_projects(self, tmp_path: Path):
        storage = ChatStorage(tmp_path)
        storage.init_home()

        # Create two projects
        storage.create_project("Alpha")
        storage.create_project("Beta")

        projects = storage.list_projects()
        names = [p.name for p in projects]
        assert "Alpha" in names
        assert "Beta" in names

    def test_ignores_reserved_dirs(self, tmp_path: Path):
        storage = ChatStorage(tmp_path)
        storage.init_home()
        storage.create_project("Real Project")

        projects = storage.list_projects()
        names = [p.name for p in projects]
        assert "_inbox" not in names
        assert "_archive" not in names
        assert ".acl" not in names


class TestListChats:
    def test_lists_md_files(self, tmp_path: Path):
        storage = ChatStorage(tmp_path)
        project_dir = tmp_path / "alpha"
        project_dir.mkdir()

        chat = _make_chat(title="Chat One")
        storage.write_chat(project_dir / "2025-02-18_chat-one.md", chat)

        chat2 = _make_chat(id="test-002", title="Chat Two")
        storage.write_chat(project_dir / "2025-02-19_chat-two.md", chat2)

        chats = storage.list_chats(project_dir)
        assert len(chats) == 2

    def test_skips_underscore_files(self, tmp_path: Path):
        storage = ChatStorage(tmp_path)
        project_dir = tmp_path / "alpha"
        project_dir.mkdir()

        chat = _make_chat()
        storage.write_chat(project_dir / "2025-02-18_chat.md", chat)
        # This should be skipped
        (project_dir / "_project.yaml").write_text("name: test")

        chats = storage.list_chats(project_dir)
        assert len(chats) == 1

    def test_nonexistent_dir(self, tmp_path: Path):
        storage = ChatStorage(tmp_path)
        chats = storage.list_chats(tmp_path / "nonexistent")
        assert chats == []


class TestMoveChat:
    def test_moves_file(self, tmp_path: Path):
        storage = ChatStorage(tmp_path)
        src_dir = tmp_path / "src_project"
        dst_dir = tmp_path / "dst_project"
        src_dir.mkdir()
        dst_dir.mkdir()

        chat = _make_chat()
        src_path = src_dir / "chat.md"
        storage.write_chat(src_path, chat)

        new_path = storage.move_chat(src_path, dst_dir)
        assert new_path.exists()
        assert not src_path.exists()
        assert new_path.parent == dst_dir

    def test_handles_name_collision(self, tmp_path: Path):
        storage = ChatStorage(tmp_path)
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()

        chat = _make_chat()
        src_path = src_dir / "chat.md"
        storage.write_chat(src_path, chat)
        # Pre-existing file with same name at destination
        (dst_dir / "chat.md").write_text("existing")

        new_path = storage.move_chat(src_path, dst_dir)
        assert new_path.exists()
        assert new_path.name == "chat_1.md"


class TestChatFilename:
    def test_generates_filename(self, tmp_path: Path):
        storage = ChatStorage(tmp_path)
        chat = _make_chat(
            title="Auth Discussion",
            created=datetime(2025, 2, 18, 14, 30, tzinfo=timezone.utc),
        )
        filename = storage.chat_filename(chat)
        assert filename == "2025-02-18_auth-discussion.md"

    def test_untitled(self, tmp_path: Path):
        storage = ChatStorage(tmp_path)
        chat = _make_chat(title="")
        filename = storage.chat_filename(chat)
        assert "untitled" in filename
