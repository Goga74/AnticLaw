"""Claude.ai provider: parse official data export into ChatData."""

from __future__ import annotations

import json
import logging
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from anticlaw.core.models import ChatData, ChatMessage, RemoteChat, RemoteProject, SyncResult
from anticlaw.providers.llm.base import Capability, ProviderInfo

log = logging.getLogger(__name__)

# --- Secret scrubbing patterns ---

_SCRUB_PATTERNS: list[tuple[re.Pattern, str]] = [
    # API keys
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "[REDACTED:api_key]"),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "[REDACTED:api_key]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9_.\-/+=]{20,}"), "[REDACTED:bearer_token]"),
    (re.compile(r"ghp_[A-Za-z0-9]{36,}"), "[REDACTED:github_token]"),
    (re.compile(r"gho_[A-Za-z0-9]{36,}"), "[REDACTED:github_token]"),
    (re.compile(r"AKIA[A-Z0-9]{16}"), "[REDACTED:aws_key]"),
    # Private keys
    (re.compile(r"-----BEGIN\s+[\w\s]*PRIVATE KEY-----"), "[REDACTED:private_key]"),
    # Connection strings
    (
        re.compile(r"(?:postgres|mysql|mongodb)://[^\s\"'`]+:[^\s\"'`]+@[^\s\"'`]+"),
        "[REDACTED:connection_string]",
    ),
    # Generic token/secret/password in assignments
    (
        re.compile(r"(?:password|passwd|token|secret|api_key)\s*[=:]\s*[\"']?[^\s\"']{8,}[\"']?", re.IGNORECASE),
        "[REDACTED:credential]",
    ),
]


def scrub_text(text: str) -> str:
    """Remove secrets from text using known patterns."""
    for pattern, replacement in _SCRUB_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class ClaudeProvider:
    """Claude.ai LLM provider — parses official data exports."""

    @property
    def name(self) -> str:
        return "claude"

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            display_name="Claude.ai",
            version="1.0.0",
            capabilities={Capability.EXPORT_BULK, Capability.SCRAPE},
        )

    def auth(self, config: dict) -> bool:
        return True  # export-based, no auth needed

    def list_projects(self) -> list[RemoteProject]:
        return []  # not available from export

    def list_chats(self, project_id: str | None = None) -> list[RemoteChat]:
        return []  # not available from export

    def export_chat(self, chat_id: str) -> ChatData:
        raise NotImplementedError("Single chat export not supported for Claude")

    def import_chat(self, project_id: str | None, chat: ChatData) -> str:
        raise NotImplementedError("Claude.ai has no import API")

    def export_all(self, output_dir: Path) -> int:
        raise NotImplementedError("Use parse_export_zip() instead")

    def sync(
        self,
        local_project: Path,
        remote_project_id: str,
        direction: str = "pull",
    ) -> SyncResult:
        raise NotImplementedError("Sync not supported for Claude")

    # --- Export parsing (the main capability) ---

    def parse_export_zip(
        self,
        zip_path: Path,
        scrub: bool = False,
    ) -> list[ChatData]:
        """Extract and parse conversations.json from a Claude export ZIP.

        Args:
            zip_path: Path to the Claude export ZIP file.
            scrub: If True, redact detected secrets from message content.

        Returns:
            List of ChatData ready for local storage.
        """
        raw_json = _extract_conversations_json(zip_path)
        conversations = json.loads(raw_json)

        if not isinstance(conversations, list):
            raise ValueError("Expected a JSON array of conversations")

        chats: list[ChatData] = []
        for conv in conversations:
            try:
                chat_data = _parse_conversation(conv, scrub=scrub)
                chats.append(chat_data)
            except Exception:
                uuid = conv.get("uuid", "unknown")
                log.warning("Failed to parse conversation %s", uuid, exc_info=True)

        log.info("Parsed %d conversations from %s", len(chats), zip_path.name)
        return chats

    def load_project_mapping(self, mapping_path: Path) -> dict[str, str]:
        """Load a chat_uuid → project_name mapping from JSON file.

        This file is typically produced by the Playwright scraper.
        """
        raw = mapping_path.read_text(encoding="utf-8")
        mapping = json.loads(raw)
        if not isinstance(mapping, dict):
            raise ValueError("Project mapping must be a JSON object {uuid: project_name}")
        return mapping


def _extract_conversations_json(zip_path: Path) -> str:
    """Extract conversations.json from a Claude export ZIP."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        # Try common locations
        for candidate in ["conversations.json", "claude/conversations.json"]:
            if candidate in zf.namelist():
                return zf.read(candidate).decode("utf-8")

        # Fallback: find any conversations.json
        for name in zf.namelist():
            if name.endswith("conversations.json"):
                return zf.read(name).decode("utf-8")

    raise FileNotFoundError(
        f"No conversations.json found in {zip_path.name}. "
        f"Expected a Claude.ai data export ZIP."
    )


def _parse_conversation(conv: dict, scrub: bool = False) -> ChatData:
    """Parse a single conversation dict from Claude's conversations.json."""
    uuid = conv.get("uuid", "")
    title = conv.get("name", "") or "Untitled"
    created_at = _parse_timestamp(conv.get("created_at"))
    updated_at = _parse_timestamp(conv.get("updated_at")) or created_at

    # Parse messages
    raw_messages = conv.get("chat_messages", [])
    messages: list[ChatMessage] = []
    for msg in raw_messages:
        role = _normalize_role(msg.get("sender", ""))
        if not role:
            continue

        # Content can be "text" field or nested in "content" array
        content = _extract_content(msg)
        if not content:
            continue

        if scrub:
            content = scrub_text(content)

        timestamp = _parse_timestamp(msg.get("created_at"))

        messages.append(ChatMessage(role=role, content=content, timestamp=timestamp))

    return ChatData(
        remote_id=uuid,
        title=title,
        provider="claude",
        model=conv.get("model", ""),
        created=created_at,
        updated=updated_at,
        messages=messages,
    )


def _normalize_role(sender: str) -> str:
    """Map Claude's sender names to our standard roles."""
    sender = sender.lower().strip()
    if sender in ("human", "user"):
        return "human"
    if sender in ("assistant", "ai"):
        return "assistant"
    return ""


def _extract_content(msg: dict) -> str:
    """Extract text content from a Claude message.

    Claude messages may have:
    - "text": "..." (simple)
    - "content": [{"type": "text", "text": "..."}] (structured)
    """
    # Simple text field
    text = msg.get("text")
    if text:
        return text.strip()

    # Structured content array
    content_arr = msg.get("content")
    if isinstance(content_arr, list):
        parts = []
        for block in content_arr:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        result = "\n".join(parts).strip()
        if result:
            return result

    # Content as plain string
    content_str = msg.get("content")
    if isinstance(content_str, str):
        return content_str.strip()

    return ""


def _parse_timestamp(value: str | None) -> datetime:
    """Parse an ISO timestamp from Claude's export."""
    if not value:
        return datetime.now(timezone.utc)
    try:
        # Handle "2025-02-18T14:30:00.000Z" and similar
        cleaned = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)
