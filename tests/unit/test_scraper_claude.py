"""Tests for anticlaw.providers.scraper.claude (Playwright CDP scraper)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anticlaw.providers.scraper.claude import ClaudeScraper

# --- Fixtures: mock API response data ---

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


def _mock_response(url: str, data: object) -> MagicMock:
    """Create a mock Playwright response object."""
    resp = MagicMock()
    resp.url = url
    resp.json.return_value = data
    return resp


def _make_pw_mock(page_url: str = "https://claude.ai") -> tuple[MagicMock, MagicMock]:
    """Create a mock Playwright instance with a browser context and page.

    Returns (pw_mock, page_mock).
    """
    mock_pw = MagicMock()
    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()

    mock_page.url = page_url
    mock_context.pages = [mock_page]
    mock_browser.contexts = [mock_context]
    mock_pw.chromium.connect_over_cdp.return_value = mock_browser

    return mock_pw, mock_page


class TestClaudeScraperProperties:
    def test_name(self):
        scraper = ClaudeScraper()
        assert scraper.name == "claude-scraper"

    def test_info(self):
        scraper = ClaudeScraper()
        info = scraper.info
        assert info.display_name == "Claude.ai Playwright Scraper"
        assert info.base_url == "https://claude.ai"
        assert "projects" in info.capabilities
        assert "chat_mapping" in info.capabilities

    def test_custom_cdp_url(self):
        scraper = ClaudeScraper(cdp_url="http://localhost:9333")
        assert scraper._cdp_url == "http://localhost:9333"

    def test_default_cdp_url(self):
        scraper = ClaudeScraper()
        assert scraper._cdp_url == "http://localhost:9222"


class TestHandleProjectsResponse:
    def test_captures_projects(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            "https://claude.ai/api/organizations/org-123/projects",
            PROJECTS_RESPONSE,
        )

        scraper._handle_response(resp)

        assert len(scraper._projects) == 3
        assert scraper._projects["proj-uuid-aaa"]["name"] == "My Project"
        assert scraper._projects["proj-uuid-bbb"]["name"] == "Another Project"
        assert scraper._projects["proj-uuid-starter"]["is_starter"] is True

    def test_captures_instructions(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            "https://claude.ai/api/organizations/org-123/projects",
            PROJECTS_RESPONSE,
        )

        scraper._handle_response(resp)

        assert scraper._projects["proj-uuid-aaa"]["instructions"] == "You are a Python expert."
        assert scraper._projects["proj-uuid-bbb"]["instructions"] == ""

    def test_skips_non_list_response(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            "https://claude.ai/api/organizations/org-123/projects",
            {"error": "not a list"},
        )

        scraper._handle_response(resp)

        assert len(scraper._projects) == 0

    def test_skips_projects_without_uuid(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            "https://claude.ai/api/organizations/org-123/projects",
            [{"uuid": "", "name": "No UUID"}, {"uuid": "valid", "name": "Valid"}],
        )

        scraper._handle_response(resp)

        assert len(scraper._projects) == 1
        assert "valid" in scraper._projects

    def test_handles_json_parse_error(self):
        scraper = ClaudeScraper()
        resp = MagicMock()
        resp.url = "https://claude.ai/api/organizations/org-123/projects"
        resp.json.side_effect = Exception("invalid JSON")

        scraper._handle_response(resp)

        assert len(scraper._projects) == 0


class TestHandleConversationsResponse:
    def test_captures_chats_from_list(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            "https://claude.ai/projects/proj-uuid-aaa/conversations_v2?limit=50",
            CHATS_PROJECT_A,
        )

        scraper._handle_response(resp)

        assert len(scraper._chat_to_project) == 2
        assert scraper._chat_to_project["chat-uuid-001"] == "proj-uuid-aaa"
        assert scraper._chat_to_project["chat-uuid-002"] == "proj-uuid-aaa"

    def test_captures_chats_from_dict_with_data_key(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            "https://claude.ai/projects/proj-uuid-bbb/conversations_v2",
            {"data": CHATS_PROJECT_B},
        )

        scraper._handle_response(resp)

        assert len(scraper._chat_to_project) == 1
        assert scraper._chat_to_project["chat-uuid-003"] == "proj-uuid-bbb"

    def test_captures_chats_from_dict_with_chats_key(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            "https://claude.ai/projects/proj-uuid-aaa/conversations_v2",
            {"chats": [{"uuid": "chat-x"}]},
        )

        scraper._handle_response(resp)

        assert scraper._chat_to_project["chat-x"] == "proj-uuid-aaa"

    def test_skips_chats_without_uuid(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            "https://claude.ai/projects/proj-uuid-aaa/conversations_v2",
            [{"uuid": ""}, {"uuid": "valid-chat"}],
        )

        scraper._handle_response(resp)

        assert len(scraper._chat_to_project) == 1
        assert "valid-chat" in scraper._chat_to_project

    def test_handles_json_parse_error(self):
        scraper = ClaudeScraper()
        resp = MagicMock()
        resp.url = "https://claude.ai/projects/proj-uuid-aaa/conversations_v2"
        resp.json.side_effect = Exception("invalid JSON")

        scraper._handle_response(resp)

        assert len(scraper._chat_to_project) == 0

    def test_extracts_project_uuid_from_url(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            "https://claude.ai/projects/my-proj-id-xyz/conversations_v2?cursor=abc",
            [{"uuid": "chat-1"}],
        )

        scraper._handle_response(resp)

        assert scraper._chat_to_project["chat-1"] == "my-proj-id-xyz"


class TestHandleResponseRouting:
    def test_ignores_unrelated_urls(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            "https://claude.ai/api/auth/current_user",
            {"account": {}},
        )

        scraper._handle_response(resp)

        assert len(scraper._projects) == 0
        assert len(scraper._chat_to_project) == 0

    def test_routes_project_url(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            "https://claude.ai/api/organizations/org-1/projects?is_archived=false",
            [{"uuid": "p1", "name": "Test"}],
        )

        scraper._handle_response(resp)

        assert "p1" in scraper._projects

    def test_routes_conversation_url(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            "https://claude.ai/projects/p1/conversations_v2",
            [{"uuid": "c1"}],
        )

        scraper._handle_response(resp)

        assert "c1" in scraper._chat_to_project


class TestBuildMapping:
    def test_builds_mapping_skipping_starter_projects(self):
        scraper = ClaudeScraper()
        scraper._projects = {
            "proj-aaa": {"name": "My Project", "instructions": "Be helpful", "is_starter": False},
            "proj-starter": {
                "name": "Getting Started",
                "instructions": "",
                "is_starter": True,
            },
        }
        scraper._chat_to_project = {
            "chat-1": "proj-aaa",
            "chat-2": "proj-aaa",
            "chat-3": "proj-starter",
        }

        mapping = scraper._build_mapping()

        assert len(mapping.chats) == 2
        assert mapping.chats["chat-1"] == "my-project"
        assert mapping.chats["chat-2"] == "my-project"
        assert "chat-3" not in mapping.chats

        assert len(mapping.projects) == 1
        assert "proj-aaa" in mapping.projects
        assert "proj-starter" not in mapping.projects

    def test_builds_mapping_with_multiple_projects(self):
        scraper = ClaudeScraper()
        scraper._projects = {
            "proj-aaa": {"name": "Project A", "instructions": "", "is_starter": False},
            "proj-bbb": {"name": "Project B", "instructions": "X", "is_starter": False},
        }
        scraper._chat_to_project = {
            "chat-1": "proj-aaa",
            "chat-2": "proj-bbb",
        }

        mapping = scraper._build_mapping()

        assert len(mapping.chats) == 2
        assert mapping.chats["chat-1"] == "project-a"
        assert mapping.chats["chat-2"] == "project-b"
        assert len(mapping.projects) == 2

    def test_empty_data(self):
        scraper = ClaudeScraper()
        mapping = scraper._build_mapping()

        assert mapping.chats == {}
        assert mapping.projects == {}
        assert mapping.scraped_at != ""

    def test_includes_scraped_at_timestamp(self):
        scraper = ClaudeScraper()
        mapping = scraper._build_mapping()

        assert mapping.scraped_at != ""
        assert "T" in mapping.scraped_at  # ISO format


class TestScrape:
    @patch("builtins.input", return_value="")
    @patch("builtins.print")
    def test_full_scrape_flow(self, mock_print, mock_input, tmp_path: Path):
        scraper = ClaudeScraper()
        output = tmp_path / "mapping.json"

        mock_pw, mock_page = _make_pw_mock()

        # Pre-populate captured data (simulating intercepted responses)
        scraper._projects = {
            "proj-aaa": {"name": "My Project", "instructions": "Expert", "is_starter": False},
            "proj-bbb": {"name": "Other", "instructions": "", "is_starter": False},
        }
        scraper._chat_to_project = {
            "chat-1": "proj-aaa",
            "chat-2": "proj-aaa",
            "chat-3": "proj-bbb",
        }

        with patch.object(scraper, "_start_playwright", return_value=mock_pw):
            mapping = scraper.scrape(output)

        # Verify mapping
        assert len(mapping.chats) == 3
        assert mapping.chats["chat-1"] == "my-project"
        assert mapping.chats["chat-2"] == "my-project"
        assert mapping.chats["chat-3"] == "other"

        assert len(mapping.projects) == 2
        assert mapping.projects["proj-aaa"]["name"] == "My Project"

        # Verify file saved
        assert output.exists()
        saved = json.loads(output.read_text())
        assert saved["chats"]["chat-1"] == "my-project"
        assert "scraped_at" in saved

        # Verify CDP connection
        mock_pw.chromium.connect_over_cdp.assert_called_once_with("http://localhost:9222")

        # Verify response interceptor was registered
        mock_page.on.assert_called_once_with("response", scraper._handle_response)

        # Verify user was prompted
        mock_input.assert_called_once()

        # Verify cleanup
        mock_pw.stop.assert_called_once()

    @patch("builtins.input", return_value="")
    @patch("builtins.print")
    def test_finds_claude_tab(self, mock_print, mock_input, tmp_path: Path):
        scraper = ClaudeScraper()
        output = tmp_path / "mapping.json"

        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()

        page_other = MagicMock()
        page_other.url = "https://google.com"
        page_claude = MagicMock()
        page_claude.url = "https://claude.ai/chat/123"

        mock_context.pages = [page_other, page_claude]
        mock_browser.contexts = [mock_context]
        mock_pw.chromium.connect_over_cdp.return_value = mock_browser

        with patch.object(scraper, "_start_playwright", return_value=mock_pw):
            scraper.scrape(output)

        # Should register on the claude.ai tab, not google.com
        page_claude.on.assert_called_once_with("response", scraper._handle_response)
        page_other.on.assert_not_called()

    @patch("builtins.input", return_value="")
    @patch("builtins.print")
    def test_opens_claude_if_no_tab(self, mock_print, mock_input, tmp_path: Path):
        scraper = ClaudeScraper()
        output = tmp_path / "mapping.json"

        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()

        page_other = MagicMock()
        page_other.url = "https://google.com"
        mock_context.pages = [page_other]
        mock_browser.contexts = [mock_context]
        mock_pw.chromium.connect_over_cdp.return_value = mock_browser

        with patch.object(scraper, "_start_playwright", return_value=mock_pw):
            scraper.scrape(output)

        # Should use first page and navigate to claude.ai
        page_other.goto.assert_called_once_with("https://claude.ai")

    def test_no_contexts_raises(self):
        scraper = ClaudeScraper()

        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_browser.contexts = []
        mock_pw.chromium.connect_over_cdp.return_value = mock_browser

        with (
            patch.object(scraper, "_start_playwright", return_value=mock_pw),
            pytest.raises(RuntimeError, match="No browser contexts found"),
        ):
            scraper.scrape(Path("out.json"))

        mock_pw.stop.assert_called_once()

    @patch("builtins.input", return_value="")
    @patch("builtins.print")
    def test_creates_parent_directories(self, mock_print, mock_input, tmp_path: Path):
        scraper = ClaudeScraper()
        output = tmp_path / "sub" / "dir" / "mapping.json"

        mock_pw, _ = _make_pw_mock()

        with patch.object(scraper, "_start_playwright", return_value=mock_pw):
            scraper.scrape(output)

        assert output.exists()

    @patch("builtins.input", return_value="")
    @patch("builtins.print")
    def test_stops_playwright_on_success(self, mock_print, mock_input, tmp_path: Path):
        scraper = ClaudeScraper()
        output = tmp_path / "mapping.json"

        mock_pw, _ = _make_pw_mock()

        with patch.object(scraper, "_start_playwright", return_value=mock_pw):
            scraper.scrape(output)

        mock_pw.stop.assert_called_once()

    def test_stops_playwright_on_error(self):
        scraper = ClaudeScraper()

        mock_pw = MagicMock()
        mock_pw.chromium.connect_over_cdp.side_effect = Exception("Connection refused")

        with (
            patch.object(scraper, "_start_playwright", return_value=mock_pw),
            pytest.raises(Exception, match="Connection refused"),
        ):
            scraper.scrape(Path("out.json"))

        mock_pw.stop.assert_called_once()

    @patch("builtins.input", return_value="")
    @patch("builtins.print")
    def test_custom_cdp_url(self, mock_print, mock_input, tmp_path: Path):
        scraper = ClaudeScraper(cdp_url="http://localhost:9333")
        output = tmp_path / "mapping.json"

        mock_pw, _ = _make_pw_mock()

        with patch.object(scraper, "_start_playwright", return_value=mock_pw):
            scraper.scrape(output)

        mock_pw.chromium.connect_over_cdp.assert_called_once_with("http://localhost:9333")

    @patch("builtins.input", return_value="")
    @patch("builtins.print")
    def test_new_page_when_no_pages(self, mock_print, mock_input, tmp_path: Path):
        scraper = ClaudeScraper()
        output = tmp_path / "mapping.json"

        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_new_page = MagicMock()

        mock_context.pages = []
        mock_context.new_page.return_value = mock_new_page
        mock_browser.contexts = [mock_context]
        mock_pw.chromium.connect_over_cdp.return_value = mock_browser

        with patch.object(scraper, "_start_playwright", return_value=mock_pw):
            scraper.scrape(output)

        mock_context.new_page.assert_called_once()
        mock_new_page.goto.assert_called_once_with("https://claude.ai")


class TestStartPlaywright:
    def test_import_error_when_playwright_missing(self):
        scraper = ClaudeScraper()

        with (
            patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}),
            pytest.raises(ImportError, match="playwright is required"),
        ):
            scraper._start_playwright()


class TestIntegrationFlow:
    """Test the full interception→mapping flow without Playwright."""

    def test_intercept_projects_then_chats(self):
        scraper = ClaudeScraper()

        # Simulate intercepted project list
        proj_resp = _mock_response(
            "https://claude.ai/api/organizations/org-1/projects",
            PROJECTS_RESPONSE,
        )
        scraper._handle_response(proj_resp)

        # Simulate intercepted chats for project A
        chats_a_resp = _mock_response(
            "https://claude.ai/projects/proj-uuid-aaa/conversations_v2",
            CHATS_PROJECT_A,
        )
        scraper._handle_response(chats_a_resp)

        # Simulate intercepted chats for project B
        chats_b_resp = _mock_response(
            "https://claude.ai/projects/proj-uuid-bbb/conversations_v2",
            CHATS_PROJECT_B,
        )
        scraper._handle_response(chats_b_resp)

        # Build mapping
        mapping = scraper._build_mapping()

        # Starter project should be excluded
        assert "proj-uuid-starter" not in mapping.projects
        assert len(mapping.projects) == 2

        # All non-starter chats mapped
        assert len(mapping.chats) == 3
        assert mapping.chats["chat-uuid-001"] == "my-project"
        assert mapping.chats["chat-uuid-002"] == "my-project"
        assert mapping.chats["chat-uuid-003"] == "another-project"

        # Project metadata
        assert mapping.projects["proj-uuid-aaa"]["name"] == "My Project"
        assert mapping.projects["proj-uuid-aaa"]["instructions"] == "You are a Python expert."
        assert mapping.projects["proj-uuid-bbb"]["instructions"] == ""

    def test_multiple_project_responses_merge(self):
        scraper = ClaudeScraper()

        resp1 = _mock_response(
            "https://claude.ai/api/organizations/org-1/projects",
            [{"uuid": "p1", "name": "First"}],
        )
        resp2 = _mock_response(
            "https://claude.ai/api/organizations/org-1/projects?cursor=next",
            [{"uuid": "p2", "name": "Second"}],
        )

        scraper._handle_response(resp1)
        scraper._handle_response(resp2)

        assert len(scraper._projects) == 2
        assert "p1" in scraper._projects
        assert "p2" in scraper._projects
