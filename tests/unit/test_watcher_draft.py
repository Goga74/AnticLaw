"""Tests for draft detection in daemon/watcher.py."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from anticlaw.core.models import Chat, ChatMessage
from anticlaw.core.storage import ChatStorage
from anticlaw.daemon.watcher import FileWatcher


def _setup_home(tmp_path: Path) -> Path:
    """Create a home with .acl and meta.db."""
    home = tmp_path / "home"
    acl = home / ".acl"
    acl.mkdir(parents=True)
    (home / "_inbox").mkdir()
    return home


def _write_chat(home: Path, project: str, chat_id: str, status: str = "active") -> Path:
    """Write a test chat file."""
    project_dir = home / project
    project_dir.mkdir(parents=True, exist_ok=True)

    storage = ChatStorage(home)
    chat = Chat(
        id=chat_id,
        title=f"Chat {chat_id}",
        provider="claude",
        status=status,
        created=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
        updated=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
        messages=[ChatMessage(role="human", content="Hello")],
    )
    chat_path = project_dir / f"2025-06-01_{chat_id}.md"
    storage.write_chat(chat_path, chat)
    return chat_path


class TestWatcherDraftDetection:
    def test_draft_triggers_process_draft(self, tmp_path: Path):
        """When a draft file is reindexed, _process_draft should be called."""
        home = _setup_home(tmp_path)
        chat_path = _write_chat(home, "proj-a", "draft-1", status="draft")

        watcher = FileWatcher(home)
        watcher._process_draft = MagicMock()

        # Call _reindex_chat directly
        watcher._reindex_chat(chat_path)

        # _process_draft should have been called
        watcher._process_draft.assert_called_once_with(chat_path)

    def test_active_does_not_trigger_draft(self, tmp_path: Path):
        """Active files should not trigger _process_draft."""
        home = _setup_home(tmp_path)
        chat_path = _write_chat(home, "proj-a", "active-1", status="active")

        watcher = FileWatcher(home)
        watcher._process_draft = MagicMock()

        watcher._reindex_chat(chat_path)

        watcher._process_draft.assert_not_called()

    def test_process_draft_disabled(self, tmp_path: Path):
        """When auto_push_drafts is False, draft processing should be skipped."""
        home = _setup_home(tmp_path)
        acl = home / ".acl"
        config = {"sync": {"auto_push_drafts": False}}
        (acl / "config.yaml").write_text(yaml.dump(config), encoding="utf-8")

        chat_path = _write_chat(home, "proj-a", "draft-1", status="draft")
        watcher = FileWatcher(home)

        # Should not raise, just skip
        with patch("anticlaw.sync.engine.SyncEngine") as mock_engine:
            watcher._process_draft(chat_path)
            mock_engine.assert_not_called()

    def test_process_draft_enabled(self, tmp_path: Path):
        """When auto_push_drafts is True, should call SyncEngine.send_chat."""
        home = _setup_home(tmp_path)
        acl = home / ".acl"
        config = {"sync": {"auto_push_drafts": True, "default_push_target": "ollama"}}
        (acl / "config.yaml").write_text(yaml.dump(config), encoding="utf-8")

        chat_path = _write_chat(home, "proj-a", "draft-1", status="draft")
        watcher = FileWatcher(home)

        mock_engine_instance = MagicMock()
        with patch(
            "anticlaw.sync.engine.SyncEngine", return_value=mock_engine_instance,
        ):
            watcher._process_draft(chat_path)
            mock_engine_instance.send_chat.assert_called_once_with(chat_path)
