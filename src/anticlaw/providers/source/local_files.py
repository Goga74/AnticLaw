"""LocalFilesProvider — scan and index local files."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from anticlaw.core.models import SourceDocument
from anticlaw.providers.source.base import SourceInfo

log = logging.getLogger(__name__)

# Extension → language mapping
_EXTENSION_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".java": "java",
    ".js": "javascript",
    ".ts": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".sql": "sql",
    ".sh": "shell",
    ".rb": "ruby",
    ".cpp": "cpp",
    ".c": "c",
    ".cs": "csharp",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".r": "r",
    ".lua": "lua",
    ".pl": "perl",
}

_TEXT_EXTENSIONS: set[str] = {
    ".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml", ".toml",
    ".properties", ".ini", ".cfg", ".conf", ".env.example",
    ".html", ".htm", ".css", ".scss", ".less",
    ".log", ".rst", ".tex", ".dockerfile",
}

_ALL_TEXT_EXTENSIONS = _TEXT_EXTENSIONS | set(_EXTENSION_LANGUAGE.keys())

DEFAULT_EXCLUDE_PATTERNS: list[str] = [
    "node_modules", ".git", "__pycache__", "target", "build", "dist",
    ".idea", ".vscode", ".acl", "_archive", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "venv", ".venv", ".env",
]

DEFAULT_MAX_FILE_SIZE_MB: int = 10

DEFAULT_EXTENSIONS: list[str] = sorted(
    list(_ALL_TEXT_EXTENSIONS) + [".pdf"]
)


def _file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file for change detection."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _read_text_file(path: Path) -> str:
    """Read a text file with fallback encoding."""
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, ValueError):
            continue
    return ""


def _read_pdf(path: Path) -> str:
    """Read PDF via pymupdf with graceful fallback."""
    try:
        import pymupdf

        doc = pymupdf.open(str(path))
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        return "\n".join(pages)
    except ImportError:
        log.debug("pymupdf not available, skipping PDF: %s", path)
        return ""
    except Exception:
        log.warning("Failed to read PDF: %s", path, exc_info=True)
        return ""


def _should_exclude(path: Path, exclude_patterns: list[str]) -> bool:
    """Check if a path matches any exclude pattern."""
    parts = path.parts
    return any(pattern in parts for pattern in exclude_patterns)


def _detect_language(ext: str) -> str:
    """Detect programming language from extension."""
    return _EXTENSION_LANGUAGE.get(ext, "")


class LocalFilesProvider:
    """Scans local directories, reads text/code/PDF files for indexing."""

    def __init__(
        self,
        *,
        extensions: list[str] | None = None,
        exclude: list[str] | None = None,
        max_file_size_mb: int = DEFAULT_MAX_FILE_SIZE_MB,
    ) -> None:
        self._extensions = set(extensions or DEFAULT_EXTENSIONS)
        self._exclude = exclude or DEFAULT_EXCLUDE_PATTERNS
        self._max_bytes = max_file_size_mb * 1024 * 1024

    @property
    def name(self) -> str:
        return "local-files"

    @property
    def info(self) -> SourceInfo:
        return SourceInfo(
            display_name="Local Files",
            version="1.0.0",
            supported_extensions=sorted(self._extensions),
            is_local=True,
        )

    def scan(self, paths: list[Path], **filters) -> list[SourceDocument]:
        """Recursively scan directories and return indexable documents."""
        documents: list[SourceDocument] = []
        for base_path in paths:
            base_path = Path(base_path).expanduser().resolve()
            if not base_path.exists():
                log.warning("Scan path does not exist: %s", base_path)
                continue
            if base_path.is_file():
                doc = self.read(base_path)
                if doc.content:
                    documents.append(doc)
                continue
            for file_path in self._walk(base_path):
                doc = self.read(file_path)
                if doc.content:
                    documents.append(doc)
        return documents

    def read(self, path: Path) -> SourceDocument:
        """Read a single file and return a SourceDocument."""
        path = Path(path).resolve()
        ext = path.suffix.lower()
        size = path.stat().st_size if path.exists() else 0

        if size > self._max_bytes:
            log.debug("Skipping large file (%d bytes): %s", size, path)
            return SourceDocument(file_path=str(path), filename=path.name, extension=ext, size=size)

        if ext == ".pdf":
            content = _read_pdf(path)
        elif ext in _ALL_TEXT_EXTENSIONS:
            content = _read_text_file(path)
        else:
            content = _read_text_file(path)

        language = _detect_language(ext)
        file_hash = _file_hash(path)

        return SourceDocument(
            file_path=str(path),
            filename=path.name,
            extension=ext,
            language=language,
            content=content,
            size=size,
            hash=file_hash,
            indexed_at=datetime.now(timezone.utc),
        )

    def watch(self, paths: list[Path], callback: Callable) -> None:
        """Watch for changes. Delegates to daemon watcher (not implemented here)."""
        raise NotImplementedError("Use daemon watcher for file monitoring")

    def _walk(self, base: Path) -> list[Path]:
        """Walk a directory tree, respecting exclude patterns and extensions."""
        results: list[Path] = []
        try:
            for item in sorted(base.iterdir()):
                if _should_exclude(item, self._exclude):
                    continue
                if item.is_dir():
                    # Skip hidden directories
                    if item.name.startswith("."):
                        continue
                    results.extend(self._walk(item))
                elif item.is_file():
                    ext = item.suffix.lower()
                    if ext in self._extensions:
                        results.append(item)
        except PermissionError:
            log.debug("Permission denied: %s", base)
        return results
