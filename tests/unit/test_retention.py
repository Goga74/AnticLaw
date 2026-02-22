"""Tests for anticlaw.core.retention."""

import gzip
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anticlaw.core.meta_db import MetaDB
from anticlaw.core.models import Chat, ChatMessage, Importance
from anticlaw.core.retention import (
    RetentionAction,
    importance_decay,
    preview_retention,
    restore,
    run_retention,
)
from anticlaw.core.storage import ChatStorage


def _setup_home(tmp_path: Path) -> Path:
    """Create a home with projects and chats of varying ages."""
    home = tmp_path / "home"
    storage = ChatStorage(home)
    storage.init_home()

    project_dir = storage.create_project("alpha", "Test project")

    # Recent active chat (2 days old)
    recent = Chat(
        id="recent-001",
        title="Recent Chat",
        provider="claude",
        created=datetime.now(timezone.utc) - timedelta(days=2),
        updated=datetime.now(timezone.utc) - timedelta(days=2),
        importance="medium",
        status="active",
        messages=[ChatMessage(role="human", content="Hello")],
    )
    storage.write_chat(project_dir / "2025-02-20_recent.md", recent)

    # Old active chat (60 days old)
    old = Chat(
        id="old-001",
        title="Old Chat",
        provider="claude",
        created=datetime.now(timezone.utc) - timedelta(days=60),
        updated=datetime.now(timezone.utc) - timedelta(days=60),
        importance="medium",
        status="active",
        messages=[ChatMessage(role="human", content="Old stuff")],
    )
    storage.write_chat(project_dir / "2025-01-01_old.md", old)

    # Critical old chat (should not be archived)
    critical = Chat(
        id="critical-001",
        title="Critical Chat",
        provider="claude",
        created=datetime.now(timezone.utc) - timedelta(days=90),
        updated=datetime.now(timezone.utc) - timedelta(days=90),
        importance="critical",
        status="active",
        messages=[ChatMessage(role="human", content="Important!")],
    )
    storage.write_chat(project_dir / "2024-12-01_critical.md", critical)

    # Build index
    db = MetaDB(home / ".acl" / "meta.db")
    db.reindex_all(home)
    db.close()

    return home


