"""Tests for anticlaw.providers.scraper.claude (Playwright CDP scraper)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anticlaw.providers.scraper.claude import ClaudeScraper

# --- Fixtures ---

ORG_UUID = "12345678-1234-1234-1234-123456789abc"

ALL_CHATS = [
    {
        "uuid": "chat-001",
        "name": "Auth discussion",
        "project_uuid": "proj-aaa",
        "project": {
            "uuid": "proj-aaa",
            "name": "My Project",
        },
    },
    {
        "uuid": "chat-002",
        "name": "DB design",
        "project_uuid": "proj-aaa",
        "project": {
            "uuid": "proj-aaa",
            "name": "My Project",
        },
    },
    {
        "uuid": "chat-003",
        "name": "UI wireframes",
        "project_uuid": "proj-bbb",
        "project": {
            "uuid": "proj-bbb",
            "name": "Another Project",
        },
    },
    {
        "uuid": "chat-004",
        "name": "General chat",
        "project_uuid": None,
        "project": None,
    },
]

# Simulates pagination: starred first, then unstarred
CHATS_STARRED = ALL_CHATS[:1]
CHATS_UNSTARRED = ALL_CHATS[1:]


def _mock_response(url: str, data: object) -> MagicMock:
    """Create a mock Playwright response."""
    resp = MagicMock()
    resp.url = url
    resp.json.return_value = data
    return resp


def _make_pw_mock(
    page_url: str = "https://claude.ai",
) -> tuple[MagicMock, MagicMock]:
    """Create mock Playwright. Returns (pw, page)."""
    mock_pw = MagicMock()
    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()

    mock_page.url = page_url
    mock_context.pages = [mock_page]
    mock_browser.contexts = [mock_context]
    mock_pw.chromium.connect_over_cdp.return_value = (
        mock_browser
    )

    return mock_pw, mock_page


def _prepopulate(scraper: ClaudeScraper) -> None:
    """Simulate state after page load intercepted responses."""
    scraper._org_id = ORG_UUID
    for chat in ALL_CHATS:
        if chat.get("uuid"):
            scraper._chats[chat["uuid"]] = chat
    scraper._projects = {
        "proj-aaa": {"name": "My Project"},
        "proj-bbb": {"name": "Another Project"},
    }


class TestClaudeScraperProperties:
    def test_name(self):
        scraper = ClaudeScraper()
        assert scraper.name == "claude-scraper"

    def test_info(self):
        scraper = ClaudeScraper()
        info = scraper.info
        assert "Claude.ai" in info.display_name
        assert info.base_url == "https://claude.ai"
        assert "projects" in info.capabilities
        assert "chat_mapping" in info.capabilities

    def test_custom_cdp_url(self):
        s = ClaudeScraper(cdp_url="http://localhost:9333")
        assert s._cdp_url == "http://localhost:9333"

    def test_default_cdp_url(self):
        s = ClaudeScraper()
        assert s._cdp_url == "http://localhost:9222"


class TestHandleChatConversations:
    def _url(self, qs: str = "") -> str:
        return (
            "https://claude.ai/api/organizations/"
            f"{ORG_UUID}/chat_conversations{qs}"
        )

    def test_captures_chats_from_list(self):
        scraper = ClaudeScraper()
        resp = _mock_response(self._url(), ALL_CHATS)

        scraper._handle_chat_conversations(resp)

        assert len(scraper._chats) == 4
        assert "chat-001" in scraper._chats
        assert "chat-004" in scraper._chats

    def test_extracts_project_info(self):
        scraper = ClaudeScraper()
        resp = _mock_response(self._url(), ALL_CHATS)

        scraper._handle_chat_conversations(resp)

        assert len(scraper._projects) == 2
        assert (
            scraper._projects["proj-aaa"]["name"]
            == "My Project"
        )
        assert (
            scraper._projects["proj-bbb"]["name"]
            == "Another Project"
        )

    def test_skips_chats_without_uuid(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            self._url(),
            [{"uuid": ""}, {"uuid": "valid"}],
        )

        scraper._handle_chat_conversations(resp)

        assert len(scraper._chats) == 1
        assert "valid" in scraper._chats

    def test_deduplicates_by_uuid(self):
        scraper = ClaudeScraper()
        resp1 = _mock_response(
            self._url("?starred=true"),
            [ALL_CHATS[0]],
        )
        resp2 = _mock_response(
            self._url("?starred=false"),
            [ALL_CHATS[0], ALL_CHATS[1]],
        )

        scraper._handle_chat_conversations(resp1)
        scraper._handle_chat_conversations(resp2)

        assert len(scraper._chats) == 2

    def test_handles_json_error(self):
        scraper = ClaudeScraper()
        resp = MagicMock()
        resp.url = self._url()
        resp.json.side_effect = Exception("bad json")

        scraper._handle_chat_conversations(resp)

        assert len(scraper._chats) == 0

    def test_handles_chats_without_project(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            self._url(),
            [
                {
                    "uuid": "c1",
                    "project": None,
                },
                {
                    "uuid": "c2",
                    "project": {"uuid": "p1", "name": "P"},
                },
            ],
        )

        scraper._handle_chat_conversations(resp)

        assert len(scraper._chats) == 2
        assert len(scraper._projects) == 1

    def test_captures_pagination(self):
        """Starred and unstarred responses merge."""
        scraper = ClaudeScraper()
        r1 = _mock_response(
            self._url("?starred=true"),
            CHATS_STARRED,
        )
        r2 = _mock_response(
            self._url("?starred=false"),
            CHATS_UNSTARRED,
        )

        scraper._handle_chat_conversations(r1)
        scraper._handle_chat_conversations(r2)

        assert len(scraper._chats) == 4
        assert len(scraper._projects) == 2

    def test_handles_dict_with_data_key(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            self._url(),
            {"data": ALL_CHATS[:2]},
        )

        scraper._handle_chat_conversations(resp)

        assert len(scraper._chats) == 2


class TestHandleResponseRouting:
    def test_ignores_unrelated_urls(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            "https://claude.ai/api/auth/current_user",
            {},
        )

        scraper._handle_response(resp)

        assert len(scraper._chats) == 0

    def test_routes_chat_conversations(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            "https://claude.ai/api/organizations/"
            f"{ORG_UUID}/chat_conversations?limit=30",
            [ALL_CHATS[0]],
        )

        scraper._handle_response(resp)

        assert "chat-001" in scraper._chats

    def test_discovers_org_id(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            "https://claude.ai/api/organizations/"
            f"{ORG_UUID}/chat_conversations",
            [],
        )

        scraper._handle_response(resp)

        assert scraper._org_id == ORG_UUID

    def test_org_id_discovered_once(self):
        scraper = ClaudeScraper()
        u1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        u2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

        scraper._handle_response(
            _mock_response(
                f"https://claude.ai/api/organizations/"
                f"{u1}/chat_conversations",
                [],
            )
        )
        scraper._handle_response(
            _mock_response(
                f"https://claude.ai/api/organizations/"
                f"{u2}/chat_conversations",
                [],
            )
        )

        assert scraper._org_id == u1

    def test_org_id_needs_valid_uuid(self):
        scraper = ClaudeScraper()
        resp = _mock_response(
            "https://claude.ai/api/organizations/"
            "short/chat_conversations",
            [],
        )

        scraper._handle_response(resp)

        assert scraper._org_id is None


class TestBuildMapping:
    def test_maps_chats_to_project_folders(self):
        scraper = ClaudeScraper()
        scraper._chats = {
            "c1": {
                "uuid": "c1",
                "project": {
                    "uuid": "p1",
                    "name": "My Project",
                },
            },
        }
        scraper._projects = {"p1": {"name": "My Project"}}

        mapping = scraper._build_mapping()

        assert mapping.chats["c1"] == "my-project"

    def test_skips_chats_without_project(self):
        scraper = ClaudeScraper()
        scraper._chats = {
            "c1": {"uuid": "c1", "project": None},
            "c2": {
                "uuid": "c2",
                "project": {
                    "uuid": "p1",
                    "name": "Proj",
                },
            },
        }
        scraper._projects = {"p1": {"name": "Proj"}}

        mapping = scraper._build_mapping()

        assert len(mapping.chats) == 1
        assert "c1" not in mapping.chats
        assert "c2" in mapping.chats

    def test_multiple_projects(self):
        scraper = ClaudeScraper()
        scraper._chats = {
            "c1": {
                "uuid": "c1",
                "project": {
                    "uuid": "pa",
                    "name": "Project A",
                },
            },
            "c2": {
                "uuid": "c2",
                "project": {
                    "uuid": "pb",
                    "name": "Project B",
                },
            },
        }
        scraper._projects = {
            "pa": {"name": "Project A"},
            "pb": {"name": "Project B"},
        }

        mapping = scraper._build_mapping()

        assert mapping.chats["c1"] == "project-a"
        assert mapping.chats["c2"] == "project-b"
        assert len(mapping.projects) == 2

    def test_empty_data(self):
        scraper = ClaudeScraper()
        mapping = scraper._build_mapping()

        assert mapping.chats == {}
        assert mapping.projects == {}
        assert mapping.scraped_at != ""

    def test_projects_have_instructions_key(self):
        scraper = ClaudeScraper()
        scraper._chats = {
            "c1": {
                "uuid": "c1",
                "project": {
                    "uuid": "p1",
                    "name": "Proj",
                },
            },
        }
        scraper._projects = {"p1": {"name": "Proj"}}

        mapping = scraper._build_mapping()

        assert "instructions" in mapping.projects["p1"]
        assert mapping.projects["p1"]["instructions"] == ""


class TestScrape:
    @patch("builtins.print")
    def test_full_scrape_flow(
        self, mock_print, tmp_path: Path
    ):
        scraper = ClaudeScraper()
        output = tmp_path / "mapping.json"
        mock_pw, mock_page = _make_pw_mock()
        _prepopulate(scraper)

        with patch.object(
            scraper,
            "_start_playwright",
            return_value=mock_pw,
        ):
            mapping = scraper.scrape(output)

        # 3 chats mapped (chat-004 has no project)
        assert len(mapping.chats) == 3
        assert mapping.chats["chat-001"] == "my-project"
        assert mapping.chats["chat-002"] == "my-project"
        assert (
            mapping.chats["chat-003"] == "another-project"
        )
        assert "chat-004" not in mapping.chats

        assert len(mapping.projects) == 2

        # File saved
        assert output.exists()
        saved = json.loads(output.read_text())
        assert saved["chats"]["chat-001"] == "my-project"
        assert "scraped_at" in saved

        # CDP connection
        mock_pw.chromium.connect_over_cdp.assert_called_once_with(
            "http://localhost:9222"
        )

        # Interceptor registered
        mock_page.on.assert_called_once_with(
            "response", scraper._handle_response
        )

        # Navigated to claude.ai
        mock_page.goto.assert_called_once_with(
            "https://claude.ai"
        )

        # Waited for networkidle
        mock_page.wait_for_load_state.assert_called_once_with(
            "networkidle"
        )

        # No per-project navigation
        assert mock_page.goto.call_count == 1

        # Summary printed
        args = [str(c) for c in mock_print.call_args_list]
        assert any("4 chats" in s for s in args)
        assert any("2 projects" in s for s in args)

        # Cleanup
        mock_pw.stop.assert_called_once()

    @patch("builtins.print")
    def test_finds_claude_tab(
        self, mock_print, tmp_path: Path
    ):
        scraper = ClaudeScraper()
        output = tmp_path / "mapping.json"
        _prepopulate(scraper)

        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()

        page_other = MagicMock()
        page_other.url = "https://google.com"
        page_claude = MagicMock()
        page_claude.url = "https://claude.ai/chat/123"

        mock_context.pages = [page_other, page_claude]
        mock_browser.contexts = [mock_context]
        mock_pw.chromium.connect_over_cdp.return_value = (
            mock_browser
        )

        with patch.object(
            scraper,
            "_start_playwright",
            return_value=mock_pw,
        ):
            scraper.scrape(output)

        page_claude.on.assert_called_once_with(
            "response", scraper._handle_response
        )
        page_other.on.assert_not_called()

    @patch("builtins.print")
    def test_uses_first_page_if_no_claude_tab(
        self, mock_print, tmp_path: Path
    ):
        scraper = ClaudeScraper()
        output = tmp_path / "mapping.json"
        _prepopulate(scraper)

        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        page_other = MagicMock()
        page_other.url = "https://google.com"
        mock_context.pages = [page_other]
        mock_browser.contexts = [mock_context]
        mock_pw.chromium.connect_over_cdp.return_value = (
            mock_browser
        )

        with patch.object(
            scraper,
            "_start_playwright",
            return_value=mock_pw,
        ):
            scraper.scrape(output)

        page_other.on.assert_called_once()
        page_other.goto.assert_called_once_with(
            "https://claude.ai"
        )

    def test_no_contexts_raises(self):
        scraper = ClaudeScraper()
        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_browser.contexts = []
        mock_pw.chromium.connect_over_cdp.return_value = (
            mock_browser
        )

        with (
            patch.object(
                scraper,
                "_start_playwright",
                return_value=mock_pw,
            ),
            pytest.raises(
                RuntimeError,
                match="No browser contexts found",
            ),
        ):
            scraper.scrape(Path("out.json"))

        mock_pw.stop.assert_called_once()

    def test_raises_if_org_id_not_discovered(self):
        scraper = ClaudeScraper()
        mock_pw, _ = _make_pw_mock()

        with (
            patch.object(
                scraper,
                "_start_playwright",
                return_value=mock_pw,
            ),
            pytest.raises(
                RuntimeError,
                match="Could not discover org ID",
            ),
        ):
            scraper.scrape(Path("out.json"))

        mock_pw.stop.assert_called_once()

    def test_raises_if_no_chats_captured(self):
        scraper = ClaudeScraper()
        scraper._org_id = ORG_UUID
        mock_pw, _ = _make_pw_mock()

        with (
            patch.object(
                scraper,
                "_start_playwright",
                return_value=mock_pw,
            ),
            pytest.raises(
                RuntimeError,
                match="No chats captured",
            ),
        ):
            scraper.scrape(Path("out.json"))

        mock_pw.stop.assert_called_once()

    @patch("builtins.print")
    def test_creates_parent_directories(
        self, mock_print, tmp_path: Path
    ):
        scraper = ClaudeScraper()
        output = tmp_path / "sub" / "dir" / "mapping.json"
        _prepopulate(scraper)
        mock_pw, _ = _make_pw_mock()

        with patch.object(
            scraper,
            "_start_playwright",
            return_value=mock_pw,
        ):
            scraper.scrape(output)

        assert output.exists()

    @patch("builtins.print")
    def test_stops_playwright_on_success(
        self, mock_print, tmp_path: Path
    ):
        scraper = ClaudeScraper()
        _prepopulate(scraper)
        mock_pw, _ = _make_pw_mock()

        with patch.object(
            scraper,
            "_start_playwright",
            return_value=mock_pw,
        ):
            scraper.scrape(tmp_path / "m.json")

        mock_pw.stop.assert_called_once()

    def test_stops_playwright_on_error(self):
        scraper = ClaudeScraper()
        mock_pw = MagicMock()
        mock_pw.chromium.connect_over_cdp.side_effect = (
            Exception("Connection refused")
        )

        with (
            patch.object(
                scraper,
                "_start_playwright",
                return_value=mock_pw,
            ),
            pytest.raises(
                Exception, match="Connection refused"
            ),
        ):
            scraper.scrape(Path("out.json"))

        mock_pw.stop.assert_called_once()

    @patch("builtins.print")
    def test_custom_cdp_url(
        self, mock_print, tmp_path: Path
    ):
        scraper = ClaudeScraper(
            cdp_url="http://localhost:9333"
        )
        _prepopulate(scraper)
        mock_pw, _ = _make_pw_mock()

        with patch.object(
            scraper,
            "_start_playwright",
            return_value=mock_pw,
        ):
            scraper.scrape(tmp_path / "m.json")

        mock_pw.chromium.connect_over_cdp.assert_called_once_with(
            "http://localhost:9333"
        )

    @patch("builtins.print")
    def test_new_page_when_no_pages(
        self, mock_print, tmp_path: Path
    ):
        scraper = ClaudeScraper()
        _prepopulate(scraper)

        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_new_page = MagicMock()
        mock_context.pages = []
        mock_context.new_page.return_value = mock_new_page
        mock_browser.contexts = [mock_context]
        mock_pw.chromium.connect_over_cdp.return_value = (
            mock_browser
        )

        with patch.object(
            scraper,
            "_start_playwright",
            return_value=mock_pw,
        ):
            scraper.scrape(tmp_path / "m.json")

        mock_context.new_page.assert_called_once()
        mock_new_page.goto.assert_called_once_with(
            "https://claude.ai"
        )

    @patch("builtins.print")
    def test_waits_for_networkidle(
        self, mock_print, tmp_path: Path
    ):
        scraper = ClaudeScraper()
        _prepopulate(scraper)
        mock_pw, mock_page = _make_pw_mock()

        with patch.object(
            scraper,
            "_start_playwright",
            return_value=mock_pw,
        ):
            scraper.scrape(tmp_path / "m.json")

        mock_page.wait_for_load_state.assert_called_once_with(
            "networkidle"
        )


class TestStartPlaywright:
    def test_import_error_when_playwright_missing(self):
        scraper = ClaudeScraper()

        with (
            patch.dict(
                "sys.modules",
                {
                    "playwright": None,
                    "playwright.sync_api": None,
                },
            ),
            pytest.raises(
                ImportError, match="playwright is required"
            ),
        ):
            scraper._start_playwright()


class TestIntegrationFlow:
    """Full interception→mapping flow without Playwright."""

    def test_capture_then_build(self):
        scraper = ClaudeScraper()

        resp = _mock_response(
            "https://claude.ai/api/organizations/"
            f"{ORG_UUID}/chat_conversations",
            ALL_CHATS,
        )
        scraper._handle_response(resp)

        assert scraper._org_id == ORG_UUID
        assert len(scraper._chats) == 4
        assert len(scraper._projects) == 2

        mapping = scraper._build_mapping()

        assert len(mapping.chats) == 3
        assert mapping.chats["chat-001"] == "my-project"
        assert mapping.chats["chat-002"] == "my-project"
        assert (
            mapping.chats["chat-003"] == "another-project"
        )
        assert "chat-004" not in mapping.chats
        assert len(mapping.projects) == 2

    def test_pagination_merges(self):
        scraper = ClaudeScraper()

        r1 = _mock_response(
            "https://claude.ai/api/organizations/"
            f"{ORG_UUID}/chat_conversations?starred=true",
            CHATS_STARRED,
        )
        r2 = _mock_response(
            "https://claude.ai/api/organizations/"
            f"{ORG_UUID}/chat_conversations?starred=false",
            CHATS_UNSTARRED,
        )

        scraper._handle_response(r1)
        scraper._handle_response(r2)

        assert len(scraper._chats) == 4
        mapping = scraper._build_mapping()
        assert len(mapping.chats) == 3
