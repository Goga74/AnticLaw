"""BackupProvider Protocol and types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class BackupResult:
    """Result of a backup or restore operation."""

    success: bool
    files_copied: int
    files_skipped: int  # already up-to-date
    bytes_transferred: int
    duration_seconds: float
    errors: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class BackupInfo:
    """Metadata about a backup provider."""

    display_name: str
    version: str
    supports_incremental: bool
    supports_restore: bool
    requires_auth: bool


@runtime_checkable
class BackupProvider(Protocol):
    """Contract for backup storage integration."""

    @property
    def name(self) -> str:
        """Unique provider ID: 'local', 'gdrive', 's3', etc."""
        ...

    @property
    def info(self) -> BackupInfo:
        """Provider metadata."""
        ...

    def auth(self, config: dict) -> bool:
        """Verify credentials / connectivity."""
        ...

    def backup(
        self,
        source_dir: Path,
        manifest: dict | None,
    ) -> tuple[BackupResult, dict]:
        """Run backup. Returns (result, updated_manifest)."""
        ...

    def restore(
        self,
        target_dir: Path,
        snapshot: str | None,
    ) -> BackupResult:
        """Restore from backup."""
        ...

    def list_snapshots(self) -> list[dict]:
        """List available backup snapshots with dates and sizes."""
        ...

    def verify(self) -> bool:
        """Verify backup integrity."""
        ...
