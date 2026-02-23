"""Tests for search_unified() in anticlaw.core.search."""

from datetime import datetime, timezone
from pathlib import Path

from anticlaw.core.meta_db import MetaDB
from anticlaw.core.models import Chat, ChatMessage, Insight, SourceDocument, Status
from anticlaw.core.search import search_unified


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


def _make_source_doc(id: str, content: str, filename: str = "file.py") -> SourceDocument:
    return SourceDocument(
        id=id,
        file_path=f"/code/{filename}",
        filename=filename,
        extension=".py",
        language="python",
        content=content,
        size=len(content),
        hash="testhash",
        indexed_at=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
    )


class TestSearchUnified:
    def test_searches_chats(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        chat = _make_chat("c1", "JWT authentication flow")
        db.index_chat(chat, tmp_path / "c1.md", "proj")

        results = search_unified(db, "JWT")
        chat_results = [r for r in results if r.result_type == "chat"]
        assert len(chat_results) == 1
        assert chat_results[0].chat_id == "c1"
        db.close()

    def test_searches_source_files(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        doc = _make_source_doc("src-1", "JWT token validation logic")
        db.index_source_file(doc)

        results = search_unified(db, "JWT")
        file_results = [r for r in results if r.result_type == "file"]
        assert len(file_results) == 1
        assert file_results[0].chat_id == "src-1"
        db.close()

    def test_searches_insights(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        insight = Insight(id="ins-1", content="JWT is the best approach for auth")
        db.add_insight(insight)

        results = search_unified(db, "JWT")
        insight_results = [r for r in results if r.result_type == "insight"]
        assert len(insight_results) == 1
        assert insight_results[0].chat_id == "ins-1"
        db.close()

    def test_searches_all_types_together(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")

        chat = _make_chat("c1", "JWT authentication flow")
        db.index_chat(chat, tmp_path / "c1.md", "proj")

        doc = _make_source_doc("src-1", "JWT token validation logic")
        db.index_source_file(doc)

        insight = Insight(id="ins-1", content="JWT is the best approach")
        db.add_insight(insight)

        results = search_unified(db, "JWT")
        types = {r.result_type for r in results}
        assert "chat" in types
        assert "file" in types
        assert "insight" in types
        db.close()

    def test_filter_by_result_type(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")

        chat = _make_chat("c1", "shared keyword topic")
        db.index_chat(chat, tmp_path / "c1.md")

        doc = _make_source_doc("src-1", "shared keyword topic")
        db.index_source_file(doc)

        # Only chats
        results = search_unified(db, "shared", result_types=["chat"])
        assert all(r.result_type == "chat" for r in results)

        # Only files
        results = search_unified(db, "shared", result_types=["file"])
        assert all(r.result_type == "file" for r in results)
        db.close()

    def test_max_results(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        for i in range(10):
            chat = _make_chat(f"c{i}", f"shared keyword content {i}")
            db.index_chat(chat, tmp_path / f"c{i}.md")

        results = search_unified(db, "shared", max_results=5)
        assert len(results) <= 5
        db.close()

    def test_empty_db(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        results = search_unified(db, "anything")
        assert results == []
        db.close()

    def test_results_sorted_by_score(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        # Add multiple items so we can check sorting
        for i in range(3):
            chat = _make_chat(f"c{i}", f"keyword topic content {i}")
            db.index_chat(chat, tmp_path / f"c{i}.md")

        results = search_unified(db, "keyword")
        if len(results) >= 2:
            scores = [abs(r.score) for r in results]
            assert scores == sorted(scores, reverse=True)
        db.close()