def _add_archived_chat(home: Path, days_old: int = 200) -> str:
    """Add an archived chat to meta.db for purge testing."""
    archive_dir = home / "_archive"
    archive_dir.mkdir(exist_ok=True)

    # Create a compressed file
    content = b"---\nid: archived-001\ntitle: Archived\n---\n## Human\nOld stuff\n"
    gz_path = archive_dir / "2024-06-01_archived.md.gz"
    with gzip.open(str(gz_path), "wb") as f:
        f.write(content)

    # Insert into meta.db
    updated = (datetime.now(timezone.utc) - timedelta(days=days_old)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    db = MetaDB(home / ".acl" / "meta.db")
    db.conn.execute(
        """INSERT OR REPLACE INTO chats
           (id, title, project_id, provider, remote_id, created, updated,
            tags, summary, importance, status, file_path, token_count,
            message_count, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "archived-001", "Archived Chat", "alpha", "claude", "",
            updated, updated, "[]", "", "low", "archived",
            str(gz_path), 0, 1, "Old stuff",
        ),
    )
    db.conn.commit()
    db.close()
    return "archived-001"


# --- Importance Decay Tests ---


class TestImportanceDecay:
    def test_no_decay_at_zero_days(self):
        assert importance_decay("critical", 0) == Importance.CRITICAL

    def test_critical_stays_high_at_15_days(self):
        result = importance_decay("critical", 15, half_life_days=30)
        assert result in (Importance.CRITICAL, Importance.HIGH)

    def test_critical_decays_to_high_at_30_days(self):
        result = importance_decay("critical", 30, half_life_days=30)
        # critical=4.0 * 0.5 = 2.0 → medium
        assert result == Importance.MEDIUM

    def test_medium_decays_to_low(self):
        # medium=2.0 * 0.5^(60/30) = 2.0 * 0.25 = 0.5 → low
        result = importance_decay("medium", 60, half_life_days=30)
        assert result == Importance.LOW

    def test_high_decays_over_time(self):
        # high=3.0 at 30 days: 3.0*0.5 = 1.5 → medium
        assert importance_decay("high", 30, half_life_days=30) == Importance.MEDIUM

    def test_low_stays_low(self):
        assert importance_decay("low", 10, half_life_days=30) == Importance.LOW

    def test_zero_half_life_defaults_to_30(self):
        result = importance_decay("medium", 0, half_life_days=0)
        assert result == Importance.MEDIUM

    def test_negative_half_life_defaults_to_30(self):
        result = importance_decay("high", 0, half_life_days=-10)
        assert result == Importance.HIGH

    def test_unknown_importance_defaults_to_medium(self):
        result = importance_decay("unknown", 0, half_life_days=30)
        assert result == Importance.MEDIUM

    def test_enum_values_work(self):
        assert importance_decay(Importance.HIGH, 0) == Importance.HIGH


# --- Preview Retention Tests ---


class TestPreviewRetention:
    def test_preview_shows_old_chats(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        result = preview_retention(home, archive_days=30)
        assert len(result.actions) >= 1
        ids = [a.chat_id for a in result.actions]
        assert "old-001" in ids
        assert "recent-001" not in ids

    def test_preview_skips_critical(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        result = preview_retention(home, archive_days=30)
        ids = [a.chat_id for a in result.actions]
        assert "critical-001" not in ids

    def test_preview_purge_archived(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        _add_archived_chat(home, days_old=200)
        result = preview_retention(home, archive_days=30, purge_days=180)
        purge_actions = [a for a in result.actions if a.action == "purge"]
        assert len(purge_actions) >= 1
        assert purge_actions[0].chat_id == "archived-001"

    def test_preview_empty_db(self, tmp_path: Path):
        home = tmp_path / "empty"
        home.mkdir()
        result = preview_retention(home)
        assert len(result.actions) == 0

    def test_preview_no_db(self, tmp_path: Path):
        home = tmp_path / "nodb"
        home.mkdir()
        result = preview_retention(home)
        assert len(result.actions) == 0

    def test_preview_custom_thresholds(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        # With 1-day threshold, both old and recent should be eligible
        result = preview_retention(home, archive_days=1)
        ids = [a.chat_id for a in result.actions]
        assert "old-001" in ids
        assert "recent-001" in ids

    def test_preview_high_threshold_no_results(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        result = preview_retention(home, archive_days=9999)
        assert len(result.actions) == 0

    def test_preview_action_fields(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        result = preview_retention(home, archive_days=30)
        for action in result.actions:
            assert action.chat_id
            assert action.action in ("archive", "purge")
            assert action.reason
            assert action.days_inactive >= 30


# --- Run Retention Tests ---


class TestRunRetention:
    def test_run_archives_old_chat(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        project_dir = home / "alpha"
        old_file = project_dir / "2025-01-01_old.md"
        assert old_file.exists()

        result = run_retention(home, archive_days=30)
        assert result.archived >= 1
        # Original file removed
        assert not old_file.exists()
        # Compressed file in _archive/
        archive_files = list((home / "_archive").glob("*.gz"))
        assert len(archive_files) >= 1

    def test_run_purges_old_archive(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        _add_archived_chat(home, days_old=200)
        gz_path = home / "_archive" / "2024-06-01_archived.md.gz"
        assert gz_path.exists()

        result = run_retention(home, archive_days=9999, purge_days=180)
        assert result.purged >= 1
        assert not gz_path.exists()

    def test_run_no_actions(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        result = run_retention(home, archive_days=9999)
        assert result.archived == 0
        assert result.purged == 0

    def test_run_updates_meta_db(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        run_retention(home, archive_days=30)

        db = MetaDB(home / ".acl" / "meta.db")
        try:
            chat = db.get_chat("old-001")
            assert chat is not None
            assert chat["status"] == "archived"
            assert chat["file_path"].endswith(".gz")
        finally:
            db.close()

    def test_run_preserves_recent(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        run_retention(home, archive_days=30)

        db = MetaDB(home / ".acl" / "meta.db")
        try:
            recent = db.get_chat("recent-001")
            assert recent is not None
            assert recent["status"] == "active"
        finally:
            db.close()


# --- Restore Tests ---


class TestRestore:
    def test_restore_archived_chat(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        # First archive it
        run_retention(home, archive_days=30)
        # Verify it's archived
        db = MetaDB(home / ".acl" / "meta.db")
        chat = db.get_chat("old-001")
        assert chat["status"] == "archived"
        db.close()

        # Restore
        result = restore(home, "old-001")
        assert result is not None
        assert result.exists()
        assert result.suffix == ".md"

        # Verify DB updated
        db = MetaDB(home / ".acl" / "meta.db")
        chat = db.get_chat("old-001")
        assert chat["status"] == "active"
        db.close()

    def test_restore_not_found(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        result = restore(home, "nonexistent-999")
        assert result is None

    def test_restore_not_archived(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        result = restore(home, "recent-001")
        assert result is None

    def test_restore_no_db(self, tmp_path: Path):
        home = tmp_path / "empty"
        home.mkdir()
        result = restore(home, "any-id")
        assert result is None

    def test_restore_partial_id(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        run_retention(home, archive_days=30)
        result = restore(home, "old-0")
        assert result is not None

    def test_restore_decompresses_correctly(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        # Read original content
        project_dir = home / "alpha"
        old_file = project_dir / "2025-01-01_old.md"
        original_content = old_file.read_text(encoding="utf-8")

        # Archive and restore
        run_retention(home, archive_days=30)
        restored_path = restore(home, "old-001")
        assert restored_path is not None

        restored_content = restored_path.read_text(encoding="utf-8")
        assert restored_content == original_content
