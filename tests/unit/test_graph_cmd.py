"""Tests for anticlaw.cli.graph_cmd — aw related, why, timeline."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from click.testing import CliRunner

from anticlaw.cli.graph_cmd import related_cmd, timeline_cmd, why_cmd
from anticlaw.core.graph import GraphDB
from anticlaw.core.models import Insight


def _setup_graph(tmp_path: Path) -> tuple[Path, str, str]:
    """Create a graph.db with test nodes and return (home, node_id_1, node_id_2)."""
    home = tmp_path / "home"
    acl_dir = home / ".acl"
    acl_dir.mkdir(parents=True)

    graph = GraphDB(acl_dir / "graph.db", temporal_window_minutes=60)
    now = datetime.now(timezone.utc)

    i1 = Insight(
        content="Chose SQLite because it's embedded and requires no server",
        category="decision",
        importance="high",
        project_id="test-project",
        created=now - timedelta(minutes=10),
    )
    i2 = Insight(
        content="SQLite WAL mode enables concurrent reads",
        category="finding",
        importance="medium",
        project_id="test-project",
        created=now,
    )

    graph.add_node(i1)
    graph.add_node(i2)
    graph.close()

    return home, i1.id, i2.id


class TestRelatedCmd:
    def test_related_shows_connected_nodes(self, tmp_path: Path):
        home, nid1, nid2 = _setup_graph(tmp_path)
        runner = CliRunner()
        result = runner.invoke(related_cmd, [nid1, "--home", str(home)])
        assert result.exit_code == 0
        assert "Related to:" in result.output

    def test_related_partial_id(self, tmp_path: Path):
        home, nid1, _ = _setup_graph(tmp_path)
        runner = CliRunner()
        result = runner.invoke(related_cmd, [nid1[:8], "--home", str(home)])
        assert result.exit_code == 0
        assert "Related to:" in result.output

    def test_related_not_found(self, tmp_path: Path):
        home, _, _ = _setup_graph(tmp_path)
        runner = CliRunner()
        result = runner.invoke(related_cmd, ["nonexistent", "--home", str(home)])
        assert result.exit_code == 0
        assert "not found" in result.output.lower()

    def test_related_no_graph_db(self, tmp_path: Path):
        home = tmp_path / "empty"
        home.mkdir()
        runner = CliRunner()
        result = runner.invoke(related_cmd, ["any-id", "--home", str(home)])
        assert result.exit_code == 0
        assert "No graph database" in result.output

    def test_related_edge_type_filter(self, tmp_path: Path):
        home, nid1, _ = _setup_graph(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            related_cmd, [nid1, "--edge-type", "causal", "--home", str(home)]
        )
        assert result.exit_code == 0


class TestWhyCmd:
    def test_why_finds_matching_nodes(self, tmp_path: Path):
        home, _, _ = _setup_graph(tmp_path)
        runner = CliRunner()
        result = runner.invoke(why_cmd, ["SQLite", "--home", str(home)])
        assert result.exit_code == 0
        assert "Node:" in result.output

    def test_why_no_match(self, tmp_path: Path):
        home, _, _ = _setup_graph(tmp_path)
        runner = CliRunner()
        result = runner.invoke(why_cmd, ["nonexistent-topic", "--home", str(home)])
        assert result.exit_code == 0
        assert "No nodes matching" in result.output

    def test_why_no_graph_db(self, tmp_path: Path):
        home = tmp_path / "empty"
        home.mkdir()
        runner = CliRunner()
        result = runner.invoke(why_cmd, ["anything", "--home", str(home)])
        assert result.exit_code == 0
        assert "No graph database" in result.output


class TestTimelineCmd:
    def test_timeline_shows_nodes(self, tmp_path: Path):
        home, _, _ = _setup_graph(tmp_path)
        runner = CliRunner()
        result = runner.invoke(timeline_cmd, ["test-project", "--home", str(home)])
        assert result.exit_code == 0
        assert "Timeline" in result.output
        assert "test-project" in result.output

    def test_timeline_no_project(self, tmp_path: Path):
        home, _, _ = _setup_graph(tmp_path)
        runner = CliRunner()
        result = runner.invoke(timeline_cmd, ["nonexistent", "--home", str(home)])
        assert result.exit_code == 0
        assert "No nodes found" in result.output

    def test_timeline_no_graph_db(self, tmp_path: Path):
        home = tmp_path / "empty"
        home.mkdir()
        runner = CliRunner()
        result = runner.invoke(timeline_cmd, ["test", "--home", str(home)])
        assert result.exit_code == 0
        assert "No graph database" in result.output
