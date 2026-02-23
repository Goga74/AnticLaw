"""Tests for advanced search tiers 2-5, fallback, auto-tier selection."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from anticlaw.core.meta_db import MetaDB
from anticlaw.core.models import Chat, ChatMessage, Status
from anticlaw.core.search import (
    _make_snippet,
    available_tiers,
    best_tier,
    search,
)


def _make_chat(
    id: str, content: str, tags: list | None = None, title: str | None = None,
) -> Chat:
    return Chat(
        id=id,
        title=title or f"Chat {id}",
        created=datetime(2025, 2, 18, 14, 30, tzinfo=timezone.utc),
        updated=datetime(2025, 2, 18, 15, 0, tzinfo=timezone.utc),
        provider="claude",
        tags=tags or [],
        importance="medium",
        status=Status.ACTIVE,
        messages=[ChatMessage(role="human", content=content)],
    )


def _setup_db(tmp_path: Path) -> MetaDB:
    """Create a MetaDB with test chats."""
    db = MetaDB(tmp_path / "meta.db")
    db.index_chat(
        _make_chat("c1", "JWT authentication and token management",
                    title="Auth Discussion"),
        tmp_path / "c1.md", "project-alpha",
    )
    db.index_chat(
        _make_chat("c2", "Database schema design with SQLite",
                    title="DB Design"),
        tmp_path / "c2.md", "project-alpha",
    )
    db.index_chat(
        _make_chat("c3", "Python API design patterns and best practices",
                    title="API Patterns"),
        tmp_path / "c3.md", "project-beta",
    )
    return db


# ---------------------------------------------------------------------------
# Mock embedder for semantic/hybrid tests
# ---------------------------------------------------------------------------

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


def _setup_vector_index(db: MetaDB, vectors_dir: Path) -> None:
    """Populate a ChromaDB vector index from MetaDB."""
    from anticlaw.core.index import VectorIndex, index_chat_vectors

    idx = VectorIndex(vectors_dir)
    embedder = MockEmbedder()
    for chat_dict in db.list_chats():
        content = chat_dict.get("content") or ""
        if content.strip():
            index_chat_vectors(
                idx, embedder,
                chat_dict["id"],
                chat_dict.get("title") or "",
                chat_dict.get("project_id") or "",
                chat_dict.get("file_path") or "",
                content,
            )


# ---------------------------------------------------------------------------
# Snippet helper
# ---------------------------------------------------------------------------

class TestMakeSnippet:
    def test_basic(self):
        snippet = _make_snippet("Hello world foo bar baz", "foo")
        assert "foo" in snippet

    def test_empty_content(self):
        assert _make_snippet("", "query") == ""

    def test_no_match(self):
        snippet = _make_snippet("Hello world", "missing")
        assert snippet.startswith("Hello")

    def test_truncation(self):
        content = "x" * 500
        snippet = _make_snippet(content, "missing", max_len=100)
        assert len(snippet) <= 104  # 100 + "..."

    def test_context_around_match(self):
        content = "A" * 100 + " target " + "B" * 100
        snippet = _make_snippet(content, "target", max_len=80)
        assert "target" in snippet
        assert snippet.startswith("...")


# ---------------------------------------------------------------------------
# Tier detection
# ---------------------------------------------------------------------------

class TestTierDetection:
    def test_keyword_always_available(self):
        assert "keyword" in available_tiers()

    def test_available_tiers_all_deps(self, monkeypatch):
        monkeypatch.setattr("anticlaw.core.search._has_bm25s", lambda: True)
        monkeypatch.setattr("anticlaw.core.search._has_rapidfuzz", lambda: True)
        monkeypatch.setattr("anticlaw.core.search._has_chromadb", lambda: True)
        tiers = available_tiers()
        assert tiers == ["keyword", "bm25", "fuzzy", "semantic", "hybrid"]

    def test_available_tiers_none(self, monkeypatch):
        monkeypatch.setattr("anticlaw.core.search._has_bm25s", lambda: False)
        monkeypatch.setattr("anticlaw.core.search._has_rapidfuzz", lambda: False)
        monkeypatch.setattr("anticlaw.core.search._has_chromadb", lambda: False)
        assert available_tiers() == ["keyword"]

    def test_available_tiers_bm25_only(self, monkeypatch):
        monkeypatch.setattr("anticlaw.core.search._has_bm25s", lambda: True)
        monkeypatch.setattr("anticlaw.core.search._has_rapidfuzz", lambda: False)
        monkeypatch.setattr("anticlaw.core.search._has_chromadb", lambda: False)
        assert available_tiers() == ["keyword", "bm25"]

    def test_best_tier_no_vectors(self, monkeypatch):
        monkeypatch.setattr("anticlaw.core.search._has_bm25s", lambda: True)
        monkeypatch.setattr("anticlaw.core.search._has_rapidfuzz", lambda: True)
        monkeypatch.setattr("anticlaw.core.search._has_chromadb", lambda: True)
        # Without vectors, should not select semantic/hybrid
        assert best_tier(has_vectors=False) == "fuzzy"

    def test_best_tier_with_vectors(self, monkeypatch):
        monkeypatch.setattr("anticlaw.core.search._has_bm25s", lambda: True)
        monkeypatch.setattr("anticlaw.core.search._has_rapidfuzz", lambda: True)
        monkeypatch.setattr("anticlaw.core.search._has_chromadb", lambda: True)
        assert best_tier(has_vectors=True) == "hybrid"

    def test_best_tier_only_bm25(self, monkeypatch):
        monkeypatch.setattr("anticlaw.core.search._has_bm25s", lambda: True)
        monkeypatch.setattr("anticlaw.core.search._has_rapidfuzz", lambda: False)
        monkeypatch.setattr("anticlaw.core.search._has_chromadb", lambda: False)
        assert best_tier(has_vectors=False) == "bm25"

    def test_best_tier_keyword_only(self, monkeypatch):
        monkeypatch.setattr("anticlaw.core.search._has_bm25s", lambda: False)
        monkeypatch.setattr("anticlaw.core.search._has_rapidfuzz", lambda: False)
        monkeypatch.setattr("anticlaw.core.search._has_chromadb", lambda: False)
        assert best_tier(has_vectors=False) == "keyword"

    def test_best_tier_semantic_no_bm25(self, monkeypatch):
        monkeypatch.setattr("anticlaw.core.search._has_bm25s", lambda: False)
        monkeypatch.setattr("anticlaw.core.search._has_rapidfuzz", lambda: False)
        monkeypatch.setattr("anticlaw.core.search._has_chromadb", lambda: True)
        # Without bm25, hybrid is not available; semantic is next best
        assert best_tier(has_vectors=True) == "semantic"


# ---------------------------------------------------------------------------
# Tier 2: BM25
# ---------------------------------------------------------------------------

class TestBM25Search:
    @pytest.fixture(autouse=True)
    def _skip_if_no_bm25s(self):
        pytest.importorskip("bm25s")

    def test_bm25_basic(self, tmp_path):
        db = _setup_db(tmp_path)
        results = search(db, "JWT authentication", tier="bm25")
        assert len(results) >= 1
        assert results[0].chat_id == "c1"
        db.close()

    def test_bm25_ranking(self, tmp_path):
        db = _setup_db(tmp_path)
        results = search(db, "database schema", tier="bm25")
        assert len(results) >= 1
        assert results[0].chat_id == "c2"
        db.close()

    def test_bm25_empty_db(self, tmp_path):
        db = MetaDB(tmp_path / "empty.db")
        results = search(db, "anything", tier="bm25")
        assert results == []
        db.close()

    def test_bm25_with_project_filter(self, tmp_path):
        db = _setup_db(tmp_path)
        results = search(db, "design", tier="bm25", project="project-beta")
        for r in results:
            assert r.project_id == "project-beta"
        db.close()

    def test_bm25_max_results(self, tmp_path):
        db = _setup_db(tmp_path)
        results = search(db, "design", tier="bm25", max_results=1)
        assert len(results) <= 1
        db.close()

    def test_bm25_score_positive(self, tmp_path):
        db = _setup_db(tmp_path)
        results = search(db, "JWT", tier="bm25")
        for r in results:
            assert r.score > 0
        db.close()

    def test_bm25_has_snippet(self, tmp_path):
        db = _setup_db(tmp_path)
        results = search(db, "JWT", tier="bm25")
        assert len(results) >= 1
        assert results[0].snippet  # non-empty
        db.close()


# ---------------------------------------------------------------------------
# Tier 3: Fuzzy
# ---------------------------------------------------------------------------

class TestFuzzySearch:
    @pytest.fixture(autouse=True)
    def _skip_if_no_rapidfuzz(self):
        pytest.importorskip("rapidfuzz")

    def test_fuzzy_basic(self, tmp_path):
        db = _setup_db(tmp_path)
        results = search(db, "authentication", tier="fuzzy")
        assert len(results) >= 1
        db.close()

    def test_fuzzy_typo_tolerance(self, tmp_path):
        db = _setup_db(tmp_path)
        # Misspelled query — should still find auth chat
        results = search(db, "autentication", tier="fuzzy")
        assert len(results) >= 1
        chat_ids = [r.chat_id for r in results]
        assert "c1" in chat_ids
        db.close()

    def test_fuzzy_empty_db(self, tmp_path):
        db = MetaDB(tmp_path / "empty.db")
        results = search(db, "anything", tier="fuzzy")
        assert results == []
        db.close()

    def test_fuzzy_score_normalized(self, tmp_path):
        db = _setup_db(tmp_path)
        results = search(db, "JWT", tier="fuzzy")
        for r in results:
            assert 0.0 <= r.score <= 1.0
        db.close()

    def test_fuzzy_with_project_filter(self, tmp_path):
        db = _setup_db(tmp_path)
        results = search(db, "design", tier="fuzzy", project="project-beta")
        for r in results:
            assert r.project_id == "project-beta"
        db.close()


# ---------------------------------------------------------------------------
# Tier 4: Semantic
# ---------------------------------------------------------------------------

class TestSemanticSearch:
    @pytest.fixture(autouse=True)
    def _skip_if_no_chromadb(self):
        pytest.importorskip("chromadb")

    def test_semantic_basic(self, tmp_path):
        db = _setup_db(tmp_path)
        vectors_dir = tmp_path / "vectors"
        _setup_vector_index(db, vectors_dir)
        embedder = MockEmbedder()

        results = search(
            db, "JWT authentication", tier="semantic",
            vectors_dir=vectors_dir, embedder=embedder,
        )
        assert len(results) >= 1
        assert results[0].chat_id == "c1"
        db.close()

    def test_semantic_different_query(self, tmp_path):
        db = _setup_db(tmp_path)
        vectors_dir = tmp_path / "vectors"
        _setup_vector_index(db, vectors_dir)
        embedder = MockEmbedder()

        results = search(
            db, "database schema SQLite", tier="semantic",
            vectors_dir=vectors_dir, embedder=embedder,
        )
        assert len(results) >= 1
        assert results[0].chat_id == "c2"
        db.close()

    def test_semantic_score_range(self, tmp_path):
        db = _setup_db(tmp_path)
        vectors_dir = tmp_path / "vectors"
        _setup_vector_index(db, vectors_dir)
        embedder = MockEmbedder()

        results = search(
            db, "auth token", tier="semantic",
            vectors_dir=vectors_dir, embedder=embedder,
        )
        for r in results:
            assert 0.0 <= r.score <= 1.0
        db.close()

    def test_semantic_empty_index(self, tmp_path):
        db = _setup_db(tmp_path)
        vectors_dir = tmp_path / "empty_vectors"
        embedder = MockEmbedder()

        results = search(
            db, "anything", tier="semantic",
            vectors_dir=vectors_dir, embedder=embedder,
        )
        assert results == []
        db.close()

    def test_semantic_with_project_filter(self, tmp_path):
        db = _setup_db(tmp_path)
        vectors_dir = tmp_path / "vectors"
        _setup_vector_index(db, vectors_dir)
        embedder = MockEmbedder()

        results = search(
            db, "design pattern", tier="semantic",
            vectors_dir=vectors_dir, embedder=embedder,
            project="project-beta",
        )
        for r in results:
            assert r.project_id == "project-beta"
        db.close()


# ---------------------------------------------------------------------------
# Tier 5: Hybrid
# ---------------------------------------------------------------------------

class TestHybridSearch:
    @pytest.fixture(autouse=True)
    def _skip_if_no_deps(self):
        pytest.importorskip("bm25s")
        pytest.importorskip("chromadb")

    def test_hybrid_basic(self, tmp_path):
        db = _setup_db(tmp_path)
        vectors_dir = tmp_path / "vectors"
        _setup_vector_index(db, vectors_dir)
        embedder = MockEmbedder()

        results = search(
            db, "JWT token", tier="hybrid",
            vectors_dir=vectors_dir, embedder=embedder, alpha=0.6,
        )
        assert len(results) >= 1
        db.close()

    def test_hybrid_alpha_zero_prefers_bm25(self, tmp_path):
        db = _setup_db(tmp_path)
        vectors_dir = tmp_path / "vectors"
        _setup_vector_index(db, vectors_dir)
        embedder = MockEmbedder()

        # alpha=0 → pure BM25
        results = search(
            db, "JWT", tier="hybrid",
            vectors_dir=vectors_dir, embedder=embedder, alpha=0.0,
        )
        assert len(results) >= 1
        db.close()

    def test_hybrid_alpha_one_prefers_semantic(self, tmp_path):
        db = _setup_db(tmp_path)
        vectors_dir = tmp_path / "vectors"
        _setup_vector_index(db, vectors_dir)
        embedder = MockEmbedder()

        # alpha=1 → pure semantic
        results = search(
            db, "auth token", tier="hybrid",
            vectors_dir=vectors_dir, embedder=embedder, alpha=1.0,
        )
        assert len(results) >= 1
        db.close()

    def test_hybrid_merges_results(self, tmp_path):
        db = _setup_db(tmp_path)
        vectors_dir = tmp_path / "vectors"
        _setup_vector_index(db, vectors_dir)
        embedder = MockEmbedder()

        results = search(
            db, "design", tier="hybrid",
            vectors_dir=vectors_dir, embedder=embedder,
        )
        # Should find results from both BM25 and semantic
        assert len(results) >= 1
        # Results should be ranked by hybrid score (descending)
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score
        db.close()


# ---------------------------------------------------------------------------
# Fallback behavior
# ---------------------------------------------------------------------------

class TestFallback:
    def test_unavailable_tier_falls_back_to_keyword(self, tmp_path, monkeypatch):
        monkeypatch.setattr("anticlaw.core.search._has_bm25s", lambda: False)
        monkeypatch.setattr("anticlaw.core.search._has_rapidfuzz", lambda: False)
        monkeypatch.setattr("anticlaw.core.search._has_chromadb", lambda: False)

        db = _setup_db(tmp_path)
        # Request bm25 but nothing installed → keyword
        results = search(db, "JWT", tier="bm25")
        assert len(results) >= 1
        assert results[0].chat_id == "c1"
        db.close()

    def test_semantic_without_vectors_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr("anticlaw.core.search._has_bm25s", lambda: False)
        monkeypatch.setattr("anticlaw.core.search._has_rapidfuzz", lambda: False)
        monkeypatch.setattr("anticlaw.core.search._has_chromadb", lambda: True)

        db = _setup_db(tmp_path)
        # Semantic available but no vectors_dir → keyword
        results = search(db, "JWT", tier="semantic")
        assert len(results) >= 1
        db.close()

    def test_hybrid_without_vectors_falls_back(self, tmp_path, monkeypatch):
        from anticlaw.core.search import _search_keyword

        monkeypatch.setattr("anticlaw.core.search._has_bm25s", lambda: True)
        monkeypatch.setattr("anticlaw.core.search._has_rapidfuzz", lambda: False)
        monkeypatch.setattr("anticlaw.core.search._has_chromadb", lambda: True)
        # Mock _search_bm25 since the real bm25s may not be installed
        monkeypatch.setattr("anticlaw.core.search._search_bm25", _search_keyword)

        db = _setup_db(tmp_path)
        # Hybrid requested but no vectors_dir → bm25 (best without vectors)
        results = search(db, "JWT", tier="hybrid")
        assert len(results) >= 1
        db.close()

    def test_auto_tier_no_deps(self, tmp_path, monkeypatch):
        monkeypatch.setattr("anticlaw.core.search._has_bm25s", lambda: False)
        monkeypatch.setattr("anticlaw.core.search._has_rapidfuzz", lambda: False)
        monkeypatch.setattr("anticlaw.core.search._has_chromadb", lambda: False)

        db = _setup_db(tmp_path)
        results = search(db, "JWT")
        assert len(results) >= 1
        db.close()


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_old_caller_works(self, tmp_path):
        """Existing callers without new params still work."""
        db = _setup_db(tmp_path)
        results = search(db, "JWT", exact=False, max_results=10)
        assert len(results) >= 1
        db.close()

    def test_old_caller_with_filters(self, tmp_path):
        db = _setup_db(tmp_path)
        results = search(
            db, "design", project="project-alpha",
            tags=None, max_results=20,
        )
        assert len(results) >= 1
        for r in results:
            assert r.project_id == "project-alpha"
        db.close()

    def test_exact_search_still_works(self, tmp_path):
        db = _setup_db(tmp_path)
        results = search(db, "JWT authentication", exact=True)
        assert len(results) >= 1
        db.close()
