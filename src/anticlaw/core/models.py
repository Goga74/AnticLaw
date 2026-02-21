"""Core data models for AnticLaw."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


# --- Enums ---


class Status(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    PURGED = "purged"


class Importance(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class InsightCategory(str, Enum):
    DECISION = "decision"
    FINDING = "finding"
    PREFERENCE = "preference"
    FACT = "fact"
    QUESTION = "question"


class EdgeType(str, Enum):
    TEMPORAL = "temporal"
    ENTITY = "entity"
    SEMANTIC = "semantic"
    CAUSAL = "causal"


# --- Helpers ---


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# --- Core Models ---


@dataclass
class ChatMessage:
    """A single message in a chat conversation."""

    role: str  # "human" or "assistant"
    content: str
    timestamp: datetime | None = None


@dataclass
class Chat:
    """A complete chat conversation with metadata."""

    id: str = field(default_factory=_uuid)
    title: str = ""
    created: datetime = field(default_factory=_now)
    updated: datetime = field(default_factory=_now)
    provider: str = ""
    remote_id: str = ""
    remote_project_id: str = ""
    model: str = ""
    tags: list[str] = field(default_factory=list)
    summary: str = ""
    token_count: int = 0
    message_count: int = 0
    importance: str = Importance.MEDIUM
    status: str = Status.ACTIVE
    messages: list[ChatMessage] = field(default_factory=list)


@dataclass
class Project:
    """A project (folder) containing chats."""

    name: str = ""
    description: str = ""
    created: datetime = field(default_factory=_now)
    updated: datetime = field(default_factory=_now)
    tags: list[str] = field(default_factory=list)
    status: str = Status.ACTIVE
    providers: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)


@dataclass
class Insight:
    """A knowledge graph node — a saved insight or decision."""

    id: str = field(default_factory=_uuid)
    content: str = ""
    category: str = InsightCategory.FACT
    importance: str = Importance.MEDIUM
    tags: list[str] = field(default_factory=list)
    project_id: str = ""
    chat_id: str | None = None
    created: datetime = field(default_factory=_now)
    updated: datetime = field(default_factory=_now)
    status: str = Status.ACTIVE


@dataclass
class Edge:
    """A knowledge graph edge connecting two insights."""

    id: str = field(default_factory=_uuid)
    source_id: str = ""
    target_id: str = ""
    edge_type: str = EdgeType.SEMANTIC
    weight: float = 1.0
    metadata: dict = field(default_factory=dict)
    created: datetime = field(default_factory=_now)


# --- Provider Models ---


@dataclass
class RemoteProject:
    """A project on a remote LLM platform."""

    id: str = ""
    name: str = ""
    provider: str = ""


@dataclass
class RemoteChat:
    """A chat on a remote LLM platform (summary, no messages)."""

    id: str = ""
    title: str = ""
    provider: str = ""
    project_id: str | None = None
    created: datetime | None = None
    updated: datetime | None = None
    message_count: int = 0


@dataclass
class ChatData:
    """Full chat data exported from a provider, ready for local storage."""

    remote_id: str = ""
    title: str = ""
    provider: str = ""
    remote_project_id: str = ""
    model: str = ""
    created: datetime = field(default_factory=_now)
    updated: datetime = field(default_factory=_now)
    messages: list[ChatMessage] = field(default_factory=list)


@dataclass
class SyncResult:
    """Result of a sync operation between local and remote."""

    provider: str = ""
    pulled: int = 0
    pushed: int = 0
    conflicts: int = 0
    errors: list[str] = field(default_factory=list)
