"""Tests for anticlaw.daemon.watcher — FileWatcher."""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from anticlaw.daemon.watcher import FileWatcher


class TestFileWatcherInit:
    def test_defaults(self, tmp_path: Path):
        w = FileWatcher(tmp_path)
        assert w.home == tmp_path
        assert w.debounce == 2.0
        assert not w.is_running

    def test_custom_debounce(self, tmp_path: Path):
        w = FileWatcher(tmp_path, debounce_seconds=5.0)
        assert w.debounce == 5.0

    def test_custom_ignore(self, tmp_path: Path):
        ignores = {"*.log", "build"}
        w = FileWatcher(tmp_path, ignore_patterns=ignores)
        assert w.ignore_patterns == ignores


class TestShouldIgnore:
    def test_ignores_tmp_files(self, tmp_path: Path):
        w = FileWatcher(tmp_path)
        assert w._should_ignore(str(tmp_path / "file.tmp")) is True

    def test_ignores_swp_files(self, tmp_path: Path):
        w = FileWatcher(tmp_path)
        assert w._should_ignore(str(tmp_path / "file.swp")) is True

    def test_ignores_git_dir(self, tmp_path: Path):
        w = FileWatcher(tmp_path)
        assert w._should_ignore(str(tmp_path / ".git" / "HEAD")) is True

    def test_ignores_acl_dir(self, tmp_path: Path):
        w = FileWatcher(tmp_path)
        assert w._should_ignore(str(tmp_path / ".acl" / "meta.db")) is True

    def test_allows_md_files(self, tmp_path: Path):
        w = FileWatcher(tmp_path)
        assert w._should_ignore(str(tmp_path / "project" / "chat.md")) is False

    def test_allows_yaml_files(self, tmp_path: Path):
        w = FileWatcher(tmp_path)
        assert w._should_ignore(str(tmp_path / "config.yaml")) is False


class TestDebounce:
    def test_multiple_events_debounced(self, tmp_path: Path):
        """Multiple rapid events should result in a single processing."""
        processed = []

        def on_change(event_type, path):
            processed.append((event_type, str(path)))

        w = FileWatcher(tmp_path, debounce_seconds=0.2, on_change=on_change)

        # Simulate multiple rapid events
        w._on_fs_event("modified", str(tmp_path / "project" / "chat.md"))
        w._on_fs_event("modified", str(tmp_path / "project" / "chat.md"))
        w._on_fs_event("modified", str(tmp_path / "project" / "chat.md"))

        # Wait for debounce to fire
        time.sleep(0.5)

        # Should only process once (same file)
        assert len(processed) == 1
        assert processed[0][0] == "modified"

    def test_different_files_all_processed(self, tmp_path: Path):
        """Different files should all be processed."""
        processed = []

        def on_change(event_type, path):
            processed.append((event_type, str(path)))

        w = FileWatcher(tmp_path, debounce_seconds=0.2, on_change=on_change)

        w._on_fs_event("created", str(tmp_path / "project" / "chat1.md"))
        w._on_fs_event("modified", str(tmp_path / "project" / "chat2.md"))

        time.sleep(0.5)
        assert len(processed) == 2

    def test_ignores_non_md_files(self, tmp_path: Path):
        processed = []

        def on_change(event_type, path):
            processed.append(path)

        w = FileWatcher(tmp_path, debounce_seconds=0.1, on_change=on_change)

        w._on_fs_event("modified", str(tmp_path / "readme.txt"))
        w._on_fs_event("modified", str(tmp_path / "data.json"))

        time.sleep(0.3)
        assert len(processed) == 0

    def test_ignores_underscore_prefix(self, tmp_path: Path):
        processed = []

        def on_change(event_type, path):
            processed.append(path)

        w = FileWatcher(tmp_path, debounce_seconds=0.1, on_change=on_change)

        w._on_fs_event("modified", str(tmp_path / "project" / "_project.md"))

        time.sleep(0.3)
        assert len(processed) == 0


class TestChangeHandler:
    def test_dispatch_calls_watcher(self, tmp_path: Path):
        w = FileWatcher(tmp_path)
        from anticlaw.daemon.watcher import _ChangeHandler

        handler = _ChangeHandler(w)

        event = MagicMock()
        event.is_directory = False
        event.event_type = "modified"
        event.src_path = str(tmp_path / "project" / "chat.md")

        # Should not raise
        handler.dispatch(event)

    def test_skips_directories(self, tmp_path: Path):
        w = FileWatcher(tmp_path)
        from anticlaw.daemon.watcher import _ChangeHandler

        handler = _ChangeHandler(w)

        event = MagicMock()
        event.is_directory = True

        # Should be a no-op
        handler.dispatch(event)


class TestStartStop:
    def test_start_and_stop(self, tmp_path: Path):
        """Start and stop with the real watchdog library (if installed)."""
        w = FileWatcher(tmp_path)
        try:
            w.start()
            assert w.is_running
            w.stop()
            assert not w.is_running
        except RuntimeError:
            # watchdog not installed — that's fine for CI
            pass

    def test_stop_idempotent(self, tmp_path: Path):
        """Stopping a never-started watcher should not raise."""
        w = FileWatcher(tmp_path)
        w.stop()
        assert not w.is_running
