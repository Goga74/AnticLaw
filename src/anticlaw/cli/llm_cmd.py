"""CLI commands for local LLM operations: aw summarize, aw autotag, aw ask."""

from __future__ import annotations

from pathlib import Path

import click

from anticlaw.core.config import load_config, resolve_home
from anticlaw.llm.ollama_client import OllamaClient
from anticlaw.llm.qa import ask as qa_ask
from anticlaw.llm.summarizer import summarize_chat, summarize_project
from anticlaw.llm.tagger import auto_tag


def _get_llm_config(home: Path) -> dict:
    """Load LLM config section from config.yaml."""
    config = load_config(home / ".acl" / "config.yaml")
    return config.get("llm", {})


def _resolve_target(home: Path, target: str) -> tuple[str, str]:
    """Resolve a target argument to (type, identifier).

    Returns ("chat", chat_id) or ("project", project_name).
    """
    from anticlaw.core.meta_db import MetaDB

    db_path = home / ".acl" / "meta.db"
    if not db_path.exists():
        return ("unknown", target)

    db = MetaDB(db_path)
    try:
        # Try as project first
        project = db.get_project(target)
        if project:
            return ("project", target)

        # Try as chat ID (exact)
        chat = db.get_chat(target)
        if chat:
            return ("chat", target)

        # Try as partial chat ID
        rows = db.conn.execute(
            "SELECT id FROM chats WHERE id LIKE ? LIMIT 2",
            (f"{target}%",),
        ).fetchall()
        if len(rows) == 1:
            return ("chat", rows[0]["id"])

        # Try as project directory name
        project_dir = home / target
        if project_dir.is_dir():
            return ("project", target)
    finally:
        db.close()

    return ("unknown", target)


# --- aw summarize <target> ---


@click.command("summarize")
@click.argument("target")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def summarize_cmd(target: str, home: Path | None) -> None:
    """Generate or update summary for a chat or project via LLM."""
    home_path = home or resolve_home()
    llm_config = _get_llm_config(home_path)
    client = OllamaClient(llm_config)

    if not client.is_available():
        click.echo("Error: Ollama is not running. Start it with 'ollama serve'.")
        return

    target_type, target_id = _resolve_target(home_path, target)

    if target_type == "chat":
        _summarize_chat(home_path, target_id, client)
    elif target_type == "project":
        _summarize_project(home_path, target_id, client)
    else:
        click.echo(f"Target not found: {target}")
        click.echo("Specify a chat ID or project name.")


def _summarize_chat(home: Path, chat_id: str, client: OllamaClient) -> None:
    from anticlaw.core.meta_db import MetaDB
    from anticlaw.core.storage import ChatStorage

    db = MetaDB(home / ".acl" / "meta.db")
    try:
        chat_row = db.get_chat(chat_id)
        if not chat_row:
            click.echo(f"Chat not found: {chat_id}")
            return

        file_path = Path(chat_row["file_path"])
        if not file_path.exists():
            click.echo(f"Chat file missing: {file_path}")
            return

        storage = ChatStorage(home)
        chat = storage.read_chat(file_path, load_messages=True)

        click.echo(f"Summarizing: {chat.title or chat_id[:8]}...")
        summary = summarize_chat(chat, client=client)

        if not summary:
            click.echo("Failed to generate summary.")
            return

        # Update the chat file and index
        chat.summary = summary
        storage.write_chat(file_path, chat)
        db.index_chat(chat, file_path, chat_row.get("project_id", ""))

        click.echo(f"Summary: {summary}")
    finally:
        db.close()


def _summarize_project(home: Path, project_name: str, client: OllamaClient) -> None:
    from anticlaw.core.meta_db import MetaDB
    from anticlaw.core.models import Chat
    from anticlaw.core.storage import ChatStorage

    db = MetaDB(home / ".acl" / "meta.db")
    try:
        project_row = db.get_project(project_name)
        description = project_row.get("description", "") if project_row else ""

        # Load chats for this project
        chat_rows = db.list_chats(project_id=project_name)
        if not chat_rows:
            click.echo(f"No chats found in project: {project_name}")
            return

        # Build Chat objects with summaries only (no messages needed)
        chats = []
        for row in chat_rows:
            chats.append(Chat(
                id=row["id"],
                title=row.get("title", ""),
                summary=row.get("summary", ""),
            ))

        click.echo(f"Summarizing project '{project_name}' ({len(chats)} chats)...")
        summary = summarize_project(
            project_name, description, chats, client=client,
        )

        if not summary:
            click.echo("Failed to generate project summary.")
            return

        click.echo(f"Summary: {summary}")

        # Update _project.yaml if it exists
        project_dir = home / project_name
        project_file = project_dir / "_project.yaml"
        if project_file.exists():
            storage = ChatStorage(home)
            project = storage.read_project(project_file)
            project.description = summary
            storage.write_project(project_file, project)
            click.echo("Updated _project.yaml description.")
    finally:
        db.close()


