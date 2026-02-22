"""Antientropy features: inbox suggestions, stale detection, duplicates, health check."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from anticlaw.core.meta_db import MetaDB
from anticlaw.core.storage import ChatStorage, _RESERVED_DIRS

log = logging.getLogger(__name__)


def _normalize_status(s: str) -> str:
    """Normalize status strings like 'Status.ACTIVE' to 'active'."""
    if not s:
        return "active"
    s_lower = s.lower()
    for status in ("active", "archived", "purged"):
        if status in s_lower:
            return status
    return s_lower


# --- Data classes ---


@dataclass
class InboxSuggestion:
    """Suggestion for classifying an inbox chat into a project."""

    chat_id: str
    title: str
    file_path: str
    suggested_project: str
    confidence: str  # "high", "medium", "low"
    reason: str


@dataclass
class StaleProject:
    """A project with no recent activity."""

    project_id: str
    name: str
    last_activity: str
    days_inactive: int
    chat_count: int


@dataclass
class DuplicatePair:
    """A pair of chats with high semantic similarity."""

    chat_id_a: str
    title_a: str
    chat_id_b: str
    title_b: str
    similarity: float


@dataclass
class HealthIssue:
    """A health check issue found in the knowledge base."""

    category: str  # "orphan_file", "missing_metadata", "broken_link", "unindexed"
    severity: str  # "warning", "error"
    message: str
    file_path: str = ""


@dataclass
class HealthReport:
    """Full health check report."""

    issues: list[HealthIssue] = field(default_factory=list)
    total_chats: int = 0
    total_projects: int = 0
    total_insights: int = 0
    indexed_chats: int = 0


@dataclass
class KBStats:
    """Global knowledge base statistics."""

    total_chats: int = 0
    total_projects: int = 0
    total_insights: int = 0
    inbox_chats: int = 0
    archived_chats: int = 0
    total_tags: int = 0
    top_tags: list[tuple[str, int]] = field(default_factory=list)
    total_messages: int = 0


# --- Inbox suggestions ---


def inbox_suggestions(
    home: Path,
    *,
    use_llm: bool = False,
) -> list[InboxSuggestion]:
    """Suggest projects for unclassified inbox chats.

    Uses tag matching against existing projects. Falls back to LLM-based
    categorization if use_llm=True and Ollama is available.

    Args:
        home: ACL_HOME path.
        use_llm: Whether to use Ollama for suggestions when tag matching fails.

    Returns:
        List of suggestions for inbox chats.
    """
    db_path = home / ".acl" / "meta.db"
    if not db_path.exists():
        return []

    db = MetaDB(db_path)
    suggestions: list[InboxSuggestion] = []
    try:
        inbox_chats = db.list_chats("_inbox")
        if not inbox_chats:
            return []

        # Build project tag index: project_id -> set of tags
        projects = db.list_projects()
        project_tags: dict[str, set[str]] = {}
        project_names: dict[str, str] = {}
        for p in projects:
            pid = p["id"]
            project_names[pid] = p.get("name", pid)
            ptags = set(json.loads(p.get("tags") or "[]"))
            # Also collect tags from chats in this project
            project_chats = db.list_chats(pid)
            for pc in project_chats:
                ctags = json.loads(pc.get("tags") or "[]")
                ptags.update(ctags)
            project_tags[pid] = ptags

        for chat_row in inbox_chats:
            chat_tags = set(json.loads(chat_row.get("tags") or "[]"))
            suggestion = _match_by_tags(
                chat_row, chat_tags, project_tags, project_names
            )
            if suggestion:
                suggestions.append(suggestion)
            elif use_llm:
                llm_suggestion = _suggest_via_llm(
                    home, chat_row, list(project_names.values())
                )
                if llm_suggestion:
                    suggestions.append(llm_suggestion)
            else:
                # No match — suggest with low confidence
                suggestions.append(InboxSuggestion(
                    chat_id=chat_row["id"],
                    title=chat_row.get("title", ""),
                    file_path=chat_row.get("file_path", ""),
                    suggested_project="",
                    confidence="low",
                    reason="No tag overlap with existing projects",
                ))
    finally:
        db.close()

    return suggestions


def _match_by_tags(
    chat_row: dict,
    chat_tags: set[str],
    project_tags: dict[str, set[str]],
    project_names: dict[str, str],
) -> InboxSuggestion | None:
    """Match inbox chat to project by tag overlap."""
    if not chat_tags:
        return None

    best_project = ""
    best_overlap = 0
    best_total = 0

    for pid, ptags in project_tags.items():
        if not ptags:
            continue
        overlap = len(chat_tags & ptags)
        if overlap > best_overlap or (overlap == best_overlap and len(ptags) < best_total):
            best_overlap = overlap
            best_project = pid
            best_total = len(ptags)

    if best_overlap == 0:
        return None

    confidence = "high" if best_overlap >= 3 else "medium" if best_overlap >= 1 else "low"
    matching_tags = chat_tags & project_tags.get(best_project, set())

    return InboxSuggestion(
        chat_id=chat_row["id"],
        title=chat_row.get("title", ""),
        file_path=chat_row.get("file_path", ""),
        suggested_project=project_names.get(best_project, best_project),
        confidence=confidence,
        reason=f"Tag overlap: {', '.join(sorted(matching_tags))}",
    )


def _suggest_via_llm(
    home: Path, chat_row: dict, project_names: list[str]
) -> InboxSuggestion | None:
    """Suggest project via LLM categorization."""
    try:
        from anticlaw.core.storage import ChatStorage
        from anticlaw.llm.ollama_client import OllamaClient, OllamaNotAvailable
        from anticlaw.llm.tagger import auto_categorize

        file_path = Path(chat_row["file_path"])
        if not file_path.exists():
            return None

        storage = ChatStorage(home)
        chat = storage.read_chat(file_path, load_messages=True)
        client = OllamaClient()

        if not client.is_available():
            return None

        suggested = auto_categorize(
            chat, existing_projects=project_names, client=client
        )
        if suggested:
            return InboxSuggestion(
                chat_id=chat_row["id"],
                title=chat_row.get("title", ""),
                file_path=chat_row.get("file_path", ""),
                suggested_project=suggested,
                confidence="medium",
                reason="LLM categorization",
            )
    except Exception:
        log.debug("LLM suggestion failed for %s", chat_row.get("id"), exc_info=True)

    return None


# --- Stale detection ---


def find_stale(
    home: Path,
    *,
    days: int = 30,
) -> list[StaleProject]:
    """Find projects with no activity for more than N days.

    Args:
        home: ACL_HOME path.
        days: Inactivity threshold in days.

    Returns:
        List of stale projects.
    """
    db_path = home / ".acl" / "meta.db"
    if not db_path.exists():
        return []

    now = datetime.now(timezone.utc)
    db = MetaDB(db_path)
    stale: list[StaleProject] = []

    try:
        projects = db.list_projects()
        for p in projects:
            pid = p["id"]
            chats = db.list_chats(pid)
            if not chats:
                # Empty project — check project's own updated date
                p_updated = p.get("updated", "")
                if p_updated:
                    try:
                        dt = datetime.fromisoformat(p_updated.replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        days_inactive = (now - dt).days
                        if days_inactive >= days:
                            stale.append(StaleProject(
                                project_id=pid,
                                name=p.get("name", pid),
                                last_activity=p_updated,
                                days_inactive=days_inactive,
                                chat_count=0,
                            ))
                    except (ValueError, TypeError):
                        pass
                continue

            # Find most recent activity across all chats
            latest = ""
            for c in chats:
                updated = c.get("updated", "")
                if updated > latest:
                    latest = updated

            if not latest:
                continue

            try:
                dt = datetime.fromisoformat(latest.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                days_inactive = (now - dt).days
                if days_inactive >= days:
                    stale.append(StaleProject(
                        project_id=pid,
                        name=p.get("name", pid),
                        last_activity=latest,
                        days_inactive=days_inactive,
                        chat_count=len(chats),
                    ))
            except (ValueError, TypeError):
                continue
    finally:
        db.close()

    # Sort by days inactive descending
    stale.sort(key=lambda s: s.days_inactive, reverse=True)
    return stale


# --- Duplicate detection ---


def find_duplicates(
    home: Path,
    *,
    threshold: float = 0.9,
    max_pairs: int = 20,
) -> list[DuplicatePair]:
    """Find pairs of chats with high semantic similarity.

    Requires ChromaDB vector index with pre-computed embeddings.
    Falls back to title-based duplicate detection if vectors unavailable.

    Args:
        home: ACL_HOME path.
        threshold: Similarity threshold (0-1, higher = more similar).
        max_pairs: Maximum number of pairs to return.

    Returns:
        List of duplicate pairs sorted by similarity descending.
    """
    pairs = _find_duplicates_semantic(home, threshold, max_pairs)
    if pairs is not None:
        return pairs

    # Fallback: title-based detection
    return _find_duplicates_by_title(home, max_pairs)


def _find_duplicates_semantic(
    home: Path, threshold: float, max_pairs: int
) -> list[DuplicatePair] | None:
    """Find duplicates using vector similarity via ChromaDB."""
    try:
        from anticlaw.core.index import VectorIndex
    except ImportError:
        return None

    vectors_dir = home / ".acl" / "vectors"
    if not vectors_dir.exists():
        return None

    try:
        vi = VectorIndex(vectors_dir)
        if vi.chat_count() < 2:
            return None
    except Exception:
        return None

    db_path = home / ".acl" / "meta.db"
    if not db_path.exists():
        return None

    db = MetaDB(db_path)
    pairs: list[DuplicatePair] = []
    seen: set[tuple[str, str]] = set()

    try:
        chats = db.list_chats()
        for chat_row in chats:
            if _normalize_status(chat_row.get("status", "")) != "active":
                continue
            chat_id = chat_row["id"]
            try:
                # Get this chat's embedding from ChromaDB
                record = vi._chats.get(ids=[chat_id], include=["embeddings"])
                if not record or not record["embeddings"]:
                    continue
                embedding = record["embeddings"][0]

                # Search for similar chats using the embedding
                results = vi.search_chats(embedding, n_results=5)
                if not results or "ids" not in results:
                    continue
                for rid, dist in zip(results["ids"][0], results["distances"][0]):
                    if rid == chat_id:
                        continue
                    # ChromaDB cosine distance: 0 = identical, 2 = opposite
                    similarity = 1.0 - (dist / 2.0)
                    if similarity < threshold:
                        continue
                    pair_key = tuple(sorted([chat_id, rid]))
                    if pair_key in seen:
                        continue
                    seen.add(pair_key)

                    other = db.get_chat(rid)
                    pairs.append(DuplicatePair(
                        chat_id_a=chat_id,
                        title_a=chat_row.get("title", ""),
                        chat_id_b=rid,
                        title_b=other.get("title", "") if other else "",
                        similarity=round(similarity, 3),
                    ))
            except Exception:
                continue

        pairs.sort(key=lambda p: p.similarity, reverse=True)
        return pairs[:max_pairs]
    finally:
        db.close()


def _find_duplicates_by_title(
    home: Path, max_pairs: int
) -> list[DuplicatePair]:
    """Fallback: find chats with very similar titles."""
    db_path = home / ".acl" / "meta.db"
    if not db_path.exists():
        return []

    try:
        from rapidfuzz import fuzz
    except ImportError:
        # Without rapidfuzz, do exact title match only
        return _find_exact_title_duplicates(home, max_pairs)

    db = MetaDB(db_path)
    pairs: list[DuplicatePair] = []
    seen: set[tuple[str, str]] = set()

    try:
        chats = [c for c in db.list_chats() if _normalize_status(c.get("status", "")) == "active"]
        for i, a in enumerate(chats):
            for b in chats[i + 1:]:
                title_a = a.get("title", "")
                title_b = b.get("title", "")
                if not title_a or not title_b:
                    continue
                ratio = fuzz.ratio(title_a.lower(), title_b.lower()) / 100.0
                if ratio >= 0.9:
                    pair_key = tuple(sorted([a["id"], b["id"]]))
                    if pair_key not in seen:
                        seen.add(pair_key)
                        pairs.append(DuplicatePair(
                            chat_id_a=a["id"],
                            title_a=title_a,
                            chat_id_b=b["id"],
                            title_b=title_b,
                            similarity=round(ratio, 3),
                        ))
        pairs.sort(key=lambda p: p.similarity, reverse=True)
        return pairs[:max_pairs]
    finally:
        db.close()


def _find_exact_title_duplicates(
    home: Path, max_pairs: int
) -> list[DuplicatePair]:
    """Find chats with exactly the same title (no deps needed)."""
    db_path = home / ".acl" / "meta.db"
    if not db_path.exists():
        return []

    db = MetaDB(db_path)
    pairs: list[DuplicatePair] = []
    seen: set[tuple[str, str]] = set()

    try:
        chats = [c for c in db.list_chats() if _normalize_status(c.get("status", "")) == "active"]
        titles: dict[str, list[dict]] = {}
        for c in chats:
            t = (c.get("title") or "").strip().lower()
            if t:
                titles.setdefault(t, []).append(c)

        for t, group in titles.items():
            if len(group) < 2:
                continue
            for i, a in enumerate(group):
                for b in group[i + 1:]:
                    pair_key = tuple(sorted([a["id"], b["id"]]))
                    if pair_key not in seen:
                        seen.add(pair_key)
                        pairs.append(DuplicatePair(
                            chat_id_a=a["id"],
                            title_a=a.get("title", ""),
                            chat_id_b=b["id"],
                            title_b=b.get("title", ""),
                            similarity=1.0,
                        ))
        return pairs[:max_pairs]
    finally:
        db.close()


# --- Health check ---


def health_check(home: Path) -> HealthReport:
    """Run a full integrity check on the knowledge base.

    Checks for:
    1. Orphan files: .md files on disk not in meta.db
    2. Missing metadata: records in meta.db pointing to nonexistent files
    3. Broken links: chats referencing projects that don't exist
    4. Unindexed chats: files that exist but aren't in the FTS index

    Args:
        home: ACL_HOME path.

    Returns:
        HealthReport with list of issues found.
    """
    report = HealthReport()

    db_path = home / ".acl" / "meta.db"
    if not db_path.exists():
        report.issues.append(HealthIssue(
            category="missing_metadata",
            severity="error",
            message="meta.db not found — run 'aw reindex'",
        ))
        return report

    db = MetaDB(db_path)
    try:
        # Collect all DB records
        db_chats = db.list_chats()
        db_projects = db.list_projects()
        report.indexed_chats = len(db_chats)
        report.total_projects = len(db_projects)
        report.total_insights = db.count_insights()

        db_chat_paths: set[str] = set()
        db_project_ids: set[str] = set()

        for p in db_projects:
            db_project_ids.add(p["id"])

        for c in db_chats:
            fp = c.get("file_path", "")
            if fp:
                db_chat_paths.add(fp)

        # 1. Scan filesystem for all .md files
        disk_files: set[str] = set()
        dirs_to_scan = []

        if (home / "_inbox").exists():
            dirs_to_scan.append(home / "_inbox")
        if (home / "_archive").exists():
            dirs_to_scan.append(home / "_archive")

        for entry in sorted(home.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name in _RESERVED_DIRS or entry.name.startswith("."):
                continue
            dirs_to_scan.append(entry)

        for d in dirs_to_scan:
            for md_file in d.glob("*.md"):
                if md_file.name.startswith("_"):
                    continue
                disk_files.add(str(md_file))

        report.total_chats = len(disk_files)

        # Check 1: Orphan files (on disk, not in DB)
        for fp in disk_files:
            if fp not in db_chat_paths:
                report.issues.append(HealthIssue(
                    category="orphan_file",
                    severity="warning",
                    message=f"File not indexed: {Path(fp).name}",
                    file_path=fp,
                ))

        # Check 2: Missing files (in DB, not on disk)
        for c in db_chats:
            fp = c.get("file_path", "")
            if not fp:
                continue
            if _normalize_status(c.get("status", "")) == "purged":
                continue
            if not Path(fp).exists():
                report.issues.append(HealthIssue(
                    category="missing_metadata",
                    severity="error",
                    message=f"Indexed file missing from disk: {Path(fp).name}",
                    file_path=fp,
                ))

        # Check 3: Broken project links
        for c in db_chats:
            pid = c.get("project_id", "")
            if not pid or pid == "_inbox" or pid == "_archive":
                continue
            if pid not in db_project_ids:
                # Check if directory exists
                project_dir = home / pid
                if not project_dir.exists():
                    report.issues.append(HealthIssue(
                        category="broken_link",
                        severity="warning",
                        message=f"Chat {c['id'][:8]} references nonexistent project '{pid}'",
                        file_path=c.get("file_path", ""),
                    ))

        # Check 4: Unindexed chats (in FTS but missing, or in DB without FTS)
        for c in db_chats:
            if _normalize_status(c.get("status", "")) == "purged":
                continue
            fts_row = db.conn.execute(
                "SELECT chat_id FROM chats_fts WHERE chat_id = ?",
                (c["id"],),
            ).fetchone()
            if not fts_row:
                report.issues.append(HealthIssue(
                    category="unindexed",
                    severity="warning",
                    message=f"Chat {c['id'][:8]} not in FTS index",
                    file_path=c.get("file_path", ""),
                ))

    finally:
        db.close()

    return report


# --- KB Statistics ---


def kb_stats(home: Path) -> KBStats:
    """Gather global knowledge base statistics.

    Args:
        home: ACL_HOME path.

    Returns:
        KBStats with counts and top tags.
    """
    stats = KBStats()

    db_path = home / ".acl" / "meta.db"
    if not db_path.exists():
        return stats

    db = MetaDB(db_path)
    try:
        chats = db.list_chats()
        projects = db.list_projects()
        stats.total_chats = len(chats)
        stats.total_projects = len(projects)
        stats.total_insights = db.count_insights()

        # Count by status
        tag_counter: dict[str, int] = {}
        for c in chats:
            status = _normalize_status(c.get("status", "active"))
            pid = c.get("project_id", "")
            if pid == "_inbox":
                stats.inbox_chats += 1
            if status == "archived":
                stats.archived_chats += 1

            # Count messages
            mc = c.get("message_count") or 0
            stats.total_messages += mc

            # Count tags
            tags = json.loads(c.get("tags") or "[]")
            for t in tags:
                tag_counter[t] = tag_counter.get(t, 0) + 1

        stats.total_tags = len(tag_counter)
        # Top 10 tags
        stats.top_tags = sorted(
            tag_counter.items(), key=lambda x: x[1], reverse=True
        )[:10]
    finally:
        db.close()

    return stats
