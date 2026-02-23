"""Tests for anticlaw.api.server."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from anticlaw.core.meta_db import MetaDB
from anticlaw.core.models import Chat, ChatMessage, Insight, SourceDocument, Status

# Check if FastAPI is available
try:
    from fastapi.testclient import TestClient

    from anticlaw.api.server import _is_localhost, create_app

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed")


def _setup_home(tmp_path: Path) -> Path:
    """Create a home dir with indexed data."""
    home = tmp_path / "home"
    acl = home / ".acl"
    acl.mkdir(parents=True)
    (home / "_inbox").mkdir(parents=True)

    db = MetaDB(acl / "meta.db")

    # Add chats
    for i in range(3):
        chat = Chat(
            id=f"chat-{i}",
            title=f"Chat {i}",
            provider="claude",
            tags=["test"],
            importance="medium",
            status=Status.ACTIVE,
            messages=[ChatMessage(role="human", content=f"content about topic {i}")],
        )
        db.index_chat(chat, home / f"chat-{i}.md", "proj-a")

    # Add source file
    doc = SourceDocument(
        id="src-1",
        file_path="/code/main.py",
        filename="main.py",
        extension=".py",
        language="python",
        content="def topic(): pass",
        size=17,
        hash="abc",
    )
    db.index_source_file(doc)

    # Add insight
    insight = Insight(id="ins-1", content="topic is important")
    db.add_insight(insight)

    # Add project
    from anticlaw.core.models import Project

    project = Project(
        name="Project A",
        description="Test project",
        created=datetime(2025, 2, 18, 14, 0, tzinfo=timezone.utc),
        updated=datetime(2025, 2, 18, 14, 0, tzinfo=timezone.utc),
    )
    project_dir = home / "proj-a"
    project_dir.mkdir(parents=True, exist_ok=True)
    db.index_project(project, project_dir)

    db.close()
    return home


class TestIsLocalhost:
    def test_ipv4_loopback(self):
        assert _is_localhost("127.0.0.1") is True

    def test_ipv6_loopback(self):
        assert _is_localhost("::1") is True

    def test_remote_ip(self):
        assert _is_localhost("192.168.1.100") is False

    def test_localhost_string(self):
        assert _is_localhost("localhost") is True


class TestHealthEndpoint:
    def test_health(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        app = create_app(home=home)
        client = TestClient(app)

        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "home" in data


class TestSearchEndpoint:
    def test_search_returns_results(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        app = create_app(home=home)
        client = TestClient(app)

        resp = client.get("/api/search", params={"q": "topic"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "topic"
        assert data["count"] > 0
        assert len(data["results"]) > 0

    def test_search_no_results(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        app = create_app(home=home)
        client = TestClient(app)

        resp = client.get("/api/search", params={"q": "nonexistent_xyz"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    def test_search_requires_query(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        app = create_app(home=home)
        client = TestClient(app)

        resp = client.get("/api/search")
        assert resp.status_code == 422  # FastAPI validation error

    def test_search_type_filter(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        app = create_app(home=home)
        client = TestClient(app)

        resp = client.get("/api/search", params={"q": "topic", "type": "file"})
        assert resp.status_code == 200
        data = resp.json()
        for r in data["results"]:
            assert r["type"] == "file"


class TestProjectsEndpoint:
    def test_list_projects(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        app = create_app(home=home)
        client = TestClient(app)

        resp = client.get("/api/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert len(data["projects"]) == 1
        assert data["projects"][0]["name"] == "Project A"


class TestStatsEndpoint:
    def test_stats(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        app = create_app(home=home)
        client = TestClient(app)

        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chats"] == 3
        assert data["projects"] == 1
        assert data["insights"] == 1
        assert data["source_files"] == 1


class TestAskEndpoint:
    def test_ask_no_question(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        app = create_app(home=home)
        client = TestClient(app)

        resp = client.post("/api/ask", json={})
        assert resp.status_code == 400

    def test_ask_with_question(self, tmp_path: Path):
        """Ask endpoint should handle gracefully (LLM may not be available)."""
        home = _setup_home(tmp_path)
        app = create_app(home=home)
        client = TestClient(app)

        resp = client.post("/api/ask", json={"question": "What is JWT?"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["question"] == "What is JWT?"
        # May have error if Ollama not running — that's ok
        assert "answer" in data
        assert "sources" in data


class TestApiKeyAuth:
    def test_no_auth_required_localhost(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        app = create_app(home=home, api_key="secret123")
        client = TestClient(app)

        # TestClient sends host='testclient', so mock _is_localhost
        with patch("anticlaw.api.server._is_localhost", return_value=True):
            resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_auth_required_remote(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        app = create_app(home=home, api_key="secret123")
        client = TestClient(app)

        # Simulate remote request by patching client host
        with patch("anticlaw.api.server._is_localhost", return_value=False):
            resp = client.get("/api/health")
            assert resp.status_code == 401

    def test_auth_valid_key_remote(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        app = create_app(home=home, api_key="secret123")
        client = TestClient(app)

        with patch("anticlaw.api.server._is_localhost", return_value=False):
            resp = client.get(
                "/api/health",
                headers={"Authorization": "Bearer secret123"},
            )
            assert resp.status_code == 200

    def test_auth_invalid_key_remote(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        app = create_app(home=home, api_key="secret123")
        client = TestClient(app)

        with patch("anticlaw.api.server._is_localhost", return_value=False):
            resp = client.get(
                "/api/health",
                headers={"Authorization": "Bearer wrong_key"},
            )
            assert resp.status_code == 401

    def test_no_key_configured_allows_all(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        app = create_app(home=home, api_key=None)
        client = TestClient(app)

        resp = client.get("/api/health")
        assert resp.status_code == 200
