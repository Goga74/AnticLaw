"""CLI sync commands: aw send, aw chat."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import click

from anticlaw.core.config import load_config, resolve_home


@click.command("send")
@click.argument("chat_id")
@click.option(
    "--provider",
    "-p",
    default=None,
    type=click.Choice(["claude", "chatgpt", "gemini", "ollama"]),
    help="LLM provider to send to (default: from config hierarchy).",
)
@click.option("--model", "-m", default=None, help="Override the default model.")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def send_cmd(chat_id: str, provider: str | None, model: str | None, home: Path | None) -> None:
    """Send a chat to an LLM API and append the response to the file.

    WARNING: Cloud API access (Claude, ChatGPT) requires SEPARATE paid API keys.
    Web subscriptions do NOT provide API access. Gemini has a free tier.
    """
    home_path = home or resolve_home()
    db_path = home_path / ".acl" / "meta.db"

    if not db_path.exists():
        click.echo("Error: No knowledge base found. Run 'aw init' first.")
        return

    # Resolve chat file path from ID
    from anticlaw.core.meta_db import MetaDB

    db = MetaDB(db_path)
    try:
        chat_path = _resolve_chat_path(db, chat_id)
    finally:
        db.close()

    if not chat_path:
        click.echo(f"Error: Chat '{chat_id}' not found.")
        return

    if not Path(chat_path).exists():
        click.echo(f"Error: Chat file not found: {chat_path}")
        return

    from anticlaw.sync.engine import SyncEngine
    from anticlaw.sync.providers import SyncAPIError, SyncAuthError

    engine = SyncEngine(home_path)
    resolved_target = provider or engine.resolve_push_target(Path(chat_path))

    if not resolved_target:
        click.echo(
            "Error: No push target configured.\n"
            "Set one of:\n"
            "  - push_target: <provider> in chat frontmatter\n"
            "  - sync.push_target in _project.yaml\n"
            "  - sync.default_push_target in config.yaml"
        )
        return

    click.echo(f"Sending to {resolved_target}...")

    try:
        response = engine.send_chat(Path(chat_path), provider_name=provider, model=model)
        lines = response.split("\n")
        preview = lines[0][:100] if lines else ""
        if len(lines) > 1 or len(preview) < len(lines[0]) if lines else False:
            preview += "..."
        click.echo(f"Response received ({len(response)} chars).")
        click.echo(f"Preview: {preview}")
        click.echo(f"Response appended to: {Path(chat_path).name}")
    except SyncAuthError as e:
        click.echo(f"Authentication error:\n{e}")
    except SyncAPIError as e:
        click.echo(f"API error: {e}")
    except ValueError as e:
        click.echo(f"Error: {e}")


@click.command("chat")
@click.argument("project")
@click.option(
    "--provider",
    "-p",
    default=None,
    type=click.Choice(["claude", "chatgpt", "gemini", "ollama"]),
    help="LLM provider (default: from config).",
)
@click.option("--model", "-m", default=None, help="Override the default model.")
@click.option("--title", "-t", default=None, help="Chat title.")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def chat_cmd(
    project: str,
    provider: str | None,
    model: str | None,
    title: str | None,
    home: Path | None,
) -> None:
    """Start an interactive file-based chat in a project.

    Creates a new .md file, prompts for messages, sends to LLM API,
    and appends responses. Type 'quit' or 'exit' to stop.

    WARNING: Cloud API access requires SEPARATE paid API keys.
    Gemini has a free tier. Ollama is free (local).
    """
    home_path = home or resolve_home()

    # Verify project exists
    project_dir = home_path / project
    if not project_dir.exists():
        click.echo(f"Error: Project '{project}' not found at {project_dir}")
        return

    from anticlaw.core.fileutil import safe_filename
    from anticlaw.core.models import Chat, ChatMessage
    from anticlaw.core.storage import ChatStorage
    from anticlaw.sync.engine import SyncEngine
    from anticlaw.sync.providers import SyncAPIError, SyncAuthError

    engine = SyncEngine(home_path)
    storage = ChatStorage(home_path)

    # Resolve provider
    config = load_config(home_path / ".acl" / "config.yaml")
    target = provider or config.get("sync", {}).get("default_push_target")
    if not target:
        click.echo(
            "Error: No provider specified. Use --provider or set "
            "sync.default_push_target in config."
        )
        return

    # Create new chat file
    now = datetime.now(timezone.utc)
    chat_title = title or f"Chat with {target}"
    chat = Chat(
        title=chat_title,
        provider=target,
        model=model or "",
        status="active",
        created=now,
        updated=now,
    )

    date_str = now.strftime("%Y-%m-%d")
    slug = safe_filename(chat_title)
    filename = f"{date_str}_{slug}.md"
    chat_path = project_dir / filename

    click.echo(f"Starting chat with {target} in {project}/")
    click.echo(f"File: {filename}")
    click.echo("Type your message (or 'quit'/'exit' to stop).\n")

    messages: list[ChatMessage] = []

    while True:
        try:
            user_input = click.prompt("You", prompt_suffix="> ")
        except (EOFError, KeyboardInterrupt):
            click.echo("\nChat ended.")
            break

        if user_input.strip().lower() in ("quit", "exit", "q"):
            click.echo("Chat ended.")
            break

        msg_time = datetime.now(timezone.utc)
        messages.append(ChatMessage(role="human", content=user_input, timestamp=msg_time))
        chat.messages = messages
        chat.message_count = len(messages)
        chat.updated = msg_time

        # Write current state (so file exists as draft)
        storage.write_chat(chat_path, chat)

        # Send to LLM
        try:
            response = engine.send_chat(chat_path, provider_name=target, model=model)
            click.echo(f"\nAssistant: {response}\n")
            # Reload messages after engine appended the response
            updated_chat = storage.read_chat(chat_path, load_messages=True)
            messages = updated_chat.messages
        except SyncAuthError as e:
            click.echo(f"\nAuth error: {e}")
            break
        except SyncAPIError as e:
            click.echo(f"\nAPI error: {e}")
            break
        except Exception as e:
            click.echo(f"\nError: {e}")
            break

    # Write final state
    if messages:
        chat.messages = messages
        chat.message_count = len(messages)
        chat.status = "active"
        storage.write_chat(chat_path, chat)
        click.echo(f"Chat saved: {chat_path}")


def _resolve_chat_path(db, chat_id: str) -> str | None:
    """Resolve a chat ID (or prefix) to its file path from MetaDB."""
    # Exact match first
    row = db.conn.execute(
        "SELECT file_path FROM chats WHERE id = ?", (chat_id,)
    ).fetchone()
    if row:
        return row["file_path"]

    # Prefix match
    rows = db.conn.execute(
        "SELECT file_path FROM chats WHERE id LIKE ?", (f"{chat_id}%",)
    ).fetchall()
    if len(rows) == 1:
        return rows[0]["file_path"]

    return None
