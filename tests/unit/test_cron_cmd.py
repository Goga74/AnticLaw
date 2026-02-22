"""Tests for anticlaw.cli.cron_cmd — aw cron CLI commands."""

from pathlib import Path
from unittest.mock import patch

import yaml
from click.testing import CliRunner

from anticlaw.cli.cron_cmd import cron_group


class TestCronList:
    def test_list_default_tasks(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        (home / ".acl").mkdir()

        runner = CliRunner()
        result = runner.invoke(cron_group, ["list", "--home", str(home)])

        assert result.exit_code == 0
        assert "reindex" in result.output
        assert "backup" in result.output
        assert "health" in result.output

    def test_list_custom_tasks(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        acl = home / ".acl"
        acl.mkdir()

        config = {
            "daemon": {
                "tasks": [
                    {"name": "my-task", "schedule": "0 1 * * *", "action": "health", "enabled": True},
                ]
            }
        }
        (acl / "config.yaml").write_text(
            yaml.dump(config, default_flow_style=False), encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cron_group, ["list", "--home", str(home)])

        assert result.exit_code == 0
        assert "my-task" in result.output


class TestCronAdd:
    def test_add_new_task(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        acl = home / ".acl"
        acl.mkdir()
        (acl / "config.yaml").write_text("{}", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            cron_group,
            ["add", "test-task", "0 5 * * *", "health", "--home", str(home)],
        )

        assert result.exit_code == 0
        assert "Added task" in result.output

        # Verify config was updated
        config = yaml.safe_load((acl / "config.yaml").read_text(encoding="utf-8"))
        tasks = config["daemon"]["tasks"]
        assert any(t["name"] == "test-task" for t in tasks)

    def test_add_duplicate_rejected(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        acl = home / ".acl"
        acl.mkdir()

        config = {
            "daemon": {
                "tasks": [
                    {"name": "existing", "schedule": "0 1 * * *", "action": "health", "enabled": True},
                ]
            }
        }
        (acl / "config.yaml").write_text(
            yaml.dump(config, default_flow_style=False), encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(
            cron_group,
            ["add", "existing", "0 5 * * *", "health", "--home", str(home)],
        )

        assert result.exit_code == 0
        assert "already exists" in result.output

    def test_add_with_json_params(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        acl = home / ".acl"
        acl.mkdir()
        (acl / "config.yaml").write_text("{}", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            cron_group,
            [
                "add", "backup-task", "0 3 * * *", "backup",
                "--home", str(home),
                "--params", '{"providers": ["local"]}',
            ],
        )

        assert result.exit_code == 0
        assert "Added" in result.output


class TestCronRemove:
    def test_remove_existing(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        acl = home / ".acl"
        acl.mkdir()

        config = {
            "daemon": {
                "tasks": [
                    {"name": "to-remove", "schedule": "0 1 * * *", "action": "health", "enabled": True},
                    {"name": "keep", "schedule": "0 2 * * *", "action": "reindex", "enabled": True},
                ]
            }
        }
        (acl / "config.yaml").write_text(
            yaml.dump(config, default_flow_style=False), encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(
            cron_group, ["remove", "to-remove", "--home", str(home)],
        )

        assert result.exit_code == 0
        assert "Removed" in result.output

        # Verify it was removed
        config = yaml.safe_load((acl / "config.yaml").read_text(encoding="utf-8"))
        task_names = [t["name"] for t in config["daemon"]["tasks"]]
        assert "to-remove" not in task_names
        assert "keep" in task_names

    def test_remove_nonexistent(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        acl = home / ".acl"
        acl.mkdir()
        (acl / "config.yaml").write_text("{}", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            cron_group, ["remove", "ghost", "--home", str(home)],
        )

        assert result.exit_code == 0
        assert "not found" in result.output


class TestCronRun:
    def test_run_task_directly(self, tmp_path: Path):
        """Run a task directly (no daemon)."""
        home = tmp_path / "home"
        home.mkdir()
        (home / ".acl").mkdir()

        config = {
            "daemon": {
                "tasks": [
                    {"name": "run-health", "schedule": "0 1 * * *", "action": "health", "enabled": True},
                ]
            }
        }
        (home / ".acl" / "config.yaml").write_text(
            yaml.dump(config, default_flow_style=False), encoding="utf-8",
        )

        runner = CliRunner()
        # Mock IPC to fail (no daemon), so it falls back to direct execution
        with patch("anticlaw.daemon.ipc.ipc_send") as mock_ipc:
            mock_ipc.return_value = {"status": "error", "message": "Cannot connect to daemon"}
            result = runner.invoke(
                cron_group, ["run", "run-health", "--home", str(home)],
            )

        assert result.exit_code == 0
        assert "health" in result.output.lower() or "healthy" in result.output.lower()


class TestCronLogs:
    def test_logs_empty(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        (home / ".acl").mkdir()

        runner = CliRunner()
        result = runner.invoke(cron_group, ["logs", "--home", str(home)])

        assert result.exit_code == 0
        assert "no cron log" in result.output.lower()

    def test_logs_with_content(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        acl = home / ".acl"
        acl.mkdir()

        # Write some log entries
        from anticlaw.daemon.scheduler import TaskScheduler

        s = TaskScheduler(home)
        s._log_execution("test", True, "done")
        s._log_execution("test2", False, "error")

        runner = CliRunner()
        result = runner.invoke(cron_group, ["logs", "--home", str(home)])

        assert result.exit_code == 0
        assert "test" in result.output
