"""ChatGPT provider: parse official data export into ChatData."""

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


class ChatGPTProvider:
    """ChatGPT LLM provider — parses official data exports."""

    @property
    def name(self) -> str:
        return "chatgpt"

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            display_name="ChatGPT",
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
        raise NotImplementedError("Single chat export not supported for ChatGPT")

    def import_chat(self, project_id: str | None, chat: ChatData) -> str:
        raise NotImplementedError("ChatGPT has no import API")

    def export_all(self, output_dir: Path) -> int:
        raise NotImplementedError("Use parse_export_zip() instead")

    def sync(
        self,
        local_project: Path,
        remote_project_id: str,
        direction: str = "pull",
    ) -> SyncResult:
        raise NotImplementedError("Sync not supported for ChatGPT")

    # --- Export parsing (the main capability) ---

    def parse_export_zip(
        self,
        zip_path: Path,
        scrub: bool = False,
    ) -> list[ChatData]:
        """Extract and parse conversations.json from a ChatGPT export ZIP.

        Args:
            zip_path: Path to the ChatGPT export ZIP file.
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
                conv_id = conv.get("conversation_id", conv.get("id", "unknown"))
                log.warning("Failed to parse conversation %s", conv_id, exc_info=True)

        log.info("Parsed %d conversations from %s", len(chats), zip_path.name)
        return chats


def _extract_conversations_json(zip_path: Path) -> str:
    """Extract conversations.json from a ChatGPT export ZIP."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        # Try common locations
        for candidate in ["conversations.json", "chatgpt/conversations.json"]:
            if candidate in zf.namelist():
                return zf.read(candidate).decode("utf-8")

        # Fallback: find any conversations.json
        for name in zf.namelist():
            if name.endswith("conversations.json"):
                return zf.read(name).decode("utf-8")

    raise FileNotFoundError(
        f"No conversations.json found in {zip_path.name}. "
        f"Expected a ChatGPT data export ZIP."
    )


def _parse_conversation(conv: dict, scrub: bool = False) -> ChatData:
    """Parse a single conversation dict from ChatGPT's conversations.json.

    ChatGPT uses a mapping dict with message nodes linked by parent/children,
    unlike Claude's flat message array. We reconstruct message order by
    walking the tree from root to leaf.
    """
    conv_id = conv.get("conversation_id", conv.get("id", ""))
    title = conv.get("title", "") or "Untitled"
    created = _parse_unix_timestamp(conv.get("create_time"))
    updated = _parse_unix_timestamp(conv.get("update_time")) or created

    mapping = conv.get("mapping", {})
    if not mapping:
        return ChatData(
            remote_id=conv_id,
            title=title,
            provider="chatgpt",
            created=created,
            updated=updated,
            messages=[],
        )

    # Walk the mapping tree to get ordered messages
    ordered_nodes = _walk_message_tree(mapping)

    messages: list[ChatMessage] = []
    model = ""

    for node in ordered_nodes:
        msg = node.get("message")
        if not msg:
            continue

        author = msg.get("author", {})
        role = _normalize_role(author.get("role", ""))
        if not role:
            continue

        content = _extract_content(msg)
        if not content:
            continue

        if scrub:
            content = scrub_text(content)

        timestamp = _parse_unix_timestamp(msg.get("create_time"))

        messages.append(ChatMessage(role=role, content=content, timestamp=timestamp))

        # Extract model from metadata (use the last assistant message's model)
        if role == "assistant" and not model:
            metadata = msg.get("metadata", {})
            model = metadata.get("model_slug", "")

    return ChatData(
        remote_id=conv_id,
        title=title,
        provider="chatgpt",
        model=model,
        created=created,
        updated=updated,
        messages=messages,
    )


def _walk_message_tree(mapping: dict) -> list[dict]:
    """Walk the ChatGPT mapping tree to produce messages in conversation order.

    ChatGPT stores messages as a tree (for branching). We follow the
    primary path: root → first child → first child → ... to get the
    linear conversation.
    """
    # Find root node (no parent or parent not in mapping)
    root_id = None
    for node_id, node in mapping.items():
        parent = node.get("parent")
        if parent is None or parent not in mapping:
            root_id = node_id
            break

    if root_id is None:
        return []

    # Walk from root following children
    ordered: list[dict] = []
    current_id = root_id
    visited: set[str] = set()

    while current_id and current_id not in visited:
        visited.add(current_id)
        node = mapping.get(current_id)
        if node is None:
            break

        ordered.append(node)

        # Follow the last child (ChatGPT uses last child as the active branch)
        children = node.get("children", [])
        current_id = children[-1] if children else None

    return ordered


def _normalize_role(role: str) -> str:
    """Map ChatGPT's role names to our standard roles."""
    role = role.lower().strip()
    if role == "user":
        return "human"
    if role == "assistant":
        return "assistant"
    # Skip system and tool messages — they are internal
    return ""


def _extract_content(msg: dict) -> str:
    """Extract text content from a ChatGPT message.

    ChatGPT messages have:
    - "content": {"content_type": "text", "parts": ["Hello", "World"]}
    - "content": {"content_type": "code", "text": "print('hi')"}
    - "content": {"content_type": "multimodal_text", "parts": [...]}
    """
    content = msg.get("content", {})
    if not isinstance(content, dict):
        return ""

    content_type = content.get("content_type", "")

    # Text and multimodal_text use "parts" array
    if content_type in ("text", "multimodal_text"):
        parts = content.get("parts", [])
        text_parts = []
        for part in parts:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict) and part.get("content_type") == "text":
                text_parts.append(part.get("text", ""))
        return "\n".join(text_parts).strip()

    # Code content
    if content_type == "code":
        return content.get("text", "").strip()

    return ""


def _parse_unix_timestamp(value: float | int | None) -> datetime:
    """Parse a Unix timestamp (seconds since epoch) from ChatGPT's export."""
    if value is None:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return datetime.now(timezone.utc)
