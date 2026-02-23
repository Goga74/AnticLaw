"""Tests for anticlaw.sync.engine — SyncEngine."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from anticlaw.core.models import Chat, ChatMessage
from anticlaw.core.storage import ChatStorage
from anticlaw.sync.engine import SyncEngine


def _setup_home(tmp_path: Path) -> Path:
    """Create a minimal home directory for engine tests."""
    home = tmp_path / "home"
    acl = home / ".acl"
    acl.mkdir(parents=True)
    (home / "_inbox").mkdir()
    return home


def _write_chat(
    home: Path,
    project: str,
    chat_id: str = "test-chat-001",
    title: str = "Test Chat",
    status: str = "active",
    push_target: str | None = None,
    messages: list[ChatMessage] | None = None,
) -> Path:
    """Write a test chat file and return its path."""
    project_dir = home / project
    project_dir.mkdir(parents=True, exist_ok=True)

    storage = ChatStorage(home)
    chat = Chat(
        id=chat_id,
        title=title,
        provider="",
        status=status,
        created=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
        updated=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
        messages=messages or [
            ChatMessage(role="human", content="Hello, how are you?"),
        ],
    )

    chat_path = project_dir / f"2025-06-01_{chat_id}.md"
    storage.write_chat(chat_path, chat)

    # If push_target specified, re-read and patch frontmatter
    if push_target:
        import frontmatter

        post = frontmatter.load(str(chat_path), encoding="utf-8")
        post.metadata["push_target"] = push_target
        chat_path.write_text(frontmatter.dumps(post), encoding="utf-8")

    return chat_path


def _write_project_yaml(home: Path, project: str, sync_cfg: dict | None = None) -> None:
    """Write a _project.yaml with optional sync config."""
    project_dir = home / project
    project_dir.mkdir(parents=True, exist_ok=True)
    data: dict = {"name": project, "description": "Test project"}
    if sync_cfg:
        data["sync"] = sync_cfg
    path = project_dir / "_project.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")


def _write_config(home: Path, sync_cfg: dict | None = None) -> None:
    """Write a config.yaml with optional sync config."""
    acl = home / ".acl"
    acl.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if sync_cfg:
        data["sync"] = sync_cfg
    (acl / "config.yaml").write_text(yaml.dump(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Push target resolution
# ---------------------------------------------------------------------------


class TestResolvePushTarget:
    def test_from_frontmatter(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        chat_path = _write_chat(home, "proj-a", push_target="gemini")
        engine = SyncEngine(home)
        assert engine.resolve_push_target(chat_path) == "gemini"

    def test_from_project_yaml(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        _write_project_yaml(home, "proj-a", sync_cfg={"push_target": "chatgpt"})
        chat_path = _write_chat(home, "proj-a")
        engine = SyncEngine(home)
        assert engine.resolve_push_target(chat_path) == "chatgpt"

    def test_from_global_config(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        _write_config(home, sync_cfg={"default_push_target": "claude"})
        chat_path = _write_chat(home, "proj-a")
        engine = SyncEngine(home)
        assert engine.resolve_push_target(chat_path) == "claude"

    def test_hierarchy_file_wins(self, tmp_path: Path):
        """File frontmatter should take precedence over project and global."""
        home = _setup_home(tmp_path)
        _write_config(home, sync_cfg={"default_push_target": "claude"})
        _write_project_yaml(home, "proj-a", sync_cfg={"push_target": "chatgpt"})
        chat_path = _write_chat(home, "proj-a", push_target="gemini")
        engine = SyncEngine(home)
        assert engine.resolve_push_target(chat_path) == "gemini"

    def test_hierarchy_project_wins_over_global(self, tmp_path: Path):
        """Project config should take precedence over global."""
        home = _setup_home(tmp_path)
        _write_config(home, sync_cfg={"default_push_target": "claude"})
        _write_project_yaml(home, "proj-a", sync_cfg={"push_target": "chatgpt"})
        chat_path = _write_chat(home, "proj-a")
        engine = SyncEngine(home)
        assert engine.resolve_push_target(chat_path) == "chatgpt"

    def test_no_target_configured(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        chat_path = _write_chat(home, "proj-a")
        engine = SyncEngine(home)
        assert engine.resolve_push_target(chat_path) is None


# ---------------------------------------------------------------------------
# send_chat
# ---------------------------------------------------------------------------


class TestSendChat:
    def test_send_chat_success(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        _write_config(home, sync_cfg={"default_push_target": "ollama"})
        chat_path = _write_chat(home, "proj-a")
        engine = SyncEngine(home)

        mock_provider = MagicMock()
        mock_provider.name = "ollama"
        mock_provider.send.return_value = "I'm doing great!"

        with patch("anticlaw.sync.engine.get_sync_provider", return_value=mock_provider):
            response = engine.send_chat(chat_path, provider_name="ollama")

        assert response == "I'm doing great!"
        mock_provider.send.assert_called_once()

        # Verify response was written back
        storage = ChatStorage(home)
        updated = storage.read_chat(chat_path, load_messages=True)
        assert len(updated.messages) == 2
        assert updated.messages[1].role == "assistant"
        assert updated.messages[1].content == "I'm doing great!"
        assert str(updated.status) == "complete"

    def test_send_empty_messages_raises(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        _write_config(home, sync_cfg={"default_push_target": "ollama"})
        chat_path = _write_chat(home, "proj-a", messages=[
            ChatMessage(role="human", content=""),
        ])
        engine = SyncEngine(home)

        mock_provider = MagicMock()
        mock_provider.name = "ollama"

        with patch("anticlaw.sync.engine.get_sync_provider", return_value=mock_provider), \
                pytest.raises(ValueError, match="no messages"):
            engine.send_chat(chat_path, provider_name="ollama")

    def test_send_no_target_raises(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        chat_path = _write_chat(home, "proj-a")
        engine = SyncEngine(home)

        with pytest.raises(ValueError, match="No push target"):
            engine.send_chat(chat_path)

    def test_send_preserves_existing_messages(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        chat_path = _write_chat(home, "proj-a", messages=[
            ChatMessage(role="human", content="First question"),
            ChatMessage(role="assistant", content="First answer"),
            ChatMessage(role="human", content="Second question"),
        ])
        engine = SyncEngine(home)

        mock_provider = MagicMock()
        mock_provider.name = "gemini"
        mock_provider.send.return_value = "Second answer"

        with patch("anticlaw.sync.engine.get_sync_provider", return_value=mock_provider):
            engine.send_chat(chat_path, provider_name="gemini")

        storage = ChatStorage(home)
        updated = storage.read_chat(chat_path, load_messages=True)
        assert len(updated.messages) == 4
        assert updated.messages[0].content == "First question"
        assert updated.messages[3].content == "Second answer"


# ---------------------------------------------------------------------------
# find_drafts
# ---------------------------------------------------------------------------


class TestFindDrafts:
    def test_find_no_drafts(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        _write_chat(home, "proj-a", status="active")
        engine = SyncEngine(home)
        assert engine.find_drafts() == []

    def test_find_draft(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        draft_path = _write_chat(home, "proj-a", chat_id="draft-1", status="draft")
        _write_chat(home, "proj-a", chat_id="active-1", status="active")
        engine = SyncEngine(home)
        drafts = engine.find_drafts()
        assert len(drafts) == 1
        assert drafts[0] == draft_path

    def test_find_multiple_drafts(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        _write_chat(home, "proj-a", chat_id="draft-1", status="draft")
        _write_chat(home, "proj-b", chat_id="draft-2", status="draft")
        _write_chat(home, "proj-a", chat_id="active-1", status="active")
        engine = SyncEngine(home)
        drafts = engine.find_drafts()
        assert len(drafts) == 2

    def test_ignores_acl_dir(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        engine = SyncEngine(home)
        assert engine.find_drafts() == []

    def test_empty_home(self, tmp_path: Path):
        home = tmp_path / "nonexistent"
        engine = SyncEngine(home)
        assert engine.find_drafts() == []


# ---------------------------------------------------------------------------
# process_drafts
# ---------------------------------------------------------------------------


class TestProcessDrafts:
    def test_process_drafts_success(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        _write_config(home, sync_cfg={"default_push_target": "ollama"})
        _write_chat(home, "proj-a", chat_id="draft-1", status="draft")

        engine = SyncEngine(home)

        mock_provider = MagicMock()
        mock_provider.name = "ollama"
        mock_provider.send.return_value = "Draft response"

        with patch("anticlaw.sync.engine.get_sync_provider", return_value=mock_provider):
            results = engine.process_drafts()

        assert len(results) == 1
        assert results[0][1] is None  # no error

    def test_process_drafts_with_error(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        _write_chat(home, "proj-a", chat_id="draft-1", status="draft")
        # No push target configured — should fail gracefully
        engine = SyncEngine(home)
        results = engine.process_drafts()
        assert len(results) == 1
        assert results[0][1] is not None  # has error message
