"""Tests for anticlaw.cli.mcp_cmd."""

from click.testing import CliRunner

from anticlaw.cli.main import cli


class TestMcpStart:
    def test_start_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["mcp", "start", "--help"])
        assert result.exit_code == 0
        assert "Start the MCP server" in result.output


class TestMcpInstall:
    def test_install_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["mcp", "install", "--help"])
        assert result.exit_code == 0
        assert "claude-code" in result.output
        assert "cursor" in result.output

    def test_install_claude_code(self, tmp_path, monkeypatch):
        from pathlib import Path

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        runner = CliRunner()
        result = runner.invoke(cli, ["mcp", "install", "claude-code"])
        assert result.exit_code == 0
        assert "Registered" in result.output
        assert "Restart Claude Code" in result.output

    def test_install_cursor(self, tmp_path, monkeypatch):
        from pathlib import Path

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        runner = CliRunner()
        result = runner.invoke(cli, ["mcp", "install", "cursor"])
        assert result.exit_code == 0
        assert "Registered" in result.output
        assert "Restart Cursor" in result.output

    def test_install_invalid_target(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["mcp", "install", "vscode"])
        assert result.exit_code != 0
