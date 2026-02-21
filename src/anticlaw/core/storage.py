"""File system storage: read/write chat .md files and project metadata."""

from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import frontmatter
import yaml

from anticlaw.core.fileutil import atomic_write, ensure_dir, file_lock, safe_filename
from anticlaw.core.models import Chat, ChatMessage, Project, Status

log = logging.getLogger(__name__)

# Directories that are not user projects
_RESERVED_DIRS = {"_inbox", "_archive", ".acl", ".git", ".github"}

# Regex to parse message headers like "## Human (14:30)" or "## Assistant (14:31)"
_MSG_HEADER_RE = re.compile(
    r"^##\s+(Human|Assistant)\s*(?:\((\d{1,2}:\d{2}(?::\d{2})?)\))?\s*$",
    re.IGNORECASE,
)


class ChatStorage:
    """CRUD operations for chat .md files and project _project.yaml files."""

    def __init__(self, home: Path) -> None:
        self.home = home

    # --- Home initialization ---

    def init_home(self) -> None:
        """Create the ACL_HOME directory structure."""
        ensure_dir(self.home)
        ensure_dir(self.home / ".acl")
        ensure_dir(self.home / "_inbox")
        ensure_dir(self.home / "_archive")
        log.info("Initialized ACL_HOME at %s", self.home)

    # --- Project operations ---

    def list_projects(self) -> list[Project]:
        """List all projects (non-reserved subdirectories with _project.yaml)."""
        projects = []
        if not self.home.exists():
            return projects
        for entry in sorted(self.home.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name in _RESERVED_DIRS or entry.name.startswith("."):
                continue
            project_file = entry / "_project.yaml"
            if project_file.exists():
                projects.append(self.read_project(project_file))
            else:
                # Directory exists but has no metadata — create minimal project
                projects.append(Project(name=entry.name))
        return projects

    def read_project(self, path: Path) -> Project:
        """Read a _project.yaml file into a Project dataclass."""
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return Project(
            name=data.get("name", path.parent.name),
            description=data.get("description", ""),
            created=_parse_dt(data.get("created")),
            updated=_parse_dt(data.get("updated")),
            tags=data.get("tags") or [],
            status=data.get("status", Status.ACTIVE),
            providers=data.get("providers") or {},
            settings=data.get("settings") or {},
        )

    def write_project(self, path: Path, project: Project) -> None:
        """Write a Project dataclass to a _project.yaml file."""
        data = {
            "name": project.name,
            "description": project.description,
            "created": _format_dt(project.created),
            "updated": _format_dt(project.updated),
            "tags": project.tags,
            "status": str(project.status),
            "providers": project.providers,
            "settings": project.settings,
        }
        content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        with file_lock(path):
            atomic_write(path, content)

    def create_project(self, name: str, description: str = "") -> Path:
        """Create a new project directory with _project.yaml."""
        dir_name = safe_filename(name)
        project_dir = self.home / dir_name
        ensure_dir(project_dir)
        project = Project(name=name, description=description)
        self.write_project(project_dir / "_project.yaml", project)
        return project_dir

    # --- Chat operations ---

    def list_chats(self, project_path: Path) -> list[Chat]:
        """List all .md chat files in a project directory (metadata only, no messages)."""
        chats = []
        if not project_path.exists():
            return chats
        for md_file in sorted(project_path.glob("*.md")):
            if md_file.name.startswith("_"):
                continue
            try:
                chats.append(self.read_chat(md_file, load_messages=False))
            except Exception:
                log.warning("Failed to read chat: %s", md_file, exc_info=True)
        return chats

    def read_chat(self, path: Path, load_messages: bool = True) -> Chat:
        """Read a .md file with YAML frontmatter into a Chat dataclass."""
        post = frontmatter.load(str(path), encoding="utf-8")
        meta = post.metadata

        chat = Chat(
            id=meta.get("id", ""),
            title=meta.get("title", ""),
            created=_parse_dt(meta.get("created")),
            updated=_parse_dt(meta.get("updated")),
            provider=meta.get("provider", ""),
            remote_id=meta.get("remote_id", ""),
            remote_project_id=meta.get("remote_project_id", ""),
            model=meta.get("model", ""),
            tags=meta.get("tags") or [],
            summary=meta.get("summary", ""),
            token_count=meta.get("token_count", 0),
            message_count=meta.get("message_count", 0),
            importance=meta.get("importance", "medium"),
            status=meta.get("status", Status.ACTIVE),
        )

        if load_messages:
            chat.messages = _parse_messages(post.content)

        return chat

    def write_chat(self, path: Path, chat: Chat) -> None:
        """Write a Chat dataclass to a .md file with YAML frontmatter."""
        meta = {
            "id": chat.id,
            "title": chat.title,
            "created": _format_dt(chat.created),
            "updated": _format_dt(chat.updated),
            "provider": chat.provider,
            "remote_id": chat.remote_id,
            "remote_project_id": chat.remote_project_id,
            "model": chat.model,
            "tags": chat.tags,
            "summary": chat.summary,
            "token_count": chat.token_count,
            "message_count": chat.message_count or len(chat.messages),
            "importance": str(chat.importance),
            "status": str(chat.status),
        }

        body = _render_messages(chat.messages)
        post = frontmatter.Post(body, **meta)
        content = frontmatter.dumps(post)

        with file_lock(path):
            atomic_write(path, content)

    def chat_filename(self, chat: Chat) -> str:
        """Generate a filename for a chat: YYYY-MM-DD_slug.md"""
        date_str = chat.created.strftime("%Y-%m-%d")
        slug = safe_filename(chat.title) if chat.title else "untitled"
        return f"{date_str}_{slug}.md"

    def move_chat(self, src_path: Path, dst_project_dir: Path) -> Path:
        """Move a chat file to a different project directory."""
        ensure_dir(dst_project_dir)
        dst_path = dst_project_dir / src_path.name
        # Handle name collisions
        counter = 1
        while dst_path.exists():
            stem = src_path.stem
            dst_path = dst_project_dir / f"{stem}_{counter}{src_path.suffix}"
            counter += 1
        shutil.move(str(src_path), str(dst_path))
        return dst_path


# --- Internal helpers ---


def _parse_messages(content: str) -> list[ChatMessage]:
    """Parse markdown body into ChatMessage list."""
    messages: list[ChatMessage] = []
    current_role: str | None = None
    current_lines: list[str] = []
    current_time: str | None = None

    for line in content.split("\n"):
        match = _MSG_HEADER_RE.match(line)
        if match:
            # Save previous message
            if current_role is not None:
                messages.append(
                    ChatMessage(
                        role=current_role.lower(),
                        content="\n".join(current_lines).strip(),
                        timestamp=_parse_time(current_time),
                    )
                )
            current_role = match.group(1)
            current_time = match.group(2)
            current_lines = []
        else:
            current_lines.append(line)

    # Don't forget the last message
    if current_role is not None:
        messages.append(
            ChatMessage(
                role=current_role.lower(),
                content="\n".join(current_lines).strip(),
                timestamp=_parse_time(current_time),
            )
        )

    return messages


def _render_messages(messages: list[ChatMessage]) -> str:
    """Render ChatMessage list into markdown body."""
    parts: list[str] = []
    for msg in messages:
        role = msg.role.capitalize()
        if msg.timestamp:
            time_str = msg.timestamp.strftime("%H:%M")
            header = f"## {role} ({time_str})"
        else:
            header = f"## {role}"
        parts.append(f"{header}\n{msg.content}")
    return "\n\n".join(parts)


def _parse_time(time_str: str | None) -> datetime | None:
    """Parse a HH:MM or HH:MM:SS time string into a datetime (today, UTC)."""
    if not time_str:
        return None
    parts = time_str.split(":")
    try:
        hour, minute = int(parts[0]), int(parts[1])
        second = int(parts[2]) if len(parts) > 2 else 0
        return datetime.now(timezone.utc).replace(
            hour=hour, minute=minute, second=second, microsecond=0
        )
    except (ValueError, IndexError):
        return None


def _parse_dt(value: str | datetime | None) -> datetime:
    """Parse a datetime from YAML (may be str or datetime already)."""
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    # Try ISO format
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return datetime.now(timezone.utc)


def _format_dt(dt: datetime) -> str:
    """Format datetime as ISO 8601 string with Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
