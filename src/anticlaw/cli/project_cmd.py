"""CLI project management commands: aw list, show, move, tag, create, reindex."""

from __future__ import annotations

import json
from pathlib import Path

import click

from anticlaw.core.config import resolve_home
from anticlaw.core.meta_db import MetaDB
from anticlaw.core.storage import ChatStorage


# --- aw list [project] ---


@click.command("list")
@click.argument("project", required=False)
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def list_cmd(project: str | None, home: Path | None) -> None:
    """List projects, or list chats in a project."""
    home_path = home or resolve_home()
    db_path = home_path / ".acl" / "meta.db"

    if not db_path.exists():
        click.echo("No index found. Run 'aw reindex' first.")
        return

    db = MetaDB(db_path)
    try:
        if project:
            chats = db.list_chats(project)
            if not chats:
                click.echo(f"No chats found in '{project}'.")
                return
            click.echo(f"Chats in {project} ({len(chats)}):\n")
            for c in chats:
                tags = json.loads(c.get("tags") or "[]")
                tag_str = f"  [{', '.join(tags)}]" if tags else ""
                created = (c.get("created") or "")[:10]
                click.echo(f"  {c['id'][:8]}  {created}  {c['title']}{tag_str}")
        else:
            projects = db.list_projects()
            if not projects:
                click.echo("No projects found. Run 'aw import' or 'aw create project' first.")
                return
            click.echo(f"Projects ({len(projects)}):\n")
            for p in projects:
                chat_count = len(db.list_chats(p["id"]))
                click.echo(f"  {p['name']}  ({chat_count} chats)")
    finally:
        db.close()


# --- aw show <chat-id> ---


@click.command("show")
@click.argument("chat_id")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def show_cmd(chat_id: str, home: Path | None) -> None:
    """Display a chat conversation."""
    home_path = home or resolve_home()
    db_path = home_path / ".acl" / "meta.db"

    if not db_path.exists():
        click.echo("No index found. Run 'aw reindex' first.")
        return

    db = MetaDB(db_path)
    try:
        chat_rec = _resolve_chat(db, chat_id)
        if not chat_rec:
            click.echo(f"Chat not found: {chat_id}")
            return

        file_path = Path(chat_rec["file_path"])
        if not file_path.exists():
            click.echo(f"Chat file not found: {file_path}")
            return

        storage = ChatStorage(home_path)
        chat = storage.read_chat(file_path)

        click.echo(f"# {chat.title}")
        click.echo(f"Provider: {chat.provider} | Model: {chat.model}")
        click.echo(f"Created: {chat.created}")
        if chat.tags:
            click.echo(f"Tags: {', '.join(chat.tags)}")
        click.echo("---")
        for msg in chat.messages:
            role = msg.role.capitalize()
            click.echo(f"\n## {role}")
            click.echo(msg.content)
    finally:
        db.close()


# --- aw move <chat-id> <project> ---


@click.command("move")
@click.argument("chat_id")
@click.argument("project")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def move_cmd(chat_id: str, project: str, home: Path | None) -> None:
    """Move a chat to a different project."""
    home_path = home or resolve_home()
    db_path = home_path / ".acl" / "meta.db"

    if not db_path.exists():
        click.echo("No index found. Run 'aw reindex' first.")
        return

    db = MetaDB(db_path)
    storage = ChatStorage(home_path)

    try:
        chat_rec = _resolve_chat(db, chat_id)
        if not chat_rec:
            click.echo(f"Chat not found: {chat_id}")
            return

        src_path = Path(chat_rec["file_path"])
        if not src_path.exists():
            click.echo(f"Chat file not found: {src_path}")
            return

        target_dir = home_path / project
        if not target_dir.exists():
            click.echo(f"Project '{project}' does not exist.")
            return

        new_path = storage.move_chat(src_path, target_dir)
        db.update_chat_path(chat_rec["id"], new_path, project)
        click.echo(f"Moved to {project}/{new_path.name}")
    finally:
        db.close()


# --- aw tag <chat-id> <tags...> ---


@click.command("tag")
@click.argument("chat_id")
@click.argument("tags", nargs=-1, required=True)
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def tag_cmd(chat_id: str, tags: tuple[str, ...], home: Path | None) -> None:
    """Add tags to a chat."""
    home_path = home or resolve_home()
    db_path = home_path / ".acl" / "meta.db"

    if not db_path.exists():
        click.echo("No index found. Run 'aw reindex' first.")
        return

    db = MetaDB(db_path)
    storage = ChatStorage(home_path)

    try:
        chat_rec = _resolve_chat(db, chat_id)
        if not chat_rec:
            click.echo(f"Chat not found: {chat_id}")
            return

        file_path = Path(chat_rec["file_path"])
        if not file_path.exists():
            click.echo(f"Chat file not found: {file_path}")
            return

        # Read chat, merge tags, write back
        chat = storage.read_chat(file_path)
        existing = set(chat.tags)
        chat.tags = sorted(existing | set(tags))
        storage.write_chat(file_path, chat)

        # Update meta.db
        db.update_chat_tags(chat_rec["id"], chat.tags)
        click.echo(f"Tags updated: {', '.join(chat.tags)}")
    finally:
        db.close()


# --- aw create project <name> ---


@click.group("create")
def create_group() -> None:
    """Create resources."""


@create_group.command("project")
@click.argument("name")
@click.option("--description", "-d", default="", help="Project description.")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def create_project_cmd(name: str, description: str, home: Path | None) -> None:
    """Create a new project."""
    home_path = home or resolve_home()
    storage = ChatStorage(home_path)
    storage.init_home()

    project_dir = storage.create_project(name, description)

    # Index the new project
    db = MetaDB(home_path / ".acl" / "meta.db")
    try:
        project = storage.read_project(project_dir / "_project.yaml")
        db.index_project(project, project_dir)
        click.echo(f"Created project: {name} ({project_dir.name}/)")
    finally:
        db.close()


# --- aw reindex ---


@click.command("reindex")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def reindex_cmd(home: Path | None) -> None:
    """Rebuild the search index from the file system."""
    home_path = home or resolve_home()
    storage = ChatStorage(home_path)
    storage.init_home()

    db = MetaDB(home_path / ".acl" / "meta.db")
    try:
        click.echo("Reindexing...")
        chats_count, projects_count = db.reindex_all(home_path)
        click.echo(f"Indexed {chats_count} chats in {projects_count} projects.")
    finally:
        db.close()


# --- Helpers ---


def _resolve_chat(db: MetaDB, chat_id: str) -> dict | None:
    """Resolve a chat by full or partial (prefix) ID."""
    chat = db.get_chat(chat_id)
    if chat:
        return chat
    # Try prefix match
    rows = db.conn.execute(
        "SELECT * FROM chats WHERE id LIKE ? LIMIT 2",
        (f"{chat_id}%",),
    ).fetchall()
    if len(rows) == 1:
        return dict(rows[0])
    return None
