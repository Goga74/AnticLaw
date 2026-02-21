"""Tests for ChromaDB vector index."""

from pathlib import Path

import pytest

chromadb = pytest.importorskip("chromadb")

from anticlaw.core.index import (
    VectorIndex,
    index_chat_vectors,
    index_insight_vectors,
    reindex_vectors,
)
from anticlaw.core.meta_db import MetaDB
from anticlaw.core.models import Chat, ChatMessage, Insight, Status

from datetime import datetime, timezone


class MockEmbedder:
    """Keyword-based mock embedder for testing."""

    _keywords = [
        "jwt", "auth", "token", "database", "sqlite", "schema",
        "python", "api", "design", "pattern", "security", "management",
    ]

    @property
    def name(self) -> str:
        return "mock"

    def embed(self, text: str) -> list[float]:
        text_lower = text.lower()
        return [1.0 if kw in text_lower else 0.01 for kw in self._keywords]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


def _make_chat(id: str, content: str, title: str = "") -> Chat:
    return Chat(
        id=id,
        title=title or f"Chat {id}",
        created=datetime(2025, 2, 18, 14, 30, tzinfo=timezone.utc),
        updated=datetime(2025, 2, 18, 15, 0, tzinfo=timezone.utc),
        provider="claude",
        tags=[],
        importance="medium",
        status=Status.ACTIVE,
        messages=[ChatMessage(role="human", content=content)],
    )


class TestVectorIndex:
    def test_create_index(self, tmp_path: Path):
        idx = VectorIndex(tmp_path / "vectors")
        assert idx.chat_count() == 0
        assert idx.insight_count() == 0

    def test_index_and_search_chat(self, tmp_path: Path):
        idx = VectorIndex(tmp_path / "vectors")
        embedding = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        idx.index_chat("c1", "Auth Chat", "proj-a", "/path/c1.md", "JWT auth", embedding)

        assert idx.chat_count() == 1

        results = idx.search_chats([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        assert len(results["ids"][0]) == 1
        assert results["ids"][0][0] == "c1"
        assert results["metadatas"][0][0]["title"] == "Auth Chat"

    def test_upsert_chat(self, tmp_path: Path):
        idx = VectorIndex(tmp_path / "vectors")
        emb = [1.0, 0.0, 0.0, 0.0]
        idx.index_chat("c1", "v1", "proj", "/p", "content", emb)
        idx.index_chat("c1", "v2", "proj", "/p", "content", emb)
        assert idx.chat_count() == 1
        results = idx.search_chats(emb)
        assert results["metadatas"][0][0]["title"] == "v2"

    def test_search_with_project_filter(self, tmp_path: Path):
        idx = VectorIndex(tmp_path / "vectors")
        emb_a = [1.0, 0.0, 0.0, 0.0]
        emb_b = [0.0, 1.0, 0.0, 0.0]
        idx.index_chat("c1", "Chat A", "proj-a", "/a.md", "content a", emb_a)
        idx.index_chat("c2", "Chat B", "proj-b", "/b.md", "content b", emb_b)

        results = idx.search_chats(emb_a, project="proj-a")
        ids = results["ids"][0]
        assert "c1" in ids
        assert "c2" not in ids

    def test_search_empty_collection(self, tmp_path: Path):
        idx = VectorIndex(tmp_path / "vectors")
        results = idx.search_chats([1.0, 0.0, 0.0])
        assert results["ids"] == [[]]

    def test_index_and_search_insight(self, tmp_path: Path):
        idx = VectorIndex(tmp_path / "vectors")
        emb = [0.5, 0.5, 0.0, 0.0]
        idx.index_insight("i1", "Use JWT for auth", emb)

        assert idx.insight_count() == 1
        results = idx.search_insights(emb)
        assert results["ids"][0][0] == "i1"

    def test_clear(self, tmp_path: Path):
        idx = VectorIndex(tmp_path / "vectors")
        emb = [1.0, 0.0, 0.0]
        idx.index_chat("c1", "title", "proj", "/p", "text", emb)
        idx.index_insight("i1", "insight", emb)

        assert idx.chat_count() == 1
        assert idx.insight_count() == 1

        idx.clear()
        assert idx.chat_count() == 0
        assert idx.insight_count() == 0

    def test_n_results_clamped(self, tmp_path: Path):
        idx = VectorIndex(tmp_path / "vectors")
        emb = [1.0, 0.0]
        idx.index_chat("c1", "t", "p", "/p", "x", emb)

        # Request more results than available
        results = idx.search_chats(emb, n_results=100)
        assert len(results["ids"][0]) == 1


class TestIndexHelpers:
    def test_index_chat_vectors(self, tmp_path: Path):
        idx = VectorIndex(tmp_path / "vectors")
        embedder = MockEmbedder()

        index_chat_vectors(idx, embedder, "c1", "Auth", "proj", "/p", "JWT auth")
        assert idx.chat_count() == 1

    def test_index_chat_vectors_empty_content(self, tmp_path: Path):
        idx = VectorIndex(tmp_path / "vectors")
        embedder = MockEmbedder()

        index_chat_vectors(idx, embedder, "c1", "Empty", "proj", "/p", "   ")
        assert idx.chat_count() == 0  # skipped

    def test_index_insight_vectors(self, tmp_path: Path):
        idx = VectorIndex(tmp_path / "vectors")
        embedder = MockEmbedder()

        index_insight_vectors(idx, embedder, "i1", "Use SQLite for storage")
        assert idx.insight_count() == 1

    def test_reindex_vectors(self, tmp_path: Path):
        home = tmp_path / "anticlaw"
        home.mkdir()
        db = MetaDB(home / ".acl" / "meta.db")

        # Index some chats in MetaDB
        c1 = _make_chat("c1", "JWT authentication flow", "Auth Chat")
        c2 = _make_chat("c2", "Database schema design", "DB Chat")
        db.index_chat(c1, home / "c1.md", "proj")
        db.index_chat(c2, home / "c2.md", "proj")

        # Add an insight
        insight = Insight(content="Use JWT tokens for API auth")
        db.add_insight(insight)

        embedder = MockEmbedder()
        chats, insights = reindex_vectors(home, db, embedder)

        assert chats == 2
        assert insights == 1

        # Verify the vectors are searchable
        from anticlaw.core.index import VectorIndex
        idx = VectorIndex(home / ".acl" / "vectors")
        assert idx.chat_count() == 2
        assert idx.insight_count() == 1

        db.close()

    def test_reindex_vectors_skips_empty(self, tmp_path: Path):
        home = tmp_path / "anticlaw"
        home.mkdir()
        db = MetaDB(home / ".acl" / "meta.db")

        # Chat with empty content
        c1 = _make_chat("c1", "")
        c1.messages = []
        db.index_chat(c1, home / "c1.md", "proj")

        embedder = MockEmbedder()
        chats, insights = reindex_vectors(home, db, embedder)
        assert chats == 0
        assert insights == 0

        db.close()