# --- aw autotag <target> ---


@click.command("autotag")
@click.argument("target")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def autotag_cmd(target: str, home: Path | None) -> None:
    """Auto-generate tags for a chat or all chats in a project via LLM."""
    home_path = home or resolve_home()
    llm_config = _get_llm_config(home_path)
    client = OllamaClient(llm_config)

    if not client.is_available():
        click.echo("Error: Ollama is not running. Start it with 'ollama serve'.")
        return

    target_type, target_id = _resolve_target(home_path, target)

    if target_type == "chat":
        _autotag_chat(home_path, target_id, client)
    elif target_type == "project":
        _autotag_project(home_path, target_id, client)
    else:
        click.echo(f"Target not found: {target}")
        click.echo("Specify a chat ID or project name.")


def _autotag_chat(home: Path, chat_id: str, client: OllamaClient) -> None:
    from anticlaw.core.meta_db import MetaDB
    from anticlaw.core.storage import ChatStorage

    db = MetaDB(home / ".acl" / "meta.db")
    try:
        chat_row = db.get_chat(chat_id)
        if not chat_row:
            click.echo(f"Chat not found: {chat_id}")
            return

        file_path = Path(chat_row["file_path"])
        if not file_path.exists():
            click.echo(f"Chat file missing: {file_path}")
            return

        storage = ChatStorage(home)
        chat = storage.read_chat(file_path, load_messages=True)

        click.echo(f"Auto-tagging: {chat.title or chat_id[:8]}...")
        tags = auto_tag(chat, client=client)

        if not tags:
            click.echo("No tags suggested.")
            return

        # Merge with existing tags
        merged = list(dict.fromkeys(chat.tags + tags))
        chat.tags = merged
        storage.write_chat(file_path, chat)
        db.update_chat_tags(chat_id, merged)

        click.echo(f"Tags: {', '.join(tags)}")
        if len(merged) > len(tags):
            click.echo(f"All tags: {', '.join(merged)}")
    finally:
        db.close()


def _autotag_project(home: Path, project_name: str, client: OllamaClient) -> None:
    from anticlaw.core.meta_db import MetaDB
    from anticlaw.core.storage import ChatStorage

    db = MetaDB(home / ".acl" / "meta.db")
    try:
        chat_rows = db.list_chats(project_id=project_name)
        if not chat_rows:
            click.echo(f"No chats found in project: {project_name}")
            return

        storage = ChatStorage(home)
        tagged = 0

        for row in chat_rows:
            file_path = Path(row["file_path"])
            if not file_path.exists():
                continue

            chat = storage.read_chat(file_path, load_messages=True)
            click.echo(f"  Tagging: {chat.title or row['id'][:8]}...")
            tags = auto_tag(chat, client=client)

            if tags:
                merged = list(dict.fromkeys(chat.tags + tags))
                chat.tags = merged
                storage.write_chat(file_path, chat)
                db.update_chat_tags(row["id"], merged)
                click.echo(f"    -> {', '.join(tags)}")
                tagged += 1

        click.echo(f"\nTagged {tagged}/{len(chat_rows)} chats in '{project_name}'.")
    finally:
        db.close()


# --- aw ask <question> ---


@click.command("ask")
@click.argument("question")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def ask_cmd(question: str, home: Path | None) -> None:
    """Ask a question over the knowledge base using local LLM."""
    home_path = home or resolve_home()
    llm_config = _get_llm_config(home_path)
    client = OllamaClient(llm_config)

    if not client.is_available():
        click.echo("Error: Ollama is not running. Start it with 'ollama serve'.")
        return

    click.echo(f"Searching knowledge base for: {question}\n")
    result = qa_ask(question, home_path, client=client)

    if result.error:
        click.echo(f"Error: {result.error}")
        return

    if result.answer:
        click.echo(result.answer)

    if result.sources:
        click.echo("\n--- Sources ---")
        for src in result.sources:
            project = f" ({src.project_id})" if src.project_id else ""
            click.echo(f"  {src.chat_id[:8]}: {src.title}{project}")
