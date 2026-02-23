"""Search dispatcher for AnticLaw (Tiers 1-5).

Tier hierarchy (highest to lowest):
    5. hybrid   — BM25 + semantic fusion (requires bm25s + chromadb + embedder)
    4. semantic  — ChromaDB vector search (requires chromadb + embedder)
    3. fuzzy    — Levenshtein distance (requires rapidfuzz)
    2. bm25     — TF-IDF ranked search (requires bm25s)
    1. keyword  — SQLite FTS5 (always available)

Auto-tier selection picks the best available tier based on installed
dependencies and whether a vector index is provided.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from anticlaw.core.meta_db import MetaDB, SearchResult

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dependency availability checks
# ---------------------------------------------------------------------------

def _has_bm25s() -> bool:
    try:
        import bm25s  # noqa: F401
        return True
    except ImportError:
        return False


def _has_rapidfuzz() -> bool:
    try:
        import rapidfuzz  # noqa: F401
        return True
    except ImportError:
        return False


def _has_chromadb() -> bool:
    try:
        import chromadb  # noqa: F401
        return True
    except ImportError:
        return False


def available_tiers() -> list[str]:
    """Return list of available search tiers based on installed deps."""
    tiers = ["keyword"]
    if _has_bm25s():
        tiers.append("bm25")
    if _has_rapidfuzz():
        tiers.append("fuzzy")
    if _has_chromadb():
        tiers.append("semantic")
    if _has_bm25s() and _has_chromadb():
        tiers.append("hybrid")
    return tiers


def best_tier(*, has_vectors: bool = False) -> str:
    """Select the best available tier.

    If has_vectors is False, semantic and hybrid tiers are excluded
    even if chromadb is installed (no index to query).
    """
    tiers = available_tiers()
    if has_vectors:
        priority = ["hybrid", "semantic", "fuzzy", "bm25", "keyword"]
    else:
        priority = ["fuzzy", "bm25", "keyword"]
    for t in priority:
        if t in tiers:
            return t
    return "keyword"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_filtered_docs(
    db: MetaDB,
    *,
    project: str | None = None,
    tags: list[str] | None = None,
    importance: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """Load chat docs from MetaDB with optional filters."""
    chats = db.list_chats(project_id=project)
    if not (tags or importance or date_from or date_to):
        return chats

    results = []
    for chat in chats:
        if importance and chat.get("importance") != importance:
            continue
        if date_from and (chat.get("created") or "") < date_from:
            continue
        if date_to and (chat.get("created") or "") > date_to:
            continue
        if tags:
            chat_tags = json.loads(chat.get("tags") or "[]")
            if not any(t in chat_tags for t in tags):
                continue
        results.append(chat)
    return results


def _make_snippet(content: str, query: str, max_len: int = 200) -> str:
    """Extract a snippet from content around query terms."""
    if not content:
        return ""

    words = query.lower().split()
    content_lower = content.lower()

    best_pos = -1
    for word in words:
        pos = content_lower.find(word)
        if pos >= 0 and (best_pos < 0 or pos < best_pos):
            best_pos = pos

    if best_pos < 0:
        return content[:max_len] + ("..." if len(content) > max_len else "")

    start = max(0, best_pos - 50)
    end = min(len(content), start + max_len)
    snippet = content[start:end]

    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."

    return snippet


# ---------------------------------------------------------------------------
# Tier implementations
# ---------------------------------------------------------------------------

def _search_keyword(
    db: MetaDB,
    query: str,
    *,
    project: str | None = None,
    tags: list[str] | None = None,
    importance: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int = 20,
    exact: bool = False,
) -> list[SearchResult]:
    """Tier 1: FTS5 keyword search (always available)."""
    return db.search_keyword(
        query,
        project=project,
        tags=tags,
        importance=importance,
        date_from=date_from,
        date_to=date_to,
        max_results=max_results,
        exact=exact,
    )


def _search_bm25(
    db: MetaDB,
    query: str,
    *,
    project: str | None = None,
    tags: list[str] | None = None,
    importance: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int = 20,
) -> list[SearchResult]:
    """Tier 2: BM25 ranked search via bm25s library."""
    import bm25s

    docs = _load_filtered_docs(
        db, project=project, tags=tags, importance=importance,
        date_from=date_from, date_to=date_to,
    )
    if not docs:
        return []

    corpus = [
        f"{d.get('title', '')} {d.get('summary', '')} {d.get('content', '')}"
        for d in docs
    ]

    corpus_tokens = bm25s.tokenize(corpus)
    retriever = bm25s.BM25()
    retriever.index(corpus_tokens)

    query_tokens = bm25s.tokenize([query])
    k = min(max_results, len(docs))
    results_arr, scores_arr = retriever.retrieve(query_tokens, k=k)

    search_results = []
    for i in range(k):
        idx = int(results_arr[0, i])
        score = float(scores_arr[0, i])
        if score <= 0:
            continue
        doc = docs[idx]
        search_results.append(SearchResult(
            chat_id=doc["id"],
            title=doc.get("title") or "",
            project_id=doc.get("project_id") or "",
            snippet=_make_snippet(doc.get("content") or "", query),
            score=score,
            file_path=doc.get("file_path") or "",
        ))

    return search_results


def _search_fuzzy(
    db: MetaDB,
    query: str,
    *,
    project: str | None = None,
    tags: list[str] | None = None,
    importance: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int = 20,
) -> list[SearchResult]:
    """Tier 3: Fuzzy search via rapidfuzz (typo-tolerant)."""
    from rapidfuzz import fuzz, process

    docs = _load_filtered_docs(
        db, project=project, tags=tags, importance=importance,
        date_from=date_from, date_to=date_to,
    )
    if not docs:
        return []

    # Build search corpus: title + summary + truncated content
    choices = [
        f"{d.get('title', '')} {d.get('summary', '')} "
        f"{(d.get('content') or '')[:500]}"
        for d in docs
    ]

    matches = process.extract(query, choices, scorer=fuzz.WRatio, limit=max_results)

    search_results = []
    for _match_text, score, idx in matches:
        if score < 50:  # minimum relevance threshold
            continue
        doc = docs[idx]
        search_results.append(SearchResult(
            chat_id=doc["id"],
            title=doc.get("title") or "",
            project_id=doc.get("project_id") or "",
            snippet=_make_snippet(doc.get("content") or "", query),
            score=score / 100.0,  # normalize to 0-1
            file_path=doc.get("file_path") or "",
        ))

    return search_results


def _search_semantic(
    db: MetaDB,
    query: str,
    *,
    vectors_dir: Path | None = None,
    embedder=None,
    project: str | None = None,
    max_results: int = 20,
) -> list[SearchResult]:
    """Tier 4: Semantic search via ChromaDB + embeddings."""
    if vectors_dir is None or embedder is None:
        log.warning("Semantic search requires vectors_dir and embedder")
        return []

    from anticlaw.core.index import VectorIndex

    index = VectorIndex(vectors_dir)
    if index.chat_count() == 0:
        log.warning("Vector index is empty — run 'aw reindex' to build it")
        return []

    query_embedding = embedder.embed(query)
    results = index.search_chats(
        query_embedding, n_results=max_results, project=project,
    )

    search_results = []
    if results["ids"] and results["ids"][0]:
        for i, chat_id in enumerate(results["ids"][0]):
            distance = results["distances"][0][i] if results.get("distances") else 0
            metadata = results["metadatas"][0][i] if results.get("metadatas") else {}
            document = (
                results["documents"][0][i] if results.get("documents") else ""
            ) or ""

            similarity = max(0.0, 1.0 - distance)
            snippet = document[:200] + ("..." if len(document) > 200 else "")

            search_results.append(SearchResult(
                chat_id=chat_id,
                title=metadata.get("title", ""),
                project_id=metadata.get("project_id", ""),
                snippet=snippet,
                score=similarity,
                file_path=metadata.get("file_path", ""),
            ))

    return search_results


def _search_hybrid(
    db: MetaDB,
    query: str,
    *,
    vectors_dir: Path | None = None,
    embedder=None,
    alpha: float = 0.6,
    project: str | None = None,
    tags: list[str] | None = None,
    importance: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int = 20,
) -> list[SearchResult]:
    """Tier 5: Hybrid fusion — BM25 + semantic with alpha blending.

    score = alpha * semantic + (1 - alpha) * BM25_normalized
    """
    # Fetch more candidates from each source, then merge
    pool_size = max_results * 2

    bm25_results = _search_bm25(
        db, query, project=project, tags=tags, importance=importance,
        date_from=date_from, date_to=date_to, max_results=pool_size,
    )
    semantic_results = _search_semantic(
        db, query, vectors_dir=vectors_dir, embedder=embedder,
        project=project, max_results=pool_size,
    )

    # Normalize BM25 scores to [0, 1] via min-max
    if bm25_results:
        raw = [r.score for r in bm25_results]
        min_s, max_s = min(raw), max(raw)
        rng = max_s - min_s if max_s != min_s else 1.0
        bm25_norm = {r.chat_id: (r.score - min_s) / rng for r in bm25_results}
    else:
        bm25_norm: dict[str, float] = {}

    # Semantic scores are already ~[0, 1] (cosine similarity)
    sem_norm = {r.chat_id: r.score for r in semantic_results}

    # Build detail lookup (prefer the richer result)
    detail: dict[str, SearchResult] = {}
    for r in bm25_results + semantic_results:
        if r.chat_id not in detail:
            detail[r.chat_id] = r

    # Blend scores
    merged = []
    for cid in set(bm25_norm) | set(sem_norm):
        bm25_s = bm25_norm.get(cid, 0.0)
        sem_s = sem_norm.get(cid, 0.0)
        hybrid_score = alpha * sem_s + (1.0 - alpha) * bm25_s
        r = detail[cid]
        merged.append(SearchResult(
            chat_id=r.chat_id,
            title=r.title,
            project_id=r.project_id,
            snippet=r.snippet,
            score=hybrid_score,
            file_path=r.file_path,
        ))

    merged.sort(key=lambda r: r.score, reverse=True)
    return merged[:max_results]


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

def search(
    db: MetaDB,
    query: str,
    *,
    project: str | None = None,
    tags: list[str] | None = None,
    importance: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int = 20,
    exact: bool = False,
    tier: str = "auto",
    vectors_dir: Path | None = None,
    embedder=None,
    alpha: float = 0.6,
) -> list[SearchResult]:
    """Search chats with automatic tier selection and graceful degradation.

    Args:
        tier: "auto" selects the best available tier. Or specify one of:
              keyword, bm25, fuzzy, semantic, hybrid.
        vectors_dir: Path to ChromaDB storage (required for semantic/hybrid).
        embedder: EmbeddingProvider instance (required for semantic/hybrid).
        alpha: Hybrid blend factor (0=BM25 only, 1=semantic only). Default 0.6.
    """
    has_vectors = vectors_dir is not None and embedder is not None

    # exact phrase matching is only supported by keyword tier
    if exact and tier == "auto":
        tier = "keyword"

    if tier == "auto":
        tier = best_tier(has_vectors=has_vectors)

    # Validate tier is available, fall back if not
    avail = available_tiers()
    if tier not in avail:
        log.warning("Tier '%s' not available (installed: %s), falling back", tier, avail)
        tier = best_tier(has_vectors=has_vectors)

    # Semantic/hybrid require vectors
    if tier in ("semantic", "hybrid") and not has_vectors:
        log.warning("Tier '%s' requires vectors_dir and embedder, falling back", tier)
        tier = best_tier(has_vectors=False)

    log.debug("Using search tier: %s", tier)

    if tier == "bm25":
        return _search_bm25(
            db, query, project=project, tags=tags, importance=importance,
            date_from=date_from, date_to=date_to, max_results=max_results,
        )
    elif tier == "fuzzy":
        return _search_fuzzy(
            db, query, project=project, tags=tags, importance=importance,
            date_from=date_from, date_to=date_to, max_results=max_results,
        )
    elif tier == "semantic":
        return _search_semantic(
            db, query, vectors_dir=vectors_dir, embedder=embedder,
            project=project, max_results=max_results,
        )
    elif tier == "hybrid":
        return _search_hybrid(
            db, query, vectors_dir=vectors_dir, embedder=embedder,
            alpha=alpha, project=project, tags=tags, importance=importance,
            date_from=date_from, date_to=date_to, max_results=max_results,
        )

    # Default: keyword (Tier 1)
    return _search_keyword(
        db, query, project=project, tags=tags, importance=importance,
        date_from=date_from, date_to=date_to, max_results=max_results,
        exact=exact,
    )


# ---------------------------------------------------------------------------
# Unified search (chats + files + insights)
# ---------------------------------------------------------------------------

def search_unified(
    db: MetaDB,
    query: str,
    *,
    project: str | None = None,
    tags: list[str] | None = None,
    importance: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int = 20,
    exact: bool = False,
    tier: str = "auto",
    vectors_dir: Path | None = None,
    embedder=None,
    alpha: float = 0.6,
    result_types: list[str] | None = None,
) -> list[SearchResult]:
    """Search across chats, source files, and insights.

    Args:
        result_types: Filter to specific types: ["chat", "file", "insight"].
                      None means all types.
    """
    types = set(result_types) if result_types else {"chat", "file", "insight"}
    all_results: list[SearchResult] = []

    # Search chats
    if "chat" in types:
        chat_results = search(
            db, query, project=project, tags=tags, importance=importance,
            date_from=date_from, date_to=date_to, max_results=max_results,
            exact=exact, tier=tier, vectors_dir=vectors_dir,
            embedder=embedder, alpha=alpha,
        )
        for r in chat_results:
            if not r.result_type or r.result_type == "chat":
                r.result_type = "chat"
            all_results.append(r)

    # Search source files
    if "file" in types:
        file_results = db.search_source_files(
            query, max_results=max_results, exact=exact,
        )
        all_results.extend(file_results)

    # Search insights
    if "insight" in types:
        insights = db.list_insights(query=query, project=project, max_results=max_results)
        for ins in insights:
            content = ins.get("content", "")
            snippet = content[:200] + ("..." if len(content) > 200 else "")
            all_results.append(SearchResult(
                chat_id=ins["id"],
                title=content[:80],
                project_id=ins.get("project_id", ""),
                snippet=snippet,
                score=0.5,
                file_path="",
                result_type="insight",
            ))

    # Sort by score descending, limit to max_results
    all_results.sort(key=lambda r: abs(r.score), reverse=True)
    return all_results[:max_results]
