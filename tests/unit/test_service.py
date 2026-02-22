"""Tests for anticlaw.daemon.service — PID management and service registration."""

import os
from pathlib import Path

from anticlaw.daemon.service import (
    get_pid_path,
    is_process_running,
    read_pid,
    remove_pid,
    write_pid,
)


class TestPIDManagement:
    def test_get_pid_path(self, tmp_path: Path):
        p = get_pid_path(tmp_path)
        assert p == tmp_path / ".acl" / "daemon.pid"

    def test_write_and_read_pid(self, tmp_path: Path):
        (tmp_path / ".acl").mkdir(parents=True)
        write_pid(tmp_path)
        pid = read_pid(tmp_path)
        assert pid == os.getpid()

    def test_read_pid_not_found(self, tmp_path: Path):
        assert read_pid(tmp_path) is None

    def test_read_pid_corrupt(self, tmp_path: Path):
        (tmp_path / ".acl").mkdir(parents=True)
        (tmp_path / ".acl" / "daemon.pid").write_text("not-a-number", encoding="utf-8")
        assert read_pid(tmp_path) is None

    def test_remove_pid(self, tmp_path: Path):
        (tmp_path / ".acl").mkdir(parents=True)
        write_pid(tmp_path)
        assert read_pid(tmp_path) is not None

        remove_pid(tmp_path)
        assert read_pid(tmp_path) is None

    def test_remove_pid_nonexistent(self, tmp_path: Path):
        # Should not raise
        remove_pid(tmp_path)


class TestIsProcessRunning:
    def test_current_process_running(self):
        assert is_process_running(os.getpid()) is True

    def test_nonexistent_process(self):
        # Use a very high PID unlikely to exist
        assert is_process_running(999999999) is False
