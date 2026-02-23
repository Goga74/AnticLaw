"""InputProvider Protocol and types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class InputInfo:
    """Metadata about an input provider."""

    display_name: str
    version: str
    supported_languages: list[str] = field(default_factory=list)
    is_local: bool = True
    requires_hardware: bool = False


@runtime_checkable
class InputProvider(Protocol):
    """Contract for query input methods.

    Implementations: WhisperInputProvider (voice), future Alexa, etc.
    """

    @property
    def name(self) -> str:
        """Unique provider ID: 'whisper', 'alexa', etc."""
        ...

    @property
    def info(self) -> InputInfo:
        """Provider metadata."""
        ...

    def listen(self) -> str:
        """Get input from user. Returns query text."""
        ...

    def respond(self, text: str) -> None:
        """Send response back to user (text, voice, etc.)."""
        ...

    def is_available(self) -> bool:
        """Check if hardware/dependencies are available."""
        ...
