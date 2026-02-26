"""CLI commands for importing LLM conversation exports."""

from __future__ import annotations

import logging
from pathlib import Path

import click

from anticlaw.core.config import resolve_home
from anticlaw.core.fileutil import safe_filename
from anticlaw.core.models import Chat, ChatData, Project
from anticlaw.core.storage import ChatStorage
from anticlaw.providers.llm.chatgpt import ChatGPTProvider
from anticlaw.providers.llm.claude import ClaudeProvider
from anticlaw.providers.llm.gemini import GeminiProvider

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
    """Import conversations from a Claude.ai data export ZIP or directory.

    EXPORT_PATH is the path to the ZIP file or extracted directory from
    Claude.ai (Settings > Privacy > Export Data).
    """
    home_path = home or resolve_home()
    storage = ChatStorage(home_path)
    storage.init_home()

    provider = ClaudeProvider()

    # Parse the export (also reads projects.json for folder mapping)
    click.echo(f"Parsing {export_path.name}...")
    chat_data_list = provider.parse_export(export_path, scrub=scrub)

    if not chat_data_list:
        click.echo("No conversations found in export.")
        return

    # Extract project metadata for _project.yaml creation
    projects_meta = provider.extract_projects(export_path)
    if projects_meta:
        click.echo(f"Found {len(projects_meta)} projects in export.")

    # Create project folders from projects.json (even without chat mapping)
    # This ensures knowledge docs and project metadata are always saved.
    created_projects: set[str] = set()
    for proj_uuid, proj_meta in projects_meta.items():
        proj_name = proj_meta.get("name", "")
        if not proj_name:
            continue
        dir_name = safe_filename(proj_name)
        if dir_name not in created_projects:
            target = home_path / dir_name
            if not (target / "_project.yaml").exists():
                _create_project_with_meta(
                    storage, home_path, proj_name, proj_uuid, projects_meta,
                )
            created_projects.add(dir_name)

    # Load explicit project mapping if provided (overrides projects.json)
    project_map: dict[str, str] = {}
    if mapping:
        project_map = provider.load_project_mapping(mapping)
        click.echo(f"Loaded project mapping: {len(project_map)} entries.")

    # Import each conversation
    imported = 0
    skipped = 0

    with click.progressbar(chat_data_list, label="Importing", show_pos=True) as bar:
        for chat_data in bar:
            # Determine target directory:
            # 1. Explicit --mapping flag takes priority
            # 2. project_name from projects.json (auto-detected)
            # 3. Fallback to _inbox
            project_name = project_map.get(chat_data.remote_id) or chat_data.project_name

            if project_name:
                dir_name = safe_filename(project_name)
                target_dir = home_path / dir_name

                if dir_name not in created_projects:
                    if not (target_dir / "_project.yaml").exists():
                        _create_project_with_meta(
                            storage, home_path, project_name,
                            chat_data.remote_project_id, projects_meta,
                        )
                    created_projects.add(dir_name)
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
    mapped_count = sum(
        1 for cd in chat_data_list
        if project_map.get(cd.remote_id) or cd.project_name
    )
    if mapped_count:
        click.echo(f"  Mapped to projects: {mapped_count}")
        click.echo(f"  Sent to _inbox: {len(chat_data_list) - mapped_count}")
    else:
        click.echo("  All sent to: _inbox/")
    if created_projects:
        click.echo(f"  Projects created: {len(created_projects)}")
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


@import_group.command("gemini")
@click.argument("export_path", type=click.Path(exists=True, path_type=Path))
@click.option("--scrub", is_flag=True, help="Redact detected secrets (API keys, passwords).")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def import_gemini(
    export_path: Path,
    scrub: bool,
    home: Path | None,
) -> None:
    """Import conversations from a Google Takeout Gemini export.

    EXPORT_PATH is the path to the Google Takeout ZIP file or extracted
    directory containing Gemini conversation data
    (Google Takeout > select Gemini > download ZIP).
    """
    home_path = home or resolve_home()
    storage = ChatStorage(home_path)
    storage.init_home()

    provider = GeminiProvider()

    # Parse the export
    click.echo(f"Parsing {export_path.name}...")
    chat_data_list = provider.parse_takeout_zip(export_path, scrub=scrub)

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


def _create_project_with_meta(
    storage: ChatStorage,
    home_path: Path,
    project_name: str,
    project_uuid: str,
    projects_meta: dict[str, dict],
) -> None:
    """Create a project folder with _project.yaml, enriched with Claude metadata."""
    from anticlaw.core.fileutil import ensure_dir

    dir_name = safe_filename(project_name)
    project_dir = home_path / dir_name
    ensure_dir(project_dir)

    project = Project(name=project_name)

    # Enrich with metadata from projects.json if available
    if project_uuid and project_uuid in projects_meta:
        meta = projects_meta[project_uuid]
        project.description = meta.get("description", "")
        if meta.get("created_at"):
            from anticlaw.providers.llm.claude import _parse_timestamp

            project.created = _parse_timestamp(meta.get("created_at"))
            project.updated = _parse_timestamp(meta.get("updated_at")) or project.created
        project.providers = {"claude": {"remote_id": project_uuid}}

        # Save knowledge docs if present
        docs = meta.get("docs", [])
        if docs:
            _save_knowledge_docs(project_dir, docs)

    storage.write_project(project_dir / "_project.yaml", project)


def _save_knowledge_docs(project_dir: Path, docs: list[dict]) -> None:
    """Save project knowledge documents to <project>/_knowledge/."""
    from anticlaw.core.fileutil import ensure_dir

    # Filter to docs that have both filename and content
    valid_docs = [d for d in docs if d.get("filename") and d.get("content")]
    if not valid_docs:
        return

    knowledge_dir = project_dir / "_knowledge"
    ensure_dir(knowledge_dir)

    for doc in valid_docs:
        doc_path = knowledge_dir / doc["filename"]
        doc_path.write_text(doc["content"], encoding="utf-8")


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
        summary=data.summary,
        messages=data.messages,
        message_count=len(data.messages),
    )
