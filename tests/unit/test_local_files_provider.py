"""Tests for anticlaw.providers.source.local_files."""

from pathlib import Path

import pytest

from anticlaw.core.models import SourceDocument
from anticlaw.providers.source.local_files import (
    DEFAULT_EXCLUDE_PATTERNS,
    DEFAULT_EXTENSIONS,
    LocalFilesProvider,
    _detect_language,
    _file_hash,
    _read_text_file,
    _should_exclude,
)


class TestFileHash:
    def test_hash_produces_hex(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        h = _file_hash(f)
        assert len(h) == 64  # SHA-256 hex
        assert h.isalnum()

    def test_same_content_same_hash(self, tmp_path: Path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("same", encoding="utf-8")
        f2.write_text("same", encoding="utf-8")
        assert _file_hash(f1) == _file_hash(f2)

    def test_different_content_different_hash(self, tmp_path: Path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("aaa", encoding="utf-8")
        f2.write_text("bbb", encoding="utf-8")
        assert _file_hash(f1) != _file_hash(f2)

    def test_nonexistent_file(self, tmp_path: Path):
        h = _file_hash(tmp_path / "nope.txt")
        assert h == ""


class TestReadTextFile:
    def test_utf8(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("hello café", encoding="utf-8")
        assert _read_text_file(f) == "hello café"

    def test_latin1_fallback(self, tmp_path: Path):
        f = tmp_path / "latin.txt"
        f.write_bytes("caf\xe9".encode("latin-1"))
        text = _read_text_file(f)
        assert "caf" in text


class TestShouldExclude:
    def test_excludes_node_modules(self):
        p = Path("/project/node_modules/pkg/index.js")
        assert _should_exclude(p, ["node_modules"]) is True

    def test_excludes_git(self):
        p = Path("/project/.git/config")
        assert _should_exclude(p, [".git"]) is True

    def test_no_match(self):
        p = Path("/project/src/main.py")
        assert _should_exclude(p, ["node_modules", ".git"]) is False


class TestDetectLanguage:
    def test_python(self):
        assert _detect_language(".py") == "python"

    def test_javascript(self):
        assert _detect_language(".js") == "javascript"

    def test_unknown(self):
        assert _detect_language(".xyz") == ""

    def test_markdown(self):
        assert _detect_language(".md") == ""  # text, not a programming language


class TestLocalFilesProvider:
    def test_name(self):
        p = LocalFilesProvider()
        assert p.name == "local-files"

    def test_info(self):
        p = LocalFilesProvider()
        info = p.info
        assert info.display_name == "Local Files"
        assert info.version == "1.0.0"
        assert info.is_local is True
        assert len(info.supported_extensions) > 0

    def test_scan_empty_dir(self, tmp_path: Path):
        p = LocalFilesProvider()
        docs = p.scan([tmp_path])
        assert docs == []

    def test_scan_text_files(self, tmp_path: Path):
        (tmp_path / "hello.py").write_text("print('hi')", encoding="utf-8")
        (tmp_path / "data.json").write_text('{"a": 1}', encoding="utf-8")
        (tmp_path / "readme.md").write_text("# Title", encoding="utf-8")

        p = LocalFilesProvider()
        docs = p.scan([tmp_path])
        assert len(docs) == 3
        filenames = {d.filename for d in docs}
        assert "hello.py" in filenames
        assert "data.json" in filenames
        assert "readme.md" in filenames

    def test_scan_returns_source_documents(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("x = 1", encoding="utf-8")

        p = LocalFilesProvider()
        docs = p.scan([tmp_path])
        assert len(docs) == 1
        doc = docs[0]
        assert isinstance(doc, SourceDocument)
        assert doc.filename == "main.py"
        assert doc.extension == ".py"
        assert doc.language == "python"
        assert doc.content == "x = 1"
        assert doc.size > 0
        assert doc.hash != ""

    def test_scan_excludes_patterns(self, tmp_path: Path):
        # Create files in excluded dirs
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "pkg.js").write_text("module", encoding="utf-8")

        git = tmp_path / ".git"
        git.mkdir()
        (git / "config").write_text("gitconfig", encoding="utf-8")

        # Create a valid file
        (tmp_path / "app.py").write_text("app code", encoding="utf-8")

        p = LocalFilesProvider()
        docs = p.scan([tmp_path])
        filenames = {d.filename for d in docs}
        assert "app.py" in filenames
        assert "pkg.js" not in filenames
        assert "config" not in filenames

    def test_scan_respects_extensions(self, tmp_path: Path):
        (tmp_path / "code.py").write_text("code", encoding="utf-8")
        (tmp_path / "image.png").write_bytes(b"fake png data")
        (tmp_path / "binary.exe").write_bytes(b"\x00\x01\x02")

        p = LocalFilesProvider()
        docs = p.scan([tmp_path])
        filenames = {d.filename for d in docs}
        assert "code.py" in filenames
        assert "image.png" not in filenames
        assert "binary.exe" not in filenames

    def test_scan_custom_extensions(self, tmp_path: Path):
        (tmp_path / "code.py").write_text("code", encoding="utf-8")
        (tmp_path / "data.csv").write_text("a,b,c", encoding="utf-8")

        p = LocalFilesProvider(extensions=[".csv"])
        docs = p.scan([tmp_path])
        assert len(docs) == 1
        assert docs[0].filename == "data.csv"

    def test_scan_max_file_size(self, tmp_path: Path):
        small = tmp_path / "small.txt"
        small.write_text("small", encoding="utf-8")

        big = tmp_path / "big.txt"
        big.write_text("x" * (2 * 1024 * 1024), encoding="utf-8")  # 2MB

        p = LocalFilesProvider(max_file_size_mb=1)
        docs = p.scan([tmp_path])
        filenames = {d.filename for d in docs}
        assert "small.txt" in filenames
        # big.txt is scanned but returns empty content due to size
        big_docs = [d for d in docs if d.filename == "big.txt"]
        assert len(big_docs) == 0  # content empty, so not added

    def test_scan_recursive(self, tmp_path: Path):
        sub = tmp_path / "src" / "lib"
        sub.mkdir(parents=True)
        (sub / "util.py").write_text("def util(): pass", encoding="utf-8")
        (tmp_path / "main.py").write_text("import lib", encoding="utf-8")

        p = LocalFilesProvider()
        docs = p.scan([tmp_path])
        filenames = {d.filename for d in docs}
        assert "util.py" in filenames
        assert "main.py" in filenames

    def test_scan_nonexistent_path(self, tmp_path: Path):
        p = LocalFilesProvider()
        docs = p.scan([tmp_path / "nope"])
        assert docs == []

    def test_scan_single_file(self, tmp_path: Path):
        f = tmp_path / "single.py"
        f.write_text("x = 42", encoding="utf-8")

        p = LocalFilesProvider()
        docs = p.scan([f])
        assert len(docs) == 1
        assert docs[0].filename == "single.py"

    def test_read_single_file(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("hello = True", encoding="utf-8")

        p = LocalFilesProvider()
        doc = p.read(f)
        assert doc.filename == "test.py"
        assert doc.content == "hello = True"
        assert doc.language == "python"
        assert doc.hash != ""

    def test_watch_raises(self):
        p = LocalFilesProvider()
        with pytest.raises(NotImplementedError):
            p.watch([], lambda x: None)

    def test_pdf_graceful_fallback(self, tmp_path: Path):
        """PDF reading should gracefully return empty if pymupdf not installed."""
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 fake pdf")

        p = LocalFilesProvider()
        doc = p.read(f)
        # pymupdf likely not installed in test env, so content empty or parsed
        assert isinstance(doc, SourceDocument)
        assert doc.filename == "doc.pdf"
        assert doc.extension == ".pdf"


class TestDefaultConstants:
    def test_exclude_patterns_include_common(self):
        assert "node_modules" in DEFAULT_EXCLUDE_PATTERNS
        assert ".git" in DEFAULT_EXCLUDE_PATTERNS
        assert "__pycache__" in DEFAULT_EXCLUDE_PATTERNS

    def test_extensions_include_common(self):
        assert ".py" in DEFAULT_EXTENSIONS
        assert ".js" in DEFAULT_EXTENSIONS
        assert ".md" in DEFAULT_EXTENSIONS
        assert ".pdf" in DEFAULT_EXTENSIONS
