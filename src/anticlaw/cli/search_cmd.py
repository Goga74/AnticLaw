"""CLI search command: aw search."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from anticlaw.core.config import resolve_home
from anticlaw.core.meta_db import MetaDB
from anticlaw.core.search import search


def _safe_echo(text: str) -> None:
    """Echo text, replacing unencodable characters for Windows consoles."""
    try:
        click.echo(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        click.echo(text.encode(encoding, errors="replace").decode(encoding))


@click.command("search")
@click.argument("query")
@click.option("--project", "-p", default=None, help="Filter by project name.")
@click.option("--tag", "-t", multiple=True, help="Filter by tag (repeatable).")
@click.option("--exact", is_flag=True, help="Exact phrase match.")
@click.option("--max-results", "-n", default=20, show_default=True, help="Maximum results.")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def search_cmd(
    query: str,
    project: str | None,
    tag: tuple[str, ...],
    exact: bool,
    max_results: int,
    home: Path | None,
) -> None:
    """Search conversations by keyword.

    Uses FTS5 full-text search across chat titles, summaries, content, and tags.
    """
    home_path = home or resolve_home()
    db_path = home_path / ".acl" / "meta.db"

    if not db_path.exists():
        click.echo("No search index found. Run 'aw reindex' first.")
        return

    db = MetaDB(db_path)
    try:
        results = search(
            db,
            query,
            project=project,
            tags=list(tag) if tag else None,
            exact=exact,
            max_results=max_results,
        )

        if not results:
            click.echo("No results found.")
            return

        _safe_echo(f"Found {len(results)} result(s):\n")
        for r in results:
            proj = r.project_id or "_inbox"
            _safe_echo(f"  [{proj}] {r.title}")
            _safe_echo(f"    ID: {r.chat_id[:8]}")
            if r.snippet:
                _safe_echo(f"    {r.snippet}")
            _safe_echo("")
    finally:
        db.close()
