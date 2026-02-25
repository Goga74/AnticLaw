"""Tests for anticlaw.providers.scraper.claude (HTTP API scraper)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anticlaw.providers.scraper.claude import ClaudeScraper

# --- Fixtures: mock API responses ---

CURRENT_USER_RESPONSE = {
    "account": {
        "memberships": [
            {
                "organization": {
                    "uuid": "org-uuid-123",
                    "name": "Personal",
                }
            }
        ]
    }
}

PROJECTS_RESPONSE = [
    {
        "uuid": "proj-uuid-aaa",
        "name": "My Project",
        "is_starter_project": False,
        "prompt_template": "You are a Python expert.",
    },
    {
        "uuid": "proj-uuid-bbb",
        "name": "Another Project",
        "is_starter_project": False,
        "prompt_template": "",
    },
    {
        "uuid": "proj-uuid-starter",
        "name": "Getting Started",
        "is_starter_project": True,
        "prompt_template": "",
    },
]

CHATS_PROJECT_A = [
    {"uuid": "chat-uuid-001", "name": "Auth discussion"},
    {"uuid": "chat-uuid-002", "name": "Database design"},
]

CHATS_PROJECT_B = [
    {"uuid": "chat-uuid-003", "name": "UI wireframes"},
]


def _mock_response(data, status_code: int = 200):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status.return_value = None
    return resp


class TestClaudeScraperProperties:
    def test_name(self):
        scraper = ClaudeScraper(session_key="test-key")
        assert scraper.name == "claude-scraper"

    def test_info(self):
        scraper = ClaudeScraper(session_key="test-key")
        info = scraper.info
        assert info.display_name == "Claude.ai HTTP Scraper"
        assert info.base_url == "https://claude.ai"
        assert "projects" in info.capabilities
        assert "chat_mapping" in info.capabilities


class TestGetOrgId:
    def test_extracts_org_uuid(self):
        scraper = ClaudeScraper(session_key="test-key")
        client = MagicMock()
        client.get.return_value = _mock_response(CURRENT_USER_RESPONSE)

        org_id = scraper._get_org_id(client)

        assert org_id == "org-uuid-123"
        client.get.assert_called_once_with("/api/auth/current_user")

    def test_no_organizations_raises(self):
        scraper = ClaudeScraper(session_key="test-key")
        client = MagicMock()
        client.get.return_value = _mock_response({"account": {"memberships": []}})

        with pytest.raises(ValueError, match="No organizations found"):
            scraper._get_org_id(client)

    def test_empty_uuid_raises(self):
        scraper = ClaudeScraper(session_key="test-key")
        client = MagicMock()
        data = {"account": {"memberships": [{"organization": {"uuid": ""}}]}}
        client.get.return_value = _mock_response(data)

        with pytest.raises(ValueError, match="Could not extract organization UUID"):
            scraper._get_org_id(client)


class TestGetProjects:
    def test_filters_starter_projects(self):
        scraper = ClaudeScraper(session_key="test-key")
        scraper._org_id = "org-123"
        client = MagicMock()
        client.get.return_value = _mock_response(PROJECTS_RESPONSE)

        projects = scraper._get_projects(client)

        assert len(projects) == 2
        names = [p["name"] for p in projects]
        assert "My Project" in names
        assert "Another Project" in names
        assert "Getting Started" not in names

    def test_invalid_response_type_raises(self):
        scraper = ClaudeScraper(session_key="test-key")
        scraper._org_id = "org-123"
        client = MagicMock()
        client.get.return_value = _mock_response("not a list")

        with pytest.raises(ValueError, match="Expected list of projects"):
            scraper._get_projects(client)


class TestGetProjectChats:
    def test_returns_chats_list(self):
        scraper = ClaudeScraper(session_key="test-key")
        scraper._org_id = "org-123"
        client = MagicMock()
        client.get.return_value = _mock_response(CHATS_PROJECT_A)

        chats = scraper._get_project_chats(client, "proj-uuid-aaa")

        assert len(chats) == 2
        assert chats[0]["uuid"] == "chat-uuid-001"

    def test_handles_dict_response_with_pagination(self):
        scraper = ClaudeScraper(session_key="test-key")
        scraper._org_id = "org-123"
        client = MagicMock()

        page1 = _mock_response({
            "data": [{"uuid": "chat-1"}, {"uuid": "chat-2"}],
            "next_page_token": "token-abc",
        })
        page2 = _mock_response({
            "data": [{"uuid": "chat-3"}],
        })
        client.get.side_effect = [page1, page2]

        chats = scraper._get_project_chats(client, "proj-uuid-aaa")

        assert len(chats) == 3
        assert client.get.call_count == 2

    def test_handles_dict_with_chats_key(self):
        scraper = ClaudeScraper(session_key="test-key")
        scraper._org_id = "org-123"
        client = MagicMock()
        client.get.return_value = _mock_response({
            "chats": [{"uuid": "chat-1"}],
        })

        chats = scraper._get_project_chats(client, "proj-uuid-aaa")

        assert len(chats) == 1
        assert chats[0]["uuid"] == "chat-1"


class TestScrape:
    def test_full_scrape_saves_mapping(self, tmp_path: Path):
        scraper = ClaudeScraper(session_key="test-key")
        output = tmp_path / "mapping.json"

        def mock_get(url):
            if "/api/auth/current_user" in url:
                return _mock_response(CURRENT_USER_RESPONSE)
            elif "/projects" in url:
                return _mock_response(PROJECTS_RESPONSE)
            elif "project_uuid=proj-uuid-aaa" in url:
                return _mock_response(CHATS_PROJECT_A)
            elif "project_uuid=proj-uuid-bbb" in url:
                return _mock_response(CHATS_PROJECT_B)
            return _mock_response([])

        mock_client = MagicMock()
        mock_client.get.side_effect = mock_get

        with patch.object(scraper, "_make_client", return_value=mock_client):
            mapping = scraper.scrape(output)

        # Check mapping result
        assert len(mapping.chats) == 3
        assert mapping.chats["chat-uuid-001"] == "my-project"
        assert mapping.chats["chat-uuid-002"] == "my-project"
        assert mapping.chats["chat-uuid-003"] == "another-project"

        assert len(mapping.projects) == 2
        assert mapping.projects["proj-uuid-aaa"]["name"] == "My Project"
        assert mapping.projects["proj-uuid-aaa"]["instructions"] == "You are a Python expert."
        assert mapping.projects["proj-uuid-bbb"]["instructions"] == ""

        assert mapping.scraped_at != ""

        # Check saved file
        assert output.exists()
        saved = json.loads(output.read_text())
        assert saved["chats"]["chat-uuid-001"] == "my-project"
        assert "scraped_at" in saved

    def test_scrape_skips_projects_without_uuid(self, tmp_path: Path):
        scraper = ClaudeScraper(session_key="test-key")
        output = tmp_path / "mapping.json"

        projects_with_missing = [
            {"uuid": "", "name": "No UUID", "is_starter_project": False},
            {"uuid": "proj-valid", "name": "Valid", "is_starter_project": False},
        ]

        def mock_get(url):
            if "/api/auth/current_user" in url:
                return _mock_response(CURRENT_USER_RESPONSE)
            elif "/projects" in url:
                return _mock_response(projects_with_missing)
            elif "project_uuid=proj-valid" in url:
                return _mock_response([{"uuid": "chat-1"}])
            return _mock_response([])

        mock_client = MagicMock()
        mock_client.get.side_effect = mock_get

        with patch.object(scraper, "_make_client", return_value=mock_client):
            mapping = scraper.scrape(output)

        # Only the valid project should have chats
        assert len(mapping.projects) == 1
        assert "proj-valid" in mapping.projects
        assert len(mapping.chats) == 1

    def test_scrape_creates_parent_directories(self, tmp_path: Path):
        scraper = ClaudeScraper(session_key="test-key")
        output = tmp_path / "sub" / "dir" / "mapping.json"

        def mock_get(url):
            if "/api/auth/current_user" in url:
                return _mock_response(CURRENT_USER_RESPONSE)
            elif "/projects" in url:
                return _mock_response([])
            return _mock_response([])

        mock_client = MagicMock()
        mock_client.get.side_effect = mock_get

        with patch.object(scraper, "_make_client", return_value=mock_client):
            scraper.scrape(output)

        assert output.exists()

    def test_scrape_closes_client(self, tmp_path: Path):
        scraper = ClaudeScraper(session_key="test-key")
        output = tmp_path / "mapping.json"

        def mock_get(url):
            if "/api/auth/current_user" in url:
                return _mock_response(CURRENT_USER_RESPONSE)
            elif "/projects" in url:
                return _mock_response([])
            return _mock_response([])

        mock_client = MagicMock()
        mock_client.get.side_effect = mock_get

        with patch.object(scraper, "_make_client", return_value=mock_client):
            scraper.scrape(output)

        mock_client.close.assert_called_once()

    def test_scrape_closes_client_on_error(self, tmp_path: Path):
        scraper = ClaudeScraper(session_key="test-key")
        output = tmp_path / "mapping.json"

        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("Connection failed")

        with patch.object(scraper, "_make_client", return_value=mock_client):
            with pytest.raises(Exception, match="Connection failed"):
                scraper.scrape(output)

        mock_client.close.assert_called_once()


class TestMakeClient:
    def test_creates_client_with_session_cookie(self):
        """Verify _make_client passes session key as cookie."""
        scraper = ClaudeScraper(session_key="my-secret-key")

        # httpx should be available (it's in sync/semantic extras)
        try:
            import httpx

            client = scraper._make_client()
            assert client.cookies.get("sessionKey") == "my-secret-key"
            assert str(client.base_url).rstrip("/") == "https://claude.ai"
            client.close()
        except ImportError:
            pytest.skip("httpx not installed")
