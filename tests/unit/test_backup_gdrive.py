"""Tests for anticlaw.providers.backup.gdrive — GDriveBackupProvider."""

from unittest.mock import MagicMock, patch

from anticlaw.providers.backup.base import BackupProvider
from anticlaw.providers.backup.gdrive import GDriveBackupProvider, _md5


class TestGDriveProviderMeta:
    def test_name(self):
        p = GDriveBackupProvider()
        assert p.name == "gdrive"

    def test_info(self):
        p = GDriveBackupProvider()
        assert p.info.display_name == "Google Drive"
        assert p.info.supports_incremental is True
        assert p.info.requires_auth is True

    def test_is_backup_provider(self):
        p = GDriveBackupProvider()
        assert isinstance(p, BackupProvider)


class TestMD5:
    def test_computes_hash(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        h = _md5(f)
        assert isinstance(h, str)
        assert len(h) == 32

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello", encoding="utf-8")
        f2.write_text("world", encoding="utf-8")
        assert _md5(f1) != _md5(f2)

    def test_same_content_same_hash(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("identical", encoding="utf-8")
        f2.write_text("identical", encoding="utf-8")
        assert _md5(f1) == _md5(f2)


class TestGDriveBackupNoService:
    def test_backup_without_credentials(self, tmp_path):
        p = GDriveBackupProvider({"folder_id": "fake"})
        result, manifest = p.backup(tmp_path, None)
        assert result.success is False
        assert len(result.errors) > 0

    def test_auth_fails_without_service(self):
        p = GDriveBackupProvider({"folder_id": "fake"})
        assert p.auth({}) is False

    def test_verify_fails_without_service(self):
        p = GDriveBackupProvider({"folder_id": "fake"})
        assert p.verify() is False

    def test_list_snapshots_empty_without_service(self):
        p = GDriveBackupProvider({"folder_id": "fake"})
        assert p.list_snapshots() == []
