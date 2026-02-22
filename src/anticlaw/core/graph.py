"""MAGMA knowledge graph — SQLite-backed with 4 edge types.

Graph types:
    temporal  — nodes created within a configurable time window
    entity    — nodes sharing extracted entities (paths, URLs, CamelCase)
    semantic  — nodes with similar embeddings (requires embedder)
    causal    — nodes linked by cause/effect language
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anticlaw.core.entities import extract_entities, has_causal_language
from anticlaw.core.models import EdgeType, Insight

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    content TEXT,
    category TEXT,
    importance TEXT,
    tags TEXT,
    project_id TEXT,
    chat_id TEXT,
    created TEXT,
    updated TEXT,
    status TEXT,
    embedding TEXT
);

CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    metadata TEXT,
    created TEXT,
    FOREIGN KEY (source_id) REFERENCES nodes(id),
    FOREIGN KEY (target_id) REFERENCES nodes(id)
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_nodes_project ON nodes(project_id);
CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_dt(dt: datetime | None) -> str:
    if dt is None:
        return _now_iso()
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(dt)


def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors (pure Python)."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def intent_detect(query: str) -> str | None:
    """Detect query intent for edge type prioritization.

    Returns edge type string or None if no specific intent detected.
    "why" → causal, "when" → temporal, "what" → entity.
    """
    q = query.lower()
    if any(w in q for w in ("why", "почему", "reason", "cause")):
        return EdgeType.CAUSAL
    if any(w in q for w in ("when", "когда", "timeline", "sequence")):
        return EdgeType.TEMPORAL
    if any(w in q for w in ("what", "что", "which", "какой")):
        return EdgeType.ENTITY
    return None


# ---------------------------------------------------------------------------
# GraphDB
# ---------------------------------------------------------------------------

class GraphDB:
    """SQLite knowledge graph at .acl/graph.db."""

    def __init__(
        self,
        db_path: Path,
        *,
        temporal_window_minutes: int = 30,
        semantic_top_k: int = 3,
    ) -> None:
        self.db_path = db_path
        self.temporal_window = temporal_window_minutes
        self.semantic_top_k = semantic_top_k
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = self._open()
        return self._conn

    def _open(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        return conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # --- Node operations ---

    def add_node(self, insight: Insight, *, embedder=None) -> str:
        """Add an insight as a graph node and auto-generate edges.

        Args:
            insight: The Insight dataclass to store.
            embedder: Optional EmbeddingProvider for semantic edges.

        Returns:
            The node ID.
        """
        tags_json = json.dumps(insight.tags) if insight.tags else "[]"
        created_str = _format_dt(insight.created)

        # Compute embedding if embedder available
        embedding_json: str | None = None
        if embedder and insight.content.strip():
            try:
                emb = embedder.embed(insight.content)
                embedding_json = json.dumps(emb)
            except Exception:
                log.warning("Failed to compute embedding for node %s", insight.id)

        self.conn.execute(
            """INSERT OR REPLACE INTO nodes
               (id, content, category, importance, tags, project_id,
                chat_id, created, updated, status, embedding)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                insight.id,
                insight.content,
                str(
                    insight.category.value
                    if hasattr(insight.category, "value") else insight.category
                ),
                str(
                    insight.importance.value
                    if hasattr(insight.importance, "value") else insight.importance
                ),
                tags_json,
                insight.project_id,
                insight.chat_id,
                created_str,
                _format_dt(insight.updated),
                str(insight.status.value if hasattr(insight.status, "value") else insight.status),
                embedding_json,
            ),
        )
        self.conn.commit()

        # Auto-generate edges
        created_dt = (
            insight.created if isinstance(insight.created, datetime)
            else _parse_dt(created_str)
        )
        self._auto_temporal_edges(insight.id, created_dt)
        self._auto_entity_edges(insight.id, insight.content)
        if embedder and embedding_json:
            self._auto_semantic_edges(insight.id, json.loads(embedding_json))
        self._auto_causal_edges(insight.id, insight.content, created_dt)

        return insight.id

    def get_node(self, node_id: str) -> dict | None:
        """Get a node by ID."""
        row = self.conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_nodes(
        self,
        *,
        project_id: str | None = None,
        status: str = "active",
        limit: int = 100,
    ) -> list[dict]:
        """List nodes with optional filters."""
        sql = "SELECT * FROM nodes WHERE status = ?"
        params: list = [status]
        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)
        sql += " ORDER BY created DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def node_count(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM nodes WHERE status = 'active'"
        ).fetchone()
        return row["cnt"] if row else 0

    def resolve_node(self, node_id: str) -> dict | None:
        """Resolve a node by full or partial (prefix) ID."""
        node = self.get_node(node_id)
        if node:
            return node
        rows = self.conn.execute(
            "SELECT * FROM nodes WHERE id LIKE ? LIMIT 2",
            (f"{node_id}%",),
        ).fetchall()
        if len(rows) == 1:
            return dict(rows[0])
        return None

    # --- Edge operations ---

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: str,
        weight: float = 1.0,
        metadata: dict | None = None,
    ) -> str:
        """Insert an edge. Returns edge ID."""
        edge_id = str(uuid.uuid4())
        self.conn.execute(
            """INSERT INTO edges (id, source_id, target_id, edge_type, weight, metadata, created)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                edge_id, source_id, target_id, edge_type, weight,
                json.dumps(metadata or {}), _now_iso(),
            ),
        )
        self.conn.commit()
        return edge_id

    def get_edges(
        self,
        node_id: str,
        edge_type: str | None = None,
    ) -> list[dict]:
        """Get all edges connected to a node (source or target)."""
        if edge_type:
            rows = self.conn.execute(
                """SELECT * FROM edges
                   WHERE (source_id = ? OR target_id = ?) AND edge_type = ?""",
                (node_id, node_id, edge_type),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM edges WHERE source_id = ? OR target_id = ?",
                (node_id, node_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def edge_count(self, edge_type: str | None = None) -> int:
        if edge_type:
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM edges WHERE edge_type = ?",
                (edge_type,),
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) as cnt FROM edges").fetchone()
        return row["cnt"] if row else 0

    # --- Traversal ---

    def traverse(
        self,
        node_id: str,
        edge_type: str | None = None,
        depth: int = 2,
    ) -> list[dict]:
        """Traverse graph from a node, returning connected nodes.

        Returns list of dicts with 'node', 'edge_type', 'weight', 'depth'.
        """
        visited: set[str] = {node_id}
        results: list[dict] = []
        frontier = [node_id]

        for d in range(1, depth + 1):
            next_frontier: list[str] = []
            for nid in frontier:
                edges = self.get_edges(nid, edge_type)
                for edge in edges:
                    # Get the other end of the edge
                    other_id = (
                        edge["target_id"]
                        if edge["source_id"] == nid
                        else edge["source_id"]
                    )
                    if other_id in visited:
                        continue
                    visited.add(other_id)
                    node = self.get_node(other_id)
                    if node and node.get("status") == "active":
                        results.append({
                            "node": node,
                            "edge_type": edge["edge_type"],
                            "weight": edge["weight"],
                            "depth": d,
                        })
                        next_frontier.append(other_id)
            frontier = next_frontier

        return results

    # --- Stats ---

    def graph_stats(self) -> dict:
        """Return graph statistics."""
        node_count = self.node_count()
        total_edges = self.edge_count()

        edge_counts = {}
        for et in [EdgeType.TEMPORAL, EdgeType.ENTITY, EdgeType.SEMANTIC, EdgeType.CAUSAL]:
            edge_counts[et.value] = self.edge_count(et.value)

        # Top entities (from entity edge metadata)
        entity_rows = self.conn.execute(
            "SELECT metadata FROM edges WHERE edge_type = 'entity'"
        ).fetchall()
        entity_freq: dict[str, int] = {}
        for row in entity_rows:
            meta = json.loads(row["metadata"] or "{}")
            entity = meta.get("entity", "")
            if entity:
                entity_freq[entity] = entity_freq.get(entity, 0) + 1
        top_entities = sorted(entity_freq.items(), key=lambda x: x[1], reverse=True)[:10]

        # Project distribution
        proj_rows = self.conn.execute(
            "SELECT project_id, COUNT(*) as cnt FROM nodes "
            "WHERE status = 'active' AND project_id != '' "
            "GROUP BY project_id ORDER BY cnt DESC"
        ).fetchall()
        project_dist = {r["project_id"]: r["cnt"] for r in proj_rows}

        return {
            "nodes": node_count,
            "edges": total_edges,
            "edge_counts": edge_counts,
            "top_entities": top_entities,
            "project_distribution": project_dist,
        }

    # --- Auto-edge generation ---

    def _auto_temporal_edges(
        self, node_id: str, created: datetime | None
    ) -> int:
        """Link to nodes created within the temporal window."""
        if created is None:
            return 0

        window_start = created - timedelta(minutes=self.temporal_window)
        window_end = created + timedelta(minutes=self.temporal_window)

        rows = self.conn.execute(
            """SELECT id, created FROM nodes
               WHERE id != ? AND status = 'active'
               AND created >= ? AND created <= ?""",
            (node_id, _format_dt(window_start), _format_dt(window_end)),
        ).fetchall()

        count = 0
        for row in rows:
            # Check no duplicate edge exists
            existing = self.conn.execute(
                """SELECT id FROM edges
                   WHERE edge_type = 'temporal'
                   AND ((source_id = ? AND target_id = ?)
                     OR (source_id = ? AND target_id = ?))""",
                (node_id, row["id"], row["id"], node_id),
            ).fetchone()
            if existing:
                continue

            # Edge direction: earlier → later
            other_dt = _parse_dt(row["created"])
            if other_dt and other_dt < created:
                src, tgt = row["id"], node_id
            else:
                src, tgt = node_id, row["id"]

            # Weight by proximity (closer = higher)
            if other_dt:
                minutes_apart = abs((created - other_dt).total_seconds()) / 60
                weight = max(0.1, 1.0 - minutes_apart / self.temporal_window)
            else:
                weight = 0.5

            self.add_edge(src, tgt, EdgeType.TEMPORAL, weight)
            count += 1

        return count

    def _auto_entity_edges(self, node_id: str, content: str) -> int:
        """Extract entities and link to other nodes sharing them."""
        entities = extract_entities(content)
        if not entities:
            return 0

        count = 0
        # For each entity, find other active nodes mentioning it
        for entity in entities:
            rows = self.conn.execute(
                """SELECT id FROM nodes
                   WHERE id != ? AND status = 'active'
                   AND content LIKE ?""",
                (node_id, f"%{entity}%"),
            ).fetchall()

            for row in rows:
                # Check no duplicate entity edge
                existing = self.conn.execute(
                    """SELECT id FROM edges
                       WHERE edge_type = 'entity'
                       AND ((source_id = ? AND target_id = ?)
                         OR (source_id = ? AND target_id = ?))
                       AND metadata LIKE ?""",
                    (node_id, row["id"], row["id"], node_id, f'%"{entity}"%'),
                ).fetchone()
                if existing:
                    continue

                self.add_edge(
                    node_id, row["id"], EdgeType.ENTITY, 1.0,
                    metadata={"entity": entity},
                )
                count += 1

        return count

    def _auto_semantic_edges(
        self, node_id: str, embedding: list[float]
    ) -> int:
        """Find top-K similar nodes and create semantic edges."""
        rows = self.conn.execute(
            "SELECT id, embedding FROM nodes "
            "WHERE id != ? AND status = 'active' AND embedding IS NOT NULL",
            (node_id,),
        ).fetchall()

        if not rows:
            return 0

        # Compute similarities
        scored: list[tuple[str, float]] = []
        for row in rows:
            try:
                other_emb = json.loads(row["embedding"])
            except (json.JSONDecodeError, TypeError):
                continue
            sim = _cosine_similarity(embedding, other_emb)
            if sim > 0.7:  # threshold for semantic edge
                scored.append((row["id"], sim))

        # Sort by similarity, take top-K
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[: self.semantic_top_k]

        count = 0
        for other_id, sim in top:
            # Check no duplicate
            existing = self.conn.execute(
                """SELECT id FROM edges
                   WHERE edge_type = 'semantic'
                   AND ((source_id = ? AND target_id = ?)
                     OR (source_id = ? AND target_id = ?))""",
                (node_id, other_id, other_id, node_id),
            ).fetchone()
            if existing:
                continue

            self.add_edge(node_id, other_id, EdgeType.SEMANTIC, sim)
            count += 1

        return count

    def _auto_causal_edges(
        self, node_id: str, content: str, created: datetime | None
    ) -> int:
        """Detect causal language and link to related nodes."""
        if not has_causal_language(content):
            return 0

        # Find candidates: nodes sharing entities or temporally close
        entities = extract_entities(content)
        candidates: set[str] = set()

        # Entity-based candidates
        for entity in entities:
            rows = self.conn.execute(
                """SELECT id FROM nodes
                   WHERE id != ? AND status = 'active'
                   AND content LIKE ?""",
                (node_id, f"%{entity}%"),
            ).fetchall()
            for row in rows:
                candidates.add(row["id"])

        # Temporal candidates (recent nodes)
        if created:
            window_start = created - timedelta(minutes=self.temporal_window * 2)
            rows = self.conn.execute(
                """SELECT id FROM nodes
                   WHERE id != ? AND status = 'active'
                   AND created >= ? AND created <= ?""",
                (node_id, _format_dt(window_start), _format_dt(created)),
            ).fetchall()
            for row in rows:
                candidates.add(row["id"])

        count = 0
        for cand_id in list(candidates)[:5]:  # limit to 5 causal edges
            existing = self.conn.execute(
                """SELECT id FROM edges
                   WHERE edge_type = 'causal'
                   AND ((source_id = ? AND target_id = ?)
                     OR (source_id = ? AND target_id = ?))""",
                (node_id, cand_id, cand_id, node_id),
            ).fetchone()
            if existing:
                continue

            # Causal direction: candidate (cause) → this node (effect)
            self.add_edge(cand_id, node_id, EdgeType.CAUSAL, 1.0)
            count += 1

        return count
