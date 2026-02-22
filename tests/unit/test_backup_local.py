"""Tests for anticlaw.providers.backup.local — LocalBackupProvider."""

import os
from pathlib import Path

from anticlaw.providers.backup.local import LocalBackupProvider


class TestLocalBackupProviderMeta:
    def test_name(self):
        p = LocalBackupProvider()
        assert p.name == "local"

    def test_info(self):
        p = LocalBackupProvider()
        assert p.info.display_name == "Local copy"
        assert p.info.supports_incremental is True
        assert p.info.supports_restore is True
        assert p.info.requires_auth is False

    def test_auth(self, tmp_path: Path):
        p = LocalBackupProvider({"path": str(tmp_path / "backups")})
        assert p.auth({"path": str(tmp_path / "backups")}) is True

    def test_verify_empty(self, tmp_path: Path):
        target = tmp_path / "backups"
        p = LocalBackupProvider({"path": str(target)})
        assert p.verify() is False

        target.mkdir()
        assert p.verify() is True


class TestLocalBackup:
    def _create_source(self, tmp_path: Path) -> Path:
        """Create a source directory with some .md files."""
        src = tmp_path / "source"
        src.mkdir()

        # Create project dir with chats
        proj = src / "project-a"
        proj.mkdir()
        (proj / "chat1.md").write_text("# Chat 1\nHello", encoding="utf-8")
        (proj / "chat2.md").write_text("# Chat 2\nWorld", encoding="utf-8")

        # Create inbox
        inbox = src / "_inbox"
        inbox.mkdir()
        (inbox / "new-chat.md").write_text("# New chat", encoding="utf-8")

        return src

    def test_full_backup(self, tmp_path: Path):
        src = self._create_source(tmp_path)
        target = tmp_path / "backups"
        target.mkdir()

        p = LocalBackupProvider({"path": str(target)})
        result, manifest = p.backup(src, None)

        assert result.success is True
        assert result.files_copied == 3
        assert result.files_skipped == 0
        assert result.bytes_transferred > 0
        assert result.errors == []
        assert manifest["provider"] == "local"
        assert len(manifest["files"]) == 3

    def test_incremental_backup_skips_unchanged(self, tmp_path: Path):
        src = self._create_source(tmp_path)
        target = tmp_path / "backups"
        target.mkdir()

        p = LocalBackupProvider({"path": str(target)})

        # First backup
        result1, manifest1 = p.backup(src, None)
        assert result1.files_copied == 3

        # Second backup with same manifest — all should be skipped
        result2, manifest2 = p.backup(src, manifest1)
        assert result2.files_copied == 0
        assert result2.files_skipped == 3

    def test_incremental_detects_modified(self, tmp_path: Path):
        src = self._create_source(tmp_path)
        target = tmp_path / "backups"
        target.mkdir()

        p = LocalBackupProvider({"path": str(target)})

        # First backup
        result1, manifest1 = p.backup(src, None)
        assert result1.files_copied == 3

        # Modify one file (need to change mtime)
        chat1 = src / "project-a" / "chat1.md"
        # Force mtime to be newer
        import time
        time.sleep(0.1)
        chat1.write_text("# Chat 1\nUpdated content", encoding="utf-8")

        result2, manifest2 = p.backup(src, manifest1)
        assert result2.files_copied == 1
        assert result2.files_skipped == 2

    def test_skips_acl_and_git_dirs(self, tmp_path: Path):
        src = self._create_source(tmp_path)

        # Add .acl and .git directories with files
        acl = src / ".acl"
        acl.mkdir()
        (acl / "meta.db").write_text("data", encoding="utf-8")

        git_dir = src / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")

        target = tmp_path / "backups"
        target.mkdir()

        p = LocalBackupProvider({"path": str(target)})
        result, _ = p.backup(src, None)

        # Only the 3 .md files, not .acl or .git
        assert result.files_copied == 3

    def test_empty_backup_all_skipped(self, tmp_path: Path):
        src = self._create_source(tmp_path)
        target = tmp_path / "backups"
        target.mkdir()

        p = LocalBackupProvider({"path": str(target)})

        # First backup
        result1, manifest = p.backup(src, None)
        assert result1.files_copied == 3

        # Second backup — nothing changed, all should be skipped
        result2, _ = p.backup(src, manifest)
        assert result2.files_copied == 0
        assert result2.files_skipped == 3


class TestLocalRestore:
    def test_restore_latest(self, tmp_path: Path):
        src = tmp_path / "source"
        src.mkdir()
        proj = src / "test"
        proj.mkdir()
        (proj / "chat.md").write_text("# Test chat", encoding="utf-8")

        target = tmp_path / "backups"
        target.mkdir()
        restore_dir = tmp_path / "restored"

        p = LocalBackupProvider({"path": str(target)})

        # Backup first
        p.backup(src, None)

        # Restore
        result = p.restore(restore_dir, None)
        assert result.success is True
        assert result.files_copied == 1

        restored_file = restore_dir / "test" / "chat.md"
        assert restored_file.exists()
        assert restored_file.read_text(encoding="utf-8") == "# Test chat"

    def test_restore_specific_snapshot(self, tmp_path: Path):
        src = tmp_path / "source"
        src.mkdir()
        (src / "file.md").write_text("v1", encoding="utf-8")

        target = tmp_path / "backups"
        target.mkdir()

        p = LocalBackupProvider({"path": str(target)})
        _, manifest1 = p.backup(src, None)
        snap_id = manifest1["last_backup"]

        restore_dir = tmp_path / "restored"
        result = p.restore(restore_dir, snap_id)
        assert result.success is True
        assert result.files_copied == 1

    def test_restore_no_snapshots(self, tmp_path: Path):
        target = tmp_path / "backups"
        target.mkdir()

        p = LocalBackupProvider({"path": str(target)})
        result = p.restore(tmp_path / "restored", None)
        assert result.success is False
        assert "No snapshots" in result.errors[0]


class TestLocalListSnapshots:
    def test_list_snapshots(self, tmp_path: Path):
        src = tmp_path / "source"
        src.mkdir()
        (src / "chat.md").write_text("content", encoding="utf-8")

        target = tmp_path / "backups"
        target.mkdir()

        p = LocalBackupProvider({"path": str(target)})
        p.backup(src, None)

        snapshots = p.list_snapshots()
        assert len(snapshots) == 1
        assert snapshots[0]["provider"] == "local"
        assert snapshots[0]["files"] == 1

    def test_list_empty(self, tmp_path: Path):
        target = tmp_path / "backups"
        p = LocalBackupProvider({"path": str(target)})
        assert p.list_snapshots() == []
