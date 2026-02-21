"""FastMCP server for AnticLaw — 13 tools for knowledge base management."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastmcp import FastMCP

from anticlaw import __version__
from anticlaw.core.config import resolve_home
from anticlaw.core.graph import GraphDB
from anticlaw.core.meta_db import MetaDB
from anticlaw.core.models import Insight
from anticlaw.core.search import search as search_fn
from anticlaw.mcp.context_store import ContextStore
from anticlaw.mcp.hooks import TurnTracker

log = logging.getLogger(__name__)

mcp = FastMCP(
    "AnticLaw",
    instructions=(
        "AnticLaw is a local-first knowledge base for LLM conversations. "
        "Use aw_search to find information, aw_remember to save decisions, "
        "and aw_projects to navigate the knowledge base."
    ),
)

_tracker = TurnTracker()


# --- Helpers ---


def _get_home() -> Path:
    return resolve_home()


def _get_db(home: Path | None = None) -> MetaDB:
    h = home or _get_home()
    return MetaDB(h / ".acl" / "meta.db")


def _get_store(home: Path | None = None) -> ContextStore:
    h = home or _get_home()
    return ContextStore(h / ".acl" / "contexts")


def _get_graph(home: Path | None = None) -> GraphDB:
    h = home or _get_home()
    return GraphDB(h / ".acl" / "graph.db")


def _with_reminder(result: str) -> str:
    """Append a turn-based reminder if threshold reached."""
    reminder = _tracker.increment()
    if reminder:
        return result + reminder
    return result


# --- Implementation functions (testable without MCP) ---


def ping_impl(home: Path) -> dict:
    db = _get_db(home)
    try:
        projects = db.list_projects()
        chats = db.list_chats()
        insights = db.count_insights()
        return {
            "status": "ok",
            "version": __version__,
            "projects": len(projects),
            "chats": len(chats),
            "insights": insights,
        }
    finally:
        db.close()


def remember_impl(
    home: Path,
    content: str,
    category: str = "fact",
    importance: str = "medium",
    tags: list[str] | None = None,
    project_id: str = "",
) -> dict:
    insight = Insight(
        content=content,
        category=category,
        importance=importance,
        tags=tags or [],
        project_id=project_id,
    )
    db = _get_db(home)
    graph = _get_graph(home)
    try:
        db.add_insight(insight)
        graph.add_node(insight)
        return {"id": insight.id, "status": "saved"}
    finally:
        graph.close()
        db.close()


def recall_impl(
    home: Path,
    query: str = "",
    project: str | None = None,
    category: str | None = None,
    importance: str | None = None,
    max_results: int = 10,
) -> list[dict]:
    db = _get_db(home)
    try:
        return db.list_insights(
            query=query,
            project=project,
            category=category,
            importance=importance,
            max_results=max_results,
        )
    finally:
        db.close()


def forget_impl(home: Path, insight_id: str) -> dict:
    db = _get_db(home)
    try:
        deleted = db.delete_insight(insight_id)
        if deleted:
            return {"status": "deleted", "id": insight_id}
        return {"status": "not_found", "id": insight_id}
    finally:
        db.close()


def search_impl(
    home: Path,
    query: str,
    project: str | None = None,
    tag: str | None = None,
    exact: bool = False,
    max_results: int = 20,
) -> list[dict]:
    db = _get_db(home)
    try:
        results = search_fn(
            db,
            query,
            project=project,
            tags=[tag] if tag else None,
            exact=exact,
            max_results=max_results,
        )
        return [
            {
                "chat_id": r.chat_id,
                "title": r.title,
                "project": r.project_id,
                "snippet": r.snippet,
            }
            for r in results
        ]
    finally:
        db.close()


def related_impl(
    home: Path,
    node_id: str,
    edge_type: str | None = None,
    depth: int = 2,
) -> dict:
    graph = _get_graph(home)
    try:
        node = graph.resolve_node(node_id)
        if not node:
            return {"status": "not_found", "node_id": node_id}
        results = graph.traverse(node["id"], edge_type, depth)
        return {
            "status": "ok",
            "node": {
                "id": node["id"],
                "content": node["content"][:200],
                "category": node.get("category", ""),
            },
            "related": [
                {
                    "id": r["node"]["id"],
                    "content": r["node"]["content"][:200],
                    "edge_type": r["edge_type"],
                    "weight": r["weight"],
                    "depth": r["depth"],
                }
                for r in results
            ],
        }
    finally:
        graph.close()


def graph_stats_impl(home: Path) -> dict:
    graph = _get_graph(home)
    try:
        stats = graph.graph_stats()
        stats["status"] = "ok"
        return stats
    finally:
        graph.close()


def projects_impl(home: Path) -> list[dict]:
    db = _get_db(home)
    try:
        projects = db.list_projects()
        result = []
        for p in projects:
            chats = db.list_chats(p["id"])
            result.append(
                {
                    "id": p["id"],
                    "name": p["name"],
                    "description": p.get("description", ""),
                    "chat_count": len(chats),
                    "last_activity": p.get("updated", ""),
                }
            )
        return result
    finally:
        db.close()


# ============================================================
# MCP Tool definitions (13 tools)
# ============================================================

# --- Core Memory (4 tools) ---


@mcp.tool()
def aw_ping() -> str:
    """Health check. Returns server status, project count, chat count, insight count."""
    return _with_reminder(json.dumps(ping_impl(_get_home())))


@mcp.tool()
def aw_remember(
    content: str,
    category: str = "fact",
    importance: str = "medium",
    tags: list[str] | None = None,
    project_id: str = "",
) -> str:
    """Save an insight or decision to the knowledge base.

    You MUST call this tool before ending any session where you made decisions,
    discovered important information, or learned something that should be
    preserved for future sessions. Failing to do so means losing valuable context.

    Categories: decision, finding, preference, fact, question.
    Importance: low, medium, high, critical.
    """
    result = remember_impl(_get_home(), content, category, importance, tags, project_id)
    _tracker.reset()
    return json.dumps(result)


@mcp.tool()
def aw_recall(
    query: str = "",
    project: str | None = None,
    category: str | None = None,
    importance: str | None = None,
    max_results: int = 10,
) -> str:
    """Retrieve insights from the knowledge base.

    Filters by keyword query, project, category (decision/finding/preference/fact/question),
    and importance (low/medium/high/critical).
    """
    results = recall_impl(_get_home(), query, project, category, importance, max_results)
    return _with_reminder(json.dumps(results))


@mcp.tool()
def aw_forget(insight_id: str) -> str:
    """Remove an insight by ID. Use with caution — this cannot be undone."""
    return _with_reminder(json.dumps(forget_impl(_get_home(), insight_id)))


# --- Search (1 tool) ---


@mcp.tool()
def aw_search(
    query: str,
    project: str | None = None,
    tag: str | None = None,
    exact: bool = False,
    max_results: int = 20,
) -> str:
    """Search across all chats in the knowledge base.

    Uses full-text search across titles, summaries, message content, and tags.
    Returns ranked results with text snippets highlighting matches.
    Use --exact for phrase matching, --project to scope to a project.
    """
    results = search_impl(_get_home(), query, project, tag, exact, max_results)
    return _with_reminder(json.dumps(results))


# --- Context Management (5 tools) ---


@mcp.tool()
def aw_load_context(
    name: str, content: str, content_type: str = "text"
) -> str:
    """Store large content as a named variable on disk.

    The content is saved and only metadata is returned (name, size, token count).
    Use aw_get_context to read the content later, or aw_chunk_context to split it.
    Useful for storing large files, logs, or code that would consume too much context window.
    """
    store = _get_store()
    meta = store.save(name, content, content_type)
    return _with_reminder(json.dumps(meta))


@mcp.tool()
def aw_inspect_context(name: str) -> str:
    """Show metadata and preview of a stored context without loading full content.

    Returns: name, type, size, line count, token estimate, chunk info, and first 5 lines.
    """
    store = _get_store()
    meta = store.inspect(name)
    return _with_reminder(json.dumps(meta))


@mcp.tool()
def aw_get_context(
    name: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Read stored context content, or a specific line range.

    Lines are 1-indexed. Omit start_line and end_line to read the full content.
    Example: start_line=10, end_line=20 reads lines 10 through 20.
    """
    store = _get_store()
    return _with_reminder(store.get(name, start_line, end_line))


