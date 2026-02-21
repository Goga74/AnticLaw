"""ChromaDB vector index for semantic search."""

from __future__ import annotations

import logging
from pathlib import Path

from anticlaw.core.meta_db import MetaDB

log = logging.getLogger(__name__)


class VectorIndex:
    """Manages ChromaDB collections for chat and insight vectors.

    Stores embeddings in a persistent ChromaDB instance at .acl/vectors/.
    Uses cosine distance for similarity.
    """

    def __init__(self, vectors_dir: Path) -> None:
        import chromadb

        vectors_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(vectors_dir))
        self._chats = self._client.get_or_create_collection(
            name="chats",
            metadata={"hnsw:space": "cosine"},
        )
        self._insights = self._client.get_or_create_collection(
            name="insights",
            metadata={"hnsw:space": "cosine"},
        )

    def index_chat(
        self,
        chat_id: str,
        title: str,
        project_id: str,
        file_path: str,
        content: str,
        embedding: list[float],
    ) -> None:
        """Index or update a chat vector."""
        self._chats.upsert(
            ids=[chat_id],
            embeddings=[embedding],
            documents=[content[:10000]],
            metadatas=[{
                "title": title,
                "project_id": project_id,
                "file_path": file_path,
            }],
        )

    def index_insight(
        self,
        insight_id: str,
        content: str,
        embedding: list[float],
    ) -> None:
        """Index or update an insight vector."""
        self._insights.upsert(
            ids=[insight_id],
            embeddings=[embedding],
            documents=[content],
        )

    def search_chats(
        self,
        query_embedding: list[float],
        n_results: int = 20,
        project: str | None = None,
    ) -> dict:
        """Search chat vectors by cosine similarity."""
        count = self._chats.count()
        if count == 0:
            return {"ids": [[]], "distances": [[]], "metadatas": [[]], "documents": [[]]}

        kwargs: dict = {
            "query_embeddings": [query_embedding],
            "n_results": min(n_results, count),
        }
        if project:
            kwargs["where"] = {"project_id": project}
        return self._chats.query(**kwargs)

    def search_insights(
        self,
        query_embedding: list[float],
        n_results: int = 20,
    ) -> dict:
        """Search insight vectors by cosine similarity."""
        count = self._insights.count()
        if count == 0:
            return {"ids": [[]], "distances": [[]], "metadatas": [[]], "documents": [[]]}

        return self._insights.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, count),
        )

    def chat_count(self) -> int:
        return self._chats.count()

    def insight_count(self) -> int:
        return self._insights.count()

    def clear(self) -> None:
        """Delete all vectors from both collections."""
        self._client.delete_collection("chats")
        self._client.delete_collection("insights")
        self._chats = self._client.get_or_create_collection(
            name="chats",
            metadata={"hnsw:space": "cosine"},
        )
        self._insights = self._client.get_or_create_collection(
            name="insights",
            metadata={"hnsw:space": "cosine"},
        )


def index_chat_vectors(
    index: VectorIndex,
    embedder,
    chat_id: str,
    title: str,
    project_id: str,
    file_path: str,
    content: str,
) -> None:
    """Embed a chat and store in vector index."""
    if not content.strip():
        return
    embedding = embedder.embed(content[:8000])
    index.index_chat(chat_id, title, project_id, file_path, content, embedding)


def index_insight_vectors(
    index: VectorIndex,
    embedder,
    insight_id: str,
    content: str,
) -> None:
    """Embed an insight and store in vector index."""
    if not content.strip():
        return
    embedding = embedder.embed(content)
    index.index_insight(insight_id, content, embedding)


def reindex_vectors(
    home: Path,
    db: MetaDB,
    embedder,
) -> tuple[int, int]:
    """Rebuild the entire vector index from MetaDB.

    Returns (chats_indexed, insights_indexed).
    """
    vectors_dir = home / ".acl" / "vectors"
    index = VectorIndex(vectors_dir)
    index.clear()

    chat_count = 0
    for chat in db.list_chats():
        content = chat.get("content") or ""
        if not content.strip():
            continue
        try:
            index_chat_vectors(
                index, embedder,
                chat["id"],
                chat.get("title") or "",
                chat.get("project_id") or "",
                chat.get("file_path") or "",
                content,
            )
            chat_count += 1
        except Exception:
            log.warning("Failed to index chat vectors: %s", chat["id"], exc_info=True)

    insight_count = 0
    for insight in db.list_insights():
        content = insight.get("content") or ""
        if not content.strip():
            continue
        try:
            index_insight_vectors(index, embedder, insight["id"], content)
            insight_count += 1
        except Exception:
            log.warning("Failed to index insight vectors: %s", insight["id"], exc_info=True)

    return chat_count, insight_count
