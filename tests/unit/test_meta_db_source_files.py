"""Tests for MetaDB source_files table and methods."""

from datetime import datetime, timezone
from pathlib import Path

from anticlaw.core.meta_db import MetaDB
from anticlaw.core.models import SourceDocument


def _make_source_doc(
    id: str = "src-001",
    file_path: str = "/home/user/code/main.py",
    filename: str = "main.py",
    extension: str = ".py",
    language: str = "python",
    content: str = "def hello(): pass",
    size: int = 17,
    hash: str = "abc123",
) -> SourceDocument:
    return SourceDocument(
        id=id,
        file_path=file_path,
        filename=filename,
        extension=extension,
        language=language,
        content=content,
        size=size,
        hash=hash,
        indexed_at=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
    )


class TestSourceFilesSchema:
    def test_source_files_table_exists(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        tables = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {r["name"] for r in tables}
        assert "source_files" in table_names
        db.close()

    def test_source_files_fts_exists(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        vtables = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='source_files_fts'"
        ).fetchall()
        assert len(vtables) == 1
        db.close()


class TestIndexSourceFile:
    def test_index_and_count(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        doc = _make_source_doc()
        db.index_source_file(doc)

        assert db.count_source_files() == 1
        db.close()

    def test_index_multiple(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        for i in range(3):
            doc = _make_source_doc(
                id=f"src-{i}",
                file_path=f"/code/file{i}.py",
                filename=f"file{i}.py",
                content=f"content {i}",
            )
            db.index_source_file(doc)

        assert db.count_source_files() == 3
        db.close()

    def test_index_updates_existing(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        doc = _make_source_doc()
        db.index_source_file(doc)

        doc.content = "updated content"
        doc.hash = "newhash"
        db.index_source_file(doc)

        assert db.count_source_files() == 1
        result = db.get_source_file(doc.file_path)
        assert result is not None
        assert result["hash"] == "newhash"
        db.close()


class TestGetSourceFile:
    def test_get_by_path(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        doc = _make_source_doc()
        db.index_source_file(doc)

        result = db.get_source_file("/home/user/code/main.py")
        assert result is not None
        assert result["id"] == "src-001"
        assert result["filename"] == "main.py"
        assert result["extension"] == ".py"
        assert result["language"] == "python"
        assert result["hash"] == "abc123"
        db.close()

    def test_get_not_found(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        assert db.get_source_file("/nope.py") is None
        db.close()


class TestSearchSourceFiles:
    def test_search_by_content(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        doc = _make_source_doc(content="implement JWT authentication handler")
        db.index_source_file(doc)

        results = db.search_source_files("JWT")
        assert len(results) == 1
        assert results[0].chat_id == "src-001"
        assert results[0].result_type == "file"
        db.close()

    def test_search_by_filename(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        doc = _make_source_doc(filename="authentication.py")
        db.index_source_file(doc)

        results = db.search_source_files("authentication")
        assert len(results) == 1
        db.close()

    def test_search_no_results(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        doc = _make_source_doc()
        db.index_source_file(doc)

        results = db.search_source_files("kubernetes")
        assert results == []
        db.close()

    def test_search_exact(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        doc = _make_source_doc(content="three main approaches to auth")
        db.index_source_file(doc)

        results = db.search_source_files("main approaches", exact=True)
        assert len(results) == 1

        results = db.search_source_files("approaches main", exact=True)
        assert len(results) == 0
        db.close()

    def test_search_max_results(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        for i in range(5):
            doc = _make_source_doc(
                id=f"src-{i}",
                file_path=f"/code/file{i}.py",
                filename=f"file{i}.py",
                content=f"shared keyword topic {i}",
            )
            db.index_source_file(doc)

        results = db.search_source_files("shared", max_results=3)
        assert len(results) == 3
        db.close()

    def test_search_returns_snippet(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        doc = _make_source_doc(content="implement JWT authentication handler")
        db.index_source_file(doc)

        results = db.search_source_files("JWT")
        assert len(results) == 1
        assert results[0].snippet != ""
        db.close()


class TestClearSourceFiles:
    def test_clear_removes_all(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        for i in range(3):
            doc = _make_source_doc(
                id=f"src-{i}",
                file_path=f"/code/f{i}.py",
                filename=f"f{i}.py",
            )
            db.index_source_file(doc)

        assert db.count_source_files() == 3
        db.clear_source_files()
        assert db.count_source_files() == 0
        db.close()

    def test_clear_empty_db(self, tmp_path: Path):
        db = MetaDB(tmp_path / "meta.db")
        db.clear_source_files()  # Should not error
        assert db.count_source_files() == 0
        db.close()