@mcp.tool()
def aw_chunk_context(
    name: str, strategy: str = "auto", chunk_size: int = 100
) -> str:
    """Split a stored context into numbered chunks for incremental reading.

    Strategies:
    - auto: Detect best strategy (headings > paragraphs > lines)
    - lines: N lines per chunk (chunk_size = number of lines)
    - paragraphs: N paragraphs per chunk
    - headings: Split on markdown headings (chunk_size ignored)
    - chars: N characters per chunk
    - regex: Reserved for future use (falls back to lines)

    After chunking, use aw_peek_chunk to read individual chunks.
    """
    store = _get_store()
    meta = store.chunk(name, strategy, chunk_size)
    return _with_reminder(json.dumps(meta))


@mcp.tool()
def aw_peek_chunk(name: str, chunk_number: int) -> str:
    """Read a specific chunk by number (1-indexed).

    Use aw_chunk_context first to split the content, then peek at individual chunks.
    """
    store = _get_store()
    return _with_reminder(store.peek(name, chunk_number))


# --- Graph (2 tools) ---


@mcp.tool()
def aw_related(
    node_id: str,
    edge_type: str | None = None,
    depth: int = 2,
) -> str:
    """Traverse the knowledge graph from a node.

    Returns related insights connected via edges.
    Edge types: semantic, temporal, causal, entity.
    Use edge_type to filter by a specific relationship type.
    """
    result = related_impl(_get_home(), node_id, edge_type, depth)
    return _with_reminder(json.dumps(result))


@mcp.tool()
def aw_graph_stats() -> str:
    """Knowledge graph statistics.

    Returns: node count, edge counts by type, top entities, project distribution.
    """
    result = graph_stats_impl(_get_home())
    return _with_reminder(json.dumps(result))


# --- Project (1 tool) ---


@mcp.tool()
def aw_projects() -> str:
    """List all projects in the knowledge base.

    Returns project name, description, chat count, and last activity for each project.
    """
    results = projects_impl(_get_home())
    return _with_reminder(json.dumps(results))
