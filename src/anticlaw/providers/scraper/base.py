"""ScraperProvider Protocol and supporting types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class ScraperInfo:
    """Metadata about a scraper provider."""

    display_name: str
    version: str
    requires_auth: bool = True
    requires_browser: bool = True


@dataclass
class ScrapedProject:
    """Project metadata collected by a scraper."""

    uuid: str
    name: str
    description: str = ""
    prompt_template: str = ""
    chat_uuids: list[str] = field(default_factory=list)


@runtime_checkable
class ScraperProvider(Protocol):
    """Contract for browser-based data collection.

    Implementations: ClaudeScraper, future ChatGPTScraper, etc.
    """

    @property
    def name(self) -> str:
        """Unique provider ID: 'claude-scraper', 'chatgpt-scraper', etc."""
        ...

    @property
    def info(self) -> ScraperInfo:
        """Provider metadata."""
        ...

    def scrape(self, output: Path | None = None) -> dict[str, str]:
        """Run scraper and return {chat_uuid: project_name} mapping.

        Args:
            output: Optional path to save mapping.json.

        Returns:
            Dict mapping chat UUIDs to project names.
        """
        ...
