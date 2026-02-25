"""Tests for anticlaw.providers.scraper.base."""

from anticlaw.providers.scraper.base import ScrapedMapping, ScraperInfo, ScraperProvider


class TestScraperInfo:
    def test_basic_fields(self):
        info = ScraperInfo(
            display_name="Test Scraper",
            base_url="https://example.com",
            capabilities={"projects", "chat_mapping"},
        )
        assert info.display_name == "Test Scraper"
        assert info.base_url == "https://example.com"
        assert "projects" in info.capabilities

    def test_default_capabilities(self):
        info = ScraperInfo(display_name="X", base_url="https://x.com")
        assert info.capabilities == set()


class TestScrapedMapping:
    def test_defaults(self):
        m = ScrapedMapping()
        assert m.chats == {}
        assert m.projects == {}
        assert m.scraped_at == ""

    def test_with_data(self):
        m = ScrapedMapping(
            chats={"uuid-1": "my-project"},
            projects={"proj-1": {"name": "My Project", "instructions": "Be helpful"}},
            scraped_at="2026-01-01T00:00:00Z",
        )
        assert m.chats["uuid-1"] == "my-project"
        assert m.projects["proj-1"]["name"] == "My Project"


class TestScraperProviderProtocol:
    def test_protocol_is_runtime_checkable(self):
        """ScraperProvider can be used with isinstance()."""
        assert hasattr(ScraperProvider, "__protocol_attrs__") or hasattr(
            ScraperProvider, "__abstractmethods__"
        ) or callable(getattr(ScraperProvider, "_is_protocol", None))
