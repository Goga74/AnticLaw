"""CLI commands for importing LLM conversation exports."""

from __future__ import annotations

import logging
from pathlib import Path

import click

from anticlaw.core.config import resolve_home
from anticlaw.core.fileutil import safe_filename
from anticlaw.core.models import Chat, ChatData
from anticlaw.core.storage import ChatStorage
from anticlaw.providers.llm.chatgpt import ChatGPTProvider
from anticlaw.providers.llm.claude import ClaudeProvider

log = logging.getLogger(__name__)


@click.group("import")
def import_group() -> None:
    """Import conversations from LLM platforms."""


@import_group.command("claude")
@click.argument("export_path", type=click.Path(exists=True, path_type=Path))
@click.option("--scrub", is_flag=True, help="Redact detected secrets (API keys, passwords).")
@click.option(
    "--mapping",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="JSON file mapping chat UUIDs to project names (from Playwright scraper).",
)
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def import_claude(
    export_path: Path,
    scrub: bool,
    mapping: Path | None,
    home: Path | None,
) -> None:
    """Import conversations from a Claude.ai data export ZIP.

    EXPORT_PATH is the path to the ZIP file downloaded from Claude.ai
    (Settings > Privacy > Export Data).
    """
    home_path = home or resolve_home()
    storage = ChatStorage(home_path)
    storage.init_home()

    provider = ClaudeProvider()

    # Parse the export
    click.echo(f"Parsing {export_path.name}...")
    chat_data_list = provider.parse_export_zip(export_path, scrub=scrub)

    if not chat_data_list:
        click.echo("No conversations found in export.")
        return

    # Load project mapping if provided
    project_map: dict[str, str] = {}
    if mapping:
        project_map = provider.load_project_mapping(mapping)
        click.echo(f"Loaded project mapping: {len(project_map)} entries.")

    # Import each conversation
    imported = 0
    skipped = 0

    with click.progressbar(chat_data_list, label="Importing", show_pos=True) as bar:
        for chat_data in bar:
            # Determine target directory
            project_name = project_map.get(chat_data.remote_id)
            if project_name:
                target_dir = home_path / safe_filename(project_name)
                if not (target_dir / "_project.yaml").exists():
                    storage.create_project(project_name)
            else:
                target_dir = home_path / "_inbox"

            # Convert ChatData → Chat
            chat = _chat_data_to_chat(chat_data)

            # Generate filename and check for duplicates
            filename = storage.chat_filename(chat)
            target_path = target_dir / filename

            if target_path.exists():
                skipped += 1
                continue

            storage.write_chat(target_path, chat)
            imported += 1

    # Summary
    click.echo()
    click.echo("Import complete:")
    click.echo(f"  Imported: {imported}")
    if skipped:
        click.echo(f"  Skipped (already exist): {skipped}")
    if project_map:
        mapped = sum(1 for cd in chat_data_list if cd.remote_id in project_map)
        click.echo(f"  Mapped to projects: {mapped}")
        click.echo(f"  Sent to _inbox: {len(chat_data_list) - mapped}")
    else:
        click.echo("  All sent to: _inbox/")
    if scrub:
        click.echo("  Secret scrubbing: enabled")


@import_group.command("chatgpt")
@click.argument("export_path", type=click.Path(exists=True, path_type=Path))
@click.option("--scrub", is_flag=True, help="Redact detected secrets (API keys, passwords).")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def import_chatgpt(
    export_path: Path,
    scrub: bool,
    home: Path | None,
) -> None:
    """Import conversations from a ChatGPT data export ZIP.

    EXPORT_PATH is the path to the ZIP file downloaded from ChatGPT
    (Settings > Data controls > Export data).
    """
    home_path = home or resolve_home()
    storage = ChatStorage(home_path)
    storage.init_home()

    provider = ChatGPTProvider()

    # Parse the export
    click.echo(f"Parsing {export_path.name}...")
    chat_data_list = provider.parse_export_zip(export_path, scrub=scrub)

    if not chat_data_list:
        click.echo("No conversations found in export.")
        return

    # Import each conversation
    imported = 0
    skipped = 0

    with click.progressbar(chat_data_list, label="Importing", show_pos=True) as bar:
        for chat_data in bar:
            target_dir = home_path / "_inbox"

            # Convert ChatData → Chat
            chat = _chat_data_to_chat(chat_data)

            # Generate filename and check for duplicates
            filename = storage.chat_filename(chat)
            target_path = target_dir / filename

            if target_path.exists():
                skipped += 1
                continue

            storage.write_chat(target_path, chat)
            imported += 1

    # Summary
    click.echo()
    click.echo("Import complete:")
    click.echo(f"  Imported: {imported}")
    if skipped:
        click.echo(f"  Skipped (already exist): {skipped}")
    click.echo("  All sent to: _inbox/")
    if scrub:
        click.echo("  Secret scrubbing: enabled")


def _chat_data_to_chat(data: ChatData) -> Chat:
    """Convert a provider ChatData into a core Chat model."""
    return Chat(
        title=data.title,
        created=data.created,
        updated=data.updated,
        provider=data.provider,
        remote_id=data.remote_id,
        remote_project_id=data.remote_project_id,
        model=data.model,
        messages=data.messages,
        message_count=len(data.messages),
    )
