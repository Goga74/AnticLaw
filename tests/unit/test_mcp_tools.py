"""Tests for anticlaw.mcp.server tool implementations."""

from datetime import datetime, timezone
from pathlib import Path

from anticlaw.core.meta_db import MetaDB
from anticlaw.core.models import Chat, ChatMessage, Insight, Project
from anticlaw.core.storage import ChatStorage
from anticlaw.mcp.server import (
    forget_impl,
    ping_impl,
    projects_impl,
    recall_impl,
    remember_impl,
    search_impl,
)


def _setup_home(tmp_path: Path) -> Path:
    """Create a home directory with indexed content."""
    home = tmp_path / "home"
    storage = ChatStorage(home)
    storage.init_home()

    # Create a project with a chat
    project_dir = storage.create_project("Test Project")
    chat = Chat(
        id="chat-001",
        title="Auth Design",
        provider="claude",
        model="claude-opus-4-6",
        created=datetime(2025, 2, 18, 14, 30, tzinfo=timezone.utc),
        messages=[
            ChatMessage(role="human", content="How should we implement JWT auth?"),
            ChatMessage(role="assistant", content="Use refresh tokens with short-lived access tokens."),
        ],
    )
    storage.write_chat(project_dir / "2025-02-18_auth-design.md", chat)

    # Reindex
    db = MetaDB(home / ".acl" / "meta.db")
    db.reindex_all(home)
    db.close()

    return home


class TestPing:
    def test_ping_ok(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        result = ping_impl(home)
        assert result["status"] == "ok"
        assert result["projects"] == 1
        assert result["chats"] == 1
        assert result["insights"] == 0

    def test_ping_empty_home(self, tmp_path: Path):
        home = tmp_path / "empty"
        storage = ChatStorage(home)
        storage.init_home()
        result = ping_impl(home)
        assert result["status"] == "ok"
        assert result["projects"] == 0
        assert result["chats"] == 0


class TestRemember:
    def test_remember_saves_insight(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        result = remember_impl(
            home,
            content="We decided to use JWT for authentication.",
            category="decision",
            importance="high",
            tags=["auth", "jwt"],
            project_id="test-project",
        )
        assert result["status"] == "saved"
        assert "id" in result

    def test_remember_default_fields(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        result = remember_impl(home, content="Simple fact.")
        assert result["status"] == "saved"


class TestRecall:
    def test_recall_finds_insight(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        remember_impl(home, content="JWT tokens expire after 15 minutes.", tags=["auth"])
        remember_impl(home, content="Database uses PostgreSQL.", tags=["db"])

        results = recall_impl(home, query="JWT")
        assert len(results) == 1
        assert "JWT" in results[0]["content"]

    def test_recall_filter_by_category(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        remember_impl(home, content="Chose JWT.", category="decision")
        remember_impl(home, content="Found JWT library.", category="finding")

        results = recall_impl(home, category="decision")
        assert len(results) == 1
        assert "Chose" in results[0]["content"]

    def test_recall_filter_by_project(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        remember_impl(home, content="Auth insight.", project_id="proj-a")
        remember_impl(home, content="DB insight.", project_id="proj-b")

        results = recall_impl(home, project="proj-a")
        assert len(results) == 1

    def test_recall_empty(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        results = recall_impl(home)
        assert results == []


class TestForget:
    def test_forget_existing(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        saved = remember_impl(home, content="Temporary insight.")
        insight_id = saved["id"]

        result = forget_impl(home, insight_id)
        assert result["status"] == "deleted"

        # Should not appear in recall
        results = recall_impl(home, query="Temporary")
        assert len(results) == 0

    def test_forget_nonexistent(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        result = forget_impl(home, "nonexistent-id")
        assert result["status"] == "not_found"


class TestSearch:
    def test_search_finds_chat(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        results = search_impl(home, "JWT")
        assert len(results) == 1
        assert results[0]["title"] == "Auth Design"

    def test_search_no_results(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        results = search_impl(home, "kubernetes")
        assert results == []

    def test_search_with_project_filter(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        results = search_impl(home, "JWT", project="test-project")
        assert len(results) == 1

    def test_search_exact(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        results = search_impl(home, "JWT auth", exact=True)
        assert len(results) == 1


class TestProjects:
    def test_projects_list(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        results = projects_impl(home)
        assert len(results) == 1
        assert results[0]["name"] == "Test Project"
        assert results[0]["chat_count"] == 1

    def test_projects_empty(self, tmp_path: Path):
        home = tmp_path / "empty"
        storage = ChatStorage(home)
        storage.init_home()
        # Reindex empty home
        db = MetaDB(home / ".acl" / "meta.db")
        db.reindex_all(home)
        db.close()

        results = projects_impl(home)
        assert results == []
