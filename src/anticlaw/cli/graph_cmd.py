"""CLI graph commands: aw related, aw why, aw timeline."""

from __future__ import annotations

from pathlib import Path

import click

from anticlaw.core.config import resolve_home
from anticlaw.core.graph import GraphDB, intent_detect


def _get_graph(home: Path) -> GraphDB:
    return GraphDB(home / ".acl" / "graph.db")


# --- aw related <node-id> ---


@click.command("related")
@click.argument("node_id")
@click.option(
    "--edge-type", "-t",
    type=click.Choice(["temporal", "entity", "semantic", "causal"]),
    default=None,
    help="Filter by edge type.",
)
@click.option("--depth", "-d", default=2, help="Traversal depth (default 2).")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def related_cmd(
    node_id: str,
    edge_type: str | None,
    depth: int,
    home: Path | None,
) -> None:
    """Traverse the knowledge graph from a node."""
    home_path = home or resolve_home()
    db_path = home_path / ".acl" / "graph.db"

    if not db_path.exists():
        click.echo("No graph database found. Save insights with 'aw_remember' first.")
        return

    graph = _get_graph(home_path)
    try:
        node = graph.resolve_node(node_id)
        if not node:
            click.echo(f"Node not found: {node_id}")
            return

        click.echo(f"Related to: {node['content'][:80]}")
        click.echo(f"  (id: {node['id'][:8]}, {node['category']}, {node['importance']})")
        click.echo("---")

        results = graph.traverse(node["id"], edge_type, depth)
        if not results:
            click.echo("No related nodes found.")
            return

        for r in results:
            n = r["node"]
            et = r["edge_type"]
            w = r["weight"]
            d = r["depth"]
            click.echo(
                f"  [{et}] (w={w:.2f}, depth={d}) {n['id'][:8]}: "
                f"{n['content'][:60]}"
            )
    finally:
        graph.close()


# --- aw why <query> ---


@click.command("why")
@click.argument("query")
@click.option("--depth", "-d", default=3, help="Causal chain depth (default 3).")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def why_cmd(query: str, depth: int, home: Path | None) -> None:
    """Trace causal chain for a decision or finding."""
    home_path = home or resolve_home()
    db_path = home_path / ".acl" / "graph.db"

    if not db_path.exists():
        click.echo("No graph database found. Save insights with 'aw_remember' first.")
        return

    graph = _get_graph(home_path)
    try:
        # Search for matching nodes
        rows = graph.conn.execute(
            "SELECT * FROM nodes WHERE status = 'active' AND content LIKE ? LIMIT 5",
            (f"%{query}%",),
        ).fetchall()

        if not rows:
            click.echo(f"No nodes matching: {query}")
            return

        for row in rows:
            node = dict(row)
            click.echo(f"\nNode: {node['content'][:80]}")
            click.echo(f"  (id: {node['id'][:8]}, {node['category']})")

            results = graph.traverse(node["id"], "causal", depth)
            if results:
                click.echo("  Causal chain:")
                for r in results:
                    n = r["node"]
                    d = r["depth"]
                    click.echo(f"    {'  ' * d}-> {n['content'][:70]}")
            else:
                click.echo("  No causal links found.")
    finally:
        graph.close()


# --- aw timeline <project> ---


@click.command("timeline")
@click.argument("project")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def timeline_cmd(project: str, home: Path | None) -> None:
    """Show temporal timeline of insights in a project."""
    home_path = home or resolve_home()
    db_path = home_path / ".acl" / "graph.db"

    if not db_path.exists():
        click.echo("No graph database found. Save insights with 'aw_remember' first.")
        return

    graph = _get_graph(home_path)
    try:
        nodes = graph.list_nodes(project_id=project, limit=50)
        if not nodes:
            click.echo(f"No nodes found for project: {project}")
            return

        # Sort by created time
        nodes.sort(key=lambda n: n.get("created") or "")

        click.echo(f"Timeline for '{project}' ({len(nodes)} nodes):\n")
        for node in nodes:
            created = (node.get("created") or "")[:16]
            category = node.get("category", "")
            importance = node.get("importance", "")
            content = node["content"][:70]
            click.echo(
                f"  {created}  [{category}/{importance}]  {node['id'][:8]}: {content}"
            )
    finally:
        graph.close()
