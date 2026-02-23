"""Gemini provider: parse Google Takeout Gemini export into ChatData."""

from __future__ import annotations

import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from anticlaw.core.models import ChatData, ChatMessage, RemoteChat, RemoteProject, SyncResult
from anticlaw.providers.llm.base import Capability, ProviderInfo
from anticlaw.providers.llm.claude import scrub_text

log = logging.getLogger(__name__)


class GeminiProvider:
    """Gemini LLM provider — parses Google Takeout Gemini exports."""

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            display_name="Gemini",
            version="1.0.0",
            capabilities={Capability.EXPORT_BULK},
        )

    def auth(self, config: dict) -> bool:
        return True  # export-based, no auth needed

    def list_projects(self) -> list[RemoteProject]:
        return []  # not available from export

    def list_chats(self, project_id: str | None = None) -> list[RemoteChat]:
        return []  # not available from export

    def export_chat(self, chat_id: str) -> ChatData:
        raise NotImplementedError("Single chat export not supported for Gemini")

    def import_chat(self, project_id: str | None, chat: ChatData) -> str:
        raise NotImplementedError("Gemini has no import API")

    def export_all(self, output_dir: Path) -> int:
        raise NotImplementedError("Use parse_takeout_zip() instead")

    def sync(
        self,
        local_project: Path,
        remote_project_id: str,
        direction: str = "pull",
    ) -> SyncResult:
        raise NotImplementedError("Sync not supported for Gemini")

    # --- Export parsing (the main capability) ---

    def parse_takeout_zip(
        self,
        zip_path: Path,
        scrub: bool = False,
    ) -> list[ChatData]:
        """Extract and parse conversations from a Google Takeout Gemini export.

        Google Takeout stores Gemini conversations as per-folder JSON files:
        Takeout/Gemini Apps/Conversations/ (or Takeout/Gemini/Conversations/)
        Each subfolder contains a conversation.json.

        Also supports a flat directory of conversation JSON files (non-ZIP).

        Args:
            zip_path: Path to the Takeout ZIP file or directory.
            scrub: If True, redact detected secrets from message content.

        Returns:
            List of ChatData ready for local storage.
        """
        if zip_path.is_dir():
            return self._parse_directory(zip_path, scrub=scrub)
        return self._parse_zip(zip_path, scrub=scrub)

    def _parse_zip(self, zip_path: Path, scrub: bool = False) -> list[ChatData]:
        """Parse conversations from a Takeout ZIP file."""
        conv_files = _find_conversation_files(zip_path)
        if not conv_files:
            raise FileNotFoundError(
                f"No Gemini conversation files found in {zip_path.name}. "
                f"Expected a Google Takeout ZIP with Gemini data."
            )

        chats: list[ChatData] = []
        with zipfile.ZipFile(zip_path, "r") as zf:
            for conv_path in conv_files:
                try:
                    raw = zf.read(conv_path).decode("utf-8")
                    conv = json.loads(raw)
                    # Derive folder name for title fallback
                    folder_name = _folder_name_from_path(conv_path)
                    chat_data = _parse_conversation(conv, folder_name=folder_name, scrub=scrub)
                    chats.append(chat_data)
                except Exception:
                    log.warning("Failed to parse %s", conv_path, exc_info=True)

        log.info("Parsed %d conversations from %s", len(chats), zip_path.name)
        return chats

    def _parse_directory(self, dir_path: Path, scrub: bool = False) -> list[ChatData]:
        """Parse conversations from an extracted Takeout directory."""
        # Find the Conversations directory
        conv_dir = _find_conversations_dir(dir_path)
        if conv_dir is None:
            raise FileNotFoundError(
                f"No Gemini Conversations directory found in {dir_path}. "
                f"Expected Google Takeout structure with Gemini/Conversations/."
            )

        chats: list[ChatData] = []
        for item in sorted(conv_dir.iterdir()):
            conv_file = None
            folder_name = ""
            if item.is_dir():
                candidate = item / "conversation.json"
                if candidate.exists():
                    conv_file = candidate
                    folder_name = item.name
            elif item.is_file() and item.suffix == ".json":
                conv_file = item
                folder_name = item.stem

            if conv_file is None:
                continue

            try:
                raw = conv_file.read_text(encoding="utf-8")
                conv = json.loads(raw)
                chat_data = _parse_conversation(conv, folder_name=folder_name, scrub=scrub)
                chats.append(chat_data)
            except Exception:
                log.warning("Failed to parse %s", conv_file, exc_info=True)

        log.info("Parsed %d conversations from %s", len(chats), dir_path)
        return chats


