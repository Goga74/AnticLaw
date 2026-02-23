"""Tests for anticlaw.cli.scan_cmd (aw scan)."""

from pathlib import Path

from click.testing import CliRunner

from anticlaw.cli.main import cli
from anticlaw.core.config import load_config
from anticlaw.core.meta_db import MetaDB


def _setup_home(tmp_path: Path) -> Path:
    """Create a home dir with basic structure."""
    home = tmp_path / "home"
    acl = home / ".acl"
    acl.mkdir(parents=True)
    (home / "_inbox").mkdir(parents=True)
    return home


class TestScanCmd:
    def test_scan_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["scan", "--help"])
        assert result.exit_code == 0
        assert "Index local files" in result.output

    def test_scan_path(self, tmp_path: Path):
        home = _setup_home(tmp_path)

        # Create some files to scan
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        (code_dir / "main.py").write_text("def main(): pass", encoding="utf-8")
        (code_dir / "utils.py").write_text("def util(): pass", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "scan", str(code_dir), "--home", str(home),
        ])
        assert result.exit_code == 0, result.output
        assert "Scanning" in result.output
        assert "Indexed:" in result.output

    def test_scan_indexes_files(self, tmp_path: Path):
        home = _setup_home(tmp_path)

        code_dir = tmp_path / "code"
        code_dir.mkdir()
        (code_dir / "hello.py").write_text("print('hi')", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "scan", str(code_dir), "--home", str(home),
        ])
        assert result.exit_code == 0

        # Verify files indexed in DB
        db = MetaDB(home / ".acl" / "meta.db")
        assert db.count_source_files() >= 1
        db.close()

    def test_scan_no_paths_no_config(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["scan", "--home", str(home)])
        assert result.exit_code == 0
        assert "No paths configured" in result.output

    def test_scan_incremental(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        (code_dir / "app.py").write_text("x = 1", encoding="utf-8")

        runner = CliRunner()

        # First scan
        result1 = runner.invoke(cli, ["scan", str(code_dir), "--home", str(home)])
        assert result1.exit_code == 0
        assert "Indexed: 1" in result1.output

        # Second scan (same files, no changes)
        result2 = runner.invoke(cli, ["scan", str(code_dir), "--home", str(home)])
        assert "Indexed: 0" in result2.output
        assert "Skipped" in result2.output


class TestApiCmd:
    def test_api_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["api", "--help"])
        assert result.exit_code == 0
        assert "HTTP API server" in result.output

    def test_api_start_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["api", "start", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output
        assert "--host" in result.output


class TestConfigDefaults:
    def test_sources_config_present(self, tmp_path: Path):
        config = load_config(tmp_path / "nonexistent.yaml")
        sources = config.get("sources", {})
        local_files = sources.get("local-files", {})
        assert "enabled" in local_files
        assert "paths" in local_files
        assert "extensions" in local_files
        assert "exclude" in local_files
        assert "max_file_size_mb" in local_files

    def test_api_config_present(self, tmp_path: Path):
        config = load_config(tmp_path / "nonexistent.yaml")
        api = config.get("api", {})
        assert "enabled" in api
        assert api["host"] == "127.0.0.1"
        assert api["port"] == 8420
        assert api["api_key"] is None
        assert api["cors_origins"] == []
