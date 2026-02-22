"""Tests for anticlaw.core.antientropy."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anticlaw.core.antientropy import (
    DuplicatePair,
    HealthIssue,
    InboxSuggestion,
    KBStats,
    StaleProject,
    find_duplicates,
    find_stale,
    health_check,
    inbox_suggestions,
    kb_stats,
    _find_exact_title_duplicates,
    _match_by_tags,
)
from anticlaw.core.meta_db import MetaDB
from anticlaw.core.models import Chat, ChatMessage, Project
from anticlaw.core.storage import ChatStorage


def _setup_home(tmp_path: Path) -> Path:
    """Create a home with projects and inbox chats."""
    home = tmp_path / "home"
    storage = ChatStorage(home)
    storage.init_home()

    # Project alpha with tags
    project_dir = storage.create_project("alpha", "Auth project")
    alpha_proj = storage.read_project(project_dir / "_project.yaml")
    alpha_proj.tags = ["auth", "jwt", "security"]
    storage.write_project(project_dir / "_project.yaml", alpha_proj)

    alpha_chat = Chat(
        id="alpha-001",
        title="Auth Discussion",
        provider="claude",
        tags=["auth", "jwt"],
        created=datetime.now(timezone.utc) - timedelta(days=5),
        updated=datetime.now(timezone.utc) - timedelta(days=5),
        messages=[ChatMessage(role="human", content="JWT vs sessions?")],
        message_count=1,
    )
    storage.write_chat(project_dir / "2025-02-18_auth.md", alpha_chat)

    # Project beta — stale
    beta_dir = storage.create_project("beta", "Old project")
    beta_chat = Chat(
        id="beta-001",
        title="Old Design",
        provider="claude",
        tags=["design"],
        created=datetime.now(timezone.utc) - timedelta(days=60),
        updated=datetime.now(timezone.utc) - timedelta(days=60),
        messages=[ChatMessage(role="human", content="Old design stuff")],
        message_count=1,
    )
    storage.write_chat(beta_dir / "2025-01-01_old-design.md", beta_chat)

    # Inbox chats
    inbox_tagged = Chat(
        id="inbox-001",
        title="Security Chat",
        provider="claude",
        tags=["auth", "security"],
        messages=[ChatMessage(role="human", content="About security")],
        message_count=1,
    )
    storage.write_chat(home / "_inbox" / "2025-02-19_security.md", inbox_tagged)

    inbox_no_tags = Chat(
        id="inbox-002",
        title="Random Chat",
        provider="claude",
        tags=[],
        messages=[ChatMessage(role="human", content="Something random")],
        message_count=1,
    )
    storage.write_chat(home / "_inbox" / "2025-02-19_random.md", inbox_no_tags)

    # Build index
    db = MetaDB(home / ".acl" / "meta.db")
    db.reindex_all(home)
    db.close()

    return home


# --- Inbox Suggestion Tests ---


class TestInboxSuggestions:
    def test_suggests_project_by_tags(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        suggestions = inbox_suggestions(home)
        assert len(suggestions) >= 1

        # inbox-001 has auth+security tags, should match alpha
        s001 = [s for s in suggestions if s.chat_id == "inbox-001"]
        assert len(s001) == 1
        assert "alpha" in s001[0].suggested_project.lower()

    def test_no_suggestion_for_untagged(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        suggestions = inbox_suggestions(home)
        s002 = [s for s in suggestions if s.chat_id == "inbox-002"]
        assert len(s002) == 1
        assert s002[0].confidence == "low"

    def test_empty_inbox(self, tmp_path: Path):
        home = tmp_path / "empty_inbox"
        storage = ChatStorage(home)
        storage.init_home()
        storage.create_project("test", "Test")
        db = MetaDB(home / ".acl" / "meta.db")
        db.reindex_all(home)
        db.close()

        suggestions = inbox_suggestions(home)
        assert len(suggestions) == 0

    def test_no_db(self, tmp_path: Path):
        home = tmp_path / "nodb"
        home.mkdir()
        suggestions = inbox_suggestions(home)
        assert len(suggestions) == 0

    def test_suggestion_confidence(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        suggestions = inbox_suggestions(home)
        for s in suggestions:
            assert s.confidence in ("high", "medium", "low")

    def test_suggestion_has_reason(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        suggestions = inbox_suggestions(home)
        for s in suggestions:
            assert s.reason


class TestMatchByTags:
    def test_match_high_overlap(self):
        chat_row = {"id": "test-1", "title": "Test", "file_path": "/test.md"}
        chat_tags = {"auth", "jwt", "security"}
        project_tags = {"alpha": {"auth", "jwt", "security", "api"}}
        project_names = {"alpha": "Alpha"}
        result = _match_by_tags(chat_row, chat_tags, project_tags, project_names)
        assert result is not None
        assert result.suggested_project == "Alpha"
        assert result.confidence == "high"

    def test_match_medium_overlap(self):
        chat_row = {"id": "test-1", "title": "Test", "file_path": "/test.md"}
        chat_tags = {"auth"}
        project_tags = {"alpha": {"auth", "jwt"}}
        project_names = {"alpha": "Alpha"}
        result = _match_by_tags(chat_row, chat_tags, project_tags, project_names)
        assert result is not None
        assert result.confidence == "medium"

    def test_no_match(self):
        chat_row = {"id": "test-1", "title": "Test", "file_path": "/test.md"}
        chat_tags = {"unrelated"}
        project_tags = {"alpha": {"auth", "jwt"}}
        project_names = {"alpha": "Alpha"}
        result = _match_by_tags(chat_row, chat_tags, project_tags, project_names)
        assert result is None

    def test_empty_chat_tags(self):
        chat_row = {"id": "test-1", "title": "Test", "file_path": "/test.md"}
        result = _match_by_tags(chat_row, set(), {"alpha": {"auth"}}, {"alpha": "A"})
        assert result is None


# --- Stale Detection Tests ---


class TestFindStale:
    def test_finds_stale_project(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        stale = find_stale(home, days=30)
        assert len(stale) >= 1
        names = [s.name for s in stale]
        assert "beta" in [n.lower() for n in names]

    def test_recent_not_stale(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        stale = find_stale(home, days=30)
        names = [s.name.lower() for s in stale]
        assert "alpha" not in names

    def test_custom_days_threshold(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        # Very low threshold — both projects inactive for at least 1 day
        stale = find_stale(home, days=1)
        assert len(stale) >= 1

    def test_high_threshold(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        stale = find_stale(home, days=9999)
        assert len(stale) == 0

    def test_no_db(self, tmp_path: Path):
        home = tmp_path / "nodb"
        home.mkdir()
        stale = find_stale(home, days=30)
        assert len(stale) == 0

    def test_stale_sorted_by_inactivity(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        stale = find_stale(home, days=1)
        if len(stale) >= 2:
            assert stale[0].days_inactive >= stale[1].days_inactive

    def test_stale_has_chat_count(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        stale = find_stale(home, days=30)
        for sp in stale:
            assert sp.chat_count >= 0


# --- Duplicate Detection Tests ---


class TestFindDuplicates:
    def test_exact_title_duplicates(self, tmp_path: Path):
        home = tmp_path / "dupes"
        storage = ChatStorage(home)
        storage.init_home()
        project_dir = storage.create_project("test", "Test")

        for i in range(2):
            chat = Chat(
                id=f"dupe-{i:03d}",
                title="Same Title Here",
                provider="claude",
                messages=[ChatMessage(role="human", content=f"Content {i}")],
            )
            storage.write_chat(project_dir / f"2025-02-{18+i}_same-title-{i}.md", chat)

        db = MetaDB(home / ".acl" / "meta.db")
        db.reindex_all(home)
        db.close()

        pairs = find_duplicates(home)
        assert len(pairs) >= 1
        assert pairs[0].similarity >= 0.9

    def test_no_duplicates(self, tmp_path: Path):
        home = tmp_path / "nodupes"
        storage = ChatStorage(home)
        storage.init_home()
        project_dir = storage.create_project("test", "Test")

        for i, title in enumerate(["Completely Different", "Totally Unique"]):
            chat = Chat(
                id=f"unique-{i:03d}",
                title=title,
                provider="claude",
                messages=[ChatMessage(role="human", content=f"Content {i}")],
            )
            storage.write_chat(project_dir / f"2025-02-{18+i}_{title.lower().replace(' ', '-')}.md", chat)

        db = MetaDB(home / ".acl" / "meta.db")
        db.reindex_all(home)
        db.close()

        pairs = find_duplicates(home)
        assert len(pairs) == 0

    def test_no_db(self, tmp_path: Path):
        home = tmp_path / "nodb"
        home.mkdir()
        pairs = find_duplicates(home)
        assert len(pairs) == 0


class TestFindExactTitleDuplicates:
    def test_finds_exact_matches(self, tmp_path: Path):
        home = tmp_path / "exact"
        storage = ChatStorage(home)
        storage.init_home()
        project_dir = storage.create_project("test", "Test")

        for i in range(3):
            chat = Chat(
                id=f"exact-{i:03d}",
                title="Exact Same",
                provider="claude",
                messages=[ChatMessage(role="human", content=f"Content {i}")],
            )
            storage.write_chat(project_dir / f"2025-02-{18+i}_exact-{i}.md", chat)

        db = MetaDB(home / ".acl" / "meta.db")
        db.reindex_all(home)
        db.close()

        pairs = _find_exact_title_duplicates(home, max_pairs=10)
        # 3 chats with same title → 3 pairs (C(3,2) = 3)
        assert len(pairs) == 3
        for p in pairs:
            assert p.similarity == 1.0


# --- Health Check Tests ---


class TestHealthCheck:
    def test_clean_kb(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        report = health_check(home)
        assert report.total_projects >= 1
        assert report.indexed_chats >= 1
        # A healthy KB should have no errors (some warnings may exist)
        errors = [i for i in report.issues if i.severity == "error"]
        assert len(errors) == 0

    def test_orphan_file(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        # Add a file not in the index
        orphan = home / "alpha" / "2025-02-20_orphan.md"
        orphan.write_text("---\nid: orphan-001\ntitle: Orphan\n---\n## Human\nHello\n")

        report = health_check(home)
        orphan_issues = [i for i in report.issues if i.category == "orphan_file"]
        assert len(orphan_issues) >= 1

    def test_missing_file(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        # Remove a file that's still in the index
        alpha_dir = home / "alpha"
        md_files = list(alpha_dir.glob("*.md"))
        if md_files:
            md_files[0].unlink()

        report = health_check(home)
        missing = [i for i in report.issues if i.category == "missing_metadata"]
        assert len(missing) >= 1

    def test_no_db(self, tmp_path: Path):
        home = tmp_path / "nodb"
        home.mkdir()
        report = health_check(home)
        assert len(report.issues) >= 1
        assert report.issues[0].category == "missing_metadata"
        assert report.issues[0].severity == "error"

    def test_report_counts(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        report = health_check(home)
        assert report.total_projects >= 1
        assert report.indexed_chats >= 1
        assert isinstance(report.total_insights, int)

    def test_broken_project_link(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        # Add a chat with a nonexistent project reference
        db = MetaDB(home / ".acl" / "meta.db")
        db.conn.execute(
            """INSERT OR REPLACE INTO chats
               (id, title, project_id, provider, remote_id, created, updated,
                tags, summary, importance, status, file_path, token_count,
                message_count, content)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "broken-001", "Broken Link", "nonexistent-project", "claude", "",
                "2025-02-18T00:00:00Z", "2025-02-18T00:00:00Z", "[]", "",
                "medium", "active", str(home / "nonexistent-project" / "test.md"),
                0, 1, "test",
            ),
        )
        db.conn.commit()
        db.close()

        report = health_check(home)
        broken = [i for i in report.issues if i.category == "broken_link"]
        assert len(broken) >= 1


# --- KB Stats Tests ---


class TestKBStats:
    def test_basic_stats(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        stats = kb_stats(home)
        assert stats.total_projects >= 2
        assert stats.total_chats >= 3  # alpha + beta + 2 inbox
        assert stats.inbox_chats >= 2
        assert stats.total_messages >= 1

    def test_top_tags(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        stats = kb_stats(home)
        assert stats.total_tags >= 1
        assert len(stats.top_tags) >= 1
        # Tags should be (name, count) tuples
        for tag, count in stats.top_tags:
            assert isinstance(tag, str)
            assert isinstance(count, int)
            assert count >= 1

    def test_empty_kb(self, tmp_path: Path):
        home = tmp_path / "empty"
        storage = ChatStorage(home)
        storage.init_home()
        db = MetaDB(home / ".acl" / "meta.db")
        db.reindex_all(home)
        db.close()

        stats = kb_stats(home)
        assert stats.total_chats == 0
        assert stats.total_projects == 0

    def test_no_db(self, tmp_path: Path):
        home = tmp_path / "nodb"
        home.mkdir()
        stats = kb_stats(home)
        assert stats.total_chats == 0
