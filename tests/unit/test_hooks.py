"""Tests for anticlaw.mcp.hooks."""

import json
from pathlib import Path

from anticlaw.mcp.hooks import (
    TurnTracker,
    generate_mcp_config,
    install_claude_code,
    install_cursor,
)


class TestTurnTracker:
    def test_no_reminder_below_threshold(self):
        tracker = TurnTracker()
        for _ in range(9):
            assert tracker.increment() is None

    def test_reminder_at_threshold_10(self):
        tracker = TurnTracker()
        for _ in range(9):
            tracker.increment()
        msg = tracker.increment()
        assert msg is not None
        assert "consider" in msg.lower() or "reminder" in msg.lower()

    def test_reminder_at_threshold_20(self):
        tracker = TurnTracker()
        for _ in range(19):
            tracker.increment()
        msg = tracker.increment()
        assert msg is not None
        assert "should save" in msg.lower() or "warning" in msg.lower()

    def test_reminder_at_threshold_30(self):
        tracker = TurnTracker()
        for _ in range(29):
            tracker.increment()
        msg = tracker.increment()
        assert msg is not None
        assert "required" in msg.lower()

    def test_reset(self):
        tracker = TurnTracker()
        for _ in range(9):
            tracker.increment()
        tracker.reset()
        assert tracker.count == 0
        # After reset, no reminder at turn 1
        assert tracker.increment() is None

    def test_custom_thresholds(self):
        tracker = TurnTracker(thresholds=[3, 6])
        for _ in range(2):
            tracker.increment()
        msg = tracker.increment()  # turn 3
        assert msg is not None


class TestGenerateConfig:
    def test_generates_valid_config(self):
        config = generate_mcp_config("/usr/bin/python3")
        assert "mcpServers" in config
        assert "anticlaw" in config["mcpServers"]
        server = config["mcpServers"]["anticlaw"]
        assert server["command"] == "/usr/bin/python3"
        assert server["args"] == ["-m", "anticlaw.mcp"]


class TestInstallClaudeCode:
    def test_creates_settings(self, tmp_path: Path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        path = install_claude_code("/usr/bin/python3")
        assert path.exists()

        data = json.loads(path.read_text(encoding="utf-8"))
        assert "mcpServers" in data
        assert "anticlaw" in data["mcpServers"]

    def test_preserves_existing(self, tmp_path: Path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        # Create existing settings
        settings_dir = fake_home / ".claude"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text(
            json.dumps({"mcpServers": {"other": {"command": "other"}}, "key": "val"}),
            encoding="utf-8",
        )

        install_claude_code("/usr/bin/python3")
        data = json.loads((settings_dir / "settings.json").read_text(encoding="utf-8"))
        assert "other" in data["mcpServers"]
        assert "anticlaw" in data["mcpServers"]
        assert data["key"] == "val"


class TestInstallCursor:
    def test_creates_mcp_json(self, tmp_path: Path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        path = install_cursor("/usr/bin/python3")
        assert path.exists()

        data = json.loads(path.read_text(encoding="utf-8"))
        assert "anticlaw" in data["mcpServers"]
