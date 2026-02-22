"""Tests for anticlaw.cli.daemon_cmd — aw daemon CLI commands."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from anticlaw.cli.daemon_cmd import daemon_group


class TestDaemonStatus:
    @patch("anticlaw.daemon.ipc.ipc_send")
    def test_status_when_running(self, mock_send, tmp_path: Path):
        mock_send.return_value = {
            "status": "ok",
            "home": str(tmp_path),
            "components": ["watcher", "scheduler", "ipc"],
            "watcher": True,
            "scheduler": True,
        }

        runner = CliRunner()
        result = runner.invoke(daemon_group, ["status", "--home", str(tmp_path)])

        assert result.exit_code == 0
        assert "running" in result.output.lower()
        assert "watcher" in result.output.lower()

    @patch("anticlaw.daemon.service.read_pid", return_value=None)
    @patch("anticlaw.daemon.ipc.ipc_send")
    def test_status_when_stopped(self, mock_send, mock_pid, tmp_path: Path):
        mock_send.return_value = {"status": "error", "message": "Cannot connect"}

        runner = CliRunner()
        result = runner.invoke(daemon_group, ["status", "--home", str(tmp_path)])

        assert result.exit_code == 0
        assert "not running" in result.output.lower()


class TestDaemonStop:
    @patch("anticlaw.daemon.service.read_pid", return_value=12345)
    @patch("anticlaw.daemon.service.is_process_running", return_value=True)
    @patch("os.kill")
    @patch("anticlaw.daemon.ipc.ipc_send")
    def test_stop_via_ipc(self, mock_send, mock_kill, mock_running, mock_pid, tmp_path: Path):
        mock_send.return_value = {"status": "ok", "message": "Shutting down"}

        runner = CliRunner()
        result = runner.invoke(daemon_group, ["stop", "--home", str(tmp_path)])

        assert result.exit_code == 0
        assert "shutdown" in result.output.lower()

    @patch("anticlaw.daemon.service.remove_pid")
    @patch("anticlaw.daemon.service.is_process_running", return_value=False)
    @patch("anticlaw.daemon.service.read_pid", return_value=None)
    @patch("anticlaw.daemon.ipc.ipc_send")
    def test_stop_not_running(self, mock_send, mock_pid, mock_running, mock_remove, tmp_path: Path):
        mock_send.return_value = {"status": "error", "message": "Cannot connect"}

        runner = CliRunner()
        result = runner.invoke(daemon_group, ["stop", "--home", str(tmp_path)])

        assert result.exit_code == 0
        assert "not running" in result.output.lower()


class TestDaemonLogs:
    def test_logs_no_file(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(daemon_group, ["logs", "--home", str(tmp_path)])

        assert result.exit_code == 0
        assert "no daemon log" in result.output.lower()

    def test_logs_with_content(self, tmp_path: Path):
        acl = tmp_path / ".acl"
        acl.mkdir(parents=True)
        log_path = acl / "daemon.log"
        log_path.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(daemon_group, ["logs", "--home", str(tmp_path), "-n", "2"])

        assert result.exit_code == 0
        assert "line 2" in result.output
        assert "line 3" in result.output


class TestDaemonInstall:
    @patch("anticlaw.daemon.service.install_service")
    def test_install(self, mock_install, tmp_path: Path):
        mock_install.return_value = "Created service at /path/to/unit"

        runner = CliRunner()
        result = runner.invoke(daemon_group, ["install", "--home", str(tmp_path)])

        assert result.exit_code == 0
        assert "Created service" in result.output


class TestDaemonUninstall:
    @patch("anticlaw.daemon.service.uninstall_service")
    def test_uninstall(self, mock_uninstall, tmp_path: Path):
        mock_uninstall.return_value = "Removed service"

        runner = CliRunner()
        result = runner.invoke(daemon_group, ["uninstall", "--home", str(tmp_path)])

        assert result.exit_code == 0
        assert "Removed" in result.output
