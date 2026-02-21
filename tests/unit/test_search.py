"""Tests for anticlaw.core.search."""

from datetime import datetime, timezone
from pathlib import Path

from anticlaw.core.meta_db import MetaDB
from anticlaw.core.models import Chat, ChatMessage, Status
from anticlaw.core.search import search


def _make_chat(id: str, content: str, tags: list | None = None) -> Chat:
    return Chat(
        id=id,
        title=f"Chat {id}",
        created=datetime(2025, 2, 18, 14, 30, tzinfo=timezone.utc),
        updated=datetime(2025, 2, 18, 15, 0, tzinfo=timezone.utc),
        provider="claude",
        tags=tags or [],
        importance="medium",
        status=Status.ACTIVE,
        messages=[ChatMessage(role="human", content=content)],
    )


class TestSearchDispatcher:
    def test_search_basic(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        chat = _make_chat("c1", "JWT authentication flow")
        db.index_chat(chat, tmp_path / "c1.md", "proj")

        results = search(db, "JWT")
        assert len(results) == 1
        assert results[0].chat_id == "c1"
        db.close()

    def test_search_with_project_filter(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        db.index_chat(_make_chat("c1", "auth topic"), tmp_path / "a.md", "proj-a")
        db.index_chat(_make_chat("c2", "auth topic"), tmp_path / "b.md", "proj-b")

        results = search(db, "auth", project="proj-a")
        assert len(results) == 1
        assert results[0].chat_id == "c1"
        db.close()

    def test_search_with_tag_filter(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        db.index_chat(
            _make_chat("c1", "auth topic", tags=["security"]),
            tmp_path / "a.md",
        )
        db.index_chat(
            _make_chat("c2", "auth topic", tags=["database"]),
            tmp_path / "b.md",
        )

        results = search(db, "auth", tags=["security"])
        assert len(results) == 1
        assert results[0].chat_id == "c1"
        db.close()

    def test_search_exact(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        db.index_chat(_make_chat("c1", "implement JWT tokens"), tmp_path / "a.md")

        results = search(db, "JWT tokens", exact=True)
        assert len(results) == 1

        results = search(db, "tokens JWT", exact=True)
        assert len(results) == 0
        db.close()

    def test_search_empty(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        results = search(db, "anything")
        assert results == []
        db.close()

    def test_search_max_results(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        for i in range(10):
            db.index_chat(
                _make_chat(f"c{i}", "shared keyword topic"),
                tmp_path / f"c{i}.md",
            )

        results = search(db, "keyword", max_results=5)
        assert len(results) == 5
        db.close()
