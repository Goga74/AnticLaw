"""CLI command: aw clear — delete _inbox/ and optionally _archive/ contents."""

from __future__ import annotations

from pathlib import Path

import click

from anticlaw.core.config import resolve_home


@click.command("clear")
@click.option("--all", "clear_all", is_flag=True, help="Also clear _archive/ and rebuild index.")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def clear_cmd(clear_all: bool, home: Path | None) -> None:
    """Delete all files in _inbox/ (and _archive/ with --all)."""
    home_path = home or resolve_home()

    if clear_all:
        prompt = "Delete _inbox/, _archive/ and rebuild index? [y/N]"
    else:
        prompt = "Delete all files in _inbox/? [y/N]"

    answer = click.prompt(prompt, default="N", show_default=False)
    if answer.lower() not in ("y", "yes"):
        click.echo("Aborted.")
        return

    inbox_count = _clear_dir(home_path / "_inbox")
    click.echo(f"Cleared {inbox_count} files from _inbox/")

    if clear_all:
        archive_count = _clear_dir(home_path / "_archive")
        click.echo(f"Cleared {archive_count} files from _archive/")

        from anticlaw.core.meta_db import MetaDB

        db = MetaDB(home_path / ".acl" / "meta.db")
        try:
            chats, projects = db.reindex_all(home_path)
            click.echo(f"Reindexed {chats} chats in {projects} projects.")
        finally:
            db.close()


def _clear_dir(dir_path: Path) -> int:
    """Delete all files in a directory (non-recursive). Return count deleted."""
    if not dir_path.is_dir():
        return 0
    count = 0
    for f in dir_path.iterdir():
        if f.is_file():
            f.unlink()
            count += 1
    return count
