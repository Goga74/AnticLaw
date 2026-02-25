"""Scraper provider protocol and supporting types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class ScraperInfo:
    """Display metadata for a scraper provider."""

    display_name: str  # "Claude.ai Scraper"
    base_url: str  # "https://claude.ai"
    capabilities: set[str] = field(default_factory=set)  # {"projects", "chat_mapping"}


@dataclass
class ScrapedMapping:
    """Result of a scrape operation: chat→project mapping + project metadata."""

    chats: dict[str, str] = field(default_factory=dict)  # {chat_uuid: project_folder_name}
    projects: dict[str, dict] = field(default_factory=dict)  # {project_uuid: {name, instructions}}
    scraped_at: str = ""  # ISO timestamp


@runtime_checkable
class ScraperProvider(Protocol):
    """Contract for API-based data collection from LLM platforms."""

    @property
    def name(self) -> str:
        """Unique provider ID: 'claude-scraper', 'chatgpt-scraper', etc."""
        ...

    @property
    def info(self) -> ScraperInfo:
        """Display name, base URL, capabilities."""
        ...

    def scrape(self, output: Path) -> ScrapedMapping:
        """Run the scrape and save mapping to output path.

        Returns the scraped mapping data.
        """
        ...
