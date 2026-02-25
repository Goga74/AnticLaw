"""Tests for anticlaw.cli.scraper_cmd (aw scrape)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from anticlaw.cli.main import cli
from anticlaw.providers.scraper.base import ScrapedMapping


class TestScrapeGroup:
    def test_scrape_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["scrape", "--help"])

        assert result.exit_code == 0
        assert "Scrape chat" in result.output
        assert "claude" in result.output


class TestScrapeClaudeCmd:
    def test_help_shows_instructions(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["scrape", "claude", "--help"])

        assert result.exit_code == 0
        assert "session-key" in result.output
        assert "DevTools" in result.output
        assert "sessionKey" in result.output

    def test_requires_session_key(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["scrape", "claude"])

        assert result.exit_code != 0
        assert "session-key" in result.output

    def test_successful_scrape(self, tmp_path: Path):
        output = tmp_path / "mapping.json"
        mapping = ScrapedMapping(
            chats={
                "chat-1": "my-project",
                "chat-2": "my-project",
                "chat-3": "other-project",
            },
            projects={
                "proj-1": {"name": "My Project", "instructions": "Be helpful"},
                "proj-2": {"name": "Other Project", "instructions": ""},
            },
            scraped_at="2026-02-26T12:00:00Z",
        )

        with patch(
            "anticlaw.providers.scraper.claude.ClaudeScraper"
        ) as MockScraper:
            instance = MagicMock()
            instance.scrape.return_value = mapping
            MockScraper.return_value = instance

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["scrape", "claude", "--session-key", "test-key", "-o", str(output)],
            )

        assert result.exit_code == 0
        assert "2 projects" in result.output
        assert "3 chats" in result.output
        assert "My Project" in result.output
        assert "Other Project" in result.output
        assert "(has instructions)" in result.output
        assert str(output) in result.output
        MockScraper.assert_called_once_with(session_key="test-key")

    def test_import_error_shows_install_hint(self, tmp_path: Path):
        output = tmp_path / "mapping.json"

        with patch(
            "anticlaw.providers.scraper.claude.ClaudeScraper"
        ) as MockScraper:
            instance = MagicMock()
            instance.scrape.side_effect = ImportError("httpx is required")
            MockScraper.return_value = instance

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["scrape", "claude", "--session-key", "test-key", "-o", str(output)],
            )

        assert result.exit_code != 0
        assert "httpx is required" in result.output

    def test_scrape_error_shows_message(self, tmp_path: Path):
        output = tmp_path / "mapping.json"

        with patch(
            "anticlaw.providers.scraper.claude.ClaudeScraper"
        ) as MockScraper:
            instance = MagicMock()
            instance.scrape.side_effect = ValueError("No organizations found")
            MockScraper.return_value = instance

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["scrape", "claude", "--session-key", "test-key", "-o", str(output)],
            )

        assert result.exit_code != 0
        assert "No organizations found" in result.output

    def test_default_output_is_mapping_json(self):
        mapping = ScrapedMapping(chats={}, projects={}, scraped_at="2026-01-01T00:00:00Z")

        with patch(
            "anticlaw.providers.scraper.claude.ClaudeScraper"
        ) as MockScraper:
            instance = MagicMock()
            instance.scrape.return_value = mapping
            MockScraper.return_value = instance

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["scrape", "claude", "--session-key", "test-key"],
            )

        # The scrape() call should use mapping.json as default
        call_args = instance.scrape.call_args[0]
        assert call_args[0] == Path("mapping.json")

    def test_shows_use_with_import_hint(self, tmp_path: Path):
        output = tmp_path / "mapping.json"
        mapping = ScrapedMapping(chats={}, projects={}, scraped_at="2026-01-01T00:00:00Z")

        with patch(
            "anticlaw.providers.scraper.claude.ClaudeScraper"
        ) as MockScraper:
            instance = MagicMock()
            instance.scrape.return_value = mapping
            MockScraper.return_value = instance

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["scrape", "claude", "--session-key", "test-key", "-o", str(output)],
            )

        assert result.exit_code == 0
        assert "aw import claude" in result.output
        assert "--mapping" in result.output
