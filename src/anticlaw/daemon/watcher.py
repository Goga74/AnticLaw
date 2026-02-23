"""File system watcher — detects .md changes and triggers reindex + graph update."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Default debounce in seconds
_DEFAULT_DEBOUNCE = 2.0

# Default patterns to ignore
_DEFAULT_IGNORE = {"*.tmp", "*.swp", "*.swx", ".git", ".acl", "__pycache__"}


class FileWatcher:
    """Watch ACL_HOME for .md file changes and trigger reindex.

    Uses watchdog for cross-platform file monitoring. Debounces rapid
    changes so that multiple saves within the debounce window produce
    a single reindex.
    """

    def __init__(
        self,
        home: Path,
        debounce_seconds: float = _DEFAULT_DEBOUNCE,
        ignore_patterns: set[str] | None = None,
        on_change: object | None = None,
    ) -> None:
        self.home = home
        self.debounce = debounce_seconds
        self.ignore_patterns = ignore_patterns or _DEFAULT_IGNORE
        self._on_change = on_change  # callback(event_type, path)
        self._observer = None
        self._pending: dict[str, tuple[str, float]] = {}  # path -> (event, time)
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._running = False

    def start(self) -> None:
        """Start watching the home directory."""
        try:
            from watchdog.observers import Observer
        except ImportError as e:
            raise RuntimeError(
                f"watchdog not installed: {e}. Install with: pip install anticlaw[daemon]"
            ) from e

        handler = _ChangeHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.home), recursive=True)
        self._observer.start()
        self._running = True
        log.info("FileWatcher started: %s", self.home)

    def stop(self) -> None:
        """Stop watching."""
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        log.info("FileWatcher stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def _should_ignore(self, path: str) -> bool:
        """Check if a path matches any ignore pattern."""
        p = Path(path)
        name = p.name

        for pattern in self.ignore_patterns:
            if pattern.startswith("*."):
                # Extension match
                if name.endswith(pattern[1:]):
                    return True
            elif pattern in p.parts:
                # Directory name match
                return True

        return False

    def _on_fs_event(self, event_type: str, src_path: str) -> None:
        """Called by the watchdog handler. Debounces and filters."""
        if self._should_ignore(src_path):
            return

        # Only care about .md files
        if not src_path.endswith(".md"):
            return

        # Skip files starting with _
        if Path(src_path).name.startswith("_"):
            return

        with self._lock:
            self._pending[src_path] = (event_type, time.monotonic())

        # Reset debounce timer
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self.debounce, self._flush_pending)
        self._timer.daemon = True
        self._timer.start()

    def _flush_pending(self) -> None:
        """Process all pending changes after debounce period."""
        with self._lock:
            pending = dict(self._pending)
            self._pending.clear()

        for path, (event_type, _ts) in pending.items():
            try:
                self._process_change(event_type, Path(path))
            except Exception:
                log.warning("Error processing %s on %s", event_type, path, exc_info=True)

    def _process_change(self, event_type: str, path: Path) -> None:
        """Process a single file change: reindex + update graph."""
        log.info("Processing %s: %s", event_type, path)

        if self._on_change is not None:
            self._on_change(event_type, path)
            return

        # Default behavior: reindex the chat
        if event_type in ("created", "modified"):
            self._reindex_chat(path)
        elif event_type == "deleted":
            self._mark_archived(path)
        elif event_type == "moved":
            self._reindex_chat(path)

    def _reindex_chat(self, path: Path) -> None:
        """Reindex a single chat file. Triggers sync for draft files."""
        if not path.exists():
            return

        try:
            from anticlaw.core.meta_db import MetaDB
            from anticlaw.core.storage import ChatStorage

            storage = ChatStorage(self.home)
            chat = storage.read_chat(path, load_messages=True)

            # Determine project from directory
            rel = path.relative_to(self.home)
            project_id = rel.parts[0] if len(rel.parts) > 1 else "_inbox"

            db = MetaDB(self.home / ".acl" / "meta.db")
            try:
                db.index_chat(chat, path, project_id)
                log.info("Reindexed chat: %s (project=%s)", chat.title, project_id)
            finally:
                db.close()

            # Update graph
            self._update_graph(chat)

            # Check for draft status — trigger sync engine
            if str(chat.status) == "draft":
                self._process_draft(path)

        except Exception:
            log.warning("Failed to reindex: %s", path, exc_info=True)

    def _process_draft(self, path: Path) -> None:
        """Send a draft chat to its push target via the sync engine."""
        try:
            from anticlaw.core.config import load_config

            config = load_config(self.home / ".acl" / "config.yaml")
            sync_cfg = config.get("sync", {})

            if not sync_cfg.get("auto_push_drafts", False):
                log.debug("auto_push_drafts disabled, skipping draft: %s", path)
                return

            from anticlaw.sync.engine import SyncEngine

            engine = SyncEngine(self.home)
            engine.send_chat(path)
            log.info("Draft sent and response written: %s", path.name)
        except Exception:
            log.warning("Failed to process draft: %s", path, exc_info=True)

    def _update_graph(self, chat) -> None:
        """Update graph edges for a reindexed chat."""
        try:
            from anticlaw.core.graph import GraphDB

            graph = GraphDB(self.home / ".acl" / "graph.db")
            try:
                # Check if node exists; if so, update, else add
                node = graph.get_node(chat.id)
                if node is None:
                    from anticlaw.core.models import Insight

                    insight = Insight(
                        id=chat.id,
                        content=chat.summary or chat.title,
                        category="fact",
                        tags=chat.tags,
                        project_id="",
                    )
                    graph.add_node(insight)
            finally:
                graph.close()
        except Exception:
            log.debug("Graph update skipped: %s", chat.id, exc_info=True)

    def _mark_archived(self, path: Path) -> None:
        """Mark a deleted chat as archived in meta.db."""
        try:
            from anticlaw.core.meta_db import MetaDB

            db = MetaDB(self.home / ".acl" / "meta.db")
            try:
                # Find chat by file path
                row = db.conn.execute(
                    "SELECT id FROM chats WHERE file_path = ?", (str(path),)
                ).fetchone()
                if row:
                    db.conn.execute(
                        "UPDATE chats SET status = 'archived' WHERE id = ?",
                        (row["id"],),
                    )
                    db.conn.commit()
                    log.info("Marked chat as archived: %s", row["id"])
            finally:
                db.close()
        except Exception:
            log.warning("Failed to mark archived: %s", path, exc_info=True)


class _ChangeHandler:
    """Watchdog event handler that delegates to FileWatcher."""

    def __init__(self, watcher: FileWatcher) -> None:
        self._watcher = watcher

    def dispatch(self, event) -> None:
        """Dispatch all watchdog events."""
        if event.is_directory:
            return

        event_type = event.event_type  # created, modified, deleted, moved
        src_path = event.src_path

        if event_type == "moved":
            # For moved events, track the destination
            src_path = getattr(event, "dest_path", event.src_path)

        self._watcher._on_fs_event(event_type, src_path)
