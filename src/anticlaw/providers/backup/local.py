"""Local backup provider — shutil-based file copy with incremental manifest."""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from anticlaw.providers.backup.base import BackupInfo, BackupResult

log = logging.getLogger(__name__)

# Directories to skip during backup
_SKIP_DIRS = {".acl", ".git", ".github", "__pycache__"}


class LocalBackupProvider:
    """Backup to a local directory with timestamped snapshots."""

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        self._target_path = Path(config.get("path", "")).expanduser()

    @property
    def name(self) -> str:
        return "local"

    @property
    def info(self) -> BackupInfo:
        return BackupInfo(
            display_name="Local copy",
            version="1.0.0",
            supports_incremental=True,
            supports_restore=True,
            requires_auth=False,
        )

    def auth(self, config: dict) -> bool:
        """Local backup needs no auth — just verify path is writable."""
        path = Path(config.get("path", str(self._target_path))).expanduser()
        return path.parent.exists()

    def backup(
        self,
        source_dir: Path,
        manifest: dict | None,
    ) -> tuple[BackupResult, dict]:
        """Run incremental backup to local directory.

        Creates a timestamped snapshot directory. Only copies files that
        changed since the last backup (by comparing mtime from manifest).
        """
        start = time.monotonic()
        manifest = manifest or {}
        files_map = manifest.get("files", {})
        new_files_map: dict[str, float] = {}
        errors: list[str] = []
        copied = 0
        skipped = 0
        bytes_transferred = 0

        # Create timestamped snapshot directory
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        snapshot_dir = self._target_path / ts

        try:
            snapshot_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return BackupResult(
                success=False,
                files_copied=0,
                files_skipped=0,
                bytes_transferred=0,
                duration_seconds=time.monotonic() - start,
                errors=[f"Cannot create snapshot dir: {e}"],
            ), manifest

        # Walk source and copy changed files
        for root, dirs, files in os.walk(source_dir):
            # Skip internal directories
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]

            rel_root = Path(root).relative_to(source_dir)

            for fname in files:
                src_file = Path(root) / fname
                rel_path = str(rel_root / fname)

                try:
                    stat = src_file.stat()
                    mtime = stat.st_mtime

                    # Check if file changed since last backup
                    prev_mtime = files_map.get(rel_path, 0.0)
                    if mtime <= prev_mtime:
                        skipped += 1
                        new_files_map[rel_path] = prev_mtime
                        continue

                    # Copy the file
                    dst_file = snapshot_dir / rel_path
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(src_file), str(dst_file))

                    new_files_map[rel_path] = mtime
                    copied += 1
                    bytes_transferred += stat.st_size

                except OSError as e:
                    errors.append(f"Failed to copy {rel_path}: {e}")
                    log.warning("Backup copy error: %s — %s", rel_path, e)

        # If nothing was copied, remove empty snapshot dir
        if copied == 0 and not errors:
            with contextlib.suppress(OSError):
                shutil.rmtree(str(snapshot_dir))

        duration = time.monotonic() - start
        new_manifest = {
            "provider": "local",
            "last_backup": ts,
            "files": new_files_map,
        }

        return BackupResult(
            success=len(errors) == 0,
            files_copied=copied,
            files_skipped=skipped,
            bytes_transferred=bytes_transferred,
            duration_seconds=duration,
            errors=errors,
        ), new_manifest

    def restore(
        self,
        target_dir: Path,
        snapshot: str | None,
    ) -> BackupResult:
        """Restore from a local backup snapshot."""
        start = time.monotonic()
        errors: list[str] = []
        copied = 0
        bytes_transferred = 0

        if snapshot:
            snapshot_dir = self._target_path / snapshot
        else:
            # Find latest snapshot
            snapshots = self.list_snapshots()
            if not snapshots:
                return BackupResult(
                    success=False,
                    files_copied=0,
                    files_skipped=0,
                    bytes_transferred=0,
                    duration_seconds=time.monotonic() - start,
                    errors=["No snapshots found"],
                )
            snapshot_dir = self._target_path / snapshots[0]["id"]

        if not snapshot_dir.exists():
            return BackupResult(
                success=False,
                files_copied=0,
                files_skipped=0,
                bytes_transferred=0,
                duration_seconds=time.monotonic() - start,
                errors=[f"Snapshot not found: {snapshot_dir}"],
            )

        # Copy all files from snapshot to target
        target_dir.mkdir(parents=True, exist_ok=True)
        for root, _dirs, files in os.walk(snapshot_dir):
            rel_root = Path(root).relative_to(snapshot_dir)
            for fname in files:
                src_file = Path(root) / fname
                dst_file = target_dir / rel_root / fname
                try:
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(src_file), str(dst_file))
                    copied += 1
                    bytes_transferred += src_file.stat().st_size
                except OSError as e:
                    errors.append(f"Failed to restore {fname}: {e}")

        return BackupResult(
            success=len(errors) == 0,
            files_copied=copied,
            files_skipped=0,
            bytes_transferred=bytes_transferred,
            duration_seconds=time.monotonic() - start,
            errors=errors,
        )

    def list_snapshots(self) -> list[dict]:
        """List available backup snapshots, newest first."""
        if not self._target_path.exists():
            return []

        snapshots = []
        for entry in sorted(self._target_path.iterdir(), reverse=True):
            if not entry.is_dir():
                continue
            # Count files and total size
            total_size = 0
            file_count = 0
            for root, _dirs, files in os.walk(entry):
                for f in files:
                    total_size += (Path(root) / f).stat().st_size
                    file_count += 1

            snapshots.append({
                "id": entry.name,
                "date": entry.name,
                "files": file_count,
                "size_bytes": total_size,
                "provider": "local",
            })

        return snapshots

    def verify(self) -> bool:
        """Verify local backup integrity (directory exists and readable)."""
        return self._target_path.exists() and self._target_path.is_dir()
