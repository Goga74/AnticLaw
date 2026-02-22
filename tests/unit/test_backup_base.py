"""Tests for anticlaw.providers.backup.base — BackupProvider Protocol and types."""

from datetime import datetime, timezone

from anticlaw.providers.backup.base import BackupInfo, BackupProvider, BackupResult


class TestBackupResult:
    def test_defaults(self):
        r = BackupResult(
            success=True,
            files_copied=5,
            files_skipped=10,
            bytes_transferred=1024,
            duration_seconds=1.5,
        )
        assert r.success is True
        assert r.files_copied == 5
        assert r.files_skipped == 10
        assert r.bytes_transferred == 1024
        assert r.duration_seconds == 1.5
        assert r.errors == []
        assert isinstance(r.timestamp, datetime)

    def test_with_errors(self):
        r = BackupResult(
            success=False,
            files_copied=0,
            files_skipped=0,
            bytes_transferred=0,
            duration_seconds=0.1,
            errors=["disk full"],
        )
        assert not r.success
        assert r.errors == ["disk full"]


class TestBackupInfo:
    def test_fields(self):
        info = BackupInfo(
            display_name="Local copy",
            version="1.0.0",
            supports_incremental=True,
            supports_restore=True,
            requires_auth=False,
        )
        assert info.display_name == "Local copy"
        assert info.supports_incremental is True
        assert info.requires_auth is False


class TestBackupProtocol:
    def test_local_provider_is_backup_provider(self):
        from anticlaw.providers.backup.local import LocalBackupProvider

        provider = LocalBackupProvider()
        assert isinstance(provider, BackupProvider)

    def test_gdrive_provider_is_backup_provider(self):
        from anticlaw.providers.backup.gdrive import GDriveBackupProvider

        provider = GDriveBackupProvider()
        assert isinstance(provider, BackupProvider)
