"""SourceProvider Protocol and types."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from anticlaw.core.models import SourceDocument


@dataclass
class SourceInfo:
    """Metadata about a source provider."""

    display_name: str
    version: str
    supported_extensions: list[str] = field(default_factory=list)
    is_local: bool = True


@runtime_checkable
class SourceProvider(Protocol):
    """Contract for content source integration."""

    @property
    def name(self) -> str:
        """Unique provider ID: 'local-files', 'obsidian', etc."""
        ...

    @property
    def info(self) -> SourceInfo:
        """Provider metadata."""
        ...

    def scan(self, paths: list[Path], **filters) -> list[SourceDocument]:
        """Scan paths, return indexable documents."""
        ...

    def read(self, path: Path) -> SourceDocument:
        """Read a single document."""
        ...

    def watch(self, paths: list[Path], callback: Callable) -> None:
        """Watch for changes (integrates with daemon watcher)."""
        ...
