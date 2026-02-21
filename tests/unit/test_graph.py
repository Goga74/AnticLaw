"""Tests for anticlaw.core.graph — MAGMA knowledge graph."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from anticlaw.core.graph import GraphDB, intent_detect
from anticlaw.core.models import EdgeType, Insight


def _make_insight(
    content: str = "Test insight",
    category: str = "fact",
    importance: str = "medium",
    project_id: str = "test-project",
    created: datetime | None = None,
    tags: list[str] | None = None,
) -> Insight:
    return Insight(
        content=content,
        category=category,
        importance=importance,
        project_id=project_id,
        created=created or datetime.now(timezone.utc),
        tags=tags or [],
    )


class TestGraphDBBasic:
    def test_create_db(self, tmp_path: Path):
        db_path = tmp_path / "graph.db"
        graph = GraphDB(db_path)
        assert graph.node_count() == 0
        assert graph.edge_count() == 0
        graph.close()

    def test_add_and_get_node(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db")
        insight = _make_insight("Use SQLite for graph storage")
        node_id = graph.add_node(insight)
        assert node_id == insight.id

        node = graph.get_node(node_id)
        assert node is not None
        assert node["content"] == "Use SQLite for graph storage"
        assert node["category"] == "fact"
        assert node["importance"] == "medium"
        assert node["project_id"] == "test-project"
        graph.close()

    def test_list_nodes(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db")
        graph.add_node(_make_insight("Node 1"))
        graph.add_node(_make_insight("Node 2"))
        graph.add_node(_make_insight("Node 3"))

        nodes = graph.list_nodes()
        assert len(nodes) == 3
        graph.close()

    def test_list_nodes_by_project(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db")
        graph.add_node(_make_insight("In alpha", project_id="alpha"))
        graph.add_node(_make_insight("In beta", project_id="beta"))

        alpha_nodes = graph.list_nodes(project_id="alpha")
        assert len(alpha_nodes) == 1
        assert alpha_nodes[0]["content"] == "In alpha"
        graph.close()

    def test_node_count(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db")
        assert graph.node_count() == 0
        graph.add_node(_make_insight())
        assert graph.node_count() == 1
        graph.close()

    def test_resolve_node_partial_id(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db")
        insight = _make_insight()
        graph.add_node(insight)

        # Full ID
        assert graph.resolve_node(insight.id) is not None
        # Partial ID (prefix)
        assert graph.resolve_node(insight.id[:8]) is not None
        # Nonexistent
        assert graph.resolve_node("nonexistent") is None
        graph.close()


class TestTemporalEdges:
    def test_temporal_edges_within_window(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db", temporal_window_minutes=30)
        now = datetime.now(timezone.utc)

        # Add two nodes 10 minutes apart
        graph.add_node(_make_insight("Node A", created=now - timedelta(minutes=10)))
        graph.add_node(_make_insight("Node B", created=now))

        assert graph.edge_count("temporal") >= 1

        graph.close()

    def test_no_temporal_edges_outside_window(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db", temporal_window_minutes=30)
        now = datetime.now(timezone.utc)

        # Add two nodes 60 minutes apart (outside 30 min window)
        graph.add_node(_make_insight("Node A", created=now - timedelta(minutes=60)))
        graph.add_node(_make_insight("Node B", created=now))

        assert graph.edge_count("temporal") == 0
        graph.close()

    def test_temporal_edges_three_nodes(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db", temporal_window_minutes=30)
        now = datetime.now(timezone.utc)

        graph.add_node(_make_insight("A", created=now - timedelta(minutes=20)))
        graph.add_node(_make_insight("B", created=now - timedelta(minutes=10)))
        graph.add_node(_make_insight("C", created=now))

        # All three are within 30 min window of each other
        assert graph.edge_count("temporal") >= 2
        graph.close()


class TestEntityEdges:
    def test_shared_entity_creates_edge(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db")

        graph.add_node(_make_insight("Use SQLite for graph storage"))
        graph.add_node(_make_insight("SQLite WAL mode for concurrency"))

        assert graph.edge_count("entity") >= 1
        graph.close()

    def test_no_shared_entity_no_edge(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db")

        graph.add_node(_make_insight("Something about apples"))
        graph.add_node(_make_insight("Something about oranges"))

        assert graph.edge_count("entity") == 0
        graph.close()

    def test_camelcase_entity_link(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db")

        graph.add_node(_make_insight("The ChatStorage class reads files"))
        graph.add_node(_make_insight("ChatStorage also writes YAML frontmatter"))

        assert graph.edge_count("entity") >= 1
        graph.close()

    def test_url_entity_link(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db")

        graph.add_node(_make_insight("See https://example.com/docs for API"))
        graph.add_node(_make_insight("Updated https://example.com/docs page"))

        assert graph.edge_count("entity") >= 1
        graph.close()


class TestCausalEdges:
    def test_because_creates_causal_edge(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db", temporal_window_minutes=60)
        now = datetime.now(timezone.utc)

        graph.add_node(_make_insight(
            "Found race condition in writer",
            created=now - timedelta(minutes=5),
        ))
        graph.add_node(_make_insight(
            "Fixed with flock because the race condition needed locking",
            created=now,
        ))

        assert graph.edge_count("causal") >= 1
        graph.close()

    def test_no_causal_without_keywords(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db", temporal_window_minutes=60)
        now = datetime.now(timezone.utc)

        graph.add_node(_make_insight("SQLite is fast", created=now - timedelta(minutes=5)))
        graph.add_node(_make_insight("We use WAL mode", created=now))

        assert graph.edge_count("causal") == 0
        graph.close()

    def test_russian_causal_keywords(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db", temporal_window_minutes=60)
        now = datetime.now(timezone.utc)

        graph.add_node(_make_insight(
            "Выбрали SQLite",
            created=now - timedelta(minutes=5),
        ))
        graph.add_node(_make_insight(
            "Потому что SQLite встроен и не требует сервера",
            created=now,
        ))

        assert graph.edge_count("causal") >= 1
        graph.close()


class TestSemanticEdges:
    """Semantic edges require an embedder. Test with a mock."""

    def test_semantic_edges_with_mock_embedder(self, tmp_path: Path):
        class MockEmbedder:
            def embed(self, text: str) -> list[float]:
                # Simple hash-based mock: similar texts get similar vectors
                if "sqlite" in text.lower():
                    return [0.9, 0.1, 0.1]
                return [0.1, 0.9, 0.1]

        graph = GraphDB(tmp_path / "graph.db")
        embedder = MockEmbedder()

        graph.add_node(
            _make_insight("Use SQLite for storage"),
            embedder=embedder,
        )
        graph.add_node(
            _make_insight("SQLite WAL mode is good"),
            embedder=embedder,
        )

        assert graph.edge_count("semantic") >= 1
        graph.close()

    def test_no_semantic_edges_without_embedder(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db")

        graph.add_node(_make_insight("Use SQLite for storage"))
        graph.add_node(_make_insight("SQLite WAL mode is good"))

        assert graph.edge_count("semantic") == 0
        graph.close()

    def test_dissimilar_content_no_semantic_edge(self, tmp_path: Path):
        class MockEmbedder:
            def embed(self, text: str) -> list[float]:
                if "apple" in text.lower():
                    return [1.0, 0.0, 0.0]
                return [0.0, 0.0, 1.0]

        graph = GraphDB(tmp_path / "graph.db")
        embedder = MockEmbedder()

        graph.add_node(_make_insight("Apples are fruits"), embedder=embedder)
        graph.add_node(_make_insight("SQL queries are fast"), embedder=embedder)

        # Cosine similarity < 0.7 threshold
        assert graph.edge_count("semantic") == 0
        graph.close()


class TestTraversal:
    def test_traverse_returns_connected_nodes(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db", temporal_window_minutes=60)
        now = datetime.now(timezone.utc)

        i1 = _make_insight("Node A", created=now - timedelta(minutes=10))
        i2 = _make_insight("Node B", created=now)

        graph.add_node(i1)
        graph.add_node(i2)

        # Should have temporal edges
        results = graph.traverse(i1.id, depth=1)
        assert len(results) >= 1
        assert any(r["node"]["id"] == i2.id for r in results)
        graph.close()

    def test_traverse_with_edge_type_filter(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db", temporal_window_minutes=60)
        now = datetime.now(timezone.utc)

        i1 = _make_insight("Node A", created=now - timedelta(minutes=10))
        i2 = _make_insight("Node B", created=now)

        graph.add_node(i1)
        graph.add_node(i2)

        # Filter by type that doesn't exist
        results = graph.traverse(i1.id, edge_type="causal", depth=1)
        # Should be empty or only causal edges
        for r in results:
            assert r["edge_type"] == "causal"
        graph.close()

    def test_traverse_empty_graph(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db")
        insight = _make_insight()
        graph.add_node(insight)

        results = graph.traverse(insight.id, depth=2)
        assert results == []
        graph.close()

    def test_traverse_depth_limit(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db", temporal_window_minutes=120)
        now = datetime.now(timezone.utc)

        i1 = _make_insight("A", created=now - timedelta(minutes=40))
        i2 = _make_insight("B", created=now - timedelta(minutes=20))
        i3 = _make_insight("C", created=now)

        graph.add_node(i1)
        graph.add_node(i2)
        graph.add_node(i3)

        # Depth 1 from i1 should not reach i3 if it goes A→B→C
        depth1 = graph.traverse(i1.id, depth=1)
        depth2 = graph.traverse(i1.id, depth=2)
        assert len(depth2) >= len(depth1)
        graph.close()


class TestGraphStats:
    def test_empty_graph_stats(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db")
        stats = graph.graph_stats()
        assert stats["nodes"] == 0
        assert stats["edges"] == 0
        graph.close()

    def test_stats_with_data(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db", temporal_window_minutes=60)
        now = datetime.now(timezone.utc)

        graph.add_node(_make_insight(
            "ChatStorage uses SQLite",
            created=now - timedelta(minutes=5),
        ))
        graph.add_node(_make_insight(
            "ChatStorage handles YAML frontmatter",
            created=now,
        ))

        stats = graph.graph_stats()
        assert stats["nodes"] == 2
        assert stats["edges"] > 0
        assert "edge_counts" in stats
        assert "top_entities" in stats
        assert "project_distribution" in stats
        graph.close()

    def test_project_distribution(self, tmp_path: Path):
        graph = GraphDB(tmp_path / "graph.db")

        graph.add_node(_make_insight("A", project_id="alpha"))
        graph.add_node(_make_insight("B", project_id="alpha"))
        graph.add_node(_make_insight("C", project_id="beta"))

        stats = graph.graph_stats()
        assert stats["project_distribution"]["alpha"] == 2
        assert stats["project_distribution"]["beta"] == 1
        graph.close()


class TestIntentDetect:
    def test_why_returns_causal(self):
        assert intent_detect("why did we choose SQLite?") == "causal"
        assert intent_detect("Why SQLite?") == "causal"

    def test_russian_why_returns_causal(self):
        assert intent_detect("почему выбрали SQLite?") == "causal"

    def test_reason_returns_causal(self):
        assert intent_detect("What was the reason for JWT?") == "causal"

    def test_when_returns_temporal(self):
        assert intent_detect("when did we decide on SQLite?") == "temporal"

    def test_russian_when_returns_temporal(self):
        assert intent_detect("когда решили использовать SQLite?") == "temporal"

    def test_timeline_returns_temporal(self):
        assert intent_detect("show me the timeline of decisions") == "temporal"

    def test_what_returns_entity(self):
        assert intent_detect("what tools do we use?") == "entity"

    def test_russian_what_returns_entity(self):
        assert intent_detect("что мы используем для поиска?") == "entity"

    def test_neutral_returns_none(self):
        assert intent_detect("search for auth") is None
        assert intent_detect("find JWT") is None

    def test_empty_returns_none(self):
        assert intent_detect("") is None
