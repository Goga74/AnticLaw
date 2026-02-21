"""Central registry for all provider types (LLM, Backup, Embedding)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class ProviderEntry:
    """Metadata about a registered provider."""

    family: str  # "llm", "backup", "embedding"
    name: str  # "claude", "gdrive", "ollama"
    cls: type  # The provider class
    extras: list[str] = field(default_factory=list)  # pip extras needed


class ProviderRegistry:
    """Central registry for all provider types."""

    def __init__(self) -> None:
        self._providers: dict[str, dict[str, ProviderEntry]] = {}

    def register(
        self,
        family: str,
        name: str,
        cls: type,
        extras: list[str] | None = None,
    ) -> None:
        """Register a provider class under a family."""
        self._providers.setdefault(family, {})[name] = ProviderEntry(
            family=family, name=name, cls=cls, extras=extras or []
        )
        log.debug("Registered provider: %s/%s", family, name)

    def get(self, family: str, name: str, config: dict | None = None) -> object:
        """Instantiate a provider by family and name."""
        fam = self._providers.get(family)
        if fam is None:
            raise KeyError(f"Unknown provider family: {family!r}")
        entry = fam.get(name)
        if entry is None:
            raise KeyError(f"Unknown provider: {family}/{name!r}")
        if config is not None:
            return entry.cls(config)
        return entry.cls()

    def get_entry(self, family: str, name: str) -> ProviderEntry:
        """Get a ProviderEntry without instantiating."""
        fam = self._providers.get(family)
        if fam is None:
            raise KeyError(f"Unknown provider family: {family!r}")
        entry = fam.get(name)
        if entry is None:
            raise KeyError(f"Unknown provider: {family}/{name!r}")
        return entry

    def list_family(self, family: str) -> list[ProviderEntry]:
        """List all providers in a family."""
        return list(self._providers.get(family, {}).values())

    def list_all(self) -> list[ProviderEntry]:
        """List all registered providers across all families."""
        return [entry for fam in self._providers.values() for entry in fam.values()]

    def families(self) -> list[str]:
        """List all registered family names."""
        return list(self._providers.keys())


# Global singleton
registry = ProviderRegistry()