def _find_conversation_files(zip_path: Path) -> list[str]:
    """Find all conversation.json files inside a Takeout ZIP."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()

    results: list[str] = []
    for name in names:
        # Match patterns like:
        # Takeout/Gemini Apps/Conversations/*/conversation.json
        # Takeout/Gemini/Conversations/*/conversation.json
        # Gemini/Conversations/*/conversation.json
        # */conversation.json (fallback)
        lower = name.lower()
        if lower.endswith("/conversation.json") or lower.endswith("\\conversation.json"):
            if "gemini" in lower:
                results.append(name)

    # If no gemini-specific paths, try any conversation.json in subfolders
    if not results:
        for name in names:
            lower = name.lower()
            if lower.endswith("/conversation.json") or lower.endswith("\\conversation.json"):
                results.append(name)

    return sorted(results)


def _find_conversations_dir(dir_path: Path) -> Path | None:
    """Find the Conversations directory inside an extracted Takeout."""
    # Try common paths
    candidates = [
        dir_path / "Takeout" / "Gemini Apps" / "Conversations",
        dir_path / "Takeout" / "Gemini" / "Conversations",
        dir_path / "Gemini Apps" / "Conversations",
        dir_path / "Gemini" / "Conversations",
        dir_path / "Conversations",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    # Fallback: walk one level for any "Conversations" dir
    for item in dir_path.iterdir():
        if item.is_dir() and item.name.lower() == "conversations":
            return item
        # Check one more level
        if item.is_dir():
            for sub in item.iterdir():
                if sub.is_dir() and sub.name.lower() == "conversations":
                    return sub

    return None


def _folder_name_from_path(zip_entry: str) -> str:
    """Extract the conversation folder name from a ZIP entry path."""
    # e.g. "Takeout/Gemini/Conversations/2025-01-15_auth-discussion/conversation.json"
    # → "2025-01-15_auth-discussion"
    parts = zip_entry.replace("\\", "/").split("/")
    if len(parts) >= 2:
        return parts[-2]
    return ""


def _parse_conversation(
    conv: dict,
    folder_name: str = "",
    scrub: bool = False,
) -> ChatData:
    """Parse a single Gemini conversation JSON into ChatData.

    Gemini conversation.json typically contains:
    - "title" or "name": conversation title
    - "id" or "conversation_id": unique identifier
    - "messages" or "chunks" or "turns": array of messages
    - "create_time"/"created" and "update_time"/"updated": timestamps
    - "model"/"model_name": model used
    """
    conv_id = (
        conv.get("id", "")
        or conv.get("conversation_id", "")
        or folder_name
    )

    # Title: from JSON metadata or folder name
    title = conv.get("title", "") or conv.get("name", "")
    if not title:
        title = _title_from_folder_name(folder_name) if folder_name else "Untitled"

    # Timestamps
    created = _parse_timestamp(
        conv.get("create_time") or conv.get("created") or conv.get("createTime")
    )
    updated = _parse_timestamp(
        conv.get("update_time") or conv.get("updated") or conv.get("updateTime")
    ) or created

    # Model info
    model = (
        conv.get("model", "")
        or conv.get("model_name", "")
        or conv.get("modelName", "")
    )

    # Parse messages — Gemini exports use various field names
    raw_messages = (
        conv.get("messages")
        or conv.get("turns")
        or conv.get("chunks")
        or []
    )

    # Also handle chunkedPrompt.chunks (AI Studio style)
    if not raw_messages:
        chunked = conv.get("chunkedPrompt", {})
        if isinstance(chunked, dict):
            raw_messages = chunked.get("chunks", [])

    messages: list[ChatMessage] = []
    for msg in raw_messages:
        role = _normalize_role(msg.get("role", ""))
        if not role:
            continue

        content = _extract_content(msg)
        if not content:
            continue

        if scrub:
            content = scrub_text(content)

        timestamp = _parse_timestamp(
            msg.get("create_time") or msg.get("timestamp") or msg.get("createTime")
        )

        messages.append(ChatMessage(role=role, content=content, timestamp=timestamp))

        # Extract model from message metadata if not set at conversation level
        if not model and role == "assistant":
            model = msg.get("model", "") or msg.get("model_name", "")

    return ChatData(
        remote_id=conv_id,
        title=title,
        provider="gemini",
        model=model,
        created=created,
        updated=updated,
        messages=messages,
    )


def _normalize_role(role: str) -> str:
    """Map Gemini's role names to our standard roles."""
    role = role.lower().strip()
    if role in ("user", "human"):
        return "human"
    if role in ("model", "assistant"):
        return "assistant"
    # Skip system/tool/thought messages
    return ""


def _extract_content(msg: dict) -> str:
    """Extract text content from a Gemini message.

    Gemini messages may have:
    - "text": "..." (simple)
    - "content": "..." (string)
    - "content": [{"text": "..."}] (structured parts)
    - "parts": [{"text": "..."}] (API-style)
    """
    # Direct text field
    text = msg.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    # Content as string
    content = msg.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()

    # Content as list of parts
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                t = part.get("text", "")
                if t:
                    parts.append(t)
        result = "\n".join(parts).strip()
        if result:
            return result

    # Parts field (Gemini API style)
    parts_field = msg.get("parts")
    if isinstance(parts_field, list):
        parts = []
        for part in parts_field:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                t = part.get("text", "")
                if t:
                    parts.append(t)
        result = "\n".join(parts).strip()
        if result:
            return result

    return ""


def _title_from_folder_name(folder_name: str) -> str:
    """Derive a human-readable title from a Takeout folder name.

    Folder names look like "2025-01-15_auth-discussion" or just "auth-discussion".
    Strip the date prefix and convert hyphens/underscores to spaces.
    """
    if not folder_name:
        return "Untitled"

    name = folder_name
    # Strip date prefix like "2025-01-15_"
    if len(name) > 11 and name[4] == "-" and name[7] == "-" and name[10] == "_":
        name = name[11:]

    # Convert separators to spaces and title-case
    name = name.replace("-", " ").replace("_", " ").strip()
    if not name:
        return folder_name  # fallback to original

    return name.title()


def _parse_timestamp(value: str | float | int | None) -> datetime:
    """Parse a timestamp from Gemini's export (ISO 8601 or Unix epoch)."""
    if value is None:
        return datetime.now(timezone.utc)

    # Unix timestamp (numeric)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            return datetime.now(timezone.utc)

    # String timestamp — try ISO 8601 first
    if isinstance(value, str):
        value_str = value.strip()
        if not value_str:
            return datetime.now(timezone.utc)

        # Try ISO 8601
        try:
            cleaned = value_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            pass

        # Try parsing as numeric string
        try:
            return datetime.fromtimestamp(float(value_str), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            pass

    return datetime.now(timezone.utc)
