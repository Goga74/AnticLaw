"""SyncEngine — orchestrates sending chats to LLM APIs and writing responses back.

Push target routing hierarchy:
  1. File frontmatter:  push_target: claude
  2. Project config:    _project.yaml → sync.push_target
  3. Global config:     config.yaml → sync.default_push_target
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from anticlaw.core.config import load_config
from anticlaw.core.storage import ChatStorage
from anticlaw.sync.providers import (
    SyncProvider,
    get_sync_provider,
)

log = logging.getLogger(__name__)


class SyncEngine:
    """Orchestrate file-as-interface bidirectional LLM sync.

    Detects files with status 'draft', sends content to the resolved
    LLM API, writes the response back, and updates status to 'complete'.
    """

    def __init__(self, home: Path) -> None:
        self.home = home
        self._storage = ChatStorage(home)
        self._config = load_config(home / ".acl" / "config.yaml")

    def resolve_push_target(self, chat_path: Path) -> str | None:
        """Resolve push target from config hierarchy.

        Checks in order:
          1. File frontmatter push_target field
          2. Project _project.yaml sync.push_target
          3. Global config sync.default_push_target

        Returns:
            Provider name (e.g. 'claude', 'gemini') or None if not configured.
        """
        # 1. File frontmatter
        try:
            import frontmatter

            post = frontmatter.load(str(chat_path), encoding="utf-8")
            target = post.metadata.get("push_target")
            if target:
                return str(target)
        except Exception:
            pass

        # 2. Project _project.yaml
        try:
            rel = chat_path.relative_to(self.home)
            if len(rel.parts) > 1:
                project_dir = self.home / rel.parts[0]
                project_yaml = project_dir / "_project.yaml"
                if project_yaml.exists():
                    data = yaml.safe_load(project_yaml.read_text(encoding="utf-8")) or {}
                    sync_cfg = data.get("sync", {})
                    target = sync_cfg.get("push_target")
                    if target:
                        return str(target)
        except (ValueError, Exception):
            pass

        # 3. Global config
        sync_cfg = self._config.get("sync", {})
        target = sync_cfg.get("default_push_target")
        if target:
            return str(target)

        return None

    def _get_provider(
        self, provider_name: str | None = None, chat_path: Path | None = None
    ) -> SyncProvider:
        """Get a sync provider, resolving the target if not specified."""
        name = provider_name
        if not name and chat_path:
            name = self.resolve_push_target(chat_path)
        if not name:
            raise ValueError(
                "No push target configured. Set one of:\n"
                "  - push_target in chat frontmatter\n"
                "  - sync.push_target in _project.yaml\n"
                "  - sync.default_push_target in config.yaml"
            )

        # Build provider config from global config
        sync_providers = self._config.get("sync", {}).get("providers", {})
        provider_cfg = dict(sync_providers.get(name, {}))

        # Resolve 'keyring' api_key reference
        if provider_cfg.get("api_key") == "keyring":
            provider_cfg.pop("api_key", None)  # let provider use _get_api_key

        return get_sync_provider(name, provider_cfg)

    def send_chat(
        self,
        chat_path: Path,
        provider_name: str | None = None,
        model: str | None = None,
    ) -> str:
        """Send a chat to an LLM API and write the response back.

        Args:
            chat_path: Path to the .md chat file.
            provider_name: Override the push target provider.
            model: Override the default model.

        Returns:
            The assistant's response text.
        """
        provider = self._get_provider(provider_name, chat_path)

        # Read chat
        chat = self._storage.read_chat(chat_path, load_messages=True)

        # Build messages list for API
        messages = [
            {"role": m.role, "content": m.content}
            for m in chat.messages
            if m.content.strip()
        ]

        if not messages:
            raise ValueError(f"Chat {chat.id} has no messages to send")

        log.info(
            "Sending chat '%s' (%d messages) to %s",
            chat.title or chat.id,
            len(messages),
            provider.name,
        )

        # Send to LLM API
        response = provider.send(messages, model=model)

        # Append response to chat file
        self._append_response(chat_path, chat, response, provider.name, model)

        return response

    def _append_response(
        self,
        chat_path: Path,
        chat,
        response: str,
        provider_name: str,
        model: str | None,
    ) -> None:
        """Append the assistant response to the chat file and update metadata."""
        from anticlaw.core.models import ChatMessage

        # Add response as new message
        now = datetime.now(timezone.utc)
        chat.messages.append(
            ChatMessage(role="assistant", content=response, timestamp=now)
        )

        # Update metadata
        chat.updated = now
        chat.message_count = len(chat.messages)
        chat.status = "complete"
        if not chat.provider:
            chat.provider = provider_name
        if model and not chat.model:
            chat.model = model

        # Write back
        self._storage.write_chat(chat_path, chat)
        log.info("Response written to %s (status=complete)", chat_path.name)

    def find_drafts(self) -> list[Path]:
        """Find all .md files with status 'draft' in the home directory.

        Returns:
            List of paths to draft chat files.
        """
        drafts: list[Path] = []
        if not self.home.exists():
            return drafts

        try:
            import frontmatter
        except ImportError:
            return drafts

        for md_file in self.home.rglob("*.md"):
            # Skip internal dirs
            rel = md_file.relative_to(self.home)
            if any(part.startswith(".") for part in rel.parts):
                continue
            if md_file.name.startswith("_"):
                continue

            try:
                post = frontmatter.load(str(md_file), encoding="utf-8")
                status = post.metadata.get("status", "")
                if str(status) == "draft":
                    drafts.append(md_file)
            except Exception:
                continue

        return drafts

    def process_drafts(self) -> list[tuple[Path, str | None]]:
        """Find and send all draft files. Returns list of (path, error_or_None)."""
        results: list[tuple[Path, str | None]] = []
        for path in self.find_drafts():
            try:
                self.send_chat(path)
                results.append((path, None))
            except Exception as e:
                log.warning("Failed to process draft %s: %s", path, e)
                results.append((path, str(e)))
        return results
