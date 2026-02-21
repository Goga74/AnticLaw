"""Tests for anticlaw.mcp.context_store."""

from pathlib import Path

from anticlaw.mcp.context_store import ContextStore


class TestSaveAndGet:
    def test_save_returns_metadata(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        meta = store.save("test", "hello world")

        assert meta["name"] == "test"
        assert meta["size_bytes"] == 11
        assert meta["line_count"] == 1
        assert meta["token_estimate"] > 0

    def test_get_full_content(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        store.save("test", "line1\nline2\nline3")

        content = store.get("test")
        assert content == "line1\nline2\nline3"

    def test_get_line_range(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        store.save("test", "line1\nline2\nline3\nline4\nline5")

        content = store.get("test", start_line=2, end_line=4)
        assert content == "line2\nline3\nline4"

    def test_get_not_found(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        result = store.get("missing")
        assert "not found" in result.lower()

    def test_save_overwrites(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        store.save("test", "old content")
        store.save("test", "new content")

        assert store.get("test") == "new content"


class TestInspect:
    def test_inspect_metadata(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        store.save("test", "hello\nworld\nfoo\nbar\nbaz\nextra")

        meta = store.inspect("test")
        assert meta["name"] == "test"
        assert "preview" in meta
        assert meta["preview"] == "hello\nworld\nfoo\nbar\nbaz"

    def test_inspect_not_found(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        meta = store.inspect("missing")
        assert "error" in meta


class TestDelete:
    def test_delete_context(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        store.save("test", "content")
        assert store.delete("test") is True
        assert "not found" in store.get("test").lower()

    def test_delete_nonexistent(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        assert store.delete("missing") is False


class TestListContexts:
    def test_list_empty(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        assert store.list_contexts() == []

    def test_list_multiple(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        store.save("alpha", "aaa")
        store.save("beta", "bbb")

        contexts = store.list_contexts()
        assert len(contexts) == 2
        names = {c["name"] for c in contexts}
        assert names == {"alpha", "beta"}


class TestChunking:
    def test_chunk_by_lines(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        content = "\n".join(f"line {i}" for i in range(10))
        store.save("test", content)

        result = store.chunk("test", strategy="lines", chunk_size=3)
        assert result["chunks"] == 4  # 10 lines / 3 = 4 chunks (3+3+3+1)
        assert result["strategy"] == "lines"

    def test_chunk_by_paragraphs(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        store.save("test", "Para one.\n\nPara two.\n\nPara three.")

        result = store.chunk("test", strategy="paragraphs", chunk_size=2)
        assert result["chunks"] == 2  # (2 paras) + (1 para)

    def test_chunk_by_headings(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        store.save("test", "# Section 1\nContent 1\n\n# Section 2\nContent 2")

        result = store.chunk("test", strategy="headings")
        assert result["chunks"] == 2

    def test_chunk_by_chars(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        store.save("test", "a" * 100)

        result = store.chunk("test", strategy="chars", chunk_size=30)
        assert result["chunks"] == 4  # 100/30 = 3.33 → 4 chunks

    def test_chunk_auto_headings(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        store.save("test", "# H1\nContent\n## H2\nMore content")

        result = store.chunk("test", strategy="auto")
        assert result["chunks"] == 2
        assert result["strategy"] == "auto"

    def test_chunk_auto_paragraphs(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        store.save("test", "Para 1 text.\n\nPara 2 text.\n\nPara 3 text.")

        result = store.chunk("test", strategy="auto", chunk_size=2)
        assert result["chunks"] == 2

    def test_chunk_auto_lines(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        store.save("test", "line1\nline2\nline3\nline4")

        result = store.chunk("test", strategy="auto", chunk_size=2)
        assert result["chunks"] == 2

    def test_chunk_not_found(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        result = store.chunk("missing")
        assert "error" in result


class TestPeek:
    def test_peek_chunk(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        store.save("test", "line1\nline2\nline3\nline4")
        store.chunk("test", strategy="lines", chunk_size=2)

        chunk1 = store.peek("test", 1)
        assert "line1" in chunk1
        assert "line2" in chunk1

        chunk2 = store.peek("test", 2)
        assert "line3" in chunk2

    def test_peek_not_found(self, tmp_path: Path):
        store = ContextStore(tmp_path / "contexts")
        result = store.peek("test", 99)
        assert "not found" in result.lower()
