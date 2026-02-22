"""Tests for anticlaw.daemon.scheduler — TaskScheduler."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from anticlaw.daemon.scheduler import DEFAULT_TASKS, TaskScheduler


class TestTaskSchedulerInit:
    def test_defaults(self, tmp_path: Path):
        s = TaskScheduler(tmp_path)
        assert s.home == tmp_path
        assert not s.is_running

    def test_get_tasks_returns_defaults(self, tmp_path: Path):
        s = TaskScheduler(tmp_path)
        tasks = s.get_tasks()
        assert len(tasks) == len(DEFAULT_TASKS)
        assert tasks[0]["name"] == "reindex"

    def test_get_tasks_from_config(self, tmp_path: Path):
        config = {
            "daemon": {
                "tasks": [
                    {"name": "test-task", "schedule": "* * * * *", "action": "health", "enabled": True}
                ]
            }
        }
        s = TaskScheduler(tmp_path, config)
        tasks = s.get_tasks()
        assert len(tasks) == 1
        assert tasks[0]["name"] == "test-task"


class TestSchedulerState:
    def test_state_file_created(self, tmp_path: Path):
        (tmp_path / ".acl").mkdir(parents=True)
        s = TaskScheduler(tmp_path)
        s._state["test"] = "2025-01-01T00:00:00Z"
        s._save_state()

        state_path = tmp_path / ".acl" / "scheduler_state.json"
        assert state_path.exists()
        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert data["test"] == "2025-01-01T00:00:00Z"

    def test_state_loaded_on_init(self, tmp_path: Path):
        acl = tmp_path / ".acl"
        acl.mkdir(parents=True)
        state_path = acl / "scheduler_state.json"
        state_path.write_text('{"reindex": "2025-01-01T00:00:00Z"}', encoding="utf-8")

        s = TaskScheduler(tmp_path)
        assert s._state["reindex"] == "2025-01-01T00:00:00Z"

    def test_state_handles_corrupt_file(self, tmp_path: Path):
        acl = tmp_path / ".acl"
        acl.mkdir(parents=True)
        (acl / "scheduler_state.json").write_text("not json", encoding="utf-8")

        s = TaskScheduler(tmp_path)
        assert s._state == {}


class TestLogExecution:
    def test_log_writes_to_file(self, tmp_path: Path):
        (tmp_path / ".acl").mkdir(parents=True)
        s = TaskScheduler(tmp_path)
        s._log_execution("test-task", True, "completed")

        log_path = tmp_path / ".acl" / "cron.log"
        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8")
        assert "[OK] test-task: completed" in content

    def test_log_failure(self, tmp_path: Path):
        (tmp_path / ".acl").mkdir(parents=True)
        s = TaskScheduler(tmp_path)
        s._log_execution("broken-task", False, "Error: disk full")

        content = (tmp_path / ".acl" / "cron.log").read_text(encoding="utf-8")
        assert "[FAIL] broken-task:" in content

    def test_get_log_lines(self, tmp_path: Path):
        (tmp_path / ".acl").mkdir(parents=True)
        s = TaskScheduler(tmp_path)
        s._log_execution("task1", True, "ok")
        s._log_execution("task2", True, "ok")
        s._log_execution("task3", False, "fail")

        lines = s.get_log_lines(n=2)
        assert len(lines) == 2
        assert "task3" in lines[-1]

    def test_get_log_lines_empty(self, tmp_path: Path):
        s = TaskScheduler(tmp_path)
        assert s.get_log_lines() == []


class TestRunTask:
    def test_run_reindex(self, tmp_path: Path):
        """Test reindex action with a proper KB setup."""
        home = tmp_path / "home"
        home.mkdir()
        (home / ".acl").mkdir()
        (home / "_inbox").mkdir()

        s = TaskScheduler(home)
        ok, msg = s._run_task("reindex", "reindex", {})
        assert ok is True
        assert "Reindexed" in msg

    def test_run_health(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        (home / ".acl").mkdir()

        s = TaskScheduler(home)
        ok, msg = s._run_task("health", "health", {})
        assert ok is True
        assert "healthy" in msg.lower() or "issues" in msg.lower()

    def test_run_retention_placeholder(self, tmp_path: Path):
        s = TaskScheduler(tmp_path)
        ok, msg = s._run_task("retention", "retention", {})
        assert ok is True
        assert "not yet implemented" in msg

    def test_run_sync_placeholder(self, tmp_path: Path):
        s = TaskScheduler(tmp_path)
        ok, msg = s._run_task("sync", "sync", {})
        assert ok is True
        assert "not yet implemented" in msg

    def test_run_unknown_action(self, tmp_path: Path):
        (tmp_path / ".acl").mkdir(parents=True)
        s = TaskScheduler(tmp_path)
        ok, msg = s._run_task("bad", "nonexistent", {})
        assert ok is False
        assert "Unknown action" in msg

    def test_run_task_now_not_found(self, tmp_path: Path):
        s = TaskScheduler(tmp_path)
        ok, msg = s.run_task_now("no-such-task")
        assert ok is False
        assert "not found" in msg.lower()

    def test_run_task_now_found(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        (home / ".acl").mkdir()

        config = {
            "daemon": {
                "tasks": [
                    {"name": "test-health", "schedule": "* * * * *", "action": "health", "enabled": True}
                ]
            }
        }
        s = TaskScheduler(home, config)
        ok, msg = s.run_task_now("test-health")
        assert ok is True


class TestShellAction:
    def test_shell_echo(self, tmp_path: Path):
        (tmp_path / ".acl").mkdir(parents=True)
        s = TaskScheduler(tmp_path)
        ok, msg = s._run_task("test-shell", "shell", {"command": "echo hello"})
        assert ok is True
        assert "hello" in msg or "Exit 0" in msg

    def test_shell_no_command(self, tmp_path: Path):
        (tmp_path / ".acl").mkdir(parents=True)
        s = TaskScheduler(tmp_path)
        ok, msg = s._run_task("no-cmd", "shell", {})
        assert ok is True
        assert "No command" in msg
