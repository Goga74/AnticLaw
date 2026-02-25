"""Tests for anticlaw.providers.scraper.base — ScraperProvider Protocol and ScraperInfo."""

from pathlib import Path

from anticlaw.providers.scraper.base import ScrapedProject, ScraperInfo, ScraperProvider


class _MockScraper:
    """Minimal implementation satisfying the ScraperProvider Protocol."""

    @property
    def name(self) -> str:
        return "mock-scraper"

    @property
    def info(self) -> ScraperInfo:
        return ScraperInfo(
            display_name="Mock Scraper",
            version="0.1.0",
            requires_auth=True,
            requires_browser=True,
        )

    def scrape(self, output: Path | None = None) -> dict[str, str]:
        return {"chat-1": "Project A", "chat-2": "Project B"}


class TestScraperInfo:
    def test_defaults(self):
        info = ScraperInfo(display_name="Test", version="1.0")
        assert info.display_name == "Test"
        assert info.version == "1.0"
        assert info.requires_auth is True
        assert info.requires_browser is True

    def test_custom_fields(self):
        info = ScraperInfo(
            display_name="Custom",
            version="2.0",
            requires_auth=False,
            requires_browser=False,
        )
        assert info.requires_auth is False
        assert info.requires_browser is False


class TestScrapedProject:
    def test_defaults(self):
        proj = ScrapedProject(uuid="abc-123", name="My Project")
        assert proj.uuid == "abc-123"
        assert proj.name == "My Project"
        assert proj.description == ""
        assert proj.prompt_template == ""
        assert proj.chat_uuids == []

    def test_all_fields(self):
        proj = ScrapedProject(
            uuid="abc-123",
            name="My Project",
            description="A test project",
            prompt_template="You are a helpful assistant.",
            chat_uuids=["chat-1", "chat-2"],
        )
        assert proj.description == "A test project"
        assert proj.prompt_template == "You are a helpful assistant."
        assert len(proj.chat_uuids) == 2


class TestScraperProviderProtocol:
    def test_mock_implements_protocol(self):
        mock = _MockScraper()
        assert isinstance(mock, ScraperProvider)

    def test_name_property(self):
        mock = _MockScraper()
        assert mock.name == "mock-scraper"

    def test_info_property(self):
        mock = _MockScraper()
        info = mock.info
        assert info.display_name == "Mock Scraper"
        assert info.version == "0.1.0"

    def test_scrape_returns_dict(self):
        mock = _MockScraper()
        result = mock.scrape()
        assert isinstance(result, dict)
        assert result == {"chat-1": "Project A", "chat-2": "Project B"}

    def test_scrape_with_output(self, tmp_path: Path):
        mock = _MockScraper()
        result = mock.scrape(output=tmp_path / "out.json")
        assert isinstance(result, dict)

    def test_non_implementing_class_fails_protocol(self):
        class _BadScraper:
            pass

        assert not isinstance(_BadScraper(), ScraperProvider)
