"""Google Drive backup provider."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from anticlaw.providers.backup.base import BackupInfo, BackupResult

log = logging.getLogger(__name__)

# Directories to skip during backup
_SKIP_DIRS = {".acl", ".git", ".github", "__pycache__"}


def _md5(path: Path) -> str:
    """Compute MD5 hash of a file."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class GDriveBackupProvider:
    """Backup to Google Drive with incremental uploads via MD5 hash."""

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        self._folder_id = config.get("folder_id", "")
        self._credential = config.get("credential", "keyring")
        self._service = None

    @property
    def name(self) -> str:
        return "gdrive"

    @property
    def info(self) -> BackupInfo:
        return BackupInfo(
            display_name="Google Drive",
            version="1.0.0",
            supports_incremental=True,
            supports_restore=True,
            requires_auth=True,
        )

    def _get_service(self):
        """Lazy-initialize the Google Drive API service."""
        if self._service is not None:
            return self._service
        try:
            import keyring
            from googleapiclient.discovery import build

            token_json = keyring.get_password("anticlaw", "gdrive_token")
            if not token_json:
                raise RuntimeError(
                    "No Google Drive token in keyring. "
                    "Run 'aw backup auth gdrive' first."
                )

            from google.oauth2.credentials import Credentials

            creds = Credentials.from_authorized_user_info(json.loads(token_json))
            self._service = build("drive", "v3", credentials=creds)
            return self._service
        except ImportError as e:
            raise RuntimeError(
                f"Google Drive SDK not installed: {e}. "
                "Install with: pip install anticlaw[backup]"
            ) from e

    def auth(self, config: dict) -> bool:
        """Verify Google Drive credentials."""
        try:
            service = self._get_service()
            service.files().list(pageSize=1).execute()
            return True
        except Exception as e:
            log.warning("GDrive auth failed: %s", e)
            return False

    def _ensure_folder(self, service, parent_id: str, name: str) -> str:
        """Find or create a folder in Google Drive. Returns folder ID."""
        query = (
            f"name='{name}' and '{parent_id}' in parents "
            f"and mimeType='application/vnd.google-apps.folder' "
            f"and trashed=false"
        )
        result = service.files().list(q=query, fields="files(id)").execute()
        files = result.get("files", [])
        if files:
            return files[0]["id"]

        metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        folder = service.files().create(body=metadata, fields="id").execute()
        return folder["id"]

    def backup(
        self,
        source_dir: Path,
        manifest: dict | None,
    ) -> tuple[BackupResult, dict]:
        """Run incremental backup to Google Drive."""
        start = time.monotonic()
        manifest = manifest or {}
        hashes = manifest.get("hashes", {})
        file_ids = manifest.get("file_ids", {})
        new_hashes: dict[str, str] = {}
        new_file_ids: dict[str, str] = {}
        errors: list[str] = []
        copied = 0
        skipped = 0
        bytes_transferred = 0

        try:
            service = self._get_service()
        except RuntimeError as e:
            return BackupResult(
                success=False,
                files_copied=0,
                files_skipped=0,
                bytes_transferred=0,
                duration_seconds=time.monotonic() - start,
                errors=[str(e)],
            ), manifest

        # Create timestamped snapshot folder
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        snapshot_folder_id = self._ensure_folder(service, self._folder_id, ts)

        for root, dirs, files in os.walk(source_dir):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            rel_root = Path(root).relative_to(source_dir)

            for fname in files:
                src_file = Path(root) / fname
                rel_path = str(rel_root / fname)

                try:
                    file_hash = _md5(src_file)
                    prev_hash = hashes.get(rel_path)

                    if file_hash == prev_hash:
                        skipped += 1
                        new_hashes[rel_path] = file_hash
                        new_file_ids[rel_path] = file_ids.get(rel_path, "")
                        continue

                    # Ensure parent folder structure in Drive
                    parent_id = snapshot_folder_id
                    parts = rel_root.parts
                    for part in parts:
                        if part == ".":
                            continue
                        parent_id = self._ensure_folder(service, parent_id, part)

                    # Upload file
                    from googleapiclient.http import MediaFileUpload

                    media = MediaFileUpload(str(src_file), resumable=True)
                    metadata = {"name": fname, "parents": [parent_id]}
                    uploaded = service.files().create(
                        body=metadata, media_body=media, fields="id"
                    ).execute()

                    new_hashes[rel_path] = file_hash
                    new_file_ids[rel_path] = uploaded["id"]
                    copied += 1
                    bytes_transferred += src_file.stat().st_size

                except Exception as e:
                    errors.append(f"Failed to upload {rel_path}: {e}")
                    log.warning("GDrive upload error: %s — %s", rel_path, e)

        duration = time.monotonic() - start
        new_manifest = {
            "provider": "gdrive",
            "last_backup": ts,
            "folder_id": self._folder_id,
            "hashes": new_hashes,
            "file_ids": new_file_ids,
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
        """Restore from a Google Drive backup snapshot."""
        start = time.monotonic()
        errors: list[str] = []
        copied = 0
        bytes_transferred = 0

        try:
            service = self._get_service()
        except RuntimeError as e:
            return BackupResult(
                success=False,
                files_copied=0,
                files_skipped=0,
                bytes_transferred=0,
                duration_seconds=time.monotonic() - start,
                errors=[str(e)],
            )

        # Find the snapshot folder
        if snapshot:
            query = (
                f"name='{snapshot}' and '{self._folder_id}' in parents "
                f"and mimeType='application/vnd.google-apps.folder' and trashed=false"
            )
        else:
            # Find latest
            query = (
                f"'{self._folder_id}' in parents "
                f"and mimeType='application/vnd.google-apps.folder' and trashed=false"
            )

        result = service.files().list(
            q=query, orderBy="name desc", fields="files(id,name)", pageSize=1,
        ).execute()
        folders = result.get("files", [])
        if not folders:
            return BackupResult(
                success=False,
                files_copied=0,
                files_skipped=0,
                bytes_transferred=0,
                duration_seconds=time.monotonic() - start,
                errors=["No snapshot found on Google Drive"],
            )

        snapshot_folder_id = folders[0]["id"]
        target_dir.mkdir(parents=True, exist_ok=True)

        # Recursively download files
        copied, bytes_transferred, errors = self._download_folder(
            service, snapshot_folder_id, target_dir,
        )

        return BackupResult(
            success=len(errors) == 0,
            files_copied=copied,
            files_skipped=0,
            bytes_transferred=bytes_transferred,
            duration_seconds=time.monotonic() - start,
            errors=errors,
        )

    def _download_folder(
        self, service, folder_id: str, local_dir: Path,
    ) -> tuple[int, int, list[str]]:
        """Recursively download folder contents."""
        copied = 0
        bytes_total = 0
        errors: list[str] = []

        query = f"'{folder_id}' in parents and trashed=false"
        result = service.files().list(
            q=query, fields="files(id,name,mimeType,size)",
        ).execute()

        for item in result.get("files", []):
            if item["mimeType"] == "application/vnd.google-apps.folder":
                sub_dir = local_dir / item["name"]
                sub_dir.mkdir(parents=True, exist_ok=True)
                c, b, e = self._download_folder(service, item["id"], sub_dir)
                copied += c
                bytes_total += b
                errors.extend(e)
            else:
                try:
                    request = service.files().get_media(fileId=item["id"])
                    content = request.execute()
                    dest = local_dir / item["name"]
                    dest.write_bytes(content)
                    copied += 1
                    bytes_total += len(content)
                except Exception as e:
                    errors.append(f"Download failed: {item['name']}: {e}")

        return copied, bytes_total, errors

    def list_snapshots(self) -> list[dict]:
        """List available backup snapshots on Google Drive."""
        try:
            service = self._get_service()
        except RuntimeError:
            return []

        query = (
            f"'{self._folder_id}' in parents "
            f"and mimeType='application/vnd.google-apps.folder' "
            f"and trashed=false"
        )
        result = service.files().list(
            q=query, orderBy="name desc", fields="files(id,name,createdTime)",
        ).execute()

        snapshots = []
        for item in result.get("files", []):
            snapshots.append({
                "id": item["name"],
                "date": item.get("createdTime", item["name"]),
                "provider": "gdrive",
                "drive_id": item["id"],
            })

        return snapshots

    def verify(self) -> bool:
        """Verify Google Drive backup folder exists and is accessible."""
        try:
            service = self._get_service()
            service.files().get(fileId=self._folder_id).execute()
            return True
        except Exception:
            return False
