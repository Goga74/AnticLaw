"""Retention lifecycle: 3-zone model (active -> archive -> purge)."""

from __future__ import annotations

import gzip
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from anticlaw.core.config import load_config
from anticlaw.core.meta_db import MetaDB
from anticlaw.core.models import Importance

log = logging.getLogger(__name__)


def _normalize_status(s: str) -> str:
    """Normalize status strings like 'Status.ACTIVE' to 'active'."""
    if not s:
        return "active"
    s_lower = s.lower()
    for status in ("active", "archived", "purged"):
        if status in s_lower:
            return status
    return s_lower


@dataclass
class RetentionAction:
    """A single retention action (archive or purge) to be performed."""

    chat_id: str
    title: str
    file_path: str
    project_id: str
    action: str  # "archive" or "purge"
    reason: str
    days_inactive: int


@dataclass
class RetentionResult:
    """Result of a retention run."""

    archived: int = 0
    purged: int = 0
    errors: list[str] = field(default_factory=list)
    actions: list[RetentionAction] = field(default_factory=list)


def importance_decay(
    base_importance: str,
    days_since_update: float,
    half_life_days: float = 30.0,
) -> str:
    """Calculate decayed importance based on time since last update.

    Uses exponential decay: effective_score = base_score * 0.5^(days/half_life).
    Returns the importance level corresponding to the decayed score.

    Args:
        base_importance: Original importance level (low/medium/high/critical).
        days_since_update: Days since the chat was last updated.
        half_life_days: Half-life in days (default 30).

    Returns:
        Decayed importance level string.
    """
    scores = {
        Importance.LOW: 1.0,
        Importance.MEDIUM: 2.0,
        Importance.HIGH: 3.0,
        Importance.CRITICAL: 4.0,
        "low": 1.0,
        "medium": 2.0,
        "high": 3.0,
        "critical": 4.0,
    }
    base_score = scores.get(base_importance, 2.0)

    if half_life_days <= 0:
        half_life_days = 30.0

    decay_factor = math.pow(0.5, days_since_update / half_life_days)
    decayed_score = base_score * decay_factor

    if decayed_score >= 3.5:
        return Importance.CRITICAL
    elif decayed_score >= 2.5:
        return Importance.HIGH
    elif decayed_score >= 1.5:
        return Importance.MEDIUM
    else:
        return Importance.LOW


def preview_retention(
    home: Path,
    *,
    archive_days: int | None = None,
    purge_days: int | None = None,
) -> RetentionResult:
    """Dry-run: determine what would be archived or purged.

    Args:
        home: ACL_HOME path.
        archive_days: Override config archive_days threshold.
        purge_days: Override config purge_days threshold.

    Returns:
        RetentionResult with actions list but no changes made.
    """
    config = load_config(home / ".acl" / "config.yaml")
    retention_cfg = config.get("retention", {})
    if archive_days is None:
        archive_days = retention_cfg.get("archive_days", 30)
    if purge_days is None:
        purge_days = retention_cfg.get("purge_days", 180)

    now = datetime.now(timezone.utc)
    db_path = home / ".acl" / "meta.db"
    if not db_path.exists():
        return RetentionResult()

    db = MetaDB(db_path)
    result = RetentionResult()
    try:
        chats = db.list_chats()
        for chat_row in chats:
            status = _normalize_status(chat_row.get("status", "active"))
            updated_str = chat_row.get("updated", "")
            if not updated_str:
                continue

            try:
                updated = datetime.fromisoformat(
                    updated_str.replace("Z", "+00:00")
                )
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            days_inactive = (now - updated).days

            file_path = chat_row.get("file_path", "")

            if status == "archived" and days_inactive >= purge_days:
                action = RetentionAction(
                    chat_id=chat_row["id"],
                    title=chat_row.get("title", ""),
                    file_path=file_path,
                    project_id=chat_row.get("project_id", ""),
                    action="purge",
                    reason=f"Archived for {days_inactive} days (threshold: {purge_days})",
                    days_inactive=days_inactive,
                )
                result.actions.append(action)

            elif status == "active" and days_inactive >= archive_days:
                # Don't archive critical items
                importance = chat_row.get("importance", "medium")
                if importance == "critical":
                    continue
                action = RetentionAction(
                    chat_id=chat_row["id"],
                    title=chat_row.get("title", ""),
                    file_path=file_path,
                    project_id=chat_row.get("project_id", ""),
                    action="archive",
                    reason=f"Inactive for {days_inactive} days (threshold: {archive_days})",
                    days_inactive=days_inactive,
                )
                result.actions.append(action)
    finally:
        db.close()

    return result


