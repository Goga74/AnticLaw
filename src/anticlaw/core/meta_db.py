"""SQLite metadata index for AnticLaw."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result with snippet."""

    chat_id: str
    title: str
    project_id: str
    snippet: str
    score: float
    file_path: str
    result_type: str = "chat"  # "chat" | "file" | "insight"


class MetaDB:
    """SQLite metadata index at .acl/meta.db."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = self._open()
        return self._conn

    def _open(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        return conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # --- Indexing ---

    def index_chat(self, chat, file_path: Path, project_id: str = "") -> None:
        """Insert or update a chat in the index."""
        content = "\n".join(m.content for m in chat.messages) if chat.messages else ""
        tags_json = json.dumps(chat.tags) if chat.tags else "[]"

        self.conn.execute(
            """INSERT OR REPLACE INTO chats
               (id, title, project_id, provider, remote_id, created, updated,
                tags, summary, importance, status, file_path, token_count,
                message_count, content)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                chat.id, chat.title, project_id, chat.provider, chat.remote_id,
                _format_dt(chat.created), _format_dt(chat.updated),
                tags_json, chat.summary, _val(chat.importance), _val(chat.status),
                str(file_path), chat.token_count,
                chat.message_count or len(chat.messages), content,
            ),
        )
        # Rebuild FTS entry
        self.conn.execute("DELETE FROM chats_fts WHERE chat_id = ?", (chat.id,))
        self.conn.execute(
            "INSERT INTO chats_fts(chat_id, title, summary, content, tags) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat.id, chat.title, chat.summary, content, tags_json),
        )
        self.conn.commit()

    def index_project(self, project, dir_path: Path) -> None:
        """Insert or update a project in the index."""
        tags_json = json.dumps(project.tags) if project.tags else "[]"
        self.conn.execute(
            """INSERT OR REPLACE INTO projects
               (id, name, description, created, updated, tags, status, dir_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                dir_path.name, project.name, project.description,
                _format_dt(project.created), _format_dt(project.updated),
                tags_json, _val(project.status), str(dir_path),
            ),
        )
        self.conn.commit()

    def reindex_all(self, home: Path) -> tuple[int, int]:
        """Walk the file system and rebuild the entire index.

        Returns (chats_indexed, projects_indexed).
        """
        from anticlaw.core.storage import _RESERVED_DIRS, ChatStorage

        storage = ChatStorage(home)
        chats_count = 0
        projects_count = 0

        # Clear existing data
        self.conn.execute("DELETE FROM chats_fts")
        self.conn.execute("DELETE FROM chats")
        self.conn.execute("DELETE FROM projects")
        self.conn.commit()

        # Collect directories to scan
        dirs_to_scan: list[tuple[Path, str]] = []

        if (home / "_inbox").exists():
            dirs_to_scan.append((home / "_inbox", "_inbox"))

        for entry in sorted(home.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name in _RESERVED_DIRS or entry.name.startswith("."):
                continue
            # It's a project directory
            project_file = entry / "_project.yaml"
            if project_file.exists():
                project = storage.read_project(project_file)
                self.index_project(project, entry)
                projects_count += 1
            dirs_to_scan.append((entry, entry.name))

        # Scan chat files
        for dir_path, project_id in dirs_to_scan:
            for md_file in sorted(dir_path.glob("*.md")):
                if md_file.name.startswith("_"):
                    continue
                try:
                    chat = storage.read_chat(md_file, load_messages=True)
                    self.index_chat(chat, md_file, project_id)
                    chats_count += 1
                except Exception:
                    log.warning("Failed to index chat: %s", md_file, exc_info=True)

        return chats_count, projects_count

    # --- Search ---

    def search_keyword(
        self,
        query: str,
        *,
        project: str | None = None,
        tags: list[str] | None = None,
        importance: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        max_results: int = 20,
        exact: bool = False,
    ) -> list[SearchResult]:
        """Search chats via FTS5 MATCH."""
        fts_query = f'"{query}"' if exact else query

        sql = """
            SELECT f.chat_id, c.title, c.project_id,
                   snippet(chats_fts, -1, '**', '**', '...', 64) as snippet,
                   f.rank as score, c.file_path
            FROM chats_fts f
            JOIN chats c ON c.id = f.chat_id
            WHERE chats_fts MATCH ?
        """
        params: list = [fts_query]

        if project:
            sql += " AND c.project_id = ?"
            params.append(project)

        if importance:
            sql += " AND c.importance = ?"
            params.append(importance)

        if date_from:
            sql += " AND c.created >= ?"
            params.append(date_from)

        if date_to:
            sql += " AND c.created <= ?"
            params.append(date_to)

        sql += " ORDER BY f.rank LIMIT ?"
        params.append(max_results)

        try:
            rows = self.conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as e:
            log.warning("FTS5 query failed: %s", e)
            return []

        results = []
        for row in rows:
            # Filter by tags in Python (JSON array in DB)
            if tags:
                chat_tags = json.loads(row["tags"] if "tags" in row.keys() else "[]")  # noqa: SIM118
                if not chat_tags:
                    # Re-read from chats table
                    chat_row = self.conn.execute(
                        "SELECT tags FROM chats WHERE id = ?", (row["chat_id"],)
                    ).fetchone()
                    chat_tags = json.loads(chat_row["tags"]) if chat_row else []
                if not any(t in chat_tags for t in tags):
                    continue

            results.append(SearchResult(
                chat_id=row["chat_id"],
                title=row["title"] or "",
                project_id=row["project_id"] or "",
                snippet=row["snippet"] or "",
                score=row["score"] or 0.0,
                file_path=row["file_path"] or "",
            ))

        return results

    # --- Lookups ---

    def get_chat(self, chat_id: str) -> dict | None:
        """Get a chat record by ID."""
        row = self.conn.execute(
            "SELECT * FROM chats WHERE id = ?", (chat_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_project(self, project_id: str) -> dict | None:
        """Get a project record by ID."""
        row = self.conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def list_projects(self) -> list[dict]:
        """List all projects."""
        rows = self.conn.execute(
            "SELECT * FROM projects ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

    def list_chats(self, project_id: str | None = None) -> list[dict]:
        """List chats, optionally filtered by project."""
        if project_id:
            rows = self.conn.execute(
                "SELECT * FROM chats WHERE project_id = ? ORDER BY created DESC",
                (project_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM chats ORDER BY created DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # --- Updates ---

    def update_chat_tags(self, chat_id: str, tags: list[str]) -> None:
        """Update tags for a chat in the index."""
        tags_json = json.dumps(tags)
        self.conn.execute(
            "UPDATE chats SET tags = ? WHERE id = ?", (tags_json, chat_id)
        )
        # Rebuild FTS entry for this chat
        row = self.conn.execute(
            "SELECT title, summary, content FROM chats WHERE id = ?", (chat_id,)
        ).fetchone()
        if row:
            self.conn.execute(
                "DELETE FROM chats_fts WHERE chat_id = ?", (chat_id,)
            )
            self.conn.execute(
                "INSERT INTO chats_fts(chat_id, title, summary, content, tags) "
                "VALUES (?, ?, ?, ?, ?)",
                (chat_id, row["title"], row["summary"], row["content"], tags_json),
            )
        self.conn.commit()

    def update_chat_path(
        self, chat_id: str, file_path: Path, project_id: str
    ) -> None:
        """Update file path and project for a chat after move."""
        self.conn.execute(
            "UPDATE chats SET file_path = ?, project_id = ? WHERE id = ?",
            (str(file_path), project_id, chat_id),
        )
        self.conn.commit()

    # --- Insights ---

    def add_insight(self, insight) -> None:
        """Insert an insight into the index."""
        tags_json = json.dumps(insight.tags) if insight.tags else "[]"
        self.conn.execute(
            """INSERT OR REPLACE INTO insights
               (id, content, category, importance, tags, project_id,
                chat_id, created, updated, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                insight.id, insight.content, _val(insight.category),
                _val(insight.importance), tags_json, insight.project_id,
                insight.chat_id, _format_dt(insight.created),
                _format_dt(insight.updated), _val(insight.status),
            ),
        )
        self.conn.commit()

    def get_insight(self, insight_id: str) -> dict | None:
        """Get an insight by ID."""
        row = self.conn.execute(
            "SELECT * FROM insights WHERE id = ?", (insight_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def list_insights(
        self,
        *,
        query: str = "",
        project: str | None = None,
        category: str | None = None,
        importance: str | None = None,
        max_results: int = 20,
    ) -> list[dict]:
        """List insights with optional filters."""
        sql = "SELECT * FROM insights WHERE status = 'active'"
        params: list = []

        if query:
            sql += " AND content LIKE ?"
            params.append(f"%{query}%")
        if project:
            sql += " AND project_id = ?"
            params.append(project)
        if category:
            sql += " AND category = ?"
            params.append(category)
        if importance:
            sql += " AND importance = ?"
            params.append(importance)

        sql += " ORDER BY created DESC LIMIT ?"
        params.append(max_results)

        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def delete_insight(self, insight_id: str) -> bool:
        """Delete an insight (set status to purged). Returns True if found."""
        cursor = self.conn.execute(
            "UPDATE insights SET status = 'purged' WHERE id = ? AND status = 'active'",
            (insight_id,),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def count_insights(self) -> int:
        """Count active insights."""
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM insights WHERE status = 'active'"
        ).fetchone()
        return row["cnt"] if row else 0

    # --- Source Files ---

    def index_source_file(self, doc) -> None:
        """Insert or update a source file in the index."""
        self.conn.execute(
            """INSERT OR REPLACE INTO source_files
               (id, file_path, filename, extension, language, size,
                hash, indexed_at, project_id, content)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                doc.id, doc.file_path, doc.filename, doc.extension,
                doc.language, doc.size, doc.hash,
                _format_dt(doc.indexed_at), doc.project_id, doc.content,
            ),
        )
        # Rebuild FTS entry
        self.conn.execute(
            "DELETE FROM source_files_fts WHERE file_id = ?", (doc.id,)
        )
        self.conn.execute(
            "INSERT INTO source_files_fts(file_id, filename, content) VALUES (?, ?, ?)",
            (doc.id, doc.filename, doc.content),
        )
        self.conn.commit()

    def search_source_files(
        self,
        query: str,
        *,
        max_results: int = 20,
        exact: bool = False,
    ) -> list[SearchResult]:
        """Search source files via FTS5 MATCH."""
        fts_query = f'"{query}"' if exact else query

        sql = """
            SELECT f.file_id, s.filename, s.file_path, s.extension, s.language,
                   snippet(source_files_fts, -1, '**', '**', '...', 64) as snippet,
                   f.rank as score
            FROM source_files_fts f
            JOIN source_files s ON s.id = f.file_id
            WHERE source_files_fts MATCH ?
            ORDER BY f.rank
            LIMIT ?
        """
        try:
            rows = self.conn.execute(sql, [fts_query, max_results]).fetchall()
        except sqlite3.OperationalError as e:
            log.warning("Source files FTS5 query failed: %s", e)
            return []

        results = []
        for row in rows:
            results.append(SearchResult(
                chat_id=row["file_id"],
                title=row["filename"],
                project_id="",
                snippet=row["snippet"] or "",
                score=row["score"] or 0.0,
                file_path=row["file_path"] or "",
                result_type="file",
            ))
        return results

    def get_source_file(self, file_path: str) -> dict | None:
        """Get a source file by path."""
        row = self.conn.execute(
            "SELECT * FROM source_files WHERE file_path = ?", (file_path,)
        ).fetchone()
        return dict(row) if row else None

    def count_source_files(self) -> int:
        """Count indexed source files."""
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM source_files"
        ).fetchone()
        return row["cnt"] if row else 0

    def clear_source_files(self) -> None:
        """Remove all source file entries."""
        self.conn.execute("DELETE FROM source_files_fts")
        self.conn.execute("DELETE FROM source_files")
        self.conn.commit()


# --- Schema ---

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY,
    title TEXT,
    project_id TEXT,
    provider TEXT,
    remote_id TEXT,
    created TEXT,
    updated TEXT,
    tags TEXT,
    summary TEXT,
    importance TEXT,
    status TEXT,
    file_path TEXT,
    token_count INTEGER,
    message_count INTEGER,
    content TEXT
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT,
    description TEXT,
    created TEXT,
    updated TEXT,
    tags TEXT,
    status TEXT,
    dir_path TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS chats_fts USING fts5(
    chat_id UNINDEXED, title, summary, content, tags
);

CREATE TABLE IF NOT EXISTS insights (
    id TEXT PRIMARY KEY,
    content TEXT,
    category TEXT,
    importance TEXT,
    tags TEXT,
    project_id TEXT,
    chat_id TEXT,
    created TEXT,
    updated TEXT,
    status TEXT
);

CREATE TABLE IF NOT EXISTS source_files (
    id TEXT PRIMARY KEY,
    file_path TEXT UNIQUE,
    filename TEXT,
    extension TEXT,
    language TEXT,
    size INTEGER,
    hash TEXT,
    indexed_at TEXT,
    project_id TEXT,
    content TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS source_files_fts USING fts5(
    file_id UNINDEXED, filename, content
);
"""


def _val(v: object) -> str:
    """Extract string value from a str Enum or plain string."""
    if isinstance(v, Enum):
        return str(v.value)
    return str(v)


def _format_dt(dt: datetime | None) -> str:
    """Format datetime as ISO string."""
    if dt is None:
        return ""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(dt)
