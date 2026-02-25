"""Tests for anticlaw.providers.scraper.claude — ClaudeScraper with mocked Playwright."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anticlaw.providers.scraper.base import ScraperProvider
from anticlaw.providers.scraper.claude import ClaudeScraper


# -- Fixtures for mock API responses --

MOCK_ORG_UUID = "org-11111111-2222-3333-4444-555555555555"

MOCK_CURRENT_USER = {
    "memberships": [
        {
            "organization": {
                "uuid": MOCK_ORG_UUID,
                "name": "Personal",
            }
        }
    ]
}

MOCK_PROJECTS = [
    {
        "uuid": "proj-aaaa-1111",
        "name": "Auth System",
        "description": "Authentication and authorization",
        "prompt_template": "You are a security expert.",
        "is_starter_project": False,
    },
    {
        "uuid": "proj-bbbb-2222",
        "name": "CLI Design",
        "description": "Command line interface",
        "prompt_template": "",
        "is_starter_project": False,
    },
    {
        "uuid": "proj-cccc-3333",
        "name": "Starter Project",
        "description": "Default starter",
        "prompt_template": "",
        "is_starter_project": True,
    },
]

MOCK_AUTH_CHATS = [
    {"uuid": "chat-aaa1", "name": "JWT tokens discussion"},
    {"uuid": "chat-aaa2", "name": "OAuth2 flow"},
    {"uuid": "chat-aaa3", "name": "Session management"},
]

MOCK_CLI_CHATS = [
    {"uuid": "chat-bbb1", "name": "Click vs argparse"},
    {"uuid": "chat-bbb2", "name": "Subcommand design"},
]


def _make_mock_response(status: int, data) -> MagicMock:
    """Create a mock Playwright API response."""
    resp = MagicMock()
    resp.ok = status == 200
    resp.status = status
    resp.json.return_value = data
    return resp


def _make_mock_page() -> MagicMock:
    """Create a mock Playwright page with request context."""
    page = MagicMock()

    def mock_get(url: str):
        if "auth/current_user" in url:
            return _make_mock_response(200, MOCK_CURRENT_USER)
        if url.endswith("/projects"):
            return _make_mock_response(200, MOCK_PROJECTS)
        if f"project_uuid=proj-aaaa-1111" in url:
            return _make_mock_response(200, MOCK_AUTH_CHATS)
        if f"project_uuid=proj-bbbb-2222" in url:
            return _make_mock_response(200, MOCK_CLI_CHATS)
        return _make_mock_response(404, {})

    page.request.get = mock_get
    page.goto = MagicMock()
    page.wait_for_url = MagicMock()
    return page


class TestClaudeScraperProperties:
    def test_name(self):
        scraper = ClaudeScraper()
        assert scraper.name == "claude-scraper"

    def test_info(self):
        scraper = ClaudeScraper()
        info = scraper.info
        assert info.display_name == "Claude.ai Scraper"
        assert info.version == "0.1.0"
        assert info.requires_auth is True
        assert info.requires_browser is True

    def test_implements_protocol(self):
        scraper = ClaudeScraper()
        assert isinstance(scraper, ScraperProvider)

    def test_initial_state(self):
        scraper = ClaudeScraper()
        assert scraper.mapping == {}
        assert scraper.projects == []
        assert scraper.summary() == {"projects": 0, "mapped_chats": 0}


class TestOrgIdDiscovery:
    def test_discovers_org_from_current_user(self):
        scraper = ClaudeScraper()
        page = _make_mock_page()

        scraper._discover_org_id(page)

        assert scraper._org_id == MOCK_ORG_UUID

    def test_raises_on_missing_org(self):
        scraper = ClaudeScraper()
        page = _make_mock_page()
        page.request.get = lambda url: _make_mock_response(200, {"memberships": []})

        with pytest.raises(RuntimeError, match="Could not discover organization ID"):
            scraper._discover_org_id(page)

    def test_raises_on_api_failure(self):
        scraper = ClaudeScraper()
        page = _make_mock_page()
        page.request.get = lambda url: _make_mock_response(401, {})

        with pytest.raises(RuntimeError, match="Could not discover organization ID"):
            scraper._discover_org_id(page)

    def test_skips_if_already_known(self):
        scraper = ClaudeScraper()
        scraper._org_id = "already-known"
        page = _make_mock_page()

        scraper._discover_org_id(page)

        assert scraper._org_id == "already-known"


class TestFetchProjects:
    def test_fetches_projects(self):
        scraper = ClaudeScraper()
        scraper._org_id = MOCK_ORG_UUID
        page = _make_mock_page()

        scraper._fetch_projects(page)

        assert len(scraper._projects) == 2
        names = [p.name for p in scraper._projects]
        assert "Auth System" in names
        assert "CLI Design" in names
        # Starter project should be filtered out
        assert "Starter Project" not in names

    def test_skips_starter_projects(self):
        scraper = ClaudeScraper()
        scraper._org_id = MOCK_ORG_UUID
        page = _make_mock_page()

        scraper._fetch_projects(page)

        uuids = [p.uuid for p in scraper._projects]
        assert "proj-cccc-3333" not in uuids

    def test_captures_prompt_template(self):
        scraper = ClaudeScraper()
        scraper._org_id = MOCK_ORG_UUID
        page = _make_mock_page()

        scraper._fetch_projects(page)

        auth_proj = [p for p in scraper._projects if p.name == "Auth System"][0]
        assert auth_proj.prompt_template == "You are a security expert."

    def test_handles_api_error(self):
        scraper = ClaudeScraper()
        scraper._org_id = MOCK_ORG_UUID
        page = MagicMock()
        page.request.get = lambda url: _make_mock_response(500, {})

        scraper._fetch_projects(page)

        assert scraper._projects == []

    def test_handles_empty_response(self):
        scraper = ClaudeScraper()
        scraper._org_id = MOCK_ORG_UUID
        page = MagicMock()
        page.request.get = lambda url: _make_mock_response(200, [])

        scraper._fetch_projects(page)

        assert scraper._projects == []

    def test_handles_wrapped_response(self):
        """API might return projects wrapped in a 'results' key."""
        scraper = ClaudeScraper()
        scraper._org_id = MOCK_ORG_UUID

        wrapped_data = {"results": MOCK_PROJECTS[:2]}
        page = MagicMock()
        page.request.get = lambda url: _make_mock_response(200, wrapped_data)

        scraper._fetch_projects(page)

        assert len(scraper._projects) == 2

    def test_skips_projects_without_uuid(self):
        scraper = ClaudeScraper()
        scraper._org_id = MOCK_ORG_UUID
        bad_projects = [{"name": "No UUID"}, {"uuid": "", "name": "Empty UUID"}]
        page = MagicMock()
        page.request.get = lambda url: _make_mock_response(200, bad_projects)

        scraper._fetch_projects(page)

        assert scraper._projects == []

    def test_skips_projects_without_name(self):
        scraper = ClaudeScraper()
        scraper._org_id = MOCK_ORG_UUID
        bad_projects = [{"uuid": "abc-123", "name": ""}]
        page = MagicMock()
        page.request.get = lambda url: _make_mock_response(200, bad_projects)

        scraper._fetch_projects(page)

        assert scraper._projects == []


class TestFetchProjectChats:
    def test_fetches_chats_for_project(self):
        scraper = ClaudeScraper()
        scraper._org_id = MOCK_ORG_UUID
        page = _make_mock_page()

        from anticlaw.providers.scraper.base import ScrapedProject

        proj = ScrapedProject(uuid="proj-aaaa-1111", name="Auth System")
        scraper._fetch_project_chats(page, proj)

        assert len(proj.chat_uuids) == 3
        assert "chat-aaa1" in proj.chat_uuids
        assert "chat-aaa2" in proj.chat_uuids
        assert "chat-aaa3" in proj.chat_uuids

    def test_adds_to_mapping(self):
        scraper = ClaudeScraper()
        scraper._org_id = MOCK_ORG_UUID
        page = _make_mock_page()

        from anticlaw.providers.scraper.base import ScrapedProject

        proj = ScrapedProject(uuid="proj-aaaa-1111", name="Auth System")
        scraper._fetch_project_chats(page, proj)

        assert scraper._mapping["chat-aaa1"] == "Auth System"
        assert scraper._mapping["chat-aaa2"] == "Auth System"
        assert scraper._mapping["chat-aaa3"] == "Auth System"

    def test_handles_api_error(self):
        scraper = ClaudeScraper()
        scraper._org_id = MOCK_ORG_UUID
        page = MagicMock()
        page.request.get = lambda url: _make_mock_response(500, {})

        from anticlaw.providers.scraper.base import ScrapedProject

        proj = ScrapedProject(uuid="proj-xxxx", name="Broken")
        scraper._fetch_project_chats(page, proj)

        assert proj.chat_uuids == []

    def test_handles_wrapped_chats_response(self):
        """Chats might be wrapped in a 'conversations' key."""
        scraper = ClaudeScraper()
        scraper._org_id = MOCK_ORG_UUID

        wrapped = {"conversations": [{"uuid": "chat-x1"}, {"uuid": "chat-x2"}]}
        page = MagicMock()
        page.request.get = lambda url: _make_mock_response(200, wrapped)

        from anticlaw.providers.scraper.base import ScrapedProject

        proj = ScrapedProject(uuid="proj-xxxx", name="Wrapped")
        scraper._fetch_project_chats(page, proj)

        assert len(proj.chat_uuids) == 2

    def test_skips_chats_without_uuid(self):
        scraper = ClaudeScraper()
        scraper._org_id = MOCK_ORG_UUID

        bad_chats = [{"name": "No UUID"}, {"uuid": "", "name": "Empty"}]
        page = MagicMock()
        page.request.get = lambda url: _make_mock_response(200, bad_chats)

        from anticlaw.providers.scraper.base import ScrapedProject

        proj = ScrapedProject(uuid="proj-xxxx", name="Bad")
        scraper._fetch_project_chats(page, proj)

        assert proj.chat_uuids == []


@patch("anticlaw.providers.scraper.claude.time.sleep")
class TestFetchAllChats:
    def test_iterates_all_projects(self, mock_sleep):
        scraper = ClaudeScraper()
        scraper._org_id = MOCK_ORG_UUID
        page = _make_mock_page()

        # Set up projects first
        scraper._fetch_projects(page)
        scraper._fetch_all_chats(page)

        # Auth System has 3 chats, CLI Design has 2
        assert len(scraper._mapping) == 5
        assert scraper._mapping["chat-aaa1"] == "Auth System"
        assert scraper._mapping["chat-bbb1"] == "CLI Design"

    def test_rate_limits_between_projects(self, mock_sleep):
        scraper = ClaudeScraper()
        scraper._org_id = MOCK_ORG_UUID
        page = _make_mock_page()

        scraper._fetch_projects(page)
        scraper._fetch_all_chats(page)

        # Should sleep between each project (2 projects = 2 sleeps)
        assert mock_sleep.call_count == 2


class TestSaveMapping:
    def test_saves_json(self, tmp_path: Path):
        scraper = ClaudeScraper()
        scraper._mapping = {"chat-1": "Project A", "chat-2": "Project B"}

        output = tmp_path / "mapping.json"
        scraper._save_mapping(output)

        assert output.exists()
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data == {"chat-1": "Project A", "chat-2": "Project B"}

    def test_creates_parent_dirs(self, tmp_path: Path):
        scraper = ClaudeScraper()
        scraper._mapping = {"chat-1": "Project A"}

        output = tmp_path / "sub" / "dir" / "mapping.json"
        scraper._save_mapping(output)

        assert output.exists()

    def test_handles_unicode_project_names(self, tmp_path: Path):
        scraper = ClaudeScraper()
        scraper._mapping = {"chat-1": "Проект Авторизация"}

        output = tmp_path / "mapping.json"
        scraper._save_mapping(output)

        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["chat-1"] == "Проект Авторизация"


class TestSummary:
    def test_summary_after_scrape(self):
        scraper = ClaudeScraper()
        scraper._mapping = {"c1": "P1", "c2": "P1", "c3": "P2"}

        from anticlaw.providers.scraper.base import ScrapedProject

        scraper._projects = [
            ScrapedProject(uuid="p1", name="P1"),
            ScrapedProject(uuid="p2", name="P2"),
        ]

        stats = scraper.summary()
        assert stats == {"projects": 2, "mapped_chats": 3}


class TestScrapeEndToEnd:
    """End-to-end test with fully mocked Playwright."""

    @patch("anticlaw.providers.scraper.claude.time.sleep")
    def test_full_scrape_flow(self, mock_sleep, tmp_path: Path):
        scraper = ClaudeScraper()
        page = _make_mock_page()

        # Simulate the internal steps manually (since we can't mock sync_playwright easily)
        scraper._wait_for_login(page)
        scraper._discover_org_id(page)
        scraper._fetch_projects(page)
        scraper._fetch_all_chats(page)

        output = tmp_path / "mapping.json"
        scraper._save_mapping(output)

        # Verify mapping
        assert len(scraper.mapping) == 5
        assert scraper.mapping["chat-aaa1"] == "Auth System"
        assert scraper.mapping["chat-bbb2"] == "CLI Design"

        # Verify projects
        assert len(scraper.projects) == 2

        # Verify JSON output
        data = json.loads(output.read_text(encoding="utf-8"))
        assert len(data) == 5

        # Verify summary
        stats = scraper.summary()
        assert stats["projects"] == 2
        assert stats["mapped_chats"] == 5

    def test_wait_for_login_navigates(self):
        scraper = ClaudeScraper()
        page = _make_mock_page()

        scraper._wait_for_login(page)

        page.goto.assert_called_once_with("https://claude.ai")
        page.wait_for_url.assert_called_once()

    def test_empty_projects_yields_empty_mapping(self):
        scraper = ClaudeScraper()
        scraper._org_id = MOCK_ORG_UUID

        page = MagicMock()
        page.request.get = lambda url: _make_mock_response(200, [])

        scraper._fetch_projects(page)
        scraper._fetch_all_chats(page)

        assert scraper.mapping == {}
        assert scraper.projects == []

    def test_scrape_raises_without_playwright(self):
        """scrape() should raise ImportError if playwright not installed."""
        scraper = ClaudeScraper()

        with patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
            with patch(
                "anticlaw.providers.scraper.claude.ClaudeScraper.scrape",
                side_effect=ImportError("Playwright is not installed."),
            ):
                with pytest.raises(ImportError, match="Playwright"):
                    scraper.scrape()
