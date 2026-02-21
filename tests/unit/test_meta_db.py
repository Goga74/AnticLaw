"""Tests for anticlaw.core.meta_db."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from anticlaw.core.meta_db import MetaDB, SearchResult
from anticlaw.core.models import Chat, ChatMessage, Project, Status
from anticlaw.core.storage import ChatStorage


def _make_chat(
    id: str = "chat-001",
    title: str = "Auth Discussion",
    provider: str = "claude",
    tags: list | None = None,
    messages: list | None = None,
    summary: str = "",
) -> Chat:
    return Chat(
        id=id,
        title=title,
        created=datetime(2025, 2, 18, 14, 30, tzinfo=timezone.utc),
        updated=datetime(2025, 2, 18, 15, 0, tzinfo=timezone.utc),
        provider=provider,
        remote_id=f"remote-{id}",
        model="claude-opus-4-6",
        tags=tags or [],
        summary=summary,
        importance="medium",
        status=Status.ACTIVE,
        messages=messages or [
            ChatMessage(role="human", content="How should we implement auth?"),
            ChatMessage(role="assistant", content="There are three main approaches."),
        ],
    )


def _make_project(name: str = "Project Alpha") -> Project:
    return Project(
        name=name,
        description="Test project",
        created=datetime(2025, 2, 18, 14, 0, tzinfo=timezone.utc),
        updated=datetime(2025, 2, 18, 14, 0, tzinfo=timezone.utc),
    )


class TestMetaDBSchema:
    def test_create_db(self, tmp_path: Path):
        db = MetaDB(tmp_path / ".acl" / "meta.db")
        assert db.conn is not None
        # Tables should exist
        tables = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {r["name"] for r in tables}
        assert "chats" in table_names
        assert "projects" in table_names
        # chats_fts is a virtual table
        vtables = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chats_fts'"
        ).fetchall()
        assert len(vtables) == 1
        db.close()

    def test_wal_mode(self, tmp_path: Path):
        db = MetaDB(tmp_path / ".acl" / "meta.db")
        mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        db.close()

    def test_creates_parent_dirs(self, tmp_path: Path):
        db_path = tmp_path / "deep" / "nested" / "meta.db"
        db = MetaDB(db_path)
        _ = db.conn
        assert db_path.exists()
        db.close()


class TestIndexChat:
    def test_index_and_retrieve(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        chat = _make_chat()
        db.index_chat(chat, tmp_path / "chat.md", "my-project")

        result = db.get_chat("chat-001")
        assert result is not None
        assert result["title"] == "Auth Discussion"
        assert result["project_id"] == "my-project"
        assert result["provider"] == "claude"
        db.close()

    def test_index_updates_existing(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        chat = _make_chat()
        db.index_chat(chat, tmp_path / "chat.md", "proj-a")

        chat.title = "Updated Title"
        db.index_chat(chat, tmp_path / "chat.md", "proj-b")

        result = db.get_chat("chat-001")
        assert result["title"] == "Updated Title"
        assert result["project_id"] == "proj-b"
        db.close()

    def test_index_stores_content(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        chat = _make_chat()
        db.index_chat(chat, tmp_path / "chat.md")

        result = db.get_chat("chat-001")
        assert "auth" in result["content"].lower()
        db.close()

    def test_index_stores_tags_json(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        chat = _make_chat(tags=["auth", "security"])
        db.index_chat(chat, tmp_path / "chat.md")

        result = db.get_chat("chat-001")
        import json
        tags = json.loads(result["tags"])
        assert tags == ["auth", "security"]
        db.close()


class TestIndexProject:
    def test_index_and_retrieve(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        project = _make_project()
        project_dir = tmp_path / "project-alpha"
        project_dir.mkdir()
        db.index_project(project, project_dir)

        result = db.get_project("project-alpha")
        assert result is not None
        assert result["name"] == "Project Alpha"
        db.close()

    def test_list_projects(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        for name, slug in [("Alpha", "alpha"), ("Beta", "beta")]:
            p = _make_project(name)
            d = tmp_path / slug
            d.mkdir()
            db.index_project(p, d)

        projects = db.list_projects()
        assert len(projects) == 2
        db.close()


class TestSearchKeyword:
    def test_search_finds_content(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        chat = _make_chat()
        db.index_chat(chat, tmp_path / "chat.md", "proj")

        results = db.search_keyword("auth")
        assert len(results) == 1
        assert results[0].chat_id == "chat-001"
        assert results[0].title == "Auth Discussion"
        db.close()

    def test_search_no_results(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        chat = _make_chat()
        db.index_chat(chat, tmp_path / "chat.md")

        results = db.search_keyword("kubernetes")
        assert results == []
        db.close()

    def test_search_exact_phrase(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        chat = _make_chat(messages=[
            ChatMessage(role="human", content="three main approaches to auth"),
        ])
        db.index_chat(chat, tmp_path / "chat.md")

        # Exact phrase should match
        results = db.search_keyword("main approaches", exact=True)
        assert len(results) == 1

        # Reversed words should not match exact
        results = db.search_keyword("approaches main", exact=True)
        assert len(results) == 0
        db.close()

    def test_search_filter_by_project(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        chat1 = _make_chat(id="c1", title="Chat A", messages=[
            ChatMessage(role="human", content="authentication topic"),
        ])
        chat2 = _make_chat(id="c2", title="Chat B", messages=[
            ChatMessage(role="human", content="authentication topic"),
        ])
        db.index_chat(chat1, tmp_path / "a.md", "proj-a")
        db.index_chat(chat2, tmp_path / "b.md", "proj-b")

        results = db.search_keyword("authentication", project="proj-a")
        assert len(results) == 1
        assert results[0].chat_id == "c1"
        db.close()

    def test_search_filter_by_tags(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        chat1 = _make_chat(id="c1", tags=["auth", "security"])
        chat2 = _make_chat(id="c2", tags=["database"])
        db.index_chat(chat1, tmp_path / "a.md")
        db.index_chat(chat2, tmp_path / "b.md")

        results = db.search_keyword("auth", tags=["security"])
        assert len(results) == 1
        assert results[0].chat_id == "c1"
        db.close()

    def test_search_returns_snippet(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        chat = _make_chat(messages=[
            ChatMessage(role="human", content="How do we implement JWT authentication?"),
        ])
        db.index_chat(chat, tmp_path / "chat.md")

        results = db.search_keyword("JWT")
        assert len(results) == 1
        assert "**" in results[0].snippet  # highlight markers
        db.close()

    def test_search_max_results(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        for i in range(5):
            chat = _make_chat(id=f"c{i}", title=f"Chat {i}", messages=[
                ChatMessage(role="human", content="common search term"),
            ])
            db.index_chat(chat, tmp_path / f"c{i}.md")

        results = db.search_keyword("common", max_results=3)
        assert len(results) == 3
        db.close()

    def test_search_multi_word(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        chat = _make_chat(messages=[
            ChatMessage(role="human", content="implement JWT authentication"),
        ])
        db.index_chat(chat, tmp_path / "chat.md")

        # FTS5 treats multiple words as AND
        results = db.search_keyword("JWT authentication")
        assert len(results) == 1
        db.close()


class TestReindexAll:
    def test_reindex_from_filesystem(self, tmp_path: Path):
        home = tmp_path / "home"
        storage = ChatStorage(home)
        storage.init_home()

        # Create a project with a chat
        project_dir = storage.create_project("Test Project")
        chat = _make_chat()
        storage.write_chat(project_dir / "chat.md", chat)

        # Create an inbox chat
        inbox_chat = _make_chat(id="inbox-1", title="Inbox Chat")
        storage.write_chat(home / "_inbox" / "inbox.md", inbox_chat)

        # Reindex
        db = MetaDB(home / ".acl" / "meta.db")
        chats_count, projects_count = db.reindex_all(home)

        assert chats_count == 2
        assert projects_count == 1

        # Verify data
        assert db.get_chat("chat-001") is not None
        assert db.get_chat("inbox-1") is not None
        assert db.get_project("test-project") is not None
        db.close()

    def test_reindex_clears_old_data(self, tmp_path: Path):
        home = tmp_path / "home"
        storage = ChatStorage(home)
        storage.init_home()

        db = MetaDB(home / ".acl" / "meta.db")

        # Index a chat directly
        chat = _make_chat(id="old-chat")
        db.index_chat(chat, tmp_path / "old.md")
        assert db.get_chat("old-chat") is not None

        # Reindex — should clear old data
        chats_count, _ = db.reindex_all(home)
        assert chats_count == 0
        assert db.get_chat("old-chat") is None
        db.close()


class TestUpdateOperations:
    def test_update_chat_tags(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        chat = _make_chat(tags=["old"])
        db.index_chat(chat, tmp_path / "chat.md")

        db.update_chat_tags("chat-001", ["new", "tags"])

        result = db.get_chat("chat-001")
        import json
        assert json.loads(result["tags"]) == ["new", "tags"]

        # FTS should still work after tag update
        results = db.search_keyword("auth")
        assert len(results) == 1
        db.close()

    def test_update_chat_path(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        chat = _make_chat()
        db.index_chat(chat, tmp_path / "old.md", "old-project")

        db.update_chat_path("chat-001", tmp_path / "new.md", "new-project")

        result = db.get_chat("chat-001")
        assert result["project_id"] == "new-project"
        assert "new.md" in result["file_path"]
        db.close()


class TestListChats:
    def test_list_all(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        for i in range(3):
            chat = _make_chat(id=f"c{i}")
            db.index_chat(chat, tmp_path / f"c{i}.md")

        chats = db.list_chats()
        assert len(chats) == 3
        db.close()

    def test_list_by_project(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        db.index_chat(_make_chat(id="c1"), tmp_path / "a.md", "proj-a")
        db.index_chat(_make_chat(id="c2"), tmp_path / "b.md", "proj-b")
        db.index_chat(_make_chat(id="c3"), tmp_path / "c.md", "proj-a")

        chats = db.list_chats("proj-a")
        assert len(chats) == 2
        db.close()

    def test_get_chat_not_found(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        assert db.get_chat("nonexistent") is None
        db.close()

    def test_get_project_not_found(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        assert db.get_project("nonexistent") is None
        db.close()
