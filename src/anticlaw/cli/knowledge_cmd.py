"""CLI knowledge management commands: aw inbox, stale, duplicates, health, retention, stats."""

from __future__ import annotations

from pathlib import Path

import click

from anticlaw.core.config import resolve_home

# --- aw inbox [--auto] ---


@click.command("inbox")
@click.option("--auto", "auto_classify", is_flag=True, help="Auto-classify using LLM.")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def inbox_cmd(auto_classify: bool, home: Path | None) -> None:
    """Show inbox chats with project suggestions."""
    home_path = home or resolve_home()
    db_path = home_path / ".acl" / "meta.db"

    if not db_path.exists():
        click.echo("No index found. Run 'aw reindex' first.")
        return

    from anticlaw.core.antientropy import inbox_suggestions

    suggestions = inbox_suggestions(home_path, use_llm=auto_classify)
    if not suggestions:
        click.echo("Inbox is empty — nothing to classify.")
        return

    click.echo(f"Inbox chats ({len(suggestions)}):\n")
    for s in suggestions:
        proj = s.suggested_project or "(no suggestion)"
        conf = s.confidence
        click.echo(f"  {s.chat_id[:8]}  {s.title}")
        click.echo(f"           → {proj} [{conf}] {s.reason}")

    if auto_classify:
        _auto_classify(home_path, suggestions)


def _auto_classify(home_path: Path, suggestions: list) -> None:
    """Move chats to suggested projects when confidence is high/medium."""
    from anticlaw.core.meta_db import MetaDB
    from anticlaw.core.storage import ChatStorage

    storage = ChatStorage(home_path)
    db = MetaDB(home_path / ".acl" / "meta.db")
    moved = 0

    try:
        for s in suggestions:
            if s.confidence == "low" or not s.suggested_project:
                continue
            src = Path(s.file_path)
            if not src.exists():
                continue
            # Resolve target directory
            target_dir = home_path / s.suggested_project
            if not target_dir.exists():
                # Create the project
                storage.create_project(s.suggested_project)
            new_path = storage.move_chat(src, target_dir)
            db.update_chat_path(s.chat_id, new_path, s.suggested_project)
            moved += 1
            click.echo(f"  Moved {s.chat_id[:8]} → {s.suggested_project}/")
    finally:
        db.close()

    click.echo(f"\nMoved {moved} chat(s).")


# --- aw stale [--days N] ---


@click.command("stale")
@click.option("--days", default=30, type=int, help="Inactivity threshold in days.")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def stale_cmd(days: int, home: Path | None) -> None:
    """List projects with no recent activity."""
    home_path = home or resolve_home()

    from anticlaw.core.antientropy import find_stale

    stale_projects = find_stale(home_path, days=days)
    if not stale_projects:
        click.echo(f"No stale projects (threshold: {days} days).")
        return

    click.echo(f"Stale projects (inactive > {days} days):\n")
    for sp in stale_projects:
        click.echo(
            f"  {sp.name}  ({sp.chat_count} chats, {sp.days_inactive} days idle)"
        )


# --- aw duplicates ---


@click.command("duplicates")
@click.option("--threshold", default=0.9, type=float, help="Similarity threshold (0-1).")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def duplicates_cmd(threshold: float, home: Path | None) -> None:
    """Detect similar or duplicate chats."""
    home_path = home or resolve_home()

    from anticlaw.core.antientropy import find_duplicates

    pairs = find_duplicates(home_path, threshold=threshold)
    if not pairs:
        click.echo("No duplicates found.")
        return

    click.echo(f"Potential duplicates ({len(pairs)}):\n")
    for p in pairs:
        click.echo(
            f"  {p.chat_id_a[:8]} \"{p.title_a}\"  ↔  "
            f"{p.chat_id_b[:8]} \"{p.title_b}\"  ({p.similarity:.0%})"
        )


# --- aw health ---


