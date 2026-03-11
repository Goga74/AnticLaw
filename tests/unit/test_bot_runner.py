"""Tests for anticlaw.bot.runner — subprocess wrappers for aw CLI and claude CLI."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from anticlaw.bot.runner import (
    is_claude_available,
    run_aw_command,
    run_aw_remember,
    run_claude_command,
    run_claude_raw,
)


class TestRunAwCommand:
    @patch("anticlaw.bot.runner.subprocess.run")
    def test_success(self, mock_run, tmp_path: Path):
        mock_run.return_value = MagicMock(
            stdout="Found 3 results\nresult1\nresult2\nresult3",
            stderr="",
            returncode=0,
        )
        result = run_aw_command(["search", "auth"], tmp_path)
        assert "Found 3 results" in result
        mock_run.assert_called_once()
        args = mock_run.call_args
        assert args[0][0] == ["aw", "search", "auth"]

    @patch("anticlaw.bot.runner.subprocess.run")
    def test_error_output(self, mock_run, tmp_path: Path):
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="Error: database not found",
            returncode=1,
        )
        result = run_aw_command(["search", "auth"], tmp_path)
        assert "database not found" in result

    @patch("anticlaw.bot.runner.subprocess.run", side_effect=subprocess.TimeoutExpired("aw", 120))
    def test_timeout(self, mock_run, tmp_path: Path):
        result = run_aw_command(["search", "auth"], tmp_path)
        assert "timed out" in result

    @patch("anticlaw.bot.runner.subprocess.run", side_effect=FileNotFoundError())
    def test_aw_not_found(self, mock_run, tmp_path: Path):
        result = run_aw_command(["search", "auth"], tmp_path)
        assert "not found" in result

    @patch("anticlaw.bot.runner.subprocess.run")
    def test_empty_output(self, mock_run, tmp_path: Path):
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        result = run_aw_command(["health"], tmp_path)
        assert result == "(no output)"

    @patch("anticlaw.bot.runner.subprocess.run")
    def test_acl_home_env(self, mock_run, tmp_path: Path):
        mock_run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
        run_aw_command(["health"], tmp_path)
        env = mock_run.call_args[1]["env"]
        assert env["ACL_HOME"] == str(tmp_path)


class TestRunClaudeCommand:
    @patch("anticlaw.bot.runner.subprocess.run")
    def test_success(self, mock_run, tmp_path: Path):
        mock_run.return_value = MagicMock(
            stdout="Here is the implementation...",
            stderr="",
            returncode=0,
        )
        result = run_claude_command("write a test", tmp_path)
        assert "implementation" in result
        args = mock_run.call_args
        assert args[0][0] == ["claude", "--print", "write a test"]
        assert args[1]["cwd"] == str(tmp_path)

    @patch("anticlaw.bot.runner.subprocess.run")
    def test_custom_claude_path(self, mock_run, tmp_path: Path):
        mock_run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
        run_claude_command("task", tmp_path, claude_path="/usr/local/bin/claude")
        args = mock_run.call_args
        assert args[0][0][0] == "/usr/local/bin/claude"

    @patch(
        "anticlaw.bot.runner.subprocess.run",
        side_effect=subprocess.TimeoutExpired("claude", 120),
    )
    def test_timeout(self, mock_run, tmp_path: Path):
        result = run_claude_command("long task", tmp_path)
        assert "timed out" in result

    @patch("anticlaw.bot.runner.subprocess.run", side_effect=FileNotFoundError())
    def test_claude_not_found(self, mock_run, tmp_path: Path):
        result = run_claude_command("task", tmp_path)
        assert "not found" in result

    @patch("anticlaw.bot.runner.subprocess.run")
    def test_error_output(self, mock_run, tmp_path: Path):
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="API key not set",
            returncode=1,
        )
        result = run_claude_command("task", tmp_path)
        assert "API key" in result


class TestRunClaudeRaw:
    @patch("anticlaw.bot.runner.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="Hello world", stderr="", returncode=0,
        )
        result = run_claude_raw("say hello")
        assert result == "Hello world"
        args = mock_run.call_args
        assert args[0][0] == ["claude", "--print", "say hello"]
        # Should NOT have cwd set
        assert "cwd" not in args[1] or args[1].get("cwd") is None

    @patch("anticlaw.bot.runner.subprocess.run", side_effect=FileNotFoundError())
    def test_not_found(self, mock_run):
        result = run_claude_raw("task")
        assert "not found" in result

    @patch("anticlaw.bot.runner.subprocess.run")
    def test_custom_path(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="ok", stderr="", returncode=0,
        )
        run_claude_raw("task", claude_path="/custom/claude")
        assert mock_run.call_args[0][0][0] == "/custom/claude"


class TestIsClaudeAvailable:
    @patch("anticlaw.bot.runner.subprocess.run")
    def test_available(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert is_claude_available() is True

    @patch("anticlaw.bot.runner.subprocess.run", side_effect=FileNotFoundError())
    def test_not_found(self, mock_run):
        assert is_claude_available() is False

    @patch(
        "anticlaw.bot.runner.subprocess.run",
        side_effect=subprocess.TimeoutExpired("claude", 10),
    )
    def test_timeout(self, mock_run):
        assert is_claude_available() is False

    @patch("anticlaw.bot.runner.subprocess.run")
    def test_custom_path(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert is_claude_available("/custom/claude") is True
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == ["/custom/claude", "--version"]


class TestRunAwRemember:
    @patch("anticlaw.mcp.server.remember_impl", return_value={"id": "acl-test-001"})
    def test_success(self, mock_remember, tmp_path: Path):
        result = run_aw_remember("important note", tmp_path)
        assert "Saved" in result
        assert "acl-test-001" in result
        mock_remember.assert_called_once_with(
            tmp_path, "important note", "fact", "medium", None, "",
        )

    @patch("anticlaw.mcp.server.remember_impl", return_value={"id": "acl-test-002"})
    def test_with_tags(self, mock_remember, tmp_path: Path):
        result = run_aw_remember("tagged note", tmp_path, tags=["auth", "jwt"])
        assert "Saved" in result
        mock_remember.assert_called_once_with(
            tmp_path, "tagged note", "fact", "medium", ["auth", "jwt"], "",
        )

    @patch("anticlaw.mcp.server.remember_impl", side_effect=Exception("DB error"))
    def test_error(self, mock_remember, tmp_path: Path):
        result = run_aw_remember("note", tmp_path)
        assert "Error" in result
