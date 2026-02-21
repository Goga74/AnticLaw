"""Search dispatcher for AnticLaw (Tier 1: keyword/FTS5)."""

from __future__ import annotations

import logging

from anticlaw.core.meta_db import MetaDB, SearchResult

log = logging.getLogger(__name__)


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
) -> list[SearchResult]:
    """Search chats. Currently dispatches to Tier 1 (keyword/FTS5).

    Future tiers (BM25, fuzzy, semantic, hybrid) will be added here
    with automatic tier selection based on available dependencies.
    """
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