@click.command("health")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def health_cmd(home: Path | None) -> None:
    """Check knowledge base integrity."""
    home_path = home or resolve_home()

    from anticlaw.core.antientropy import health_check

    report = health_check(home_path)

    click.echo("KB Health Report")
    click.echo(f"  Chats on disk: {report.total_chats}")
    click.echo(f"  Chats indexed: {report.indexed_chats}")
    click.echo(f"  Projects: {report.total_projects}")
    click.echo(f"  Insights: {report.total_insights}")
    click.echo()

    if not report.issues:
        click.echo("No issues found.")
        return

    click.echo(f"Issues ({len(report.issues)}):\n")
    for issue in report.issues:
        severity_mark = "!" if issue.severity == "error" else "?"
        click.echo(f"  [{severity_mark}] {issue.category}: {issue.message}")


# --- aw retention preview / run ---


@click.group("retention")
def retention_group() -> None:
    """Retention lifecycle management."""


@retention_group.command("preview")
@click.option("--archive-days", default=None, type=int, help="Override archive threshold.")
@click.option("--purge-days", default=None, type=int, help="Override purge threshold.")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def retention_preview_cmd(
    archive_days: int | None, purge_days: int | None, home: Path | None
) -> None:
    """Dry-run: show what would be archived or purged."""
    home_path = home or resolve_home()

    from anticlaw.core.retention import preview_retention

    result = preview_retention(home_path, archive_days=archive_days, purge_days=purge_days)
    if not result.actions:
        click.echo("No chats eligible for retention action.")
        return

    archive_actions = [a for a in result.actions if a.action == "archive"]
    purge_actions = [a for a in result.actions if a.action == "purge"]

    if archive_actions:
        click.echo(f"Would archive ({len(archive_actions)}):\n")
        for a in archive_actions:
            click.echo(f"  {a.chat_id[:8]}  {a.title}  ({a.reason})")

    if purge_actions:
        click.echo(f"\nWould purge ({len(purge_actions)}):\n")
        for a in purge_actions:
            click.echo(f"  {a.chat_id[:8]}  {a.title}  ({a.reason})")


@retention_group.command("run")
@click.option("--archive-days", default=None, type=int, help="Override archive threshold.")
@click.option("--purge-days", default=None, type=int, help="Override purge threshold.")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def retention_run_cmd(
    archive_days: int | None, purge_days: int | None, home: Path | None
) -> None:
    """Execute retention: archive stale chats, purge old archives."""
    home_path = home or resolve_home()

    from anticlaw.core.retention import run_retention

    result = run_retention(home_path, archive_days=archive_days, purge_days=purge_days)

    if result.archived == 0 and result.purged == 0:
        click.echo("No chats eligible for retention action.")
        return

    if result.archived:
        click.echo(f"Archived: {result.archived} chat(s)")
    if result.purged:
        click.echo(f"Purged: {result.purged} chat(s)")
    if result.errors:
        click.echo(f"Errors: {len(result.errors)}")
        for e in result.errors:
            click.echo(f"  {e}")


# --- aw restore <chat-id> ---


@click.command("restore")
@click.argument("chat_id")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def restore_cmd(chat_id: str, home: Path | None) -> None:
    """Restore an archived chat back to its project."""
    home_path = home or resolve_home()

    from anticlaw.core.retention import restore

    result = restore(home_path, chat_id)
    if result:
        click.echo(f"Restored → {result}")
    else:
        click.echo(f"Could not restore chat '{chat_id}'. Check if it exists and is archived.")


# --- aw stats ---


@click.command("stats")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def stats_cmd(home: Path | None) -> None:
    """Show global knowledge base statistics."""
    home_path = home or resolve_home()

    from anticlaw.core.antientropy import kb_stats

    s = kb_stats(home_path)

    click.echo("Knowledge Base Statistics\n")
    click.echo(f"  Projects:   {s.total_projects}")
    click.echo(f"  Chats:      {s.total_chats}")
    click.echo(f"    Active:   {s.total_chats - s.archived_chats - s.inbox_chats}")
    click.echo(f"    Inbox:    {s.inbox_chats}")
    click.echo(f"    Archived: {s.archived_chats}")
    click.echo(f"  Messages:   {s.total_messages}")
    click.echo(f"  Insights:   {s.total_insights}")
    click.echo(f"  Tags:       {s.total_tags}")

    if s.top_tags:
        click.echo("\n  Top tags:")
        for tag, count in s.top_tags:
            click.echo(f"    {tag}: {count}")
