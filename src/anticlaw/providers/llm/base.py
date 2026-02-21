"""LLM Provider protocol and supporting types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from anticlaw.core.models import ChatData, RemoteChat, RemoteProject, SyncResult


class Capability(str, Enum):
    """Capabilities an LLM provider may support."""

    EXPORT_BULK = "export_bulk"  # parse official data export (ZIP/JSON)
    EXPORT_SINGLE = "export_single"  # export one chat by ID
    IMPORT = "import"  # push chats to platform
    LIST_PROJECTS = "list_projects"  # enumerate remote projects
    LIST_CHATS = "list_chats"  # enumerate remote chats
    SYNC = "sync"  # bidirectional sync
    SCRAPE = "scrape"  # browser scraper for supplementary data


@dataclass
class ProviderInfo:
    """Display metadata and capabilities for a provider."""

    display_name: str
    version: str
    capabilities: set[str] = field(default_factory=set)


@runtime_checkable
class LLMProvider(Protocol):
    """Contract for LLM platform integration."""

    @property
    def name(self) -> str:
        """Unique provider ID: 'claude', 'chatgpt', 'gemini', 'ollama'."""
        ...

    @property
    def info(self) -> ProviderInfo:
        """Display name, version, capabilities."""
        ...

    def auth(self, config: dict) -> bool:
        """Verify credentials / connectivity."""
        ...

    def list_projects(self) -> list[RemoteProject]:
        """List all projects on the remote platform."""
        ...

    def list_chats(self, project_id: str | None = None) -> list[RemoteChat]:
        """List chats, optionally filtered by project."""
        ...

    def export_chat(self, chat_id: str) -> ChatData:
        """Export a single chat with all messages."""
        ...

    def export_all(self, output_dir: Path) -> int:
        """Bulk export from official data dump. Returns count."""
        ...

    def import_chat(self, project_id: str | None, chat: ChatData) -> str:
        """Push a chat to the remote platform. Returns remote chat ID."""
        ...

    def sync(
        self,
        local_project: Path,
        remote_project_id: str,
        direction: str = "pull",
    ) -> SyncResult:
        """Sync between local folder and remote project."""
        ...
