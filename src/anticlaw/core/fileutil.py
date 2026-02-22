"""File system utilities: atomic writes, safe names, permissions, locking."""

from __future__ import annotations

import contextlib
import logging
import os
import platform
import re
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)

FILE_MODE = 0o600
DIR_MODE = 0o700

_IS_WINDOWS = platform.system() == "Windows"


def safe_filename(title: str, max_length: int = 200) -> str:
    """Convert a title to a safe filename slug.

    Strips path traversal, special characters, and limits length.
    """
    # Normalize unicode
    name = title.strip()
    # Remove path traversal
    name = name.replace("..", "").replace("/", "-").replace("\\", "-")
    # Keep only safe chars: alphanumeric, hyphen, underscore, dot, space
    name = re.sub(r"[^\w\s\-.]", "", name)
    # Collapse whitespace / hyphens
    name = re.sub(r"[\s]+", "-", name)
    name = re.sub(r"-+", "-", name)
    # Strip leading/trailing hyphens and dots
    name = name.strip("-.")
    # Lowercase
    name = name.lower()
    # Truncate
    if len(name) > max_length:
        name = name[:max_length].rstrip("-.")
    # Fallback for empty result
    if not name:
        name = "untitled"
    return name


def ensure_dir(path: Path) -> Path:
    """Create directory with secure permissions if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)
    if not _IS_WINDOWS:
        path.chmod(DIR_MODE)
    return path


def ensure_file_permissions(path: Path) -> None:
    """Set file permissions to owner-only read/write."""
    if not _IS_WINDOWS and path.exists():
        path.chmod(FILE_MODE)


def atomic_write(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write content to file atomically via temp file + rename.

    Ensures the file is never partially written on crash.
    """
    ensure_dir(path.parent)

    # Write to temp file in the same directory (so rename is atomic on same FS)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=".tmp_",
        suffix=path.suffix,
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        # Atomic replace
        _replace(tmp_path, path)
    except BaseException:
        # Clean up temp file on failure
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise

    ensure_file_permissions(path)


def _replace(src: str, dst: Path) -> None:
    """Cross-platform atomic replace."""
    os.replace(src, dst)


@contextmanager
def file_lock(path: Path) -> Generator[None, None, None]:
    """Cross-platform advisory file lock.

    Uses fcntl.flock on Unix, msvcrt.locking on Windows.
    """
    lock_path = path.parent / f".{path.name}.lock"
    ensure_dir(lock_path.parent)

    if _IS_WINDOWS:
        yield from _windows_lock(lock_path)
    else:
        yield from _unix_lock(lock_path)


def _unix_lock(lock_path: Path) -> Generator[None, None, None]:
    import fcntl

    with open(lock_path, "w") as fd:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    with contextlib.suppress(OSError):
        lock_path.unlink()


def _windows_lock(lock_path: Path) -> Generator[None, None, None]:
    import msvcrt

    with open(lock_path, "w") as fd:
        try:
            msvcrt.locking(fd.fileno(), msvcrt.LK_LOCK, 1)
            yield
        finally:
            with contextlib.suppress(OSError):
                msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
    with contextlib.suppress(OSError):
        lock_path.unlink()