def run_retention(
    home: Path,
    *,
    archive_days: int | None = None,
    purge_days: int | None = None,
) -> RetentionResult:
    """Execute retention: move stale chats to _archive/, purge old archives.

    Archive: moves file to _archive/, compresses with gzip, updates meta.db status.
    Purge: deletes archived file, logs deletion in meta.db.

    Args:
        home: ACL_HOME path.
        archive_days: Override config archive_days threshold.
        purge_days: Override config purge_days threshold.

    Returns:
        RetentionResult with counts and any errors.
    """
    preview = preview_retention(home, archive_days=archive_days, purge_days=purge_days)
    if not preview.actions:
        return RetentionResult()

    db_path = home / ".acl" / "meta.db"
    db = MetaDB(db_path)
    archive_dir = home / "_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    result = RetentionResult()
    try:
        for action in preview.actions:
            try:
                if action.action == "archive":
                    _archive_chat(home, db, action, archive_dir)
                    result.archived += 1
                elif action.action == "purge":
                    _purge_chat(db, action)
                    result.purged += 1
                result.actions.append(action)
            except Exception as e:
                msg = f"Failed to {action.action} {action.chat_id}: {e}"
                log.warning(msg)
                result.errors.append(msg)
    finally:
        db.close()

    return result


def _archive_chat(
    home: Path, db: MetaDB, action: RetentionAction, archive_dir: Path
) -> None:
    """Move a chat to _archive/ and compress it."""
    src = Path(action.file_path)
    if not src.exists():
        log.warning("File not found for archival: %s", src)
        return

    # Compress file with gzip
    dst = archive_dir / (src.name + ".gz")
    counter = 1
    while dst.exists():
        dst = archive_dir / f"{src.stem}_{counter}{src.suffix}.gz"
        counter += 1

    content = src.read_bytes()
    with gzip.open(str(dst), "wb") as f:
        f.write(content)

    # Remove original
    src.unlink()

    # Update meta.db: status -> archived, file_path -> new location
    db.conn.execute(
        "UPDATE chats SET status = ?, file_path = ? WHERE id = ?",
        ("archived", str(dst), action.chat_id),
    )
    db.conn.commit()
    log.info("Archived chat %s → %s", action.chat_id, dst)


def _purge_chat(db: MetaDB, action: RetentionAction) -> None:
    """Delete an archived chat file and mark as purged in meta.db."""
    file_path = Path(action.file_path)
    if file_path.exists():
        file_path.unlink()

    # Update meta.db status -> purged (keep record for audit trail)
    db.conn.execute(
        "UPDATE chats SET status = ? WHERE id = ?",
        ("purged", action.chat_id),
    )
    db.conn.commit()
    log.info("Purged chat %s", action.chat_id)


def restore(home: Path, chat_id: str) -> Path | None:
    """Restore an archived chat back to its original project.

    Decompresses the gzipped file and moves it back to the project directory.

    Args:
        home: ACL_HOME path.
        chat_id: ID of the chat to restore.

    Returns:
        Path to the restored file, or None if not found/not archived.
    """
    db_path = home / ".acl" / "meta.db"
    if not db_path.exists():
        return None

    db = MetaDB(db_path)
    try:
        chat_row = _resolve_chat(db, chat_id)
        if not chat_row:
            log.warning("Chat not found: %s", chat_id)
            return None

        if _normalize_status(chat_row.get("status", "")) != "archived":
            log.warning("Chat %s is not archived (status: %s)", chat_id, chat_row.get("status"))
            return None

        archived_path = Path(chat_row["file_path"])
        if not archived_path.exists():
            log.warning("Archived file not found: %s", archived_path)
            return None

        # Determine target directory
        project_id = chat_row.get("project_id", "_inbox")
        target_dir = (
            home / project_id if project_id and project_id != "_inbox"
            else home / "_inbox"
        )
        target_dir.mkdir(parents=True, exist_ok=True)

        # Decompress
        original_name = archived_path.name
        if original_name.endswith(".gz"):
            original_name = original_name[:-3]

        target_path = target_dir / original_name
        counter = 1
        while target_path.exists():
            stem = Path(original_name).stem
            suffix = Path(original_name).suffix
            target_path = target_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        with gzip.open(str(archived_path), "rb") as f:
            content = f.read()
        target_path.write_bytes(content)

        # Remove archive file
        archived_path.unlink()

        # Update meta.db
        db.conn.execute(
            "UPDATE chats SET status = ?, file_path = ?, project_id = ? WHERE id = ?",
            ("active", str(target_path), project_id, chat_row["id"]),
        )
        db.conn.commit()
        log.info("Restored chat %s → %s", chat_id, target_path)
        return target_path
    finally:
        db.close()


def _resolve_chat(db: MetaDB, chat_id: str) -> dict | None:
    """Resolve a chat by full or partial (prefix) ID."""
    chat = db.get_chat(chat_id)
    if chat:
        return chat
    rows = db.conn.execute(
        "SELECT * FROM chats WHERE id LIKE ? LIMIT 2",
        (f"{chat_id}%",),
    ).fetchall()
    if len(rows) == 1:
        return dict(rows[0])
    return None
