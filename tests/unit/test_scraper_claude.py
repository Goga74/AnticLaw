"""Tests for anticlaw.providers.scraper.claude (Playwright CDP scraper)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anticlaw.providers.scraper.claude import ClaudeScraper

# --- Fixtures: mock API response data ---

CURRENT_USER_DATA = {
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


def _mock_response(url: str, data: object) -> MagicMock:
    """Create a mock Playwright response object."""
    resp = MagicMock()
    resp.url = url
    resp.json.return_value = data
    return resp


def _make_pw_mock(
    page_url: str = "https://claude.ai",
) -> tuple[MagicMock, MagicMock]:
    """Create a mock Playwright instance with browser context and page.

    Sets up page.evaluate to return CURRENT_USER_DATA then PROJECTS_RESPONSE.
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

    # Default evaluate responses for automated flow
    mock_page.evaluate.side_effect = [CURRENT_USER_DATA, PROJECTS_RESPONSE]

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

        assert (
            scraper._projects["proj-uuid-aaa"]["instructions"]
            == "You are a Python expert."
        )
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
            [
                {"uuid": "", "name": "No UUID"},
                {"uuid": "valid", "name": "Valid"},
            ],
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
        resp.url = (
            "https://claude.ai/projects/proj-uuid-aaa/conversations_v2"
        )
        resp.json.side_effect = Exception("invalid JSON")

        scraper._handle_response(resp)

        assert len(scraper._chat_to_project) == 0

    def test_extracts_project_uuid_from_url(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            "https://claude.ai/projects/my-proj-id-xyz/"
            "conversations_v2?cursor=abc",
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
            "https://claude.ai/api/organizations/org-1/"
            "projects?is_archived=false",
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
            "proj-aaa": {
                "name": "My Project",
                "instructions": "Be helpful",
                "is_starter": False,
            },
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
            "proj-aaa": {
                "name": "Project A",
                "instructions": "",
                "is_starter": False,
            },
            "proj-bbb": {
                "name": "Project B",
                "instructions": "X",
                "is_starter": False,
            },
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


class TestExtractOrgId:
    def test_extracts_org_uuid(self):
        scraper = ClaudeScraper()
        org_id = scraper._extract_org_id(CURRENT_USER_DATA)
        assert org_id == "org-uuid-123"

    def test_no_memberships_raises(self):
        scraper = ClaudeScraper()
        with pytest.raises(ValueError, match="No organizations found"):
            scraper._extract_org_id({"account": {"memberships": []}})

    def test_empty_uuid_raises(self):
        scraper = ClaudeScraper()
        data = {
            "account": {
                "memberships": [{"organization": {"uuid": ""}}]
            }
        }
        with pytest.raises(
            ValueError, match="Could not extract organization UUID"
        ):
            scraper._extract_org_id(data)

    def test_missing_account_key_raises(self):
        scraper = ClaudeScraper()
        with pytest.raises(ValueError, match="No organizations found"):
            scraper._extract_org_id({})


class TestScrape:
    @patch("builtins.print")
    def test_full_scrape_flow(self, mock_print, tmp_path: Path):
        scraper = ClaudeScraper()
        output = tmp_path / "mapping.json"

        mock_pw, mock_page = _make_pw_mock()

        # Pre-populate chat mapping (simulating intercepted conversations_v2)
        scraper._chat_to_project = {
            "chat-uuid-001": "proj-uuid-aaa",
            "chat-uuid-002": "proj-uuid-aaa",
            "chat-uuid-003": "proj-uuid-bbb",
        }

        with patch.object(
            scraper, "_start_playwright", return_value=mock_pw
        ):
            mapping = scraper.scrape(output)

        # Verify mapping (starter excluded)
        assert len(mapping.chats) == 3
        assert mapping.chats["chat-uuid-001"] == "my-project"
        assert mapping.chats["chat-uuid-002"] == "my-project"
        assert mapping.chats["chat-uuid-003"] == "another-project"

        assert len(mapping.projects) == 2
        assert mapping.projects["proj-uuid-aaa"]["name"] == "My Project"

        # Verify file saved
        assert output.exists()
        saved = json.loads(output.read_text())
        assert saved["chats"]["chat-uuid-001"] == "my-project"
        assert "scraped_at" in saved

        # Verify CDP connection
        mock_pw.chromium.connect_over_cdp.assert_called_once_with(
            "http://localhost:9222"
        )

        # Verify response interceptor registered
        mock_page.on.assert_called_once_with(
            "response", scraper._handle_response
        )

        # Verify org_id and projects fetched via evaluate
        assert mock_page.evaluate.call_count == 2
        first_call = mock_page.evaluate.call_args_list[0]
        assert "current_user" in first_call.args[0]
        second_call = mock_page.evaluate.call_args_list[1]
        assert "organizations" in second_call.args[0]
        assert second_call.args[1] == "org-uuid-123"

        # Verify navigation to non-starter projects only
        goto_urls = [c.args[0] for c in mock_page.goto.call_args_list]
        assert "https://claude.ai/project/proj-uuid-aaa" in goto_urls
        assert "https://claude.ai/project/proj-uuid-bbb" in goto_urls
        assert not any("proj-uuid-starter" in u for u in goto_urls)

        # Verify wait after each navigation
        assert mock_page.wait_for_timeout.call_count == 2
        mock_page.wait_for_timeout.assert_called_with(2000)

        # Verify progress printed
        print_args = [str(c) for c in mock_print.call_args_list]
        assert any("1/2" in s for s in print_args)
        assert any("2/2" in s for s in print_args)

        # Verify cleanup
        mock_pw.stop.assert_called_once()

    @patch("builtins.print")
    def test_finds_claude_tab(self, mock_print, tmp_path: Path):
        scraper = ClaudeScraper()
        output = tmp_path / "mapping.json"

        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()

        page_other = MagicMock()
        page_other.url = "https://google.com"
        page_claude = MagicMock()
        page_claude.url = "https://claude.ai/chat/123"
        page_claude.evaluate.side_effect = [
            CURRENT_USER_DATA,
            PROJECTS_RESPONSE,
        ]

        mock_context.pages = [page_other, page_claude]
        mock_browser.contexts = [mock_context]
        mock_pw.chromium.connect_over_cdp.return_value = mock_browser

        with patch.object(
            scraper, "_start_playwright", return_value=mock_pw
        ):
            scraper.scrape(output)

        # Should register on the claude.ai tab, not google.com
        page_claude.on.assert_called_once_with(
            "response", scraper._handle_response
        )
        page_other.on.assert_not_called()

    @patch("builtins.print")
    def test_opens_claude_if_no_tab(self, mock_print, tmp_path: Path):
        scraper = ClaudeScraper()
        output = tmp_path / "mapping.json"

        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()

        page_other = MagicMock()
        page_other.url = "https://google.com"
        page_other.evaluate.side_effect = [
            CURRENT_USER_DATA,
            PROJECTS_RESPONSE,
        ]
        mock_context.pages = [page_other]
        mock_browser.contexts = [mock_context]
        mock_pw.chromium.connect_over_cdp.return_value = mock_browser

        with patch.object(
            scraper, "_start_playwright", return_value=mock_pw
        ):
            scraper.scrape(output)

        # Should use first page and navigate to claude.ai first
        first_goto = page_other.goto.call_args_list[0]
        assert first_goto.args[0] == "https://claude.ai"

    def test_no_contexts_raises(self):
        scraper = ClaudeScraper()

        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_browser.contexts = []
        mock_pw.chromium.connect_over_cdp.return_value = mock_browser

        with (
            patch.object(
                scraper, "_start_playwright", return_value=mock_pw
            ),
            pytest.raises(RuntimeError, match="No browser contexts found"),
        ):
            scraper.scrape(Path("out.json"))

        mock_pw.stop.assert_called_once()

    @patch("builtins.print")
    def test_creates_parent_directories(
        self, mock_print, tmp_path: Path
    ):
        scraper = ClaudeScraper()
        output = tmp_path / "sub" / "dir" / "mapping.json"

        mock_pw, _ = _make_pw_mock()

        with patch.object(
            scraper, "_start_playwright", return_value=mock_pw
        ):
            scraper.scrape(output)

        assert output.exists()

    @patch("builtins.print")
    def test_stops_playwright_on_success(
        self, mock_print, tmp_path: Path
    ):
        scraper = ClaudeScraper()
        output = tmp_path / "mapping.json"

        mock_pw, _ = _make_pw_mock()

        with patch.object(
            scraper, "_start_playwright", return_value=mock_pw
        ):
            scraper.scrape(output)

        mock_pw.stop.assert_called_once()

    def test_stops_playwright_on_error(self):
        scraper = ClaudeScraper()

        mock_pw = MagicMock()
        mock_pw.chromium.connect_over_cdp.side_effect = Exception(
            "Connection refused"
        )

        with (
            patch.object(
                scraper, "_start_playwright", return_value=mock_pw
            ),
            pytest.raises(Exception, match="Connection refused"),
        ):
            scraper.scrape(Path("out.json"))

        mock_pw.stop.assert_called_once()

    @patch("builtins.print")
    def test_custom_cdp_url(self, mock_print, tmp_path: Path):
        scraper = ClaudeScraper(cdp_url="http://localhost:9333")
        output = tmp_path / "mapping.json"

        mock_pw, _ = _make_pw_mock()

        with patch.object(
            scraper, "_start_playwright", return_value=mock_pw
        ):
            scraper.scrape(output)

        mock_pw.chromium.connect_over_cdp.assert_called_once_with(
            "http://localhost:9333"
        )

    @patch("builtins.print")
    def test_new_page_when_no_pages(self, mock_print, tmp_path: Path):
        scraper = ClaudeScraper()
        output = tmp_path / "mapping.json"

        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_new_page = MagicMock()
        mock_new_page.evaluate.side_effect = [
            CURRENT_USER_DATA,
            PROJECTS_RESPONSE,
        ]

        mock_context.pages = []
        mock_context.new_page.return_value = mock_new_page
        mock_browser.contexts = [mock_context]
        mock_pw.chromium.connect_over_cdp.return_value = mock_browser

        with patch.object(
            scraper, "_start_playwright", return_value=mock_pw
        ):
            scraper.scrape(output)

        mock_context.new_page.assert_called_once()
        first_goto = mock_new_page.goto.call_args_list[0]
        assert first_goto.args[0] == "https://claude.ai"

    @patch("builtins.print")
    def test_skips_starter_in_navigation(
        self, mock_print, tmp_path: Path
    ):
        scraper = ClaudeScraper()
        output = tmp_path / "mapping.json"

        mock_pw, mock_page = _make_pw_mock()

        with patch.object(
            scraper, "_start_playwright", return_value=mock_pw
        ):
            scraper.scrape(output)

        # Only 2 non-starter projects navigated
        goto_urls = [c.args[0] for c in mock_page.goto.call_args_list]
        assert len(goto_urls) == 2
        assert not any("proj-uuid-starter" in u for u in goto_urls)

    @patch("builtins.print")
    def test_prints_progress(self, mock_print, tmp_path: Path):
        scraper = ClaudeScraper()
        output = tmp_path / "mapping.json"

        mock_pw, _ = _make_pw_mock()

        with patch.object(
            scraper, "_start_playwright", return_value=mock_pw
        ):
            scraper.scrape(output)

        print_args = [str(c) for c in mock_print.call_args_list]
        assert any("Loading project 1/2" in s for s in print_args)
        assert any("Loading project 2/2" in s for s in print_args)
        assert any("My Project" in s for s in print_args)
        assert any("Another Project" in s for s in print_args)

    @patch("builtins.print")
    def test_waits_after_each_navigation(
        self, mock_print, tmp_path: Path
    ):
        scraper = ClaudeScraper()
        output = tmp_path / "mapping.json"

        mock_pw, mock_page = _make_pw_mock()

        with patch.object(
            scraper, "_start_playwright", return_value=mock_pw
        ):
            scraper.scrape(output)

        assert mock_page.wait_for_timeout.call_count == 2
        for call in mock_page.wait_for_timeout.call_args_list:
            assert call.args[0] == 2000

    @patch("builtins.print")
    def test_processes_evaluate_projects_data(
        self, mock_print, tmp_path: Path
    ):
        """Projects data from evaluate populates self._projects."""
        scraper = ClaudeScraper()
        output = tmp_path / "mapping.json"

        mock_pw, _ = _make_pw_mock()

        with patch.object(
            scraper, "_start_playwright", return_value=mock_pw
        ):
            scraper.scrape(output)

        # All 3 projects (including starter) should be in _projects
        assert len(scraper._projects) == 3
        assert scraper._projects["proj-uuid-aaa"]["name"] == "My Project"
        assert scraper._projects["proj-uuid-starter"]["is_starter"] is True


class TestStartPlaywright:
    def test_import_error_when_playwright_missing(self):
        scraper = ClaudeScraper()

        with (
            patch.dict(
                "sys.modules",
                {"playwright": None, "playwright.sync_api": None},
            ),
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
        assert (
            mapping.projects["proj-uuid-aaa"]["name"] == "My Project"
        )
        assert (
            mapping.projects["proj-uuid-aaa"]["instructions"]
            == "You are a Python expert."
        )
        assert mapping.projects["proj-uuid-bbb"]["instructions"] == ""

    def test_multiple_project_responses_merge(self):
        scraper = ClaudeScraper()

        resp1 = _mock_response(
            "https://claude.ai/api/organizations/org-1/projects",
            [{"uuid": "p1", "name": "First"}],
        )
        resp2 = _mock_response(
            "https://claude.ai/api/organizations/org-1/"
            "projects?cursor=next",
            [{"uuid": "p2", "name": "Second"}],
        )

        scraper._handle_response(resp1)
        scraper._handle_response(resp2)

        assert len(scraper._projects) == 2
        assert "p1" in scraper._projects
        assert "p2" in scraper._projects
