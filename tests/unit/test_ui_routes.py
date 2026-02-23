"""Tests for anticlaw.ui.app — Web UI routes."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from anticlaw.core.meta_db import MetaDB
from anticlaw.core.models import Chat, ChatMessage, Insight, Status

# Check if FastAPI and Jinja2 are available
try:
    from fastapi.testclient import TestClient

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

try:
    import jinja2  # noqa: F401

    HAS_JINJA2 = True
except ImportError:
    HAS_JINJA2 = False

HAS_UI = HAS_FASTAPI and HAS_JINJA2

pytestmark = pytest.mark.skipif(not HAS_UI, reason="FastAPI or Jinja2 not installed")


def _setup_home(tmp_path: Path) -> Path:
    """Create a home dir with seeded data for UI tests."""
    home = tmp_path / "home"
    acl = home / ".acl"
    acl.mkdir(parents=True)
    (home / "_inbox").mkdir(parents=True)

    db = MetaDB(acl / "meta.db")

    # Add project
    from anticlaw.core.models import Project

    project = Project(
        name="Project Alpha",
        description="Test project",
        created=datetime(2025, 2, 18, 14, 0, tzinfo=timezone.utc),
        updated=datetime(2025, 2, 18, 14, 0, tzinfo=timezone.utc),
    )
    project_dir = home / "proj-alpha"
    project_dir.mkdir(parents=True, exist_ok=True)
    db.index_project(project, project_dir)

    # Add regular chats in project
    for i in range(3):
        chat = Chat(
            id=f"chat-{i}",
            title=f"Chat {i}",
            provider="claude",
            tags=["test", "alpha"],
            importance="medium",
            status=Status.ACTIVE,
            messages=[ChatMessage(role="human", content=f"content about topic {i}")],
        )
        db.index_chat(chat, home / f"chat-{i}.md", "proj-alpha")

    # Add inbox chats
    for i in range(2):
        chat = Chat(
            id=f"inbox-{i}",
            title=f"Inbox Chat {i}",
            provider="chatgpt",
            tags=["unclassified"],
            importance="low",
            status=Status.ACTIVE,
            messages=[ChatMessage(role="human", content=f"inbox content {i}")],
        )
        db.index_chat(chat, home / f"_inbox/inbox-{i}.md", "_inbox")

    # Add insight
    insight = Insight(id="ins-1", content="topic is important")
    db.add_insight(insight)

    db.close()
    return home


def _create_client(home: Path) -> "TestClient":
    """Create a TestClient with UI enabled."""
    from anticlaw.api.server import create_app

    app = create_app(home=home, enable_ui=True)
    return TestClient(app)


class TestUiDashboard:
    def test_dashboard_returns_html(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        client = _create_client(home)
        resp = client.get("/ui")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_dashboard_trailing_slash(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        client = _create_client(home)
        resp = client.get("/ui/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_dashboard_contains_stats(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        client = _create_client(home)
        resp = client.get("/ui")
        html = resp.text
        # Should show chat count (5 = 3 project + 2 inbox)
        assert "5" in html
        # Should show project count
        assert "1" in html
        # Should contain Dashboard heading
        assert "Dashboard" in html

    def test_dashboard_contains_nav(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        client = _create_client(home)
        resp = client.get("/ui")
        html = resp.text
        assert "AnticLaw" in html
        assert "/ui/search" in html
        assert "/ui/projects" in html
        assert "/ui/inbox" in html


class TestUiSearch:
    def test_search_page_returns_html(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        client = _create_client(home)
        resp = client.get("/ui/search")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Search" in resp.text

    def test_search_with_query(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        client = _create_client(home)
        resp = client.get("/ui/search", params={"q": "topic"})
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_search_results_partial(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        client = _create_client(home)
        resp = client.get("/ui/search/results", params={"q": "topic"})
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_search_results_empty(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        client = _create_client(home)
        resp = client.get("/ui/search/results", params={"q": "nonexistent_xyz_999"})
        assert resp.status_code == 200
        assert "No results found" in resp.text


class TestUiProjects:
    def test_projects_page_returns_html(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        client = _create_client(home)
        resp = client.get("/ui/projects")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Projects" in resp.text

    def test_projects_lists_projects(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        client = _create_client(home)
        resp = client.get("/ui/projects")
        assert "Project Alpha" in resp.text

    def test_projects_with_selected(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        client = _create_client(home)
        resp = client.get("/ui/projects", params={"project": "proj-alpha"})
        assert resp.status_code == 200
        # Should show chats from the project
        assert "Chat 0" in resp.text

    def test_project_chats_partial(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        client = _create_client(home)
        resp = client.get("/ui/projects/chats", params={"project": "proj-alpha"})
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


class TestUiInbox:
    def test_inbox_returns_html(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        client = _create_client(home)
        resp = client.get("/ui/inbox")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Inbox" in resp.text

    def test_inbox_shows_chats(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        client = _create_client(home)
        resp = client.get("/ui/inbox")
        assert "Inbox Chat 0" in resp.text
        assert "Inbox Chat 1" in resp.text


class TestUiDisabled:
    def test_ui_not_mounted_when_disabled(self, tmp_path: Path):
        """When enable_ui=False, /ui routes should 404."""
        home = _setup_home(tmp_path)
        from anticlaw.api.server import create_app

        app = create_app(home=home, enable_ui=False)
        client = TestClient(app)
        resp = client.get("/ui")
        assert resp.status_code == 404
