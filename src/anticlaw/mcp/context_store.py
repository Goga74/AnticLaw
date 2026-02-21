"""Context-as-variable storage for MCP tools."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)


class ContextStore:
    """Stores large content as named variables on disk.

    Content is saved to .acl/contexts/<name>.txt with JSON metadata sidecars.
    Supports 6 chunking strategies: auto, lines, paragraphs, headings, chars, regex.
    """

    def __init__(self, contexts_dir: Path) -> None:
        self.dir = contexts_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def _content_path(self, name: str) -> Path:
        return self.dir / f"{name}.txt"

    def _meta_path(self, name: str) -> Path:
        return self.dir / f"{name}.json"

    def _chunks_dir(self, name: str) -> Path:
        return self.dir / f"{name}_chunks"

    # --- CRUD ---

    def save(self, name: str, content: str, content_type: str = "text") -> dict:
        """Save content as a named variable. Returns metadata."""
        self._content_path(name).write_text(content, encoding="utf-8")

        lines = content.count("\n") + 1
        chars = len(content)
        tokens = chars // 4  # rough estimate

        meta = {
            "name": name,
            "type": content_type,
            "size_bytes": chars,
            "line_count": lines,
            "token_estimate": tokens,
            "chunks": None,
            "chunk_strategy": None,
        }
        self._meta_path(name).write_text(json.dumps(meta), encoding="utf-8")
        return meta

    def inspect(self, name: str) -> dict:
        """Return metadata + preview of a stored context."""
        meta_path = self._meta_path(name)
        if not meta_path.exists():
            return {"error": f"Context '{name}' not found"}

        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        content_path = self._content_path(name)
        if content_path.exists():
            lines = content_path.read_text(encoding="utf-8").split("\n")
            meta["preview"] = "\n".join(lines[:5])
        return meta

    def get(
        self,
        name: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> str:
        """Read stored content, or a specific line range (1-indexed)."""
        content_path = self._content_path(name)
        if not content_path.exists():
            return f"Context '{name}' not found"

        content = content_path.read_text(encoding="utf-8")
        if start_line is not None or end_line is not None:
            lines = content.split("\n")
            start = (start_line or 1) - 1
            end = end_line or len(lines)
            return "\n".join(lines[start:end])
        return content

    def delete(self, name: str) -> bool:
        """Delete a stored context and its chunks."""
        deleted = False
        for path in [self._content_path(name), self._meta_path(name)]:
            if path.exists():
                path.unlink()
                deleted = True
        chunks_dir = self._chunks_dir(name)
        if chunks_dir.exists():
            for f in chunks_dir.iterdir():
                f.unlink()
            chunks_dir.rmdir()
            deleted = True
        return deleted

    def list_contexts(self) -> list[dict]:
        """List all stored contexts (metadata only)."""
        contexts = []
        for meta_path in sorted(self.dir.glob("*.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                contexts.append(meta)
            except Exception:
                log.warning("Failed to read context meta: %s", meta_path)
        return contexts

    # --- Chunking ---

    def chunk(self, name: str, strategy: str = "auto", chunk_size: int = 100) -> dict:
        """Split content into numbered chunks. Returns chunk metadata."""
        content_path = self._content_path(name)
        if not content_path.exists():
            return {"error": f"Context '{name}' not found"}

        content = content_path.read_text(encoding="utf-8")
        chunks = self._split(content, strategy, chunk_size)

        # Save chunks to individual files
        chunks_dir = self._chunks_dir(name)
        chunks_dir.mkdir(exist_ok=True)
        # Clear old chunks
        for f in chunks_dir.iterdir():
            f.unlink()
        for i, chunk_text in enumerate(chunks, 1):
            (chunks_dir / f"{i}.txt").write_text(chunk_text, encoding="utf-8")

        # Update metadata
        meta_path = self._meta_path(name)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["chunks"] = len(chunks)
        meta["chunk_strategy"] = strategy
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        return {
            "name": name,
            "chunks": len(chunks),
            "strategy": strategy,
            "chunk_sizes": [len(c) for c in chunks],
        }

    def peek(self, name: str, chunk_number: int) -> str:
        """Read a specific chunk by number (1-indexed)."""
        chunk_path = self._chunks_dir(name) / f"{chunk_number}.txt"
        if not chunk_path.exists():
            return f"Chunk {chunk_number} not found for context '{name}'"
        return chunk_path.read_text(encoding="utf-8")

    # --- Splitting strategies ---

    def _split(self, content: str, strategy: str, chunk_size: int) -> list[str]:
        if strategy == "auto":
            if re.search(r"^#+\s", content, re.MULTILINE):
                return self._split_headings(content)
            elif "\n\n" in content:
                return self._split_paragraphs(content, chunk_size)
            else:
                return self._split_lines(content, chunk_size)
        elif strategy == "lines":
            return self._split_lines(content, chunk_size)
        elif strategy == "paragraphs":
            return self._split_paragraphs(content, chunk_size)
        elif strategy == "headings":
            return self._split_headings(content)
        elif strategy == "chars":
            return self._split_chars(content, chunk_size)
        elif strategy == "regex":
            return self._split_lines(content, chunk_size)
        else:
            return self._split_lines(content, chunk_size)

    def _split_lines(self, content: str, chunk_size: int) -> list[str]:
        lines = content.split("\n")
        chunks = []
        for i in range(0, len(lines), chunk_size):
            chunk = "\n".join(lines[i : i + chunk_size])
            if chunk.strip():
                chunks.append(chunk)
        return chunks or [content]

    def _split_paragraphs(self, content: str, chunk_size: int) -> list[str]:
        paragraphs = re.split(r"\n{2,}", content)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]
        if not paragraphs:
            return [content]
        chunks = []
        for i in range(0, len(paragraphs), chunk_size):
            chunk = "\n\n".join(paragraphs[i : i + chunk_size])
            chunks.append(chunk)
        return chunks

    def _split_headings(self, content: str) -> list[str]:
        parts = re.split(r"(?=^#+\s)", content, flags=re.MULTILINE)
        chunks = [p.strip() for p in parts if p.strip()]
        return chunks or [content]

    def _split_chars(self, content: str, chunk_size: int) -> list[str]:
        chunks = []
        for i in range(0, len(content), chunk_size):
            chunk = content[i : i + chunk_size]
            if chunk.strip():
                chunks.append(chunk)
        return chunks or [content]
