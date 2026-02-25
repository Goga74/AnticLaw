"""Tests for anticlaw.cli.scraper_cmd (aw scrape) and import --scrape flag."""

from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

from click.testing import CliRunner

from anticlaw.cli.main import cli


class TestScrapeHelp:
    def test_scrape_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["scrape", "--help"])
        assert result.exit_code == 0
        assert "scrape" in result.output.lower()

    def test_scrape_claude_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["scrape", "claude", "--help"])
        assert result.exit_code == 0
        assert "--output" in result.output
        assert "mapping" in result.output.lower()


class TestScrapeClaudeCmd:
    @patch("anticlaw.providers.scraper.claude.ClaudeScraper")
    def test_successful_scrape_no_session(self, MockScraper, tmp_path: Path):
        """First run (no session) — shows login prompt."""
        mock_instance = MagicMock()
        mock_instance.scrape.return_value = {
            "chat-1": "Auth System",
            "chat-2": "Auth System",
            "chat-3": "CLI Design",
        }
        mock_instance.summary.return_value = {"projects": 2, "mapped_chats": 3}

        # session_path does not exist
        fake_session = tmp_path / ".acl" / "claude_session.json"
        type(mock_instance).session_path = PropertyMock(return_value=fake_session)

        from anticlaw.providers.scraper.base import ScrapedProject

        mock_instance.projects = [
            ScrapedProject(uuid="p1", name="Auth System", chat_uuids=["chat-1", "chat-2"]),
            ScrapedProject(uuid="p2", name="CLI Design", chat_uuids=["chat-3"]),
        ]
        MockScraper.return_value = mock_instance

        output = tmp_path / "mapping.json"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["scrape", "claude", "--output", str(output), "--home", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert "Launching browser" in result.output
        assert "10 minutes" in result.output
        assert "Found 2 projects" in result.output
        assert "Auth System: 2 chats" in result.output
        assert "CLI Design: 1 chats" in result.output
        assert "3 chats" in result.output
        mock_instance.scrape.assert_called_once_with(output=output)

    @patch("anticlaw.providers.scraper.claude.ClaudeScraper")
    def test_successful_scrape_with_session(self, MockScraper, tmp_path: Path):
        """Subsequent run (session exists) — shows 'Using saved session'."""
        mock_instance = MagicMock()
        mock_instance.scrape.return_value = {"chat-1": "Auth System"}
        mock_instance.summary.return_value = {"projects": 1, "mapped_chats": 1}

        # Create session file so it "exists"
        acl_dir = tmp_path / ".acl"
        acl_dir.mkdir(parents=True)
        session_file = acl_dir / "claude_session.json"
        session_file.write_text("{}", encoding="utf-8")
        type(mock_instance).session_path = PropertyMock(return_value=session_file)

        from anticlaw.providers.scraper.base import ScrapedProject

        mock_instance.projects = [
            ScrapedProject(uuid="p1", name="Auth System", chat_uuids=["chat-1"]),
        ]
        MockScraper.return_value = mock_instance

        output = tmp_path / "mapping.json"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["scrape", "claude", "--output", str(output), "--home", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert "Using saved session" in result.output
        assert "Launching browser" not in result.output

    @patch("anticlaw.providers.scraper.claude.ClaudeScraper")
    def test_runtime_error(self, MockScraper, tmp_path: Path):
        mock_instance = MagicMock()
        mock_instance.scrape.side_effect = RuntimeError("Could not discover organization ID")
        fake_session = tmp_path / ".acl" / "claude_session.json"
        type(mock_instance).session_path = PropertyMock(return_value=fake_session)
        MockScraper.return_value = mock_instance

        runner = CliRunner()
        result = runner.invoke(cli, ["scrape", "claude", "--home", str(tmp_path)])

        assert result.exit_code == 1
        assert "Could not discover organization ID" in result.output

    @patch("anticlaw.providers.scraper.claude.ClaudeScraper")
    def test_default_output_path(self, MockScraper, tmp_path: Path):
        mock_instance = MagicMock()
        mock_instance.scrape.return_value = {}
        mock_instance.summary.return_value = {"projects": 0, "mapped_chats": 0}
        mock_instance.projects = []
        fake_session = tmp_path / ".acl" / "claude_session.json"
        type(mock_instance).session_path = PropertyMock(return_value=fake_session)
        MockScraper.return_value = mock_instance

        runner = CliRunner()
        result = runner.invoke(cli, ["scrape", "claude", "--home", str(tmp_path)])

        assert result.exit_code == 0
        mock_instance.scrape.assert_called_once()
        call_kwargs = mock_instance.scrape.call_args
        assert call_kwargs[1]["output"] == Path("mapping.json")

    @patch("anticlaw.providers.scraper.claude.ClaudeScraper")
    def test_session_saved_message(self, MockScraper, tmp_path: Path):
        """After scrape, if session file exists, print path."""
        mock_instance = MagicMock()
        mock_instance.scrape.return_value = {}
        mock_instance.summary.return_value = {"projects": 0, "mapped_chats": 0}
        mock_instance.projects = []

        # Session file created during scrape
        acl_dir = tmp_path / ".acl"
        acl_dir.mkdir(parents=True)
        session_file = acl_dir / "claude_session.json"
        session_file.write_text("{}", encoding="utf-8")
        type(mock_instance).session_path = PropertyMock(return_value=session_file)
        MockScraper.return_value = mock_instance

        runner = CliRunner()
        result = runner.invoke(cli, ["scrape", "claude", "--home", str(tmp_path)])

        assert result.exit_code == 0
        assert "Session saved to" in result.output


class TestImportScrapeFlag:
    def test_import_claude_has_scrape_flag(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["import", "claude", "--help"])
        assert result.exit_code == 0
        assert "--scrape" in result.output

    @patch("anticlaw.providers.scraper.claude.ClaudeScraper")
    def test_scrape_flag_runs_scraper(self, MockScraper, tmp_path: Path):
        """--scrape flag should invoke the scraper before import."""
        mock_instance = MagicMock()
        mock_instance.scrape.return_value = {"chat-uuid-1": "Auth System"}
        mock_instance.summary.return_value = {"projects": 1, "mapped_chats": 1}
        MockScraper.return_value = mock_instance

        export_dir = tmp_path / "export"
        export_dir.mkdir()
        (export_dir / "conversations.json").write_text("[]", encoding="utf-8")

        home = tmp_path / "home"

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "import", "claude", str(export_dir),
                "--scrape", "--home", str(home),
            ],
        )

        assert result.exit_code == 0
        assert "Launching browser" in result.output
        mock_instance.scrape.assert_called_once()

    @patch("anticlaw.providers.scraper.claude.ClaudeScraper")
    def test_scrape_flag_passes_home(self, MockScraper, tmp_path: Path):
        """--scrape flag passes home to ClaudeScraper."""
        mock_instance = MagicMock()
        mock_instance.scrape.return_value = {}
        mock_instance.summary.return_value = {"projects": 0, "mapped_chats": 0}
        MockScraper.return_value = mock_instance

        export_dir = tmp_path / "export"
        export_dir.mkdir()
        (export_dir / "conversations.json").write_text("[]", encoding="utf-8")

        home = tmp_path / "home"

        runner = CliRunner()
        runner.invoke(
            cli,
            [
                "import", "claude", str(export_dir),
                "--scrape", "--home", str(home),
            ],
        )

        MockScraper.assert_called_once_with(home=home)

    @patch("anticlaw.providers.scraper.claude.ClaudeScraper")
    def test_scrape_flag_ignored_if_mapping_provided(self, MockScraper, tmp_path: Path):
        """--mapping takes precedence over --scrape."""
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        (export_dir / "conversations.json").write_text("[]", encoding="utf-8")

        mapping_file = tmp_path / "mapping.json"
        mapping_file.write_text('{"chat-1": "Project A"}', encoding="utf-8")

        home = tmp_path / "home"

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "import", "claude", str(export_dir),
                "--mapping", str(mapping_file),
                "--scrape",
                "--home", str(home),
            ],
        )

        assert result.exit_code == 0
        # Scraper should not be instantiated because --mapping takes priority
        MockScraper.assert_not_called()

    def test_scrape_flag_import_error(self, tmp_path: Path):
        """--scrape with missing playwright should exit with error."""
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        (export_dir / "conversations.json").write_text("[]", encoding="utf-8")

        runner = CliRunner()
        # Patch the import to fail
        with patch.dict(
            "sys.modules",
            {"anticlaw.providers.scraper.claude": None},
        ):
            result = runner.invoke(
                cli,
                [
                    "import", "claude", str(export_dir),
                    "--scrape", "--home", str(tmp_path / "home"),
                ],
            )

        assert result.exit_code == 1
        assert "scraper dependencies not installed" in result.output

    @patch("anticlaw.providers.scraper.claude.ClaudeScraper")
    def test_scrape_runtime_error_continues_without_mapping(
        self, MockScraper, tmp_path: Path,
    ):
        """If scraper fails at runtime, import continues without mapping."""
        mock_instance = MagicMock()
        mock_instance.scrape.side_effect = RuntimeError("Network error")
        MockScraper.return_value = mock_instance

        export_dir = tmp_path / "export"
        export_dir.mkdir()
        (export_dir / "conversations.json").write_text("[]", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "import", "claude", str(export_dir),
                "--scrape", "--home", str(tmp_path / "home"),
            ],
        )

        assert result.exit_code == 0
        assert "Scraper error" in result.output
        assert "Continuing import" in result.output
