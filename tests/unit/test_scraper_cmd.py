"""Tests for anticlaw.cli.scraper_cmd (aw scrape — Playwright CDP)."""

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
    def test_help_shows_cdp_instructions(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["scrape", "claude", "--help"])

        assert result.exit_code == 0
        assert "cdp-url" in result.output
        assert "remote-debugging-port" in result.output
        assert "chrome" in result.output.lower() or "Chrome" in result.output

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
        ) as mock_scraper_cls:
            instance = MagicMock()
            instance.scrape.return_value = mapping
            mock_scraper_cls.return_value = instance

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["scrape", "claude", "-o", str(output)],
            )

        assert result.exit_code == 0
        assert "2 projects" in result.output
        assert "3 chats" in result.output
        assert "My Project" in result.output
        assert "Other Project" in result.output
        assert "(has instructions)" in result.output
        assert str(output) in result.output
        mock_scraper_cls.assert_called_once_with(cdp_url="http://localhost:9222")

    def test_custom_cdp_url(self, tmp_path: Path):
        output = tmp_path / "mapping.json"
        mapping = ScrapedMapping(chats={}, projects={}, scraped_at="2026-01-01T00:00:00Z")

        with patch(
            "anticlaw.providers.scraper.claude.ClaudeScraper"
        ) as mock_scraper_cls:
            instance = MagicMock()
            instance.scrape.return_value = mapping
            mock_scraper_cls.return_value = instance

            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "scrape", "claude",
                    "--cdp-url", "http://localhost:9333",
                    "-o", str(output),
                ],
            )

        assert result.exit_code == 0
        mock_scraper_cls.assert_called_once_with(cdp_url="http://localhost:9333")

    def test_import_error_shows_install_hint(self, tmp_path: Path):
        output = tmp_path / "mapping.json"

        with patch(
            "anticlaw.providers.scraper.claude.ClaudeScraper"
        ) as mock_scraper_cls:
            instance = MagicMock()
            instance.scrape.side_effect = ImportError("playwright is required")
            mock_scraper_cls.return_value = instance

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["scrape", "claude", "-o", str(output)],
            )

        assert result.exit_code != 0
        assert "playwright is required" in result.output

    def test_scrape_error_shows_message(self, tmp_path: Path):
        output = tmp_path / "mapping.json"

        with patch(
            "anticlaw.providers.scraper.claude.ClaudeScraper"
        ) as mock_scraper_cls:
            instance = MagicMock()
            instance.scrape.side_effect = RuntimeError("No browser contexts found")
            mock_scraper_cls.return_value = instance

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["scrape", "claude", "-o", str(output)],
            )

        assert result.exit_code != 0
        assert "No browser contexts found" in result.output

    def test_default_output_is_mapping_json(self):
        mapping = ScrapedMapping(chats={}, projects={}, scraped_at="2026-01-01T00:00:00Z")

        with patch(
            "anticlaw.providers.scraper.claude.ClaudeScraper"
        ) as mock_scraper_cls:
            instance = MagicMock()
            instance.scrape.return_value = mapping
            mock_scraper_cls.return_value = instance

            runner = CliRunner()
            runner.invoke(
                cli,
                ["scrape", "claude"],
            )

        # The scrape() call should use mapping.json as default
        call_args = instance.scrape.call_args[0]
        assert call_args[0] == Path("mapping.json")

    def test_shows_use_with_import_hint(self, tmp_path: Path):
        output = tmp_path / "mapping.json"
        mapping = ScrapedMapping(chats={}, projects={}, scraped_at="2026-01-01T00:00:00Z")

        with patch(
            "anticlaw.providers.scraper.claude.ClaudeScraper"
        ) as mock_scraper_cls:
            instance = MagicMock()
            instance.scrape.return_value = mapping
            mock_scraper_cls.return_value = instance

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["scrape", "claude", "-o", str(output)],
            )

        assert result.exit_code == 0
        assert "aw import claude" in result.output
        assert "--mapping" in result.output

    def test_shows_connecting_message(self, tmp_path: Path):
        output = tmp_path / "mapping.json"
        mapping = ScrapedMapping(chats={}, projects={}, scraped_at="2026-01-01T00:00:00Z")

        with patch(
            "anticlaw.providers.scraper.claude.ClaudeScraper"
        ) as mock_scraper_cls:
            instance = MagicMock()
            instance.scrape.return_value = mapping
            mock_scraper_cls.return_value = instance

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["scrape", "claude", "-o", str(output)],
            )

        assert result.exit_code == 0
        assert "Connecting to Chrome" in result.output
